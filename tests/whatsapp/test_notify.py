"""Alert push (PLAN_WHATSAPP.md W1 to W7). HTTP is mocked with httpx.MockTransport; conftest.py refuses anything real."""
import base64
import importlib.util
import json
import logging
import time
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from kami.notify import DryRunNotifier, NotificationManager, TriggerRule, TwilioWhatsAppNotifier, build_manager, format_message, load_settings
from kami.notify.base import Notifier, SendOutcome
from kami.notify.message import PREFIX

ROOT = Path(__file__).resolve().parents[2]
# obviously fake values, assembled so that no line of this file looks like a credential or a real number
SID = "AC" + "test_not_a_real_sid"
TOKEN = "tok_" + "test_NOT_REAL_value"
FROM = "whatsapp:+" + "0" * 10 + "1"
TO = "whatsapp:+" + "0" * 10 + "2"
SECRETS = (SID, TOKEN, FROM, TO, FROM.split("+")[1], TO.split("+")[1])
MSG_SID = "SM" + "0" * 32


def ev(node="node-1", id=1, priority="High", category="Infrastructure", status="active", ts="2018-01-07T16:50:00", **over):
    """An alert event as the live processor emits it."""
    e = {"id": id, "node_id": node, "category": category, "priority": priority, "max_priority": priority, "start_ts": "2018-01-07T15:00:00",
         "last_ts": ts, "end_ts": None, "status": status, "confidence": 0.63,
         "explanation": f"{category} anomaly, priority {priority} (confidence 0.63): infrastructure evidence 0.99, above threshold for 1.8 h, "
                        "suddenness 1.00, 1 episode(s) in the last 7 days."}
    e.update(over)
    return e


def env(tmp_path, **over):
    e = {"KAMI_WHATSAPP_ENABLE": "1", "TWILIO_ACCOUNT_SID": SID, "TWILIO_AUTH_TOKEN": TOKEN, "TWILIO_WHATSAPP_FROM": FROM, "WHATSAPP_TO": TO,
         "KAMI_NOTIFY_ENV_FILE": str(tmp_path / "no_such.env"), "KAMI_NOTIFY_DIR": str(tmp_path / "notifications")}
    e.update(over)
    return {k: v for k, v in e.items() if v is not None}


class Twilio:
    """Scripted stand-in for api.twilio.com. `post` and `get` are lists of (status, json) answers or exceptions; the last one repeats."""

    def __init__(self, post=((201, {"sid": MSG_SID, "status": "queued", "error_code": None}),), get=((200, {"status": "delivered", "error_code": None}),)):
        self.answers = {"POST": list(post), "GET": list(get)}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answers = self.answers[request.method]
        a = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(a, Exception):
            raise a
        return httpx.Response(a[0], json=a[1])

    def n(self, method="POST") -> int:
        return sum(r.method == method for r in self.requests)

    @property
    def transport(self):
        return httpx.MockTransport(self)


def twilio_manager(tmp_path, fake: Twilio, **over):
    kw = {"backoff": (0.0, 0.0), "check_delay": 0.0}
    kw.update(over.pop("kw", {}))
    return build_manager({"node-1": "Katpadi Junction"}, env=env(tmp_path, **over), transport=fake.transport, **kw)


def read_log(tmp_path) -> list[dict]:
    p = tmp_path / "notifications" / "dryrun_log.jsonl"
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


# ------------------------------------------------------------------ W2: trigger rule (pure, time passed in)
def test_trigger_opens_only_with_high_or_critical():
    r = TriggerRule()
    assert r.evaluate(ev(id=1, priority="Low"), 0).reason == "not_triggered"
    assert r.evaluate(ev(node="node-2", id=2, priority="Medium"), 0).reason == "not_triggered"
    d = r.evaluate(ev(node="node-3", id=3, priority="High"), 0)
    assert d.send and d.reason == "opened"
    d = r.evaluate(ev(node="node-4", id=4, priority="Critical"), 0)
    assert d.send and d.reason == "opened"


def test_trigger_escalation_and_no_repeat_for_an_unchanged_state():
    r = TriggerRule()
    assert not r.evaluate(ev(priority="Medium"), 0).send  # opened below High: nothing
    d = r.evaluate(ev(priority="High"), 10)
    assert d.send and d.reason == "escalated"
    r.commit(ev(priority="High"), 10)
    assert r.evaluate(ev(priority="High"), 2000).reason == "not_triggered"  # same state again
    assert r.evaluate(ev(priority="High", category="Combined"), 2000).reason == "not_triggered"  # category change alone
    assert r.evaluate(ev(priority="Medium"), 2100).reason == "not_triggered"  # de-escalation
    assert r.evaluate(ev(priority="High"), 2200).reason == "not_triggered"  # back to a priority already notified
    d = r.evaluate(ev(priority="Critical"), 2300)
    assert d.send and d.reason == "escalated"
    r.commit(ev(priority="Critical"), 2300)
    assert r.evaluate(ev(priority="Critical"), 9000).reason == "not_triggered"
    assert r.evaluate(ev(status="closed", priority="Critical"), 9100).reason == "not_triggered"  # closing sends nothing
    d = r.evaluate(ev(id=2, priority="High"), 9200)  # a NEW episode on the same node
    assert d.send and d.reason == "opened"


def test_cooldown_one_message_per_node_per_ten_minutes():
    r = TriggerRule()
    assert r.evaluate(ev(id=1), 0).send
    r.commit(ev(id=1), 0)
    d = r.evaluate(ev(id=1, priority="Critical"), 599)  # escalation inside the cooldown
    assert not d.send and d.reason == "cooldown" and d.suppressed
    assert r.evaluate(ev(node="node-2", id=2), 599).send  # another node is not affected
    d = r.evaluate(ev(id=1, priority="Critical"), 600)  # held back, not marked as notified: sent once the cooldown is over
    assert d.send and d.reason == "escalated"


def test_hourly_cap_thirty_messages_overall():
    r = TriggerRule(max_total=1000)
    for i in range(30):
        e = ev(node=f"node-{i}", id=i)
        assert r.evaluate(e, i).send
        r.commit(e, i)
    d = r.evaluate(ev(node="node-99", id=99), 100)
    assert not d.send and d.reason == "hourly_cap"
    assert r.sent_last_hour(100) == 30
    assert not r.evaluate(ev(node="node-99", id=99), 3599).send  # the first message is still inside the hour
    assert r.evaluate(ev(node="node-99", id=99), 3600).send  # one slot is free again
    assert r.sent_last_hour(3600) == 29


def test_lifetime_budget_stops_sending():
    r = TriggerRule(max_total=3, used_total=1)
    for i in range(2):
        e = ev(node=f"node-{i}", id=i)
        assert r.evaluate(e, i).send
        r.commit(e, i)
    d = r.evaluate(ev(node="node-9", id=9), 5000)
    assert not d.send and d.reason == "budget" and r.budget_remaining == 0


# ------------------------------------------------------------------ W3: message text
def test_message_text_has_prefix_real_values_and_stays_under_600_characters():
    a = {**ev(priority="Critical", category="Combined"), "ts": "2018-01-07T16:50:00"}
    text = format_message(a, "Katpadi Junction")
    lines = text.split("\n")
    assert lines[0] == PREFIX == "[KAMI DEMO - simulated data]"
    assert "Katpadi Junction (node-1)" in lines[1]
    assert lines[2] == "Category: Combined | Priority: Critical | Confidence: 0.63"
    assert a["explanation"] in text and lines[-1] == "Replay time: 2018-01-07 16:50"
    long = format_message({**a, "explanation": "x" * 5000}, "N" * 40)
    assert len(long) < 600 and long.startswith(PREFIX) and long.endswith("Replay time: 2018-01-07 16:50") and "..." in long


# ------------------------------------------------------------------ W1: dry run is the default and the fallback
def test_dry_run_writes_the_message_and_nothing_else_happens(tmp_path):
    mgr = NotificationManager(DryRunNotifier(tmp_path / "notifications"), node_names={"node-1": "Katpadi Junction"})
    mgr.on_event("assessment", {"node_id": "node-1"})  # other listener events are ignored
    mgr.on_event("alert", ev(priority="Medium"))
    mgr.on_event("alert", ev(priority="High"))
    mgr.on_event("alert", ev(priority="High", category="Combined"))  # unchanged priority: no second message
    assert mgr.wait_idle()
    mgr.stop()
    rows = read_log(tmp_path)
    assert len(rows) == 1 and rows[0]["mode"] == "dry_run"
    assert rows[0]["alert"]["id"] == 1 and rows[0]["alert"]["priority"] == "High" and rows[0]["alert"]["ts"] == "2018-01-07T16:50:00"
    assert rows[0]["text"].startswith(PREFIX) and "Katpadi Junction" in rows[0]["text"] and "evidence 0.99" in rows[0]["text"]
    s = mgr.status()
    assert s["mode"] == "dry_run" and (s["sent"], s["suppressed"], s["failed"]) == (1, 0, 0) and s["last_send_utc"]


@pytest.mark.parametrize("missing", ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM", "WHATSAPP_TO"])
def test_falls_back_to_dry_run_when_a_credential_is_missing_and_logs_the_name_only(tmp_path, caplog, missing):
    fake = Twilio()
    with caplog.at_level(logging.DEBUG):
        mgr = build_manager(env=env(tmp_path, **{missing: None}), transport=fake.transport)
        mgr.on_event("alert", ev())
        assert mgr.wait_idle()
        mgr.stop()
    s = mgr.status()
    assert s["mode"] == "dry_run" and missing in s["detail"] and s["sent"] == 1
    assert missing in caplog.text and not any(v in caplog.text for v in SECRETS)
    assert fake.requests == [] and len(read_log(tmp_path)) == 1


def test_dry_run_unless_enabled_and_well_formed(tmp_path):
    assert not load_settings(env(tmp_path, KAMI_WHATSAPP_ENABLE="0")).ready
    assert not load_settings(env(tmp_path, KAMI_WHATSAPP_ENABLE=None)).ready
    s = load_settings(env(tmp_path, WHATSAPP_TO="+" + "0" * 11))  # no whatsapp: prefix
    assert not s.ready and s.missing == ("WHATSAPP_TO",)
    assert load_settings(env(tmp_path, WHATSAPP_TO="whatsapp:+91XXXXXXXXXX")).missing == ("WHATSAPP_TO",)  # the placeholder
    assert load_settings(env(tmp_path)).ready
    fake = Twilio()
    forced = build_manager(env=env(tmp_path), transport=fake.transport, force_dry_run=True)  # what every check and test run uses
    forced.on_event("alert", ev())
    assert forced.wait_idle() and forced.status()["mode"] == "dry_run" and fake.requests == []
    forced.stop()


def test_env_file_is_read_and_the_process_environment_wins(tmp_path):
    f = tmp_path / "x.env"
    f.write_text(f"# comment\nKAMI_WHATSAPP_ENABLE=1\nTWILIO_ACCOUNT_SID={SID}\nTWILIO_AUTH_TOKEN='{TOKEN}'\n"
                 f"TWILIO_WHATSAPP_FROM={FROM}\nWHATSAPP_TO={TO}\nWHATSAPP_MAX_TOTAL=5\n", encoding="utf-8")
    s = load_settings({"KAMI_NOTIFY_ENV_FILE": str(f)})
    assert s.ready and s.max_total == 5 and s.value("TWILIO_AUTH_TOKEN") == TOKEN
    assert not load_settings({"KAMI_NOTIFY_ENV_FILE": str(f), "KAMI_WHATSAPP_ENABLE": "0"}).ready
    assert not any(v in repr(s) + s.describe() + str(s) for v in SECRETS)


# ------------------------------------------------------------------ W1/W4: Twilio notifier over mocked HTTPS
def test_twilio_request_is_a_plain_form_post_with_basic_auth(tmp_path):
    fake = Twilio()
    mgr = twilio_manager(tmp_path, fake)
    mgr.on_event("alert", ev())
    assert mgr.wait_idle()
    mgr.stop()
    post = next(r for r in fake.requests if r.method == "POST")
    assert str(post.url) == f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json"
    assert post.headers["authorization"] == "Basic " + base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    assert post.headers["content-type"] == "application/x-www-form-urlencoded"
    form = {k: v[0] for k, v in parse_qs(post.content.decode()).items()}
    assert form["To"] == TO and form["From"] == FROM and set(form) == {"To", "From", "Body"}
    assert form["Body"].startswith(PREFIX) and "Katpadi Junction (node-1)" in form["Body"] and len(form["Body"]) < 600
    assert fake.n("POST") == 1 and fake.n("GET") == 1  # one send, one later status check
    s = mgr.status()
    assert s["mode"] == "twilio" and (s["sent"], s["suppressed"], s["failed"]) == (1, 0, 0)
    assert s["budget_used"] == 1 and s["budget_remaining"] == 79
    assert json.loads((tmp_path / "notifications" / "state.json").read_text(encoding="utf-8"))["messages_handed_to_twilio"] == 1


@pytest.mark.parametrize("answer", [(503, {"message": "down"}), (429, {"code": 20429}), httpx.ConnectError("boom"), httpx.ReadTimeout("slow")])
def test_failures_are_retried_at_most_twice_then_counted_as_failed(tmp_path, answer):
    fake = Twilio(post=[answer])
    mgr = twilio_manager(tmp_path, fake)
    mgr.on_event("alert", ev())
    assert mgr.wait_idle()
    assert fake.n("POST") == 3  # first attempt + two retries, never more
    s = mgr.status()
    assert (s["sent"], s["failed"]) == (0, 1) and "gave up after 3 attempts" in s["last_problem"]
    assert s["budget_used"] == 3  # every request spends budget
    mgr.on_event("alert", ev(node="node-2", id=2))  # the loop is alive and the next alert is handled
    assert mgr.wait_idle() and fake.n("POST") == 6
    mgr.stop()


def test_a_retry_that_succeeds_counts_as_sent(tmp_path):
    fake = Twilio(post=[(503, {}), httpx.ConnectError("boom"), (201, {"sid": MSG_SID, "status": "queued"})])
    mgr = twilio_manager(tmp_path, fake)
    mgr.on_event("alert", ev())
    assert mgr.wait_idle()
    mgr.stop()
    s = mgr.status()
    assert fake.n("POST") == 3 and (s["sent"], s["failed"]) == (1, 0)


def test_window_closed_is_suppressed_without_retries_and_pauses_sending(tmp_path, caplog):
    fake = Twilio(post=[(400, {"code": 63016, "message": f"Failed to send freeform message to {TO}", "status": 400})])
    with caplog.at_level(logging.DEBUG):
        mgr = twilio_manager(tmp_path, fake)
        mgr.on_event("alert", ev())
        assert mgr.wait_idle()
        mgr.on_event("alert", ev(node="node-2", id=2))  # held back while the window is closed: no request, no budget spent
        assert mgr.wait_idle()
        mgr.stop()
    s = mgr.status()
    assert fake.n("POST") == 1
    assert (s["sent"], s["suppressed"], s["failed"]) == (0, 2, 0) and s["suppressed_by"] == {"window_closed": 1, "on_hold": 1}
    line = "WhatsApp alert not sent: window closed: reply to the sandbox number to reopen (HTTP 400, Twilio error 63016)"
    assert s["last_problem"] == line and caplog.text.count(line) == 1
    assert s["budget_used"] == 1


def test_window_closed_reported_later_by_the_status_check(tmp_path):
    fake = Twilio(get=[(200, {"status": "undelivered", "error_code": 63016})])
    mgr = twilio_manager(tmp_path, fake)
    mgr.on_event("alert", ev())
    assert mgr.wait_idle()
    mgr.stop()
    s = mgr.status()
    assert fake.n("POST") == 1 and fake.n("GET") == 1
    assert (s["sent"], s["suppressed"], s["failed"]) == (0, 1, 0) and "window closed" in s["last_problem"]


def test_sandbox_not_joined_and_bad_credentials_are_one_clear_line(tmp_path, caplog):
    for i, (answer, words) in enumerate([((400, {"code": 63015, "message": "x"}), "has not joined the sandbox or the join expired"),
                                         ((401, {"code": 20003, "message": "Authenticate"}), "Twilio rejected the credentials"),
                                         ((400, {"code": 21211, "message": f"bad number {TO}"}), "Twilio did not accept the message (HTTP 400, Twilio error 21211)")]):
        fake = Twilio(post=[answer])
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            mgr = twilio_manager(tmp_path / str(i), fake)
            mgr.on_event("alert", ev())
            assert mgr.wait_idle()
            mgr.stop()
        s = mgr.status()
        assert fake.n("POST") == 1 and (s["sent"], s["failed"]) == (0, 1) and words in s["last_problem"]
        problem_lines = [r.getMessage() for r in caplog.records if "not sent" in r.getMessage()]
        assert len(problem_lines) == 1 and "\n" not in problem_lines[0]


def test_lifetime_budget_is_kept_across_restarts(tmp_path):
    fake = Twilio()
    mgr = twilio_manager(tmp_path, fake, WHATSAPP_MAX_TOTAL="2")
    for i in range(3):
        mgr.on_event("alert", ev(node=f"node-{i}", id=i))
    assert mgr.wait_idle()
    mgr.stop()
    s = mgr.status()
    assert fake.n("POST") == 2 and (s["sent"], s["suppressed"]) == (2, 1) and s["suppressed_by"] == {"budget": 1}
    assert s["budget_remaining"] == 0 and s["limits"]["max_total"] == 2
    again = twilio_manager(tmp_path, fake, WHATSAPP_MAX_TOTAL="2")  # a new process with the same folder
    again.on_event("alert", ev(node="node-7", id=7))
    assert again.wait_idle() and fake.n("POST") == 2 and again.status()["budget_remaining"] == 0
    again.stop()


def test_unreadable_budget_file_stops_sending(tmp_path):
    (tmp_path / "notifications").mkdir()
    (tmp_path / "notifications" / "state.json").write_text("{not json", encoding="utf-8")
    fake = Twilio()
    mgr = twilio_manager(tmp_path, fake)
    mgr.on_event("alert", ev())
    assert mgr.wait_idle() and fake.requests == [] and mgr.status()["budget_remaining"] == 0
    assert "budget file is unreadable" in mgr.status()["last_problem"]
    mgr.stop()


def test_cooldown_and_cap_are_enforced_by_the_manager(tmp_path):
    now = [1000.0]
    fake = Twilio()
    mgr = twilio_manager(tmp_path, fake, kw={"clock": lambda: now[0], "check_delay": None})
    mgr.on_event("alert", ev(id=1))
    mgr.on_event("alert", ev(id=1, priority="Critical"))  # 0 s later: cooldown
    now[0] += 601
    mgr.on_event("alert", ev(id=1, priority="Critical", category="Combined"))  # still not notified at Critical: sent now
    for i in range(2, 40):  # other nodes: the hourly cap stops them at 30 in total
        mgr.on_event("alert", ev(node=f"node-{i}", id=i))
    assert mgr.wait_idle()
    mgr.stop()
    s = mgr.status()
    assert fake.n("POST") == 30 and s["sent"] == 30 and s["messages_last_hour"] == 30
    assert s["suppressed_by"] == {"cooldown": 1, "hourly_cap": 10} and s["suppressed"] == 11


# ------------------------------------------------------------------ W4: never crash or block the processing loop
class Exploding(Notifier):
    mode = "twilio"

    def send(self, text, alert):
        raise RuntimeError(f"boom {TOKEN}")


class Slow(Notifier):
    mode = "twilio"

    def send(self, text, alert):
        time.sleep(0.6)
        return SendOutcome("sent")


def test_failures_do_not_crash_or_block_the_processing_loop(tmp_path, caplog):
    with caplog.at_level(logging.DEBUG):
        mgr = NotificationManager(Exploding())
        mgr.on_event("alert", ev())  # the notifier raises in the worker thread
        mgr.on_event("alert", {"nonsense": True})  # malformed event: must not raise into the caller
        mgr.on_event("alert", None)
        assert mgr.wait_idle()
        mgr.on_event("alert", ev(node="node-2", id=2))  # still working afterwards
        assert mgr.wait_idle() and mgr._thread.is_alive()
        mgr.stop()
    s = mgr.status()
    assert s["sent"] == 0 and s["failed"] == 4 and "RuntimeError" in caplog.text
    assert TOKEN not in caplog.text and TOKEN not in json.dumps(s)  # exception texts are never logged
    slow = NotificationManager(Slow())
    t0 = time.perf_counter()
    for i in range(5):
        slow.on_event("alert", ev(node=f"node-{i}", id=i))
    assert time.perf_counter() - t0 < 0.2  # sending happens in the background
    slow.stop()


def test_processor_keeps_running_when_the_notifier_fails():
    """The real alert lifecycle with a failing notifier attached as a listener."""
    from kami.live.processor import LiveProcessor, _Node

    proc = LiveProcessor()
    mgr = NotificationManager(Exploding())
    seen = []
    proc.listeners += [mgr.on_event, lambda kind, data: seen.append(kind)]
    n = _Node()
    for i, (cat, pri) in enumerate([("Infrastructure", "High"), ("Combined", "Critical")]):
        event = proc._update_alert(n, {"node_id": "n", "ts": f"2018-01-01T00:0{i}:00", "category": cat, "priority": pri,
                                       "confidence": 0.7, "explanation": "x"})
        for fn in proc.listeners:
            fn("alert", event)
    assert mgr.wait_idle() and seen == ["alert", "alert"] and mgr.status()["failed"] >= 1
    mgr.stop()


# ------------------------------------------------------------------ W5/W6: no secret in logs, files or responses
def test_secrets_never_appear_in_logs_status_or_files(tmp_path, caplog):
    answers = [(201, {"sid": MSG_SID, "status": "queued", "to": TO, "from": FROM, "account_sid": SID}),
               (401, {"code": 20003, "message": f"Authentication Error - invalid username {SID}"}),
               (400, {"code": 21211, "message": f"The 'To' number {TO} is not valid", "more_info": f"https://x/{SID}"}),
               httpx.ConnectError(f"cannot reach https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json with {TOKEN}"),
               (500, {"message": TOKEN})]
    text = ""
    with caplog.at_level(logging.DEBUG):
        for i, a in enumerate(answers):
            fake = Twilio(post=[a], get=[(200, {"status": "failed", "error_code": 30008, "to": TO})])
            mgr = twilio_manager(tmp_path / str(i), fake)
            mgr.on_event("alert", ev())
            assert mgr.wait_idle()
            mgr.stop()
            text += json.dumps(mgr.status()) + repr(mgr.notifier) + repr(load_settings(env(tmp_path))) + repr(mgr.__dict__)
            for f in (tmp_path / str(i)).rglob("*"):
                if f.is_file():
                    text += f.read_text(encoding="utf-8")
        text += caplog.text + "".join(str(r.__dict__) for r in caplog.records)
    assert "WhatsApp alert not sent" in text and "messages_handed_to_twilio" in text  # the haystack is not empty
    for secret in SECRETS:
        assert secret not in text, f"a secret value leaked: ...{secret[-6:]}"


def test_httpx_request_logging_is_off_because_the_url_contains_the_account_sid():
    import kami.notify.twilio  # noqa: F401

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING


def test_api_status_endpoint_reports_mode_and_counts_without_secrets(tmp_path):
    from kami.api.app import create_app
    from kami.ingest.bus import InProcessBus
    from kami.runtime import Stack
    from kami.store import SqliteStore

    stack = Stack.create(mode="fallback", store=SqliteStore(":memory:"), bus=InProcessBus())
    app = create_app(stack)
    with TestClient(app) as c:
        assert c.get("/notifications/status").status_code == 503  # live pipeline not started
        fake = Twilio()
        stack.extras["notifications"] = mgr = twilio_manager(tmp_path, fake)
        mgr.on_event("alert", ev())
        mgr.on_event("alert", ev(priority="Critical"))  # cooldown
        assert mgr.wait_idle()
        r = c.get("/notifications/status")
        s = r.json()
        assert r.status_code == 200 and s["mode"] == "twilio" and (s["sent"], s["suppressed"], s["failed"]) == (1, 1, 0)
        assert s["last_send_utc"] and s["limits"] == {"min_priority": "High", "cooldown_seconds_per_node": 600.0, "max_per_hour": 30, "max_total": 80}
        assert not any(v in r.text for v in SECRETS) and "whatsapp:+" not in r.text
        mgr.stop()


def test_live_system_defaults_to_a_forced_dry_run(tmp_path, monkeypatch):
    """build_live (used by every check script and test) never picks Twilio, even with complete credentials."""
    from kami.ingest.bus import InProcessBus
    from kami.live.system import build_live
    from kami.runtime import Stack
    from kami.store import SqliteStore

    for k, v in env(tmp_path).items():
        monkeypatch.setenv(k, v)
    stack = Stack.create(mode="fallback", store=SqliteStore(":memory:"), bus=InProcessBus())
    live = build_live(stack, speed=0)
    mgr = stack.extras["notifications"]
    assert mgr.status()["mode"] == "dry_run" and "forced" in mgr.status()["detail"]
    assert mgr.on_event in live.processor.listeners
    mgr.stop()


# ------------------------------------------------------------------ W7: the test-alert script
def _script():
    spec = importlib.util.spec_from_file_location("send_test_alert", ROOT / "scripts" / "send_test_alert.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_send_test_alert_is_a_dry_run_unless_enabled(tmp_path):
    out: list[str] = []
    fake = Twilio()
    code = _script().main(env=env(tmp_path, KAMI_WHATSAPP_ENABLE="0"), transport=fake.transport, out=out.append, check_delay=0.0)
    rows = read_log(tmp_path)
    assert code == 0 and fake.requests == [] and "Dry run, nothing was sent" in out[0]
    assert len(rows) == 1 and "TEST MESSAGE" in rows[0]["text"] and rows[0]["text"].startswith(PREFIX)


def test_send_test_alert_sends_exactly_one_labelled_message_when_enabled(tmp_path):
    out: list[str] = []
    fake = Twilio()
    code = _script().main(env=env(tmp_path), transport=fake.transport, out=out.append, check_delay=0.0)
    body = parse_qs(fake.requests[0].content.decode())["Body"][0]
    assert code == 0 and fake.n("POST") == 1 and "TEST MESSAGE" in body and body.startswith(PREFIX) and "Category: TEST" in body
    assert "accepted by Twilio" in out[0] and not any(v in " ".join(out) for v in SECRETS)
    closed = Twilio(post=[(400, {"code": 63016})])
    out.clear()
    assert _script().main(env=env(tmp_path / "b"), transport=closed.transport, out=out.append, check_delay=0.0) == 1
    assert "window closed: reply to the sandbox number to reopen" in out[0]


# ------------------------------------------------------------------ W6: the guard itself
def test_a_real_request_is_refused_and_would_fail_the_test(no_real_http):
    with pytest.raises(AssertionError, match="real HTTP request"):
        httpx.post("https://api.twilio.com/2010-04-01/Accounts/x/Messages.json", data={"Body": "x"})
    settings = load_settings({"KAMI_WHATSAPP_ENABLE": "1", "TWILIO_ACCOUNT_SID": SID, "TWILIO_AUTH_TOKEN": TOKEN,
                              "TWILIO_WHATSAPP_FROM": FROM, "WHATSAPP_TO": TO, "KAMI_NOTIFY_ENV_FILE": "no_such.env"})
    with pytest.raises(AssertionError, match="real HTTP request"):
        TwilioWhatsAppNotifier(settings).send("x", {})  # a notifier without a mock transport cannot get out either
    assert no_real_http == ["POST api.twilio.com", "POST api.twilio.com"]
    no_real_http.clear()  # the two attempts above were the point of this test

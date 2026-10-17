"""Alert push through a Telegram bot (PLAN_ROUND4.md T2, T4, T5). HTTP is mocked with httpx.MockTransport; conftest.py
refuses anything real."""
import importlib.util
import json
import logging
import time
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from kami.notify import DryRunNotifier, NotificationManager, TelegramNotifier, TriggerRule, build_manager, load_settings
from kami.notify.base import Notifier, SendOutcome
from kami.notify.message import PREFIX
from kami.notify.telegram import MSG_CHAT, MSG_FORBIDDEN, MSG_TOKEN

from .helpers import CHAT, OK, SECRETS, TOKEN, Bot, env, ev

ROOT = Path(__file__).resolve().parents[2]


def manager(tmp_path, bot: Bot, sleeps: list | None = None, real: bool = True, **over):
    kw = over.pop("kw", {})
    kw.setdefault("sleep", (sleeps if sleeps is not None else []).append)  # waits are recorded, not slept
    return build_manager({"node-1": "Katpadi Junction"}, allow_real_sending=real, env=env(tmp_path, **over), transport=bot.transport, **kw)


def run(mgr, *events):
    for e in events:
        mgr.on_event("alert", e)
    assert mgr.wait_idle()
    mgr.stop()
    return mgr.status()


def read_log(tmp_path) -> list[dict]:
    p = tmp_path / "notifications" / "dryrun_log.jsonl"
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def read_state(tmp_path) -> dict:
    return json.loads((tmp_path / "notifications" / "state.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ trigger rule (pure, time passed in)
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
    r = TriggerRule()
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


def test_there_is_no_lifetime_budget(tmp_path):
    now = [0.0]
    bot = Bot()
    mgr = manager(tmp_path, bot, kw={"clock": lambda: now[0]})
    for i in range(200):  # far more than any old budget; only the hourly cap limits it
        now[0] += 130.0
        mgr.on_event("alert", ev(node=f"node-{i}", id=i))
    assert mgr.wait_idle(30)
    mgr.stop()
    s = mgr.status()
    assert s["sent"] == 200 == bot.n and s["suppressed"] == 0
    assert "budget" not in json.dumps(s) and set(s["limits"]) == {"min_priority", "cooldown_seconds_per_node", "max_per_hour"}


# ------------------------------------------------------------------ dry run is the default and the fallback
def test_dry_run_writes_the_message_and_the_state_file(tmp_path):
    mgr = NotificationManager(DryRunNotifier(tmp_path / "notifications"), node_names={"node-1": "Katpadi Junction"},
                              state_path=tmp_path / "notifications" / "state.json")
    mgr.on_event("assessment", {"node_id": "node-1"})  # other listener events are ignored
    s = run(mgr, ev(priority="Medium"), ev(priority="High"), ev(priority="High", category="Combined"))  # one trigger only
    rows = read_log(tmp_path)
    assert len(rows) == 1 and rows[0]["mode"] == "dry_run"
    assert rows[0]["alert"]["id"] == 1 and rows[0]["alert"]["priority"] == "High" and rows[0]["alert"]["ts"] == "2018-01-07T16:50:00"
    assert rows[0]["text"].startswith(PREFIX) and "Katpadi Junction" in rows[0]["text"] and "model score 0.99" in rows[0]["text"]
    assert s["mode"] == "dry_run" and (s["sent"], s["suppressed"], s["failed"]) == (1, 0, 0) and s["last_send_utc"]
    st = read_state(tmp_path)
    assert (st["mode"], st["sent"], st["suppressed"], st["failed"]) == ("dry_run", 1, 0, 0) and st["last_send_utc"] == s["last_send_utc"]
    assert set(st) == {"mode", "sent", "suppressed", "failed", "suppressed_by", "last_send_utc", "last_problem", "started_utc", "updated_utc"}


@pytest.mark.parametrize("missing", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
def test_falls_back_to_dry_run_when_a_setting_is_missing_and_logs_the_name_only(tmp_path, caplog, missing):
    bot = Bot()
    with caplog.at_level(logging.DEBUG):
        mgr = manager(tmp_path, bot, **{missing: None})
        s = run(mgr, ev())
    assert s["mode"] == "dry_run" and missing in s["detail"] and s["sent"] == 1
    assert missing in caplog.text and not any(v in caplog.text + json.dumps(s) for v in SECRETS)
    assert bot.requests == [] and len(read_log(tmp_path)) == 1


@pytest.mark.parametrize("over", [{"KAMI_TELEGRAM_ENABLE": "0"}, {"KAMI_TELEGRAM_ENABLE": None}, {"KAMI_TELEGRAM_ENABLE": "yes"},
                                  {"TELEGRAM_BOT_TOKEN": "not-a-token"}, {"TELEGRAM_BOT_TOKEN": "123456:has space"},
                                  {"TELEGRAM_CHAT_ID": "@somebody"}, {"TELEGRAM_CHAT_ID": ""}])
def test_dry_run_unless_switched_on_and_well_formed(tmp_path, over):
    assert not load_settings(env(tmp_path, **over)).ready
    bot = Bot()
    s = run(manager(tmp_path, bot, **over), ev())
    assert s["mode"] == "dry_run" and bot.requests == [] and s["sent"] == 1


def test_complete_settings_are_ready_but_checks_and_tests_are_forced_to_dry_run(tmp_path):
    assert load_settings(env(tmp_path)).ready and load_settings(env(tmp_path, TELEGRAM_CHAT_ID="-1001234")).ready
    bot = Bot()
    s = run(manager(tmp_path, bot, real=False), ev())  # what build_live and launch() do by default
    assert s["mode"] == "dry_run" and "forced" in s["detail"] and bot.requests == [] and len(read_log(tmp_path)) == 1


def test_env_file_is_read_and_the_process_environment_wins(tmp_path):
    f = tmp_path / "x.env"
    f.write_text(f"# comment\nKAMI_TELEGRAM_ENABLE=1\nTELEGRAM_BOT_TOKEN='{TOKEN}'\nTELEGRAM_CHAT_ID={CHAT}\n", encoding="utf-8")
    s = load_settings({"KAMI_NOTIFY_ENV_FILE": str(f)})
    assert s.ready and s.value("TELEGRAM_BOT_TOKEN") == TOKEN and s.value("TELEGRAM_CHAT_ID") == CHAT
    assert not load_settings({"KAMI_NOTIFY_ENV_FILE": str(f), "KAMI_TELEGRAM_ENABLE": "0"}).ready
    assert not any(v in repr(s) + s.describe() + str(s) for v in SECRETS)


# ------------------------------------------------------------------ Telegram notifier over mocked HTTPS
def test_request_is_one_plain_text_post_to_send_message(tmp_path):
    bot = Bot()
    s = run(manager(tmp_path, bot), ev())
    assert bot.n == 1
    req = bot.requests[0]
    assert req.method == "POST" and str(req.url) == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert req.headers["content-type"] == "application/x-www-form-urlencoded"
    form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
    assert set(form) == {"chat_id", "text", "disable_web_page_preview"}  # plain text: no parse_mode
    assert form["chat_id"] == CHAT and form["disable_web_page_preview"] == "true"
    assert form["text"].startswith(PREFIX) and "Katpadi Junction (node-1 · Ward 1)" in form["text"] and len(form["text"]) < 600
    assert s["mode"] == "telegram" and (s["sent"], s["suppressed"], s["failed"]) == (1, 0, 0) and s["last_send_utc"]
    assert read_state(tmp_path)["sent"] == 1 and read_log(tmp_path) == []


@pytest.mark.parametrize("answer", [(500, {"ok": False, "error_code": 500, "description": "Internal Server Error"}), (502, None),
                                    httpx.ConnectError("boom"), httpx.ReadTimeout("slow")])
def test_network_and_server_errors_are_retried_at_most_twice_with_backoff(tmp_path, answer):
    bot, sleeps = Bot(answer), []
    mgr = manager(tmp_path, bot, sleeps)
    mgr.on_event("alert", ev())
    assert mgr.wait_idle()
    assert bot.n == 3 and sleeps == [2.0, 6.0]  # first attempt + two retries, never more
    s = mgr.status()
    assert (s["sent"], s["failed"]) == (0, 1) and "gave up after 3 attempts" in s["last_problem"]
    mgr.on_event("alert", ev(node="node-2", id=2))  # the loop is alive and the next alert is handled
    assert mgr.wait_idle() and bot.n == 6
    mgr.stop()


def test_a_retry_that_succeeds_counts_as_sent(tmp_path):
    bot = Bot((503, None), httpx.ConnectError("boom"), OK)
    s = run(manager(tmp_path, bot), ev())
    assert bot.n == 3 and (s["sent"], s["failed"]) == (1, 0)


def test_too_many_requests_waits_retry_after_once_then_gives_up(tmp_path):
    limited = (429, {"ok": False, "error_code": 429, "description": "Too Many Requests: retry after 7", "parameters": {"retry_after": 7}})
    bot, sleeps = Bot(limited), []
    s = run(manager(tmp_path, bot, sleeps), ev())
    assert bot.n == 2 and sleeps == [7.0]  # one wait, one more attempt, then give up
    assert (s["sent"], s["failed"]) == (0, 1)
    assert s["last_problem"] == "Alert message not sent: Telegram: too many requests, the message was not sent; gave up after 2 attempts (HTTP 429, error_code 429)"


def test_too_many_requests_wait_is_capped_and_a_later_success_counts(tmp_path):
    bot, sleeps = Bot((429, {"ok": False, "error_code": 429, "parameters": {"retry_after": 5000}}), OK), []
    s = run(manager(tmp_path / "a", bot, sleeps), ev())
    assert bot.n == 2 and sleeps == [60.0] and (s["sent"], s["failed"]) == (1, 0)
    bot, sleeps = Bot((429, {"ok": False}), OK), []  # no retry_after given: a short default wait
    s = run(manager(tmp_path / "b", bot, sleeps), ev())
    assert sleeps == [1.0] and s["sent"] == 1


@pytest.mark.parametrize("answer, sentence", [
    ((401, {"ok": False, "error_code": 401, "description": "Unauthorized"}), MSG_TOKEN),
    ((404, {"ok": False, "error_code": 404, "description": "Not Found"}), MSG_TOKEN),
    ((400, {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}), MSG_CHAT),
    ((403, {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}), MSG_FORBIDDEN),
    ((403, {"ok": False, "error_code": 403, "description": "Forbidden: bot can't initiate conversation with a user"}), MSG_FORBIDDEN),
])
def test_token_chat_and_blocked_errors_are_not_retried_and_give_one_clear_line(tmp_path, caplog, answer, sentence):
    bot, sleeps = Bot(answer), []
    with caplog.at_level(logging.DEBUG):
        mgr = manager(tmp_path, bot, sleeps)
        mgr.on_event("alert", ev())
        assert mgr.wait_idle()
        mgr.on_event("alert", ev(node="node-2", id=2))  # held back for a while: asking again would fail the same way
        assert mgr.wait_idle()
        mgr.stop()
    s = mgr.status()
    assert bot.n == 1 and sleeps == []
    assert (s["sent"], s["suppressed"], s["failed"]) == (0, 1, 1) and s["suppressed_by"] == {"on_hold": 1}
    line = f"Alert message not sent: {sentence} (HTTP {answer[0]}, error_code {answer[0]})"
    assert s["last_problem"] == line
    assert [r.getMessage() for r in caplog.records if "not sent" in r.getMessage()] == [line]
    assert answer[1]["description"] not in caplog.text + json.dumps(s)  # Telegram's own text is never passed on


def test_fixed_sentences_name_the_setting_and_the_helper_script():
    assert MSG_TOKEN == "Telegram: bot token rejected, check TELEGRAM_BOT_TOKEN in .env"
    assert MSG_CHAT == "Telegram: chat not found, press Start in the bot and run scripts/telegram_find_chat.py"


def test_other_rejections_fail_without_retry_and_without_a_pause(tmp_path):
    bot = Bot((400, {"ok": False, "error_code": 400, "description": "Bad Request: message is too long"}), (200, {"ok": False}), (200, None), OK)
    mgr = manager(tmp_path, bot)
    s = run(mgr, *[ev(node=f"node-{i}", id=i) for i in range(4)])
    assert bot.n == 4 and (s["sent"], s["suppressed"], s["failed"]) == (1, 0, 3)


def test_cooldown_and_cap_are_enforced_by_the_manager(tmp_path):
    now = [1000.0]
    bot = Bot()
    mgr = manager(tmp_path, bot, kw={"clock": lambda: now[0]})
    mgr.on_event("alert", ev(id=1))
    mgr.on_event("alert", ev(id=1, priority="Critical"))  # 0 s later: cooldown
    now[0] += 601
    mgr.on_event("alert", ev(id=1, priority="Critical", category="Combined"))  # still not notified at Critical: sent now
    for i in range(2, 40):  # other nodes: the hourly cap stops them at 30 in total
        mgr.on_event("alert", ev(node=f"node-{i}", id=i))
    assert mgr.wait_idle()
    mgr.stop()
    s = mgr.status()
    assert bot.n == 30 and s["sent"] == 30 and s["messages_last_hour"] == 30
    assert s["suppressed_by"] == {"cooldown": 1, "hourly_cap": 10} and s["suppressed"] == 11
    assert read_state(tmp_path)["suppressed_by"] == {"cooldown": 1, "hourly_cap": 10}


# ------------------------------------------------------------------ never crash or block the processing loop
class Exploding(Notifier):
    mode = "telegram"

    def send(self, text, alert):
        raise RuntimeError(f"boom https://api.telegram.org/bot{TOKEN}/sendMessage")


class Slow(Notifier):
    mode = "telegram"

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
    assert not any(v in caplog.text + json.dumps(s) for v in SECRETS)  # exception texts are never logged
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


# ------------------------------------------------------------------ the token and the chat id never leave the notifier
def test_token_and_chat_id_never_appear_in_logs_status_state_or_dry_run_log(tmp_path, caplog):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    answers = [OK,
               (401, {"ok": False, "error_code": 401, "description": f"Unauthorized: token {TOKEN}"}),
               (400, {"ok": False, "error_code": 400, "description": f"Bad Request: chat not found {CHAT}"}),
               (400, {"ok": False, "error_code": 400, "description": f"Bad Request: chat_id {CHAT} is wrong"}),
               (403, {"ok": False, "error_code": 403, "description": f"Forbidden for {CHAT}"}),
               (429, {"ok": False, "error_code": 429, "description": url, "parameters": {"retry_after": 1}}),
               httpx.ConnectError(f"cannot reach {url} for chat {CHAT}"),
               (500, {"ok": False, "description": TOKEN})]
    text = ""
    with caplog.at_level(logging.DEBUG):
        for i, a in enumerate(answers):
            mgr = manager(tmp_path / str(i), Bot(a))
            run(mgr, ev())
            text += json.dumps(mgr.status()) + repr(mgr.notifier) + repr(load_settings(env(tmp_path))) + repr(mgr.__dict__)
        dry = manager(tmp_path / "dry", Bot(), real=False)  # complete settings present, dry run forced
        run(dry, ev())
        text += json.dumps(dry.status()) + repr(dry.__dict__)
        for f in tmp_path.rglob("*"):
            if f.is_file():
                text += f.read_text(encoding="utf-8")
        text += caplog.text + "".join(str(r.__dict__) for r in caplog.records)
    assert "Alert message not sent" in text and '"mode": "telegram"' in text and "dryrun_log" not in text  # the haystack is real
    assert sum(1 for f in tmp_path.rglob("state.json")) == 9 and len(read_log(tmp_path / "dry")) == 1
    for secret in SECRETS:
        assert secret not in text, "a secret value leaked"


def test_httpx_request_logging_is_off_because_the_url_contains_the_token():
    import kami.notify.telegram  # noqa: F401

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
        stack.extras["notifications"] = mgr = manager(tmp_path, Bot())
        mgr.on_event("alert", ev())
        mgr.on_event("alert", ev(priority="Critical"))  # cooldown
        assert mgr.wait_idle()
        r = c.get("/notifications/status")
        s = r.json()
        assert r.status_code == 200 and s["mode"] == "telegram" and (s["sent"], s["suppressed"], s["failed"]) == (1, 1, 0)
        assert s["last_send_utc"] and s["limits"] == {"min_priority": "High", "cooldown_seconds_per_node": 600.0, "max_per_hour": 30}
        assert not any(v in r.text for v in SECRETS)
        mgr.stop()


def test_live_system_defaults_to_a_forced_dry_run(tmp_path, monkeypatch):
    """build_live (used by every check script and test) never picks Telegram, even with complete settings."""
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


# ------------------------------------------------------------------ the test-alert script
def _script(name="send_test_alert"):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_send_test_alert_is_a_dry_run_unless_enabled(tmp_path):
    out: list[str] = []
    bot = Bot()
    code = _script().main(env=env(tmp_path, KAMI_TELEGRAM_ENABLE="0"), transport=bot.transport, out=out.append)
    rows = read_log(tmp_path)
    assert code == 0 and bot.requests == [] and "Dry run, nothing was sent (KAMI_TELEGRAM_ENABLE is not 1)" in out[0]
    assert len(rows) == 1 and "TEST MESSAGE" in rows[0]["text"] and "not an alert" in rows[0]["text"] and rows[0]["text"].startswith(PREFIX)


def test_send_test_alert_sends_exactly_one_labelled_message_when_enabled(tmp_path):
    out: list[str] = []
    bot = Bot()
    code = _script().main(env=env(tmp_path), transport=bot.transport, out=out.append)
    body = parse_qs(bot.requests[0].content.decode())["text"][0]
    assert code == 0 and bot.n == 1 and body.startswith(PREFIX) and "Category: TEST" in body
    assert "TEST MESSAGE" in body and "not an alert" in body and len(body) < 600
    assert "accepted by Telegram" in out[0] and not any(v in " ".join(out) for v in SECRETS)
    out.clear()
    bad = Bot((400, {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}))
    assert _script().main(env=env(tmp_path / "b"), transport=bad.transport, out=out.append) == 1
    assert MSG_CHAT in out[0] and not any(v in " ".join(out) for v in SECRETS)


# ------------------------------------------------------------------ the guard itself
def test_a_real_request_is_refused_and_would_fail_the_test(no_real_http, tmp_path):
    with pytest.raises(AssertionError, match="real HTTP request"):
        httpx.post("https://api.telegram.org/botX/sendMessage", data={"text": "x"})
    with pytest.raises(AssertionError, match="real HTTP request"):
        TelegramNotifier(load_settings(env(tmp_path))).send("x", {})  # a notifier without a mock transport cannot get out either
    assert no_real_http == ["POST api.telegram.org", "POST api.telegram.org"]
    no_real_http.clear()  # the two attempts above were the point of this test

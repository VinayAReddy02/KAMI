"""Shared test doubles for the alert-push tests. All values are obviously fake."""
import httpx

TOKEN = "123456:TEST-TOKEN"
CHAT = "7700112233"
SECRETS = (TOKEN, TOKEN.split(":")[1], CHAT)
OK = (200, {"ok": True, "result": {"message_id": 1}})


def ev(node="node-1", id=1, priority="High", category="Infrastructure", status="active", ts="2018-01-07T16:50:00", **over):
    """An alert event as the live processor emits it."""
    e = {"id": id, "node_id": node, "category": category, "priority": priority, "max_priority": priority, "start_ts": "2018-01-07T15:00:00",
         "last_ts": ts, "end_ts": None, "status": status, "confidence": 0.63,
         "explanation": f"{category} anomaly, priority {priority} (confidence 0.63): infrastructure evidence 0.99, above threshold for 1.8 h, "
                        "suddenness 1.00, 1 episode(s) in the last 7 days.",
         "p_infra": 0.99, "p_quality": 0.02,
         "temporal": {"infra_persist_steps": 22.0, "infra_suddenness": 1.0, "infra_persist_frac": 0.3, "infra_recurrence": 1.0,
                      "quality_persist_steps": 0.0, "quality_suddenness": 0.0, "quality_persist_frac": 0.0, "quality_recurrence": 0.0}}
    e.update(over)
    return e


def env(tmp_path, **over):
    """A complete, enabled configuration; pass NAME=None to leave a setting out."""
    e = {"KAMI_TELEGRAM_ENABLE": "1", "TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": CHAT,
         "KAMI_NOTIFY_ENV_FILE": str(tmp_path / "no_such.env"), "KAMI_NOTIFY_DIR": str(tmp_path / "notifications")}
    e.update(over)
    return {k: v for k, v in e.items() if v is not None}


class Bot:
    """Scripted stand-in for api.telegram.org. `answers` is a list of (status, json) or exceptions; the last one repeats."""

    def __init__(self, *answers):
        self.answers = list(answers) or [OK]
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, Exception):
            raise a
        return httpx.Response(a[0], json=a[1]) if a[1] is not None else httpx.Response(a[0], text="<html>not json</html>")

    @property
    def n(self) -> int:
        return len(self.requests)

    @property
    def transport(self):
        return httpx.MockTransport(self)

"""WhatsApp through the Twilio Messages REST API: one plain HTTPS POST per message (httpx, no Twilio SDK).

    POST https://api.twilio.com/2010-04-01/Accounts/{AccountSid}/Messages.json   (HTTP Basic auth, form fields To/From/Body)

Nothing here logs or returns a credential, the recipient number, the request, the URL (it contains the Account SID),
an exception text or Twilio's own error text. Outcomes carry the HTTP status, Twilio's numeric error code and one of
the fixed sentences below.
"""
from __future__ import annotations

import logging

import httpx

from .base import Notifier, SendOutcome
from .settings import Settings

# httpx logs every request URL at INFO level, and the URL contains the Account SID
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

API_ROOT = "https://api.twilio.com/2010-04-01/Accounts"
WINDOW_CLOSED = 63016  # free-form message outside the 24 h window after the recipient's last message
NOT_JOINED = 63015  # sandbox: the recipient has not joined, or the join expired (after 3 days)
BAD_CREDENTIALS = 20003
MSG_WINDOW = "window closed: reply to the sandbox number to reopen"
MSG_JOIN = "recipient has not joined the sandbox or the join expired: send the join code to the sandbox number again"
MSG_AUTH = "Twilio rejected the credentials: check TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env"


def _body(r: httpx.Response) -> dict:
    try:
        b = r.json()
    except ValueError:
        return {}
    return b if isinstance(b, dict) else {}


def _code(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def classify(status: int, code: int | None, sid: str | None = None) -> SendOutcome:
    """Map an HTTP status and a Twilio error code to an outcome. No retry for anything the same request cannot fix."""
    if code == WINDOW_CLOSED:
        return SendOutcome("suppressed", status, code, MSG_WINDOW, sid)
    if code == NOT_JOINED:
        return SendOutcome("failed", status, code, MSG_JOIN, sid)
    if status in (401, 403) or code == BAD_CREDENTIALS:
        return SendOutcome("failed", status, code, MSG_AUTH, sid)
    if 200 <= status < 300 and code is None:
        return SendOutcome("sent", status, None, "", sid)
    if status == 429 or status >= 500:
        return SendOutcome("retry", status, code, f"Twilio is busy or unavailable (HTTP {status})", sid)
    return SendOutcome("failed", status, code, f"Twilio did not accept the message (HTTP {status}, Twilio error {code})", sid)


class TwilioWhatsAppNotifier(Notifier):
    mode = "twilio"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None, timeout: float = 10.0):
        if not settings.ready:
            raise ValueError("WhatsApp sending is not enabled or a setting is missing: " + settings.describe())
        self._url = f"{API_ROOT}/{settings.value('TWILIO_ACCOUNT_SID')}/Messages"
        self._from, self._to = settings.value("TWILIO_WHATSAPP_FROM"), settings.value("WHATSAPP_TO")
        self._client = httpx.Client(auth=(settings.value("TWILIO_ACCOUNT_SID"), settings.value("TWILIO_AUTH_TOKEN")),
                                    timeout=timeout, transport=transport)

    def __repr__(self) -> str:  # never show the URL, the numbers or the credentials
        return "TwilioWhatsAppNotifier()"

    def send(self, text: str, alert: dict) -> SendOutcome:
        try:
            r = self._client.post(self._url + ".json", data={"To": self._to, "From": self._from, "Body": text})
        except httpx.HTTPError as e:
            return SendOutcome("retry", reason=f"network error ({type(e).__name__})")
        b = _body(r)
        ok = 200 <= r.status_code < 300
        sid = b.get("sid") if ok and isinstance(b.get("sid"), str) and b["sid"].isalnum() and len(b["sid"]) <= 64 else None
        return classify(r.status_code, _code(b.get("error_code") if ok else b.get("code")), sid)

    def check(self, sid: str) -> SendOutcome | None:
        """One later look at an accepted message: Twilio may report the window or sandbox error only afterwards."""
        try:
            r = self._client.get(f"{self._url}/{sid}.json")
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        b = _body(r)
        code = _code(b.get("error_code"))
        if code == WINDOW_CLOSED:
            return SendOutcome("suppressed", 200, code, MSG_WINDOW, sid)
        if code == NOT_JOINED:
            return SendOutcome("failed", 200, code, MSG_JOIN, sid)
        if code is not None or b.get("status") in ("failed", "undelivered"):
            return SendOutcome("failed", 200, code, f"Twilio reported the message as not delivered (Twilio error {code})", sid)
        return None

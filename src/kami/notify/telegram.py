"""Telegram bot notifier: one HTTPS POST per message to the Bot API method sendMessage (httpx, no Telegram SDK).

    POST https://api.telegram.org/bot<TOKEN>/sendMessage     fields: chat_id, text, disable_web_page_preview=true

The text is plain: no parse_mode, so nothing in an explanation can break the formatting. The bot token is part of the
URL, therefore nothing here logs or returns a URL, the token, the chat id, an exception text or Telegram's own
`description`. Outcomes carry the HTTP status, Telegram's numeric `error_code` and one of the fixed sentences below.
"""
from __future__ import annotations

import logging

import httpx

from .base import Notifier, SendOutcome
from .settings import CHAT, TOKEN, Settings

# httpx logs every request URL at INFO level, and the URL contains the bot token
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

API_ROOT = "https://api.telegram.org"
MAX_WAIT_S = 60.0
MSG_TOKEN = "Telegram: bot token rejected, check TELEGRAM_BOT_TOKEN in .env"
MSG_CHAT = "Telegram: chat not found, press Start in the bot and run scripts/telegram_find_chat.py"
MSG_FORBIDDEN = "Telegram: the bot may not write to this chat (it was blocked or Start was never pressed), press Start in the bot"
MSG_LIMIT = "Telegram: too many requests, the message was not sent"
MSG_SERVER = "Telegram: service unavailable"
MSG_NETWORK = "Telegram: network error"
MSG_REJECTED = "Telegram: the message was not accepted"
MSG_ODD = "Telegram: unexpected answer"


def body_of(r: httpx.Response) -> dict:
    try:
        b = r.json()
    except ValueError:
        return {}
    return b if isinstance(b, dict) else {}


def _int(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def classify(status: int, body: dict) -> SendOutcome:
    """Map one Bot API answer to an outcome. `description` is read to recognise "chat not found" and is never passed on."""
    code = _int(body.get("error_code"))
    if status == 200 and body.get("ok") is True:
        return SendOutcome("sent", status)
    if status in (401, 404):  # 404 is what the API answers for a token that does not have the right shape
        return SendOutcome("failed", status, code, MSG_TOKEN, pause=True)
    if status == 403:
        return SendOutcome("failed", status, code, MSG_FORBIDDEN, pause=True)
    if status == 400 and "chat not found" in str(body.get("description", "")).lower():
        return SendOutcome("failed", status, code, MSG_CHAT, pause=True)
    if status == 429:
        params = body.get("parameters") if isinstance(body.get("parameters"), dict) else {}
        after = params.get("retry_after")
        after = float(after) if isinstance(after, (int, float)) and not isinstance(after, bool) and after > 0 else 1.0
        return SendOutcome("wait", status, code, MSG_LIMIT, retry_after=min(after, MAX_WAIT_S))
    if status >= 500:
        return SendOutcome("retry", status, code, MSG_SERVER)
    if status == 200:
        return SendOutcome("failed", status, code, MSG_ODD)
    return SendOutcome("failed", status, code, MSG_REJECTED)


class TelegramNotifier(Notifier):
    mode = "telegram"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None, timeout: float = 10.0):
        if not settings.ready:
            raise ValueError("Telegram sending is not enabled or a setting is missing: " + settings.describe())
        self._url = f"{API_ROOT}/bot{settings.value(TOKEN)}/sendMessage"
        self._chat = settings.value(CHAT)
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def __repr__(self) -> str:  # never show the URL (it contains the token) or the chat id
        return "TelegramNotifier()"

    def send(self, text: str, alert: dict) -> SendOutcome:
        try:
            r = self._client.post(self._url, data={"chat_id": self._chat, "text": text, "disable_web_page_preview": "true"})
        except httpx.HTTPError as e:
            return SendOutcome("retry", reason=f"{MSG_NETWORK} ({type(e).__name__})")
        return classify(r.status_code, body_of(r))

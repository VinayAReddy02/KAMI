"""Telegram Bot API for the citizen interface: long polling in, text and voice out (httpx, no Telegram SDK).

    getUpdates (offset, long poll)   getFile + file download   sendMessage   sendVoice (OGG/Opus)   sendChatAction

The bot token is part of every URL, including file downloads. So, as in notify/telegram.py, nothing here logs or
returns a URL, the token, a chat id, an exception text or Telegram's own `description`. Errors carry a fixed
sentence, the HTTP status and Telegram's numeric `error_code`.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

import httpx

from ..notify.telegram import API_ROOT, body_of  # importing it also keeps httpx request logging off

log = logging.getLogger("kami.citizen")
POLL_SECONDS = 25
BACKOFF = (2.0, 5.0, 15.0, 30.0)
SENTENCES = {
    "network": "Telegram: network error",
    "token": "Telegram: bot token rejected, check TELEGRAM_BOT_TOKEN in .env",
    "conflict": "Telegram: another program is reading this bot's messages (or a webhook is set); only one poller can run",
    "limit": "Telegram: too many requests",
    "server": "Telegram: service unavailable",
    "rejected": "Telegram: the request was not accepted",
    "too_big": "Telegram: the file is larger than the allowed size",
}


class BotApiError(Exception):
    """kind: network | token | conflict | limit | server | rejected | too_big. The text is a fixed sentence."""

    def __init__(self, kind: str, status: int | None = None, code: int | None = None, retry_after: float | None = None, detail: str = ""):
        self.kind, self.status, self.code, self.retry_after = kind, status, code, retry_after
        extra = [f"HTTP {status}"] if status else []
        if code is not None:
            extra.append(f"error_code {code}")
        if detail:
            extra.append(detail)  # an exception TYPE name only, never its text
        super().__init__(SENTENCES[kind] + (f" ({', '.join(extra)})" if extra else ""))


def _kind(status: int) -> str:
    if status in (401, 404):
        return "token"
    if status == 409:
        return "conflict"
    if status == 429:
        return "limit"
    return "server" if status >= 500 else "rejected"


class TelegramClient:
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None, timeout: float = 20.0):
        self._base = f"{API_ROOT}/bot{token}"
        self._files = f"{API_ROOT}/file/bot{token}"
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def __repr__(self) -> str:  # never show the URLs (they contain the token)
        return "TelegramClient()"

    def _call(self, method: str, timeout: float | None = None, **kw):
        try:
            r = self._client.post(f"{self._base}/{method}", timeout=timeout or self._client.timeout, **kw)
        except httpx.HTTPError as e:
            raise BotApiError("network", detail=type(e).__name__) from None
        b = body_of(r)
        if r.status_code == 200 and b.get("ok") is True:
            return b.get("result")
        code = b.get("error_code") if isinstance(b.get("error_code"), int) else None
        params = b.get("parameters") if isinstance(b.get("parameters"), dict) else {}
        after = params.get("retry_after")
        raise BotApiError(_kind(r.status_code) if r.status_code != 200 else "rejected", r.status_code, code,
                          float(after) if isinstance(after, (int, float)) and not isinstance(after, bool) else None)

    def get_updates(self, offset: int | None, poll_seconds: int = POLL_SECONDS) -> list:
        data = {"timeout": poll_seconds, "allowed_updates": '["message"]'}
        if offset is not None:
            data["offset"] = offset
        out = self._call("getUpdates", timeout=poll_seconds + 15, data=data)
        return out if isinstance(out, list) else []

    def get_file(self, file_id: str) -> tuple[str, int]:
        """(path on the file server, size in bytes or 0 if not given)."""
        f = self._call("getFile", data={"file_id": file_id})
        if not isinstance(f, dict) or not isinstance(f.get("file_path"), str):
            raise BotApiError("rejected")
        return f["file_path"], int(f.get("file_size") or 0)

    def download(self, file_path: str, max_bytes: int) -> bytes:
        """The file content; stops reading as soon as it is larger than `max_bytes`."""
        try:
            with self._client.stream("GET", f"{self._files}/{file_path}") as r:
                if r.status_code != 200:
                    raise BotApiError(_kind(r.status_code), r.status_code)
                chunks, n = [], 0
                for chunk in r.iter_bytes():
                    n += len(chunk)
                    if n > max_bytes:
                        raise BotApiError("too_big")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as e:
            raise BotApiError("network", detail=type(e).__name__) from None

    def send_message(self, chat_id: int, text: str) -> None:
        self._call("sendMessage", data={"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"})

    def send_voice(self, chat_id: int, ogg_opus: bytes) -> None:
        self._call("sendVoice", data={"chat_id": chat_id}, files={"voice": ("answer.ogg", ogg_opus, "audio/ogg")})

    def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        try:
            self._call("sendChatAction", data={"chat_id": chat_id, "action": action})
        except BotApiError:
            pass  # cosmetic only


class Poller:
    """Background thread: long-polls getUpdates with an offset and hands every update to `handler`.

    Messages that were already waiting when the poller starts are skipped (an old question is not answered late).
    A handler error never stops the thread; a rejected token does (retrying cannot help)."""

    def __init__(self, client: TelegramClient, handler: Callable[[dict], None], sleep: Callable[[float], object] | None = None):
        self.client, self.handler = client, handler
        self.updates = self.errors = self.skipped = 0
        self.state = "stopped"  # stopped | polling | stopped: <fixed sentence>
        self._stop = threading.Event()
        self._sleep = sleep or self._stop.wait
        self._thread = threading.Thread(target=self._run, name="kami-citizen-poll", daemon=True)

    def start(self) -> None:
        self.state = "polling"
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def _skip_backlog(self) -> int | None:
        last = self.client.get_updates(-1, poll_seconds=0)
        ids = [u["update_id"] for u in last if isinstance(u, dict) and isinstance(u.get("update_id"), int)]
        if not ids:
            return None
        self.skipped = 1  # at least one message was waiting; how many exactly is not known and not needed
        return max(ids) + 1

    def _run(self) -> None:
        offset, started, fails = None, False, 0
        while not self._stop.is_set():
            try:
                if not started:
                    offset, started = self._skip_backlog(), True
                    continue
                batch = self.client.get_updates(offset)
                fails = 0
            except BotApiError as e:
                self.errors += 1
                if e.kind == "token":
                    self.state = "stopped: " + SENTENCES["token"]
                    log.warning("citizen bot stopped: %s", e)
                    return
                wait = min(e.retry_after or 0, 60.0) if e.kind == "limit" else 0.0
                wait = max(wait, 30.0 if e.kind == "conflict" else BACKOFF[min(fails, len(BACKOFF) - 1)])
                fails += 1
                log.warning("citizen bot: %s; next try in %.0f s", e, wait)
                self._sleep(wait)
                continue
            for u in batch:
                if not isinstance(u, dict) or not isinstance(u.get("update_id"), int):
                    continue
                offset = u["update_id"] + 1 if offset is None else max(offset, u["update_id"] + 1)
                self.updates += 1
                try:
                    self.handler(u)
                except Exception as e:  # one bad message must not end the polling
                    self.errors += 1
                    log.warning("citizen bot: a message could not be handled (%s)", type(e).__name__)
        self.state = "stopped"

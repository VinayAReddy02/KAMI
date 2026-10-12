"""Settings of the citizen interface. Read from the process environment or from `.env` (git-ignored), like the alert
push. The bot token and every chat id are secrets: their values are never logged, printed or returned by a status call."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..notify.settings import _SHAPE, CHAT, ROOT, TOKEN, env_file, read_env_file

ENABLE, ALLOWED = "KAMI_CITIZEN_ENABLE", "CITIZEN_ALLOWED_CHAT_IDS"
DEFAULT_OLLAMA_URL, DEFAULT_OLLAMA_MODEL = "http://127.0.0.1:11434", "llama3.2:3b"
DATA_DIR = ROOT / "data" / "citizen"  # tracked demo data (fictional)


def work_dir(env=None) -> Path:
    """Where uploads go (git-ignored). KAMI_CITIZEN_DIR redirects it, for tests and checks."""
    env = os.environ if env is None else env
    return Path(env.get("KAMI_CITIZEN_DIR") or DATA_DIR)


@dataclass(frozen=True)
class CitizenSettings:
    enable_requested: bool
    missing: tuple  # names of settings that are absent or malformed
    asr: str = ""
    tts: str = ""
    device: str = "cuda"
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    ollama_url: str = DEFAULT_OLLAMA_URL
    _token: str = field(default="", repr=False, compare=False)
    _allowed: frozenset = field(default_factory=frozenset, repr=False, compare=False)

    @property
    def ready(self) -> bool:
        """Inbound handling is possible only when it was switched on AND the token and at least one allowed chat are usable."""
        return self.enable_requested and not self.missing

    @property
    def token(self) -> str:
        return self._token

    def is_allowed(self, chat_id) -> bool:
        return isinstance(chat_id, int) and not isinstance(chat_id, bool) and chat_id in self._allowed

    @property
    def allowed_count(self) -> int:
        return len(self._allowed)

    def __repr__(self) -> str:  # never show values
        return f"CitizenSettings(enable_requested={self.enable_requested}, missing={self.missing}, allowed_chats={len(self._allowed)})"

    def describe(self) -> str:
        """One line for the log and the status: names only."""
        if self.ready:
            return "citizen bot is on"
        if not self.enable_requested:
            return f"{ENABLE} is not 1"
        return f"{ENABLE}=1 but missing or malformed in .env: " + ", ".join(self.missing)


def load_citizen_settings(env=None) -> CitizenSettings:
    env = os.environ if env is None else env
    file_vals = read_env_file(env_file(env))

    def get(k: str, default: str = "") -> str:
        return (env.get(k) or file_vals.get(k) or default).strip()  # the process environment wins over the file

    token, chat = get(TOKEN), get(CHAT)
    missing = [k for k, v in ((TOKEN, token), (CHAT, chat)) if not _SHAPE[k].fullmatch(v)]
    allowed, extra_ok = set(), True
    if CHAT not in missing:
        allowed.add(int(chat))
    for part in get(ALLOWED).split(","):
        part = part.strip()
        if not part:
            continue
        if _SHAPE[CHAT].fullmatch(part):
            allowed.add(int(part))
        else:
            extra_ok = False
    if not extra_ok:
        missing.append(ALLOWED)
    url = get("OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/")
    device = get("CITIZEN_DEVICE", "cuda").lower()
    return CitizenSettings(get(ENABLE) == "1", tuple(missing), get("CITIZEN_ASR"), get("CITIZEN_TTS"), device if device in ("cuda", "cpu") else "cuda",
                           get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL), url, token if TOKEN not in missing else "", frozenset(allowed))

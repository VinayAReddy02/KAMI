"""Settings of the alert push. The bot token and the chat id come only from the process environment or from `.env` in
the repo root (git-ignored). Their values are never logged, printed or returned by any status call; only setting NAMES are."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKEN, CHAT, ENABLE = "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "KAMI_TELEGRAM_ENABLE"
SECRETS = (TOKEN, CHAT)
_SHAPE = {TOKEN: re.compile(r"\d+:[A-Za-z0-9_-]+"),  # <bot id>:<secret>, as @BotFather gives it
          CHAT: re.compile(r"-?\d+")}  # a numeric chat id (private chats are positive, groups negative)


def notify_dir(env=None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("KAMI_NOTIFY_DIR") or ROOT / "results" / "notifications")


def env_file(env=None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("KAMI_NOTIFY_ENV_FILE") or ROOT / ".env")


def read_env_file(path: Path) -> dict:
    """Minimal KEY=VALUE parser (comments and blank lines ignored, optional quotes stripped)."""
    out = {}
    if not Path(path).is_file():
        return out
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


@dataclass(frozen=True)
class Settings:
    enable_requested: bool
    missing: tuple  # names of settings that are absent or malformed
    _values: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def ready(self) -> bool:
        """Real sending is possible only when it was switched on AND the token and the chat id are usable."""
        return self.enable_requested and not self.missing

    def value(self, name: str) -> str:
        return self._values[name]

    def __repr__(self) -> str:  # never show values
        return f"Settings(enable_requested={self.enable_requested}, missing={self.missing})"

    def describe(self) -> str:
        """One line for the log and the status: names only."""
        if self.ready:
            return "Telegram sending is on"
        if not self.enable_requested:
            return f"{ENABLE} is not 1"
        return f"{ENABLE}=1 but missing or malformed in .env: " + ", ".join(self.missing)


def load_settings(env=None) -> Settings:
    env = os.environ if env is None else env
    file_vals = read_env_file(env_file(env))

    def get(k: str) -> str:
        return (env.get(k) or file_vals.get(k) or "").strip()  # the process environment wins over the file

    values = {k: get(k) for k in SECRETS}
    missing = tuple(k for k in SECRETS if not _SHAPE[k].fullmatch(values[k]))
    return Settings(get(ENABLE) == "1", missing, values)

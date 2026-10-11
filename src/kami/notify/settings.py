"""Settings for the WhatsApp alert push. Credentials come only from the process environment or from `.env` in the
repo root (git-ignored). Values are never logged, printed or returned by any status call; only setting NAMES are."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CREDENTIALS = ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM", "WHATSAPP_TO")
DEFAULT_MAX_TOTAL = 80


def notify_dir(env=None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("KAMI_NOTIFY_DIR") or ROOT / "results" / "notifications")


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
    max_total: int
    missing: tuple  # names of credentials that are absent or malformed
    _values: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def ready(self) -> bool:
        """WhatsApp sending is allowed only when it was switched on AND all four credentials are usable."""
        return self.enable_requested and not self.missing

    def value(self, name: str) -> str:
        return self._values[name]

    def __repr__(self) -> str:  # never show values
        return f"Settings(enable_requested={self.enable_requested}, max_total={self.max_total}, missing={self.missing})"

    def describe(self) -> str:
        """One line for the log: names only."""
        if self.ready:
            return "WhatsApp sending is ON"
        if not self.enable_requested:
            return "dry run: KAMI_WHATSAPP_ENABLE is not 1"
        return "dry run: KAMI_WHATSAPP_ENABLE=1 but these settings are missing or malformed: " + ", ".join(self.missing)


def load_settings(env=None, env_file: Path | None = None) -> Settings:
    env = os.environ if env is None else env
    env_file = Path(env_file or env.get("KAMI_NOTIFY_ENV_FILE") or ROOT / ".env")
    file_vals = read_env_file(env_file)

    def get(k: str) -> str:
        return (env.get(k) or file_vals.get(k) or "").strip()  # the process environment wins over the file

    values = {k: get(k) for k in CREDENTIALS}
    missing = [k for k in CREDENTIALS if not values[k]]
    for k in ("TWILIO_WHATSAPP_FROM", "WHATSAPP_TO"):  # Twilio needs the channel prefix and a full number
        v = values[k]
        if v and not (v.startswith("whatsapp:+") and v[len("whatsapp:+"):].isdigit()):
            missing.append(k)
    try:
        max_total = max(0, int(get("WHATSAPP_MAX_TOTAL") or DEFAULT_MAX_TOTAL))
    except ValueError:
        max_total = DEFAULT_MAX_TOTAL
    return Settings(get("KAMI_WHATSAPP_ENABLE") == "1", max_total, tuple(missing), values)

"""Runtime configuration: backend selection and ports."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MQTT_PORT = int(os.environ.get("KAMI_MQTT_PORT", 1883))
PG_PORT = int(os.environ.get("KAMI_PG_PORT", 5432))
API_PORT = int(os.environ.get("KAMI_API_PORT", 8000))
TOPIC_READINGS = "kami/nodes/{node_id}/readings"
TOPIC_READINGS_ALL = "kami/nodes/+/readings"
SQLITE_PATH = Path(os.environ.get("KAMI_SQLITE", ROOT / "data" / "processed" / "kami.sqlite"))
PG_DSN = os.environ.get("KAMI_PG_DSN", f"postgresql://kami:kami@localhost:{PG_PORT}/kami")


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


def port_open(port: int, host: str = "localhost", timeout: float = 0.5) -> bool:
    import socket

    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def stack_up() -> bool:
    """True if the MQTT broker and TimescaleDB of docker-compose.yml accept connections."""
    return port_open(MQTT_PORT) and port_open(PG_PORT)


def resolve_mode() -> str:
    """'docker' (MQTT + TimescaleDB) or 'fallback' (in-process bus + SQLite).

    Override with KAMI_MODE=docker|fallback. Without it, docker mode is chosen only when the stack is actually up
    (both ports answer): a running Docker Desktop without `docker compose up -d` means fallback.
    """
    forced = os.environ.get("KAMI_MODE")
    if forced in ("docker", "fallback"):
        return forced
    return "docker" if stack_up() else "fallback"

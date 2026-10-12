"""Start KAMI: virtual nodes -> bus -> worker -> processor -> API + dashboard.

    python scripts/run_demo.py                 # fallback mode: one process, in-process bus, SQLite. Dashboard at http://127.0.0.1:8000
    python scripts/run_demo.py --port 8200     # another port (Windows reserves 7981-8080 on some machines)
    python scripts/run_demo.py --speed 1200    # faster replay
    python scripts/run_demo.py --mode docker   # docker mode: MQTT (Mosquitto) + TimescaleDB, and the nodes, the ingest worker and
                                               # the API as three separate processes. Needs Docker Desktop; starts the containers
                                               # with `docker compose up -d` if they are not up. Stop them with `docker compose down`.
    python scripts/run_demo.py --check         # smoke test and exit (add --mode docker, or set KAMI_MODE=docker, for the docker mode)

The mode is fallback unless --mode docker or KAMI_MODE=docker is given: a running Docker Desktop alone changes nothing.
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Use the project's virtual environment if this was started with another Python.
_venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
if _venv_py.is_file() and Path(sys.executable).resolve() != _venv_py.resolve():
    import subprocess

    raise SystemExit(subprocess.call([str(_venv_py), str(Path(__file__).resolve()), *sys.argv[1:]]))

from kami import config  # noqa: E402
from kami.live.launch import launch  # noqa: E402


def ensure_stack(start: bool = True) -> bool:
    """True once the MQTT broker and TimescaleDB answer. Starts the containers with `docker compose up -d` if needed."""
    import shutil
    import subprocess

    if config.stack_up():
        return True
    docker = shutil.which("docker")
    if not start or docker is None:
        print("The MQTT broker and TimescaleDB are not reachable" + (" and the docker command was not found." if docker is None else "."))
        print("Start Docker Desktop, then run: docker compose up -d")
        return False
    print("Starting the containers: docker compose up -d")
    if subprocess.run([docker, "compose", "up", "-d"], cwd=ROOT).returncode != 0:
        return False
    for _ in range(120):
        if config.stack_up():
            time.sleep(3)  # TimescaleDB accepts the port a moment before it accepts logins
            return True
        time.sleep(1)
    print("The containers did not become reachable in 2 minutes.")
    return False


def smoke(speed: float, mode: str) -> int:
    import httpx

    if mode == "docker":
        from kami.live.launch import launch_docker
        from kami.notify.lock import forget_bot_settings
        from kami.simulator.node import node_ids
        from kami.store.timescale_store import TimescaleStore

        if not ensure_stack():
            return 1
        forget_bot_settings()  # a smoke test never sends: the three processes inherit an environment without the bot settings
        h = launch_docker(speed=max(speed, 3000), port=8190, lock=True)
    else:
        h = launch(speed=max(speed, 3000), port=8190, mode="fallback", temp_store=True)
    ok = True
    try:
        c = httpx.Client(base_url=h.url, timeout=10)
        time.sleep(10 if mode == "docker" else 6)
        checks = {
            "health ok": c.get("/health").json()["status"] == "ok",
            "8 nodes in /network": len(c.get("/network").json()["nodes"]) == 8,
            "all nodes assessed": all(n["latest"] for n in c.get("/network").json()["nodes"]),
            "readings stored": c.get("/health").json()["readings"] > 100,
            "inject accepted": c.post("/demo/inject", json={"type": "infra_burst", "node": "node-2"}).status_code == 200,
            "bad inject rejected": c.post("/demo/inject", json={"type": "nope", "node": "node-2"}).status_code == 422,
        }
        if mode == "docker":
            store = TimescaleStore(config.PG_DSN)
            counts = {n: store.count(n) for n in node_ids(8)}
            store.close()
            checks["docker mode reported by the API"] = c.get("/health").json()["mode"] == "docker"
            checks["three separate processes are running (nodes, ingest, API)"] = (all(h.alive().values()) and len({p.pid for p in h.procs.values()}) == 3)
            checks[f"the ingest process stored readings of all 8 nodes in TimescaleDB (min {min(counts.values())} rows)"] = min(counts.values()) >= 20
        for k, v in checks.items():
            print(("PASS " if v else "FAIL ") + k)
            ok &= v
    finally:
        gone = h.stop()
        if mode == "docker":
            print(("PASS " if all(gone.values()) else "FAIL ") + "the three processes stopped cleanly")
            ok &= all(gone.values())
    return 0 if ok else 1


def main() -> int:
    import os

    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=float, default=600.0, help="replay speed-up vs real time (default 600 = 0.5 s per 5-min step)")
    ap.add_argument("--port", type=int, default=config.API_PORT)
    ap.add_argument("--mode", choices=["fallback", "docker"], default=os.environ.get("KAMI_MODE") if os.environ.get("KAMI_MODE") in ("fallback", "docker") else "fallback",
                    help="fallback (default): one process, in-process bus, SQLite. docker: MQTT + TimescaleDB, three processes")
    ap.add_argument("--check", action="store_true", help="run a short smoke test and exit")
    a = ap.parse_args()
    if a.check:
        return smoke(a.speed, a.mode)
    dist = ROOT / "frontend" / "dist"
    if a.mode == "docker":
        from kami.live.launch import launch_docker

        if not ensure_stack():
            return 1
        h = launch_docker(speed=a.speed, port=a.port, notifications="auto", citizen="auto")  # Telegram alerts and the citizen bot only if enabled in .env
        st = httpx_get(h.url + "/notifications/status")
        cz = httpx_get(h.url + "/citizen/status")
        print(f"KAMI running in docker mode: MQTT port {config.MQTT_PORT}, TimescaleDB port {config.PG_PORT}; three processes "
              f"(nodes {h.procs['nodes'].pid}, ingest {h.procs['ingest'].pid}, API {h.procs['api'].pid}); logs in {h.log_dir}")
        print(f"API: {h.url}  (docs: {h.url}/docs)")
        print(f"Dashboard: {h.url}/" if dist.is_dir() else "Frontend not built: run `npm run build` in frontend/ (or `npm run dev` for port 5173).")
        print("Alerts: Telegram on" if st.get("mode") == "telegram" else f"Alerts: dry run ({st.get('detail')})")
        print("Citizen bot: on (speech models load in the background)" if cz.get("enabled") else f"Citizen bot: off ({cz.get('detail')})")
        print("Ctrl+C stops the three processes. The containers keep running: stop them with `docker compose down`.")
        try:
            while all(h.alive().values()):
                time.sleep(1)
            print(f"A process ended: {h.alive()}. See the logs in {h.log_dir}.")
            return 1
        except KeyboardInterrupt:
            return 0
        finally:
            h.stop()
    h = launch(speed=a.speed, port=a.port, mode="fallback", notifications="auto", citizen="auto")  # Telegram alerts and the citizen bot only if enabled in .env
    print(f"KAMI running in fallback mode (one process, in-process bus, SQLite). API: {h.url}  (docs: {h.url}/docs)")
    print(f"Dashboard: {h.url}/" if dist.is_dir() else "Frontend not built: run `npm run build` in frontend/ (or `npm run dev` for port 5173).")
    st = h.stack.extras["notifications"].status()
    print("Alerts: Telegram on" if st["mode"] == "telegram" else f"Alerts: dry run ({st['detail']})")
    cz = h.stack.extras["citizen"]
    print("Citizen bot: on (speech models load in the background)" if cz.enabled else f"Citizen bot: off ({cz.detail})")
    print("Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        h.stop()
    return 0


def httpx_get(url: str) -> dict:
    import httpx

    try:
        return httpx.get(url, timeout=10).json()
    except Exception:
        return {}


if __name__ == "__main__":
    sys.exit(main())

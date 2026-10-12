"""Part B of Round 6: run the Docker stack checks and record them in results/docker/part_b.json.

    python scripts/docker_checks.py            # needs Docker Desktop running; starts the containers, runs every check, stops them
    python scripts/docker_checks.py --keep     # leave the containers running at the end

What is checked (PLAN_ROUND6.md, D1 to D4):
  docker info works; `docker compose up -d` brings up Mosquitto and TimescaleDB; the MQTT and TimescaleDB tests run and
  pass (none skipped), and so does the whole test suite; scripts/check_step_1.py and scripts/run_demo.py --check pass in docker mode; the demo runs as
  three separate processes that ingest from all 8 nodes, obey control messages and stop cleanly; the browser tests pass
  against the docker-mode demo; the fallback mode still passes; the containers are stopped at the end.
No Telegram message can be sent: every child process gets an environment without the bot settings, and the demo
processes are started with the lock that refuses HTTP requests to other machines.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "results" / "docker" / "part_b.json"
results: dict = {}


def record(key: str, ok: bool, **detail) -> bool:
    results[key] = {"ok": bool(ok), **detail}
    print(("PASS " if ok else "FAIL ") + key + (" " + json.dumps(detail)[:200] if detail else ""), flush=True)
    return bool(ok)


def run(cmd, env=None, timeout=1800, cwd=ROOT):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=timeout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="leave the containers running at the end")
    a = ap.parse_args()
    from kami import config
    from kami.notify.lock import forget_bot_settings

    forget_bot_settings()  # this process and all its children: no bot settings, a settings file that does not exist
    tmp = Path(tempfile.mkdtemp(prefix="kami_docker_checks_"))
    env = dict(os.environ)
    env.update({"KAMI_E2E_OUT": str(tmp / "e2e"), "KAMI_CITIZEN_DIR": str(tmp / "citizen"), "KAMI_NOTIFY_DIR": str(tmp / "notifications")})
    env_docker, env_fallback = {**env, "KAMI_MODE": "docker"}, {**env, "KAMI_MODE": "fallback"}
    docker = shutil.which("docker")
    py = sys.executable

    # ---------------------------------------------------------------- D1: Docker
    info = run([docker, "info", "--format", "{{.ServerVersion}}"]) if docker else None
    compose = run([docker, "compose", "version", "--short"]) if docker else None
    ran = bool(docker) and info.returncode == 0
    record("docker_info", ran, docker_version=info.stdout.strip() if info else None, compose_version=compose.stdout.strip() if compose else None)
    if not ran:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"made_by": "scripts/docker_checks.py", "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                   "docker_ran": False, "reason": "docker info failed or the docker command was not found", **results}, indent=1) + "\n", encoding="utf-8")
        return 1

    # ---------------------------------------------------------------- D2: the real stack
    up = run([docker, "compose", "up", "-d"], timeout=1800)
    for _ in range(120):
        if config.stack_up():
            break
        time.sleep(1)
    time.sleep(5)  # TimescaleDB accepts the port a moment before it accepts logins
    images = run([docker, "compose", "images", "--format", "json"]).stdout
    record("compose_up", up.returncode == 0 and config.stack_up(), mqtt_port=config.MQTT_PORT, timescale_port=config.PG_PORT,
           images=sorted(set(re.findall(r'"Repository":"([^"]+)"', images))))
    t = run([py, "-m", "pytest", "tests/step1", "tests/docker", "-vv", "-rs", "-p", "no:warnings", "-p", "no:cacheprovider"], env=env)
    passed = re.findall(r"(\S+) PASSED", t.stdout)
    needed = ["test_store_contract[timescale]", "test_bus_contract[mqtt]", "test_timescale_returns_the_same_time_format_as_sqlite_and_keeps_tickets",
              "test_two_mqtt_clients_exchange_control_messages_through_the_broker",
              "test_the_three_process_demo_takes_an_injection_as_soon_as_it_is_launched"]
    record("mqtt_timescale_tests", t.returncode == 0 and "SKIPPED" not in t.stdout and all(any(n in p for p in passed) for n in needed),
           passed=len(passed), skipped=t.stdout.count("SKIPPED"), summary=t.stdout.strip().splitlines()[-1][-80:] if t.stdout.strip() else "")
    full = run([py, "-m", "pytest", "-rs", "-p", "no:cacheprovider"], env=env_fallback)  # the whole suite while the stack is up: nothing may be skipped
    last = full.stdout.strip().splitlines()[-1] if full.stdout.strip() else ""
    n_pass = re.search(r"(\d+) passed", last)
    record("pytest_all_with_stack_up", full.returncode == 0 and "SKIPPED" not in full.stdout and "skipped" not in last and n_pass is not None,
           passed=int(n_pass.group(1)) if n_pass else 0, skipped=full.stdout.count("SKIPPED"), summary=last[-60:])
    s1 = run([py, "scripts/check_step_1.py"], env=env_docker)
    record("check_step_1_docker", s1.returncode == 0 and "mode: docker" in s1.stdout, fails=[ln for ln in s1.stdout.splitlines() if ln.startswith("FAIL")])
    rd = run([py, "scripts/run_demo.py", "--check"], env=env_docker)
    record("run_demo_check_docker", rd.returncode == 0 and "three separate processes" in rd.stdout,
           lines=[ln for ln in rd.stdout.splitlines() if ln.startswith(("PASS", "FAIL"))])

    # ---------------------------------------------------------------- D3: three separate processes
    import httpx

    from kami.live.launch import launch_docker
    from kami.simulator.node import node_ids
    from kami.store.timescale_store import TimescaleStore

    detail, ok3 = {}, False
    h = launch_docker(speed=3000, port=8230, lock=True, env=env_docker)
    try:
        c = httpx.Client(base_url=h.url, timeout=10)
        store = TimescaleStore(config.PG_DSN)
        t0 = time.time()
        while True:  # the ingest process must store at least 100 readings of every node (limit: 60 s)
            counts = {n: store.count(n) for n in node_ids(8)}
            waited = round(time.time() - t0, 1)
            if min(counts.values()) >= 100 or waited > 60:
                break
            time.sleep(0.5)
        health = c.get("/health").json()
        net = c.get("/network").json()
        st1 = c.get("/demo/status").json()
        notify = c.get("/notifications/status").json()
        inj = c.post("/demo/inject", json={"type": "infra_burst", "node": "node-2"})
        alert = None
        for _ in range(120):  # the injection travels API -> MQTT -> nodes; the alert comes back nodes -> MQTT -> API
            alerts = c.get("/alerts", params={"node": "node-2"}).json()
            if alerts:
                alert = alerts[0]
                break
            time.sleep(0.5)
        c.post("/demo/control", json={"paused": True})
        time.sleep(1.5)
        p1 = c.get("/demo/status").json()["step"]
        time.sleep(1.5)
        p2 = c.get("/demo/status").json()["step"]
        c.post("/demo/control", json={"paused": False})
        time.sleep(1.5)
        p3 = c.get("/demo/status").json()["step"]
        after = store.count()
        store.close()
        pids = {role: p.pid for role, p in h.procs.items()}
        detail = {"pids": pids, "rows_per_node": counts, "seconds_until_100_rows_per_node": waited, "replay_speed": 3000, "api_mode": health.get("mode"), "api_accepted": health.get("accepted"),
                  "nodes_assessed": sum(bool(n["latest"]) for n in net["nodes"]), "replay_step_first": st1.get("step"), "alert_push_mode": notify.get("mode"),
                  "inject_status": inj.status_code, "alert_after_injection": alert and {k: alert[k] for k in ("category", "priority", "status")},
                  "paused_steps": [p1, p2], "resumed_step": p3, "readings_in_timescaledb": after}
        ok3 = (len(set(pids.values())) == 3 and all(h.alive().values()) and min(counts.values()) >= 100 and health.get("mode") == "docker"
               and detail["nodes_assessed"] == 8 and inj.status_code == 200 and alert is not None and p1 == p2 and p3 > p2 and notify.get("mode") == "dry_run")
    finally:
        gone = h.stop()
    detail["stopped"] = gone
    record("separate_processes", ok3 and all(gone.values()), **detail)

    # ---------------------------------------------------------------- D4: browser tests against the docker-mode demo
    npm, npx = shutil.which("npm"), shutil.which("npx")
    build = run([npm, "run", "build"], env=env, cwd=ROOT / "frontend")
    pw = run([npx, "playwright", "test"], env={**env_docker, "KAMI_E2E_MODE": "docker"}, cwd=ROOT / "frontend", timeout=1800)
    tail = [ln.strip() for ln in pw.stdout.splitlines() if ln.strip()][-1:] or [pw.stderr[-200:]]
    shots = len(list((tmp / "e2e" / "screens").glob("*.png"))) if (tmp / "e2e" / "screens").is_dir() else 0
    n_ok = len(re.findall(r"^\s+ok\s+\d+ ", pw.stdout, flags=re.M))
    not_ok = [ln.strip()[:120] for ln in pw.stdout.splitlines() if re.match(r"^\s+(x|-)\s+\d+ ", ln)]
    record("playwright_docker", build.returncode == 0 and pw.returncode == 0 and n_ok >= 34 and shots == 16,
           summary=tail[0], tests_ok=n_ok, tests_failed_or_not_run=not_ok, screenshots_in_scratch_folder=shots,
           note="output went to a scratch folder; the stored paper screenshots were not regenerated")

    # ---------------------------------------------------------------- fallback mode unchanged; containers stopped
    f1 = run([py, "scripts/check_step_1.py"], env=env_fallback)
    f2 = run([py, "scripts/run_demo.py", "--check"], env=env_fallback)
    record("fallback_unchanged", f1.returncode == 0 and "mode: fallback" in f1.stdout and f2.returncode == 0 and "three separate processes" not in f2.stdout)
    if a.keep:
        record("containers_stopped", False, note="--keep was given: the containers were left running")
    else:
        down = run([docker, "compose", "down"], timeout=300)
        left = run([docker, "compose", "ps", "-q"]).stdout.strip()
        record("containers_stopped", down.returncode == 0 and left == "" and not config.stack_up())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out = {"made_by": "scripts/docker_checks.py", "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "docker_ran": True,
           "git_commit": run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip(), **results}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0 if all(v["ok"] for v in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

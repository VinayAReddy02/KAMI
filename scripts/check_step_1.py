"""Exit 0 only if Step 1 criteria hold (stack runs, 8 nodes stored, API serves, tests pass)."""
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import httpx  # noqa: E402
import uvicorn  # noqa: E402

from kami import config  # noqa: E402
from kami.api.app import create_app  # noqa: E402
from kami.runtime import Stack  # noqa: E402
from kami.simulator.node import NodeFleet, build_node_frames, node_ids  # noqa: E402
from kami.store import SqliteStore  # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name)
    ok &= bool(cond)


mode = config.resolve_mode()
print("mode:", mode)
if mode == "docker":
    stack = Stack.create(mode="docker")
else:
    tmp = tempfile.mkdtemp()
    store = SqliteStore(Path(tmp) / "step1.sqlite")
    store.init()
    stack = Stack.create(mode="fallback", store=store)
port = 8101
server = uvicorn.Server(uvicorn.Config(create_app(stack), port=port, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(50):
    try:
        httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)
        break
    except Exception:
        time.sleep(0.2)

frames = build_node_frames(8)
fleet = NodeFleet(stack.bus, frames, speed=6000)
t0 = time.time()
fleet.start()
time.sleep(20)
fleet.stop()
print(f"ran nodes for {time.time() - t0:.1f}s, published {fleet.published}")

counts = {n: stack.store.count(n) for n in node_ids(8)}
print("rows per node:", counts)
check("all 8 nodes have >= 100 rows", all(c >= 100 for c in counts.values()))
h = httpx.get(f"http://127.0.0.1:{port}/health").json()
check("GET /health ok", h["status"] == "ok")
rows = httpx.get(f"http://127.0.0.1:{port}/readings", params={"node": "node-3", "limit": 50}).json()
check("GET /readings returns rows", len(rows) == 50 and rows[0]["node_id"] == "node-3")
nodes = httpx.get(f"http://127.0.0.1:{port}/nodes").json()
check("GET /nodes lists 8 nodes", len(nodes) == 8)
server.should_exit = True

r = subprocess.run([sys.executable, "-m", "pytest", "tests/step1", "-q"], cwd=ROOT)
check("pytest tests/step1", r.returncode == 0)
sys.exit(0 if ok else 1)

"""Exit 0 only if Step 0 criteria hold."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kami.data.raw_loaders import USGS_STATIONS, load_battledim, load_usgs  # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name)
    ok &= bool(cond)


doc = (ROOT / "docs" / "datasets.md").read_text(encoding="utf-8")
check("datasets.md lists selected infrastructure", bool(re.search(r"selected \(infrastructure\)", doc)))
check("datasets.md lists selected quality", bool(re.search(r"selected \(quality\)", doc)))
for d in ("battledim", "usgs"):
    check(f"{d} SOURCE.md", (ROOT / "data/raw" / d / "SOURCE.md").is_file())

for yr in (2018, 2019):
    b = load_battledim(yr)
    n = len(b["pressure"])
    leak_rows = int((b["leak"] > 0).any(axis=1).sum())
    print(f"BattLeDIM {yr}: pressure {b['pressure'].shape}, flow {b['flow'].shape}, "
          f"range {b['pressure'].index.min()} .. {b['pressure'].index.max()}, rows with active leak {leak_rows}, "
          f"leak pipes {int((b['leak'].max() > 0).sum())}")
    check(f"BattLeDIM {yr} rows > 10000", n > 10000)
    check(f"BattLeDIM {yr} timestamps readable", b["pressure"].index.notna().all())
for s in USGS_STATIONS:
    u = load_usgs(s)
    print(f"USGS {s}: rows {len(u)}, {u.ts.min()} .. {u.ts.max()}, turbidity non-null {u.turbidity.notna().sum()}, "
          f"conductance non-null {u.conductance.notna().sum()}, labels: none")
    check(f"USGS {s} rows > 10000", len(u) > 10000)
    check(f"USGS {s} timestamps readable", u.ts.notna().all())
sys.exit(0 if ok else 1)

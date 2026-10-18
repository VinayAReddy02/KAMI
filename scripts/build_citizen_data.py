"""Build the fictional tanker schedule of the citizen demo (seeded, reproducible).

    python scripts/build_citizen_data.py            # writes data/citizen/tanker_schedule_demo_fictional.csv
    python scripts/build_citizen_data.py --check    # exit 0 only if the file on disk equals what this script produces

Every row is invented. A row says: on the day `day_offset` days from the current replay day (0 = today, 1 = tomorrow,
-1 = yesterday), tanker `tanker_id` is planned for ward `ward` in the slot `slot_start`-`slot_end`. `planned_status` is
`scheduled` or `delayed` (then `delay_minutes` says by how much). What a citizen hears (scheduled, en route, delivered,
delayed) is derived from this row and the replay clock by kami.citizen.data.ScheduleService.
"""
import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "citizen" / "tanker_schedule_demo_fictional.csv"
SEED = 20261012
WARDS = range(1, 9)
OFFSETS = (-1, 0, 1, 2)
SLOTS = (("06:00", "08:00"), ("10:00", "12:00"), ("16:00", "18:00"))
TANKERS = [f"TKR-{i:02d}" for i in range(1, 11)]
DELAYS = (30, 45, 60)
HEADER = ("# demo_fictional: invented tanker schedule for the KAMI demo, built by scripts/build_citizen_data.py with seed "
          f"{SEED}; day_offset is relative to the replay day\n"
          "tanker_id,ward,day_offset,slot_start,slot_end,planned_status,delay_minutes\n")


def build() -> str:
    rng = np.random.default_rng(SEED)
    rows = []
    for offset in OFFSETS:
        for ward in WARDS:
            n = int(rng.choice([1, 2], p=[0.6, 0.4]))
            for k in sorted(rng.choice(len(SLOTS), size=n, replace=False).tolist()):
                rows.append([str(rng.choice(TANKERS)), ward, offset, *SLOTS[k], "scheduled", 0])
    today = [r for r in rows if r[2] == 0]
    for i in sorted(rng.choice(len(today), size=3, replace=False).tolist()):  # three of today's deliveries are planned as delayed
        today[i][5], today[i][6] = "delayed", int(rng.choice(DELAYS))
    return HEADER + "".join(",".join(str(v) for v in r) + "\n" for r in rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    text = build()
    if a.check:
        # line endings are not content: a checkout with core.autocrlf=true has CRLF on disk (Round 8, after the repo history was rewritten)
        same = OUT.is_file() and OUT.read_bytes().replace(b"\r\n", b"\n") == text.encode("utf-8")
        print("schedule file matches the seeded build" if same else "schedule file DIFFERS from the seeded build")
        return 0 if same else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(text.encode("utf-8"))
    print(f"wrote {OUT.relative_to(ROOT)} ({text.count(chr(10)) - 2} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

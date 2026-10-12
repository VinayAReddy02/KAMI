"""Fictional demo data of the citizen interface (wards, tanker schedule, notices) and the schedule service.

All of it is `demo_fictional`. The schedule is resolved against the replay clock, and against the live KAMI state: a
ward whose sensor node has an open High or Critical alert has its pending tankers reported as possibly delayed.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from .settings import DATA_DIR

WARDS_FILE = DATA_DIR / "wards_demo_fictional.json"
SCHEDULE_FILE = DATA_DIR / "tanker_schedule_demo_fictional.csv"
NOTICES_FILE = DATA_DIR / "notices_demo_fictional.json"
EN_ROUTE_BEFORE = timedelta(hours=1)  # a tanker counts as "en route" from one hour before its slot
ALERTING = ("High", "Critical")
ALERT_NOTE = "possibly delayed: active network alert in your area"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class Ward:
    number: int
    node_id: str
    name_en: str
    name_hi: str
    aliases: tuple


@dataclass(frozen=True)
class Row:
    tanker_id: str
    ward: int
    day_offset: int
    slot_start: str
    slot_end: str
    planned_status: str
    delay_minutes: int


@dataclass(frozen=True)
class Delivery:
    """One planned delivery as a citizen should hear it now. Every field is a fact the answer may state."""

    ward: int
    ward_name: str
    tanker_id: str
    day_offset: int
    date: str  # ISO date of the replay day it belongs to
    date_text: str  # "7 Jan"
    slot: str  # planned slot "10:00-12:00"
    status: str  # scheduled | en route | delivered | delayed
    expected: str  # the slot to expect: equal to `slot`, or shifted for a delayed tanker
    delay_minutes: int
    alert_note: bool  # the ward's node has an open High/Critical alert and this tanker has not delivered yet

    def facts(self) -> dict:
        d = {"ward": self.ward, "ward_name": self.ward_name, "tanker": self.tanker_id, "day": DAY_WORD.get(self.day_offset, self.date_text),
             "date": self.date_text, "planned_slot": self.slot, "status": self.status}
        if self.status == "delayed":
            d["delay_minutes"], d["expected_slot"] = self.delay_minutes, self.expected
        if self.alert_note:
            d["note"] = ALERT_NOTE
        return d


DAY_WORD = {-1: "yesterday", 0: "today", 1: "tomorrow", 2: "the day after tomorrow"}


def load_wards() -> list[Ward]:
    raw = json.loads(WARDS_FILE.read_text(encoding="utf-8"))
    assert raw["label"] == "demo_fictional"
    return [Ward(w["number"], w["node_id"], w["name_en"], w["name_hi"], tuple(w.get("aliases", ()))) for w in raw["wards"]]


def speech_vocabulary() -> str:
    """Words a citizen is likely to say that a general speech model tends to mis-hear: the ward names and the loanwords
    "ward" and "tanker" in both scripts. Given to the recogniser as hint words."""
    wards = load_wards()
    return " ".join(["वार्ड", "टैंकर", "पानी", *[w.name_hi for w in wards], "ward", "tanker", *[w.name_en for w in wards]])


def load_notices() -> list[dict]:
    raw = json.loads(NOTICES_FILE.read_text(encoding="utf-8"))
    assert raw["label"] == "demo_fictional"
    return raw["notices"]


def load_schedule() -> list[Row]:
    lines = SCHEDULE_FILE.read_text(encoding="utf-8").splitlines()
    assert "demo_fictional" in lines[0]
    return [Row(r["tanker_id"], int(r["ward"]), int(r["day_offset"]), r["slot_start"], r["slot_end"], r["planned_status"], int(r["delay_minutes"]))
            for r in csv.DictReader(lines[1:])]


def _at(day: date, hhmm: str) -> datetime:
    h, m = hhmm.split(":")
    return datetime(day.year, day.month, day.day, int(h), int(m))


def date_text(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]}"


class ScheduleService:
    """`clock()` gives the current replay time; `open_alert(node_id)` gives that node's open alert (a dict with a
    `priority`) or None. Both are passed in, so the service is deterministic and testable."""

    def __init__(self, wards: list[Ward] | None = None, rows: list[Row] | None = None,
                 clock: Callable[[], datetime] = datetime.now, open_alert: Callable[[str], dict | None] = lambda node_id: None):
        self.wards = {w.number: w for w in (wards if wards is not None else load_wards())}
        self.rows = rows if rows is not None else load_schedule()
        self.clock, self.open_alert = clock, open_alert

    def ward_alert(self, ward: int) -> dict | None:
        """The open High/Critical alert of the ward's node, if there is one."""
        try:
            a = self.open_alert(self.wards[ward].node_id)
        except Exception:
            return None  # the live state is optional: never let it break an answer
        return a if isinstance(a, dict) and a.get("priority") in ALERTING else None

    def deliveries(self, ward: int, day_offset: int | None = None) -> list[Delivery]:
        """Deliveries of a ward, oldest first; all known days, or one day (0 = today)."""
        if ward not in self.wards:
            return []
        now = self.clock()
        alert = self.ward_alert(ward) is not None
        out = []
        for r in self.rows:
            if r.ward != ward or (day_offset is not None and r.day_offset != day_offset):
                continue
            day = now.date() + timedelta(days=r.day_offset)
            delay = timedelta(minutes=r.delay_minutes if r.planned_status == "delayed" else 0)
            start, end = _at(day, r.slot_start) + delay, _at(day, r.slot_end) + delay
            if now >= end:
                status = "delivered"
            elif r.planned_status == "delayed":
                status = "delayed"
            elif now >= start - EN_ROUTE_BEFORE:
                status = "en route"
            else:
                status = "scheduled"
            out.append(Delivery(ward, self.wards[ward].name_en, r.tanker_id, r.day_offset, day.isoformat(), date_text(day),
                                f"{r.slot_start}-{r.slot_end}", status,
                                f"{r.slot_start}-{r.slot_end}" if status == "delivered" else f"{start:%H:%M}-{end:%H:%M}",  # a past delivery is reported by its planned slot
                                r.delay_minutes if status == "delayed" else 0, alert and status != "delivered"))
        return sorted(out, key=lambda d: (d.day_offset, d.slot))

    def next_delivery(self, ward: int) -> Delivery | None:
        """The first delivery that has not happened yet (today or later)."""
        return next((d for d in self.deliveries(ward) if d.day_offset >= 0 and d.status != "delivered"), None)

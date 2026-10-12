from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .base import SIGNALS, Store


class SqliteStore(Store):
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def init(self) -> None:
        with self._lock:
            self._db.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                CREATE TABLE IF NOT EXISTS readings(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  node_id TEXT NOT NULL, ts TEXT NOT NULL,
                  flow REAL, pressure REAL, turbidity REAL, tds REAL);
                CREATE INDEX IF NOT EXISTS ix_readings ON readings(node_id, ts);
                CREATE TABLE IF NOT EXISTS assessments(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  node_id TEXT NOT NULL, ts TEXT NOT NULL, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS ix_assess ON assessments(node_id, ts);
                CREATE TABLE IF NOT EXISTS complaints(
                  id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL);
                """
            )
            self._db.commit()

    def write_reading(self, r: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO readings(node_id, ts, flow, pressure, turbidity, tds) VALUES (?,?,?,?,?,?)",
                (r["node_id"], r["ts"], *[r.get(s) for s in SIGNALS]),
            )
            self._db.commit()

    def read_readings(self, node=None, since=None, limit=1000):
        q, args = "SELECT node_id, ts, flow, pressure, turbidity, tds FROM readings WHERE 1=1", []
        if node:
            q += " AND node_id=?"
            args.append(node)
        if since:
            q += " AND ts>=?"
            args.append(since)
        q += " ORDER BY ts, id LIMIT ?"
        args.append(limit)
        with self._lock:
            return [dict(x) for x in self._db.execute(q, args)]

    def nodes(self):
        with self._lock:
            rows = self._db.execute(
                "SELECT node_id, COUNT(*) n, MIN(ts) first_ts, MAX(ts) last_ts FROM readings GROUP BY node_id ORDER BY node_id"
            )
            return [dict(x) for x in rows]

    def count(self, node=None):
        with self._lock:
            if node:
                return self._db.execute("SELECT COUNT(*) FROM readings WHERE node_id=?", (node,)).fetchone()[0]
            return self._db.execute("SELECT COUNT(*) FROM readings").fetchone()[0]

    def write_assessment(self, a: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO assessments(node_id, ts, body) VALUES (?,?,?)",
                (a["node_id"], a["ts"], json.dumps(a)),
            )
            self._db.commit()

    def read_assessments(self, node=None, limit=500):
        q, args = "SELECT body FROM assessments", []
        if node:
            q += " WHERE node_id=?"
            args.append(node)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            return [json.loads(x["body"]) for x in self._db.execute(q, args)]

    def write_complaint(self, c: dict) -> int:
        with self._lock:
            cur = self._db.execute("INSERT INTO complaints(body) VALUES (?)", (json.dumps(c),))
            self._db.commit()
            return int(cur.lastrowid)

    def read_complaints(self, limit=200):
        with self._lock:
            rows = self._db.execute("SELECT id, body FROM complaints ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{**json.loads(r["body"]), "id": r["id"]} for r in rows]

    def clear(self) -> None:
        with self._lock:
            for t in ("readings", "assessments", "complaints"):
                self._db.execute(f"DELETE FROM {t}")
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

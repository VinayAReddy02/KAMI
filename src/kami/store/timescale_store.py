"""TimescaleDB backend (needs Docker; see docker-compose.yml). Same interface as SqliteStore."""
from __future__ import annotations

import json
import threading

from .base import SIGNALS, Store


class TimescaleStore(Store):
    def __init__(self, dsn: str):
        import psycopg

        self._conn = psycopg.connect(dsn, autocommit=True)
        self._lock = threading.Lock()

    def init(self) -> None:
        with self._lock, self._conn.cursor() as c:
            c.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
            c.execute(
                """CREATE TABLE IF NOT EXISTS readings(
                     node_id TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL,
                     flow DOUBLE PRECISION, pressure DOUBLE PRECISION,
                     turbidity DOUBLE PRECISION, tds DOUBLE PRECISION)"""
            )
            c.execute("SELECT create_hypertable('readings','ts', if_not_exists => TRUE)")
            c.execute("CREATE INDEX IF NOT EXISTS ix_readings ON readings(node_id, ts)")
            c.execute(
                """CREATE TABLE IF NOT EXISTS assessments(
                     node_id TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL, body JSONB NOT NULL)"""
            )
            c.execute("CREATE TABLE IF NOT EXISTS complaints(id BIGSERIAL PRIMARY KEY, body JSONB NOT NULL)")

    def write_reading(self, r: dict) -> None:
        with self._lock, self._conn.cursor() as c:
            c.execute(
                "INSERT INTO readings(node_id, ts, flow, pressure, turbidity, tds) VALUES (%s,%s,%s,%s,%s,%s)",
                (r["node_id"], r["ts"], *[r.get(s) for s in SIGNALS]),
            )

    def read_readings(self, node=None, since=None, limit=1000):
        q, args = "SELECT node_id, ts::text, flow, pressure, turbidity, tds FROM readings WHERE TRUE", []
        if node:
            q += " AND node_id=%s"
            args.append(node)
        if since:
            q += " AND ts>=%s"
            args.append(since)
        q += " ORDER BY ts LIMIT %s"
        args.append(limit)
        keys = ("node_id", "ts", *SIGNALS)
        with self._lock, self._conn.cursor() as c:
            c.execute(q, args)
            return [dict(zip(keys, row)) for row in c.fetchall()]

    def nodes(self):
        with self._lock, self._conn.cursor() as c:
            c.execute(
                "SELECT node_id, COUNT(*), MIN(ts)::text, MAX(ts)::text FROM readings GROUP BY node_id ORDER BY node_id"
            )
            return [dict(zip(("node_id", "n", "first_ts", "last_ts"), r)) for r in c.fetchall()]

    def count(self, node=None):
        with self._lock, self._conn.cursor() as c:
            if node:
                c.execute("SELECT COUNT(*) FROM readings WHERE node_id=%s", (node,))
            else:
                c.execute("SELECT COUNT(*) FROM readings")
            return c.fetchone()[0]

    def write_assessment(self, a: dict) -> None:
        with self._lock, self._conn.cursor() as c:
            c.execute("INSERT INTO assessments(node_id, ts, body) VALUES (%s,%s,%s)",
                      (a["node_id"], a["ts"], json.dumps(a)))

    def read_assessments(self, node=None, limit=500):
        q, args = "SELECT body FROM assessments", []
        if node:
            q += " WHERE node_id=%s"
            args.append(node)
        q += " ORDER BY ts DESC LIMIT %s"
        args.append(limit)
        with self._lock, self._conn.cursor() as c:
            c.execute(q, args)
            return [r[0] for r in c.fetchall()]

    def write_complaint(self, c: dict) -> int:
        with self._lock, self._conn.cursor() as cur:
            cur.execute("INSERT INTO complaints(body) VALUES (%s) RETURNING id", (json.dumps(c),))
            return int(cur.fetchone()[0])

    def read_complaints(self, limit=200):
        with self._lock, self._conn.cursor() as cur:
            cur.execute("SELECT id, body FROM complaints ORDER BY id DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
        return [{**(b if isinstance(b, dict) else json.loads(b)), "id": int(i)} for i, b in rows]

    def close(self) -> None:
        self._conn.close()

# KAMI: contextual anomaly intelligence for water networks

Skeleton (completed in Step 7).

## Quick start (Windows, PowerShell)
```
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python scripts\check_step_1.py
```

## Modes
- **docker**: Mosquitto (MQTT 1883) + TimescaleDB (5432) via `docker compose up -d`.
- **fallback** (used when Docker is absent): in-process bus + SQLite. Because the bus is in-process, the API, ingest worker and virtual nodes run inside one process (`scripts/run_demo.py`, Step 7).
- Force a mode with `KAMI_MODE=docker|fallback`.

## Ports
MQTT 1883, Postgres 5432, API 8000, frontend 5173 (`KAMI_API_PORT`, `KAMI_MQTT_PORT`, `KAMI_PG_PORT`).

## Data honesty
Infrastructure data (BattLeDIM) are simulated; node series that mix BattLeDIM and USGS data are `semi_synthetic`. See `docs/datasets.md`.

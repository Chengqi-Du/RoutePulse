# RoutePulse backend

Simulation-only FastAPI backend generated from the supplied API contract and backend PRD. It implements the six contract endpoints, stores state in SQLite, and includes the in-process routing and limited question parser in `app/integration.py`.

The fixed map is only a simulated road network. A route is the shortest-distance candidate under current simulated reports; it is not a safety assessment or real-world rescue navigation. The frontend should always display:

> SIMULATION ONLY — Not for real-world rescue navigation.

## Run locally

Python 3.10 or newer is recommended.

```bash
cd outputs/routepulse-backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

On first startup, the backend creates `routepulse.sqlite3` in the launch directory and inserts the fixed exercise once. Later startups reuse that database and preserve reports and route history. To use a separate exercise database, set `ROUTEPULSE_DB_PATH` before launch:

```bash
ROUTEPULSE_DB_PATH=./work/routepulse-demo.sqlite3 uvicorn app.main:app --reload --port 8000
```

To start a fresh repeatable exercise, choose a new database path. The service does not clear an existing database on startup.

Configure local frontend origins with a comma-separated `ROUTEPULSE_CORS_ORIGINS`; the defaults are `http://localhost:5173` and `http://localhost:3000`.

## API

Base URL: `http://localhost:8000/api`

- `GET /scenario`
- `GET /areas/area-a/state`
- `POST /areas/area-a/routes`
- `POST /areas/area-a/reports`
- `POST /areas/area-a/demo-advance`
- `POST /areas/area-a/questions`

All mutations and question requests include `expected_version`. A successful route question is a state mutation; `why_changed`, `needs_check`, and unsupported questions are read-only. Error responses use `{ "error": { "code", "message", "current_version" } }`.

Interactive API documentation is available at `/docs` while the server is running.

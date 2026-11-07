# RoutePulse backend

Simulation-only FastAPI backend generated from the supplied API contract and backend PRD. It implements the six contract endpoints, stores state in SQLite, and imports the shared pure routing and question modules from `algorithm/`.

The fixed map is only a simulated road network. A route is the shortest-distance candidate under current simulated reports; it is not a safety assessment or real-world rescue navigation. The frontend should always display:

> SIMULATION ONLY — Not for real-world rescue navigation.

## Run locally

Python 3.10 or newer is recommended.

```bash
cd routepulse-backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=.. python -m uvicorn app.main:app --reload --port 8000
```

The repository root must be on `PYTHONPATH` so the backend imports the single
shared `algorithm/` package. Alternatively, with the same virtual environment
activated, start from the `RoutePulse/` repository root:

```bash
PYTHONPATH=routepulse-backend python -m uvicorn app.main:app --reload --port 8000
```

On first startup, the backend creates `routepulse.sqlite3` in the launch directory and inserts the fixed exercise once. Later startups reuse that database and preserve reports and route history. To use a separate exercise database, set `ROUTEPULSE_DB_PATH` before launch:

```bash
ROUTEPULSE_DB_PATH=./work/routepulse-demo.sqlite3 PYTHONPATH=.. python -m uvicorn app.main:app --reload --port 8000
```

The last command assumes the current directory is `routepulse-backend/`.
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

## Integration tests

With the backend dependencies installed and the virtual environment activated,
run from the `RoutePulse/` root:

```bash
python -m unittest discover -s algorithm/tests -v
python -m unittest discover -s routepulse-backend/tests -v
```

The backend tests use temporary databases and exercise real HTTP requests for
both supported launch directories; they do not use or modify your demo database.

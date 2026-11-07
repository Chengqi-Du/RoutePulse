# RoutePulse backend

Simulation-only FastAPI backend generated from the supplied API contract and backend PRD. It implements the six contract endpoints, stores state in SQLite, and imports the shared pure routing and question modules from `algorithm/`.

The default legacy map is a simulated road network. The optional Anamizu mode
uses OSM road geometry with fictional simulated road conditions. A route is
the shortest-distance candidate under current simulated reports; it is not a
safety assessment or real-world rescue navigation. The frontend should always display:

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

## Anamizu seven-day OSM exercise

The default `legacy` mode above remains the original four-edge demonstration. To
run the separate Anamizu graph, use a separate database and select the mode:

```bash
cd routepulse-backend
ROUTEPULSE_SCENARIO_MODE=anamizu-7day \
ROUTEPULSE_DB_PATH=./work/anamizu-7day.sqlite3 \
PYTHONPATH=.. python -m uvicorn app.main:app --reload --port 8000
```

On first startup this mode imports the shared `data/map.osm` into its own
SQLite database, using the same `algorithm.osm_graph.build_graph` converter
as Integration. The checked-in `../data/anamizu-v2/seven-day-scenario.json`
is the default daily observation file and uses that graph's exact version and
directed edge IDs. The source OSM SHA-256 is
`3aadb5e0145bd091b9f981b9da28255e758c926f5efbee26cf36901d72d9bc08`.
The separate frontend map has not been changed and is not yet unified or
connected to this backend.

The importer uses OSM highway ways as directed, node-to-node candidate edges,
excluding highway areas, and returns each edge's GeoJSON LineString geometry.
The graph starts with unknown road
conditions: an OSM road on the map is not evidence that it is passable after an
earthquake. Turn restrictions are currently not applied, and the screenshot
coverage has not been verified. Read `data/README.md` before presenting the map.

`POST /api/areas/area-a/reports/batch` adds a validated group of manual reports
atomically. In this mode a successful manual report advances `scenario_time` by
one second. `POST /api/areas/area-a/advance-day` applies one Integration-provided
day frame atomically and recalculates the current route once. To use a different
file, set `ROUTEPULSE_DAY_TEMPLATES_PATH`; if it is missing, the endpoint
returns `DAY_TEMPLATES_NOT_CONFIGURED`. Its top-level object must include the imported
`graph_version` and exactly seven ordered `days`; each day must identify
`day_index`, `frame_id`, `scenario_date_local`, timezone-aware `scenario_time`,
`observations_are_simulated: true`, `observation_source_id`, and a
`road_observations` list of `{ "edge_id", "status", "note" }` records. The
`graph_version` returned by `/api/areas/area-a/state` lets Integration target
the exact imported extract.

Before the first frame is applied, state reports `day_index: 0`
and every road remains `unknown`. The first successful `/advance-day` applies
day 1; it does not mark roads open by default.

The new mode reports its map bounds and import metadata from `/scenario` and
`/areas/area-a/state`. The area `bbox` is the OSM extract bounds, not a verified
match to the attached screenshot. `ROUTEPULSE_OSM_PATH` can select a different
OSM extract, but its graph version must match the selected template.
If the OSM file or graph conversion version changes, generate a matching
template and choose a new database path. Existing Anamizu databases created
with the old backend importer have different graph versions; startup refuses
to silently replace their data. They are not automatically migrated or deleted.

Configure local frontend origins with a comma-separated `ROUTEPULSE_CORS_ORIGINS`; the defaults are `http://localhost:5173` and `http://localhost:3000`.

## API

Base URL: `http://localhost:8000/api`

- `GET /scenario`
- `GET /areas/area-a/state`
- `POST /areas/area-a/routes`
- `POST /areas/area-a/reports`
- `POST /areas/area-a/demo-advance`
- `POST /areas/area-a/questions`
- In `anamizu-7day` mode, also `POST /areas/area-a/reports/batch` and
  `POST /areas/area-a/advance-day`

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
both supported launch directories, the checked-in full seven-day scenario,
manual feedback, failure handling and database restart. They do not use or
modify your demo database.

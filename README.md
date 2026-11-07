# RoutePulse

## Local frontend and backend

The frontend reads the backend API, but the road statuses and seven-day frames
are fictional exercise data, not live conditions or real-world navigation.

### Quick demo on this Mac

Open two terminals in the project root. With the existing backend `.venv` and
local `.tools` Node runtime installed, start the backend in the first terminal:

```bash
ROUTEPULSE_SCENARIO_MODE=anamizu-7day \
ROUTEPULSE_DB_PATH=routepulse-backend/work/anamizu-accessible-demo.sqlite3 \
PYTHONPATH=routepulse-backend \
routepulse-backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 9000
```

In the second terminal:

```bash
PATH="$PWD/.tools/node-v22.23.4-darwin-arm64/bin:$PATH" npm run dev -- --host 127.0.0.1 --port 5173
```

Open <http://127.0.0.1:5173/>, select **Rescue Route**, and click **Load Day
1**. Choose a start and destination and click **Calculate route**. The map
labels both endpoints; **Next day** applies the next simulated day and
recalculates the current route. Click a road and submit a manual blocked report
to close both available directions and recalculate after an on-the-ground
update. Open and suspected reports apply to the selected direction only.

The database persists between runs. For a fresh exercise or when switching
scenarios/graph versions, choose a **new** `ROUTEPULSE_DB_PATH`; do not delete
or overwrite an old database. The example uses a separate demo database.
If the project is used on another machine, install Python dependencies from
`routepulse-backend/requirements.txt`, install Node and run `npm ci`; `.tools`
is local to this machine and not included in the repository.

The default exercise blocks 95 of 2,540 physical segments per day (3.74%),
with both newly closed and reopened segments each day. Its simulated closures
preserve the directed reachability already present in the original graph; the
named start/end choices use its largest mutually reachable group. Later manual
reports can still make routes impossible. These are scripted conditions, not
satellite imagery or real disaster data. Graph coverage, vehicle suitability,
and safety are not established. The original high-damage scenario remains at
`data/anamizu-v2/seven-day-scenario.json` and can be selected for a fresh
database with `ROUTEPULSE_DAY_TEMPLATES_PATH`.

### Other platforms

From the project root in PowerShell, with backend dependencies installed:

```powershell
$env:PYTHONPATH = "routepulse-backend"
$env:ROUTEPULSE_SCENARIO_MODE = "anamizu-7day"
$env:ROUTEPULSE_DB_PATH = "routepulse-backend/work/anamizu-accessible-demo.sqlite3"
python -m uvicorn app.main:app --reload --port 9000
```

In a second terminal at the project root, run `npm install` and `npm run dev`.
Vite proxies `/api` to `http://localhost:9000`. For another backend address,
set `VITE_API_BASE_URL` to its API root before starting or building the frontend;
configure the backend CORS allowlist if using a cross-origin URL. The backend
uses persistent SQLite data; use `ROUTEPULSE_DB_PATH` to choose a fresh exercise.

Click a road to submit a manual report. A blocked report applies to both
available directions of that segment; open and suspected reports apply only
to the selected direction. `Next day` advances
the seven-day exercise sequentially and cannot rewind it. Submit manual reports
after advancing to Day 1: a Day 0 report advances the backend clock to the
first frame's timestamp, which would otherwise prevent applying that frame.

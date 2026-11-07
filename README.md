# RoutePulse

## Local frontend and backend

The frontend reads the backend API, but the road statuses and seven-day frames
are fictional exercise data, not live conditions or real-world navigation.

From the project root in PowerShell, with backend dependencies installed:

```powershell
$env:PYTHONPATH = "routepulse-backend"
$env:ROUTEPULSE_SCENARIO_MODE = "anamizu-7day"
python -m uvicorn app.main:app --reload --port 9000
```

In a second terminal at the project root, run `npm install` and `npm run dev`.
Vite proxies `/api` to `http://localhost:9000`. For another backend address,
set `VITE_API_BASE_URL` to its API root before starting or building the frontend;
configure the backend CORS allowlist if using a cross-origin URL. The backend
uses persistent SQLite data; use `ROUTEPULSE_DB_PATH` to choose a fresh exercise.

Click a road to select its direction for a manual report. Opposite directions
can have different statuses and are submitted separately. `Next day` advances
the seven-day exercise sequentially and cannot rewind it. Submit manual reports
after advancing to Day 1: a Day 0 report advances the backend clock to the
first frame's timestamp, which would otherwise prevent applying that frame.

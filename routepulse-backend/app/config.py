from __future__ import annotations

import os
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def scenario_mode() -> str:
    value = os.environ.get("ROUTEPULSE_SCENARIO_MODE", "legacy").strip().casefold()
    if value not in {"legacy", "anamizu-7day"}:
        raise ValueError("ROUTEPULSE_SCENARIO_MODE must be 'legacy' or 'anamizu-7day'.")
    return value


def osm_path() -> Path:
    return Path(os.environ.get("ROUTEPULSE_OSM_PATH", str(BACKEND_DIR / "data" / "map.osm"))).expanduser()


def day_templates_path() -> Path:
    return Path(os.environ.get("ROUTEPULSE_DAY_TEMPLATES_PATH", str(BACKEND_DIR / "data" / "day_templates.json"))).expanduser()


def database_path() -> Path:
    """Return the configured SQLite path (relative paths use the launch directory)."""
    default = "routepulse-anamizu-7day.sqlite3" if scenario_mode() == "anamizu-7day" else "routepulse.sqlite3"
    return Path(os.environ.get("ROUTEPULSE_DB_PATH", default)).expanduser()


def cors_origins() -> list[str]:
    configured = os.environ.get("ROUTEPULSE_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
    return [origin.strip() for origin in configured.split(",") if origin.strip()]

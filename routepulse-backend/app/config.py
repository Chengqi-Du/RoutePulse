from __future__ import annotations

import os
from pathlib import Path


def database_path() -> Path:
    """Return the configured SQLite path (relative paths use the launch directory)."""
    return Path(os.environ.get("ROUTEPULSE_DB_PATH", "routepulse.sqlite3")).expanduser()


def cors_origins() -> list[str]:
    configured = os.environ.get("ROUTEPULSE_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
    return [origin.strip() for origin in configured.split(",") if origin.strip()]

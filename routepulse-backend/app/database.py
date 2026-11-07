from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .config import database_path


SCENARIO_ID = "earthquake-demo"
AREA_ID = "area-a"
INITIAL_SCENARIO_TIME = "2026-01-01T10:00:00Z"

NODES = [
    ("S", "Base S", "base", -8.480, 51.900),
    ("A", "Junction A", "junction", -8.475, 51.902),
    ("B", "Junction B", "junction", -8.475, 51.898),
    ("T", "Incident T", "incident", -8.470, 51.900),
]
EDGES = [
    ("road-sa", "S", "A", 1000),
    ("road-at", "A", "T", 1000),
    ("road-sb", "S", "B", 2000),
    ("road-bt", "B", "T", 2000),
]
SEED_REPORTS = [
    ("seed-sa", "road-sa"),
    ("seed-at", "road-at"),
    ("seed-sb", "road-sb"),
    ("seed-bt", "road-bt"),
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="auto").replace("+00:00", "Z")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def initialize_database() -> None:
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS area_state (
                area_id TEXT PRIMARY KEY,
                scenario_id TEXT NOT NULL,
                scenario_time TEXT NOT NULL,
                version INTEGER NOT NULL,
                demo_advanced INTEGER NOT NULL DEFAULT 0,
                current_route_id TEXT,
                route_change_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                area_id TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                longitude REAL NOT NULL,
                latitude REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS edges (
                id TEXT PRIMARY KEY,
                area_id TEXT NOT NULL,
                from_node_id TEXT NOT NULL,
                to_node_id TEXT NOT NULL,
                length_m INTEGER NOT NULL CHECK(length_m >= 0)
            );
            CREATE TABLE IF NOT EXISTS reports (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL UNIQUE,
                edge_id TEXT NOT NULL,
                status TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                note TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reports_edge_source
                ON reports(edge_id, source_type, source_id, observed_at);
            CREATE TABLE IF NOT EXISTS route_results (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                start_node_id TEXT NOT NULL,
                end_node_id TEXT NOT NULL,
                node_ids_json TEXT NOT NULL,
                edge_ids_json TEXT NOT NULL,
                distance_m INTEGER,
                computed_at TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_report_id TEXT
            );
            """
        )
        with transaction(connection):
            exists = connection.execute(
                "SELECT 1 FROM area_state WHERE area_id = ?", (AREA_ID,)
            ).fetchone()
            if exists:
                return
            connection.execute(
                "INSERT INTO area_state(area_id, scenario_id, scenario_time, version, demo_advanced, current_route_id, route_change_json) "
                "VALUES (?, ?, ?, 1, 0, NULL, ?)",
                (AREA_ID, SCENARIO_ID, INITIAL_SCENARIO_TIME,
                 '{"has_previous":false,"changed":false,"affected_previous_route":false,"trigger_report_id":null}'),
            )
            connection.executemany(
                "INSERT INTO nodes(id, area_id, name, type, longitude, latitude) VALUES (?, ?, ?, ?, ?, ?)",
                [(node_id, AREA_ID, name, node_type, lon, lat) for node_id, name, node_type, lon, lat in NODES],
            )
            connection.executemany(
                "INSERT INTO edges(id, area_id, from_node_id, to_node_id, length_m) VALUES (?, ?, ?, ?, ?)",
                [(edge_id, AREA_ID, start, end, length) for edge_id, start, end, length in EDGES],
            )
            recorded_at = utc_now_iso()
            connection.executemany(
                "INSERT INTO reports(id, edge_id, status, source_type, source_id, source_name, observed_at, recorded_at, note) "
                "VALUES (?, ?, 'reported_open', 'seed', 'seed', 'Simulated initial report', ?, ?, '')",
                [(report_id, edge_id, INITIAL_SCENARIO_TIME, recorded_at) for report_id, edge_id in SEED_REPORTS],
            )

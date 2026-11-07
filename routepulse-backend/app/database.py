from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .config import database_path, osm_path, scenario_mode
from .osm_import import load_osm_graph


SCENARIO_ID = "earthquake-demo"
AREA_ID = "area-a"
INITIAL_SCENARIO_TIME = "2026-01-01T10:00:00Z"
ANAMIZU_SCENARIO_ID = "anamizu-seven-day-exercise"
ANAMIZU_INITIAL_TIME = "2024-01-02T00:59:59Z"

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
SEED_REPORTS = [("seed-sa", "road-sa"), ("seed-at", "road-at"), ("seed-sb", "road-sb"), ("seed-bt", "road-bt")]


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


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS area_state (
            area_id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, scenario_time TEXT NOT NULL,
            version INTEGER NOT NULL, demo_advanced INTEGER NOT NULL DEFAULT 0,
            current_route_id TEXT, route_change_json TEXT NOT NULL,
            scenario_mode TEXT NOT NULL DEFAULT 'legacy', graph_version TEXT,
            graph_metadata_json TEXT, day_index INTEGER NOT NULL DEFAULT 0,
            day_count INTEGER NOT NULL DEFAULT 0, scenario_date_local TEXT, frame_id TEXT,
            day_frame_json TEXT
        );
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY, area_id TEXT NOT NULL, name TEXT NOT NULL, type TEXT NOT NULL,
            longitude REAL NOT NULL, latitude REAL NOT NULL, osm_node_id TEXT, tags_json TEXT
        );
        CREATE TABLE IF NOT EXISTS edges (
            id TEXT PRIMARY KEY, area_id TEXT NOT NULL, from_node_id TEXT NOT NULL,
            to_node_id TEXT NOT NULL, length_m REAL NOT NULL CHECK(length_m >= 0),
            osm_way_id TEXT, highway TEXT, name TEXT, direction TEXT, geometry_json TEXT, tags_json TEXT
        );
        CREATE TABLE IF NOT EXISTS reports (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, edge_id TEXT NOT NULL,
            status TEXT NOT NULL, source_type TEXT NOT NULL, source_id TEXT NOT NULL,
            source_name TEXT NOT NULL, observed_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
            note TEXT NOT NULL, graph_version TEXT, frame_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_reports_edge_source ON reports(edge_id, source_type, source_id, observed_at);
        CREATE TABLE IF NOT EXISTS route_results (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, status TEXT NOT NULL,
            start_node_id TEXT NOT NULL, end_node_id TEXT NOT NULL, node_ids_json TEXT NOT NULL,
            edge_ids_json TEXT NOT NULL, distance_m REAL, computed_at TEXT NOT NULL,
            trigger_type TEXT NOT NULL, trigger_report_id TEXT,
            trigger_report_ids_json TEXT NOT NULL DEFAULT '[]', frame_id TEXT,
            affected_previous_edge_ids_json TEXT NOT NULL DEFAULT '[]'
        );
        """
    )
    # Additive migrations preserve existing legacy databases.
    additions = {
        "area_state": [
            ("scenario_mode", "TEXT NOT NULL DEFAULT 'legacy'"), ("graph_version", "TEXT"),
            ("graph_metadata_json", "TEXT"), ("day_index", "INTEGER NOT NULL DEFAULT 0"),
            ("day_count", "INTEGER NOT NULL DEFAULT 0"), ("scenario_date_local", "TEXT"),
            ("frame_id", "TEXT"), ("day_frame_json", "TEXT"),
        ],
        "nodes": [("osm_node_id", "TEXT"), ("tags_json", "TEXT")],
        "edges": [("osm_way_id", "TEXT"), ("highway", "TEXT"), ("name", "TEXT"),
                  ("direction", "TEXT"), ("geometry_json", "TEXT"), ("tags_json", "TEXT")],
        "reports": [("graph_version", "TEXT"), ("frame_id", "TEXT")],
        "route_results": [("trigger_report_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
                          ("frame_id", "TEXT"), ("affected_previous_edge_ids_json", "TEXT NOT NULL DEFAULT '[]'")],
    }
    for table, columns in additions.items():
        existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        for name, declaration in columns:
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def _initialize_legacy(connection: sqlite3.Connection) -> None:
    exists = connection.execute("SELECT 1 FROM area_state WHERE area_id = ?", (AREA_ID,)).fetchone()
    if exists:
        if exists["scenario_mode"] != "legacy":
            raise RuntimeError("Database belongs to another scenario mode; configure a separate ROUTEPULSE_DB_PATH.")
        return
    with transaction(connection):
        connection.execute(
            "INSERT INTO area_state(area_id,scenario_id,scenario_time,version,demo_advanced,current_route_id,route_change_json,scenario_mode) "
            "VALUES(?,?,?,1,0,NULL,?,'legacy')",
            (AREA_ID, SCENARIO_ID, INITIAL_SCENARIO_TIME,
             '{"has_previous":false,"changed":false,"affected_previous_route":false,"trigger_report_id":null,"trigger_report_ids":[],"affected_previous_edge_ids":[]}'),
        )
        connection.executemany(
            "INSERT INTO nodes(id,area_id,name,type,longitude,latitude) VALUES(?,?,?,?,?,?)",
            [(node_id, AREA_ID, name, node_type, lon, lat) for node_id, name, node_type, lon, lat in NODES],
        )
        connection.executemany(
            "INSERT INTO edges(id,area_id,from_node_id,to_node_id,length_m) VALUES(?,?,?,?,?)",
            [(edge_id, AREA_ID, start, end, length) for edge_id, start, end, length in EDGES],
        )
        recorded_at = utc_now_iso()
        connection.executemany(
            "INSERT INTO reports(id,edge_id,status,source_type,source_id,source_name,observed_at,recorded_at,note) "
            "VALUES(?,?,'reported_open','seed','seed','Simulated initial report',?,?, '')",
            [(report_id, edge_id, INITIAL_SCENARIO_TIME, recorded_at) for report_id, edge_id in SEED_REPORTS],
        )


def _initialize_anamizu(connection: sqlite3.Connection) -> None:
    try:
        graph = load_osm_graph(osm_path())
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Could not import the configured OSM map: {exc}") from exc
    existing = connection.execute("SELECT * FROM area_state WHERE area_id = ?", (AREA_ID,)).fetchone()
    if existing:
        if existing["scenario_mode"] != "anamizu-7day":
            raise RuntimeError("Database belongs to another scenario mode; configure a separate ROUTEPULSE_DB_PATH.")
        if existing["graph_version"] != graph["graph_version"]:
            raise RuntimeError("OSM graph differs from this database. Set a new ROUTEPULSE_DB_PATH to import the new graph safely.")
        return
    with transaction(connection):
        connection.execute(
            "INSERT INTO area_state(area_id,scenario_id,scenario_time,version,demo_advanced,current_route_id,route_change_json,scenario_mode,graph_version,graph_metadata_json,day_index,day_count,scenario_date_local) "
            "VALUES(?,?,?,1,0,NULL,?,?,?,?,0,7,'2024-01-02')",
            (AREA_ID, ANAMIZU_SCENARIO_ID, ANAMIZU_INITIAL_TIME,
             '{"has_previous":false,"changed":false,"affected_previous_route":false,"trigger_report_id":null,"trigger_report_ids":[],"affected_previous_edge_ids":[]}',
             "anamizu-7day", graph["graph_version"], json.dumps(graph["metadata"], ensure_ascii=False, separators=(",", ":"))),
        )
        connection.executemany(
            "INSERT INTO nodes(id,area_id,name,type,longitude,latitude,osm_node_id,tags_json) VALUES(?,?,?,?,?,?,?,?)",
            [(node["id"], AREA_ID, node["name"], node["type"], node["coordinates"][0], node["coordinates"][1],
              node["osm_node_id"], json.dumps(node["tags"], ensure_ascii=False, separators=(",", ":"))) for node in graph["nodes"]],
        )
        connection.executemany(
            "INSERT INTO edges(id,area_id,from_node_id,to_node_id,length_m,osm_way_id,highway,name,direction,geometry_json,tags_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(edge["id"], AREA_ID, edge["from_node_id"], edge["to_node_id"], edge["length_m"], edge["osm_way_id"],
              edge["highway"], edge["name"], edge["direction"],
              json.dumps(edge["geometry"], separators=(",", ":")),
              json.dumps(edge["tags"], ensure_ascii=False, separators=(",", ":"))) for edge in graph["edges"]],
        )


def initialize_database() -> None:
    with connect() as connection:
        _create_schema(connection)
        mode = scenario_mode()
        if mode == "legacy":
            _initialize_legacy(connection)
        else:
            _initialize_anamizu(connection)

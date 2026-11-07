from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator

from .config import cors_origins, day_templates_path, scenario_mode
from .database import AREA_ID, SCENARIO_ID, ANAMIZU_SCENARIO_ID, connect, initialize_database, transaction, utc_now_iso
from .simulation import load_day_templates
from algorithm.questions import parse_question
from algorithm.routing import find_route


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("routepulse")

app = FastAPI(
    title="RoutePulse API",
    version="1.0.0",
    description="Simulation-only earthquake exercise backend.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, current_version: int | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.current_version = current_version


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RouteRequest(StrictModel):
    expected_version: int
    start_node_id: str
    end_node_id: str


class ReportRequest(StrictModel):
    expected_version: int
    edge_id: str
    status: str
    source_id: str
    source_name: str
    observed_at: datetime
    note: str = ""

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        if value not in {"reported_open", "reported_blocked", "reported_suspected"}:
            raise ValueError("invalid report status")
        return value

    @field_validator("source_id", "source_name")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @field_validator("observed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(timezone.utc)


class VersionRequest(StrictModel):
    expected_version: int


class BatchReportRequest(StrictModel):
    expected_version: int
    edge_ids: list[str]
    status: str
    source_id: str
    source_name: str
    observed_at: datetime
    note: str = ""

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        if value not in {"reported_open", "reported_blocked", "reported_suspected"}:
            raise ValueError("invalid report status")
        return value

    @field_validator("edge_ids")
    @classmethod
    def nonempty_unique_edges(cls, value: list[str]) -> list[str]:
        if not value or any(not edge_id.strip() for edge_id in value) or len(set(value)) != len(value):
            raise ValueError("edge_ids must be a non-empty list of unique IDs")
        return value

    @field_validator("source_id", "source_name")
    @classmethod
    def required_batch_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @field_validator("observed_at")
    @classmethod
    def batch_timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(timezone.utc)


class QuestionRequest(StrictModel):
    expected_version: int
    question: str

    @field_validator("question")
    @classmethod
    def nonempty_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be empty")
        return value.strip()


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "current_version": exc.current_version}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "INVALID_INPUT", "message": "Request fields are invalid.", "current_version": None}},
    )


@app.exception_handler(Exception)
async def internal_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled RoutePulse request failure", exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "The request could not be completed.", "current_version": None}},
    )


@app.on_event("startup")
def startup() -> None:
    initialize_database()


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="auto").replace("+00:00", "Z")


def decode_json(value: str) -> Any:
    return json.loads(value)


def require_area(connection: sqlite3.Connection, area_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM area_state WHERE area_id = ?", (area_id,)).fetchone()
    if row is None:
        raise ApiError(404, "AREA_NOT_FOUND", "Area was not found.")
    return row


def check_version(area: sqlite3.Row, expected_version: int) -> None:
    if expected_version != area["version"]:
        raise ApiError(409, "VERSION_CONFLICT", "Area state changed. Refresh and retry.", area["version"])


def next_report_id(connection: sqlite3.Connection) -> str:
    return f"report-{connection.execute('SELECT COUNT(*) FROM reports').fetchone()[0] + 1:03d}"


def next_route_id(connection: sqlite3.Connection) -> str:
    return f"route-{connection.execute('SELECT COUNT(*) FROM route_results').fetchone()[0] + 1:03d}"


def all_nodes(connection: sqlite3.Connection, area_id: str) -> list[dict[str, Any]]:
    rows = connection.execute("SELECT * FROM nodes WHERE area_id = ? ORDER BY rowid", (area_id,)).fetchall()
    return [
        {"id": row["id"], "name": row["name"], "type": row["type"],
         "coordinates": [row["longitude"], row["latitude"]],
         **({"osm_node_id": row["osm_node_id"]} if row["osm_node_id"] else {})}
        for row in rows
    ]


def raw_reports(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute("SELECT * FROM reports ORDER BY seq").fetchall()


def is_fresh(observed_at: str, scenario_time: str) -> bool:
    observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    now = datetime.fromisoformat(scenario_time.replace("Z", "+00:00"))
    age_seconds = (now - observed).total_seconds()
    return 0 <= age_seconds <= 30 * 60


def edge_snapshot(
    connection: sqlite3.Connection, area_id: str, scenario_time: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    report_rows = raw_reports(connection)
    latest_by_source: dict[tuple[str, str, str], sqlite3.Row] = {}
    latest_times: dict[tuple[str, str, str], datetime] = {}
    non_seed_edges: set[str] = set()
    for report in report_rows:
        key = (report["edge_id"], report["source_type"], report["source_id"])
        observed = datetime.fromisoformat(report["observed_at"].replace("Z", "+00:00"))
        if key not in latest_times or observed > latest_times[key]:
            latest_by_source[key] = report
            latest_times[key] = observed
        if report["source_type"] != "seed":
            non_seed_edges.add(report["edge_id"])

    latest_ids = {row["id"] for row in latest_by_source.values()}
    latest_by_edge: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for (edge_id, _, _), report in latest_by_source.items():
        latest_by_edge[edge_id].append(report)
    report_payloads = [{
        "id": report["id"],
        "edge_id": report["edge_id"],
        "status": report["status"],
        "source_type": report["source_type"],
        "source_id": report["source_id"],
        "source_name": report["source_name"],
        "observed_at": report["observed_at"],
        "recorded_at": report["recorded_at"],
        "note": report["note"],
        "graph_version": report["graph_version"],
        "frame_id": report["frame_id"],
        "is_latest_for_source": report["id"] in latest_ids,
        "is_fresh": is_fresh(report["observed_at"], scenario_time),
    } for report in report_rows]

    edge_rows = connection.execute("SELECT * FROM edges WHERE area_id = ? ORDER BY rowid", (area_id,)).fetchall()
    edges: list[dict[str, Any]] = []
    for edge in edge_rows:
        has_non_seed_ever = edge["id"] in non_seed_edges
        evidence: list[sqlite3.Row] = []
        for report in latest_by_edge[edge["id"]]:
            fresh = is_fresh(report["observed_at"], scenario_time)
            if report["source_type"] == "seed":
                if not has_non_seed_ever and fresh:
                    evidence.append(report)
            elif report["source_type"] == "manual":
                if report["status"] in {"reported_blocked", "reported_suspected"} or fresh:
                    evidence.append(report)
            elif fresh:
                evidence.append(report)

        statuses = {report["status"] for report in evidence}
        opened = "reported_open" in statuses
        blocked = "reported_blocked" in statuses
        suspected = "reported_suspected" in statuses
        if opened and (blocked or suspected):
            effective_status = "conflict"
        elif blocked:
            effective_status = "blocked"
        elif suspected:
            effective_status = "suspected"
        elif opened:
            effective_status = "open"
        else:
            effective_status = "unknown"
        edges.append({
            "id": edge["id"],
            "from_node_id": edge["from_node_id"],
            "to_node_id": edge["to_node_id"],
            "length_m": edge["length_m"],
            "osm_way_id": edge["osm_way_id"],
            "highway": edge["highway"],
            "name": edge["name"],
            "direction": edge["direction"],
            "geometry": decode_json(edge["geometry_json"]) if edge["geometry_json"] else None,
            "effective_status": effective_status,
            "evidence_report_ids": [report["id"] for report in sorted(evidence, key=lambda item: item["seq"])],
        })
    return edges, report_payloads


def route_object(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "status": row["status"],
        "start_node_id": row["start_node_id"],
        "end_node_id": row["end_node_id"],
        "node_ids": decode_json(row["node_ids_json"]),
        "edge_ids": decode_json(row["edge_ids_json"]),
        "distance_m": row["distance_m"],
        "computed_at": row["computed_at"],
        "trigger": {"type": row["trigger_type"], "report_id": row["trigger_report_id"],
                    "report_ids": decode_json(row["trigger_report_ids_json"]), "frame_id": row["frame_id"]},
        "affected_previous_edge_ids": decode_json(row["affected_previous_edge_ids_json"]),
    }


def get_route(connection: sqlite3.Connection, route_id: str | None) -> dict[str, Any] | None:
    if route_id is None:
        return None
    row = connection.execute("SELECT * FROM route_results WHERE id = ?", (route_id,)).fetchone()
    return route_object(row)


def state_payload(connection: sqlite3.Connection, area: sqlite3.Row) -> dict[str, Any]:
    nodes = all_nodes(connection, area["area_id"])
    edges, reports = edge_snapshot(connection, area["area_id"], area["scenario_time"])
    current = get_route(connection, area["current_route_id"])
    if current is None:
        history_rows = connection.execute("SELECT * FROM route_results ORDER BY seq").fetchall()
    else:
        history_rows = connection.execute(
            "SELECT * FROM route_results WHERE id != ? ORDER BY seq", (current["id"],)
        ).fetchall()
    return {
        "scenario_id": area["scenario_id"],
        "area_id": area["area_id"],
        "is_simulation": True,
        "version": area["version"],
        "scenario_time": area["scenario_time"],
        "scenario_mode": area["scenario_mode"],
        "graph_version": area["graph_version"],
        "graph_metadata": decode_json(area["graph_metadata_json"]) if area["graph_metadata_json"] else None,
        "day_index": area["day_index"],
        "day_count": area["day_count"],
        "scenario_date_local": area["scenario_date_local"],
        "day_frame": decode_json(area["day_frame_json"]) if area["day_frame_json"] else None,
        "nodes": nodes,
        "edges": edges,
        "reports": reports,
        "current_result": current,
        "history": [route_object(row) for row in history_rows],
        "route_change": decode_json(area["route_change_json"]),
    }


def ensure_nodes_exist(connection: sqlite3.Connection, area_id: str, *node_ids: str) -> None:
    known = {row["id"] for row in connection.execute(
        "SELECT id FROM nodes WHERE area_id = ?", (area_id,)
    ).fetchall()}
    for node_id in node_ids:
        if node_id not in known:
            raise ApiError(404, "NODE_NOT_FOUND", f"Node '{node_id}' was not found.")


def effective_edges(connection: sqlite3.Connection, area: sqlite3.Row) -> list[dict[str, Any]]:
    return edge_snapshot(connection, area["area_id"], area["scenario_time"])[0]


def compute_and_store_route(
    connection: sqlite3.Connection,
    area: sqlite3.Row,
    start_node_id: str,
    end_node_id: str,
    trigger_type: str,
    trigger_report_id: str | None,
    trigger_report_ids: list[str] | None = None,
    frame_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ensure_nodes_exist(connection, area["area_id"], start_node_id, end_node_id)
    previous = get_route(connection, area["current_route_id"])
    path = find_route(
        all_nodes(connection, area["area_id"]),
        effective_edges(connection, area),
        start_node_id,
        end_node_id,
    )
    report_ids = trigger_report_ids if trigger_report_ids is not None else ([trigger_report_id] if trigger_report_id else [])
    report_rows = raw_reports(connection)
    reports_by_id = {report["id"]: report for report in report_rows}
    affected_previous_edge_ids = sorted({
        reports_by_id[report_id]["edge_id"] for report_id in report_ids
        if report_id in reports_by_id and previous is not None
        and previous["status"] == "found"
        and reports_by_id[report_id]["edge_id"] in previous["edge_ids"]
    })
    route_id = next_route_id(connection)
    connection.execute(
        "INSERT INTO route_results(id, status, start_node_id, end_node_id, node_ids_json, edge_ids_json, distance_m, computed_at, trigger_type, trigger_report_id, trigger_report_ids_json, frame_id, affected_previous_edge_ids_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (route_id, path["status"], start_node_id, end_node_id, json.dumps(path["node_ids"]),
         json.dumps(path["edge_ids"]), path["distance_m"], area["scenario_time"], trigger_type, trigger_report_id,
         json.dumps(report_ids), frame_id, json.dumps(affected_previous_edge_ids)),
    )
    current = {
        "id": route_id,
        "status": path["status"],
        "start_node_id": start_node_id,
        "end_node_id": end_node_id,
        "node_ids": path["node_ids"],
        "edge_ids": path["edge_ids"],
        "distance_m": path["distance_m"],
        "computed_at": area["scenario_time"],
        "trigger": {"type": trigger_type, "report_id": trigger_report_id,
                    "report_ids": report_ids, "frame_id": frame_id},
        "affected_previous_edge_ids": affected_previous_edge_ids,
    }
    changed = bool(previous is not None and (
        previous["status"] != current["status"] or previous["edge_ids"] != current["edge_ids"]
    ))
    affected = bool(affected_previous_edge_ids)
    change = {
        "has_previous": previous is not None,
        "changed": changed,
        "affected_previous_route": affected,
        "trigger_report_id": trigger_report_id,
        "trigger_report_ids": report_ids,
        "frame_id": frame_id,
        "affected_previous_edge_ids": affected_previous_edge_ids,
    }
    return current, change


def save_calculation(
    connection: sqlite3.Connection,
    area: sqlite3.Row,
    route: dict[str, Any],
    change: dict[str, Any],
) -> int:
    version = area["version"] + 1
    connection.execute(
        "UPDATE area_state SET version = ?, current_route_id = ?, route_change_json = ? WHERE area_id = ?",
        (version, route["id"], json.dumps(change, separators=(",", ":")), area["area_id"]),
    )
    return version


def recompute_if_current(
    connection: sqlite3.Connection,
    area: sqlite3.Row,
    report_id: str | None,
    trigger_type: str,
    report_ids: list[str] | None = None,
    frame_id: str | None = None,
) -> None:
    previous = get_route(connection, area["current_route_id"])
    if previous is None:
        return
    route, change = compute_and_store_route(
        connection, area, previous["start_node_id"], previous["end_node_id"], trigger_type, report_id,
        trigger_report_ids=report_ids, frame_id=frame_id,
    )
    connection.execute(
        "UPDATE area_state SET current_route_id = ?, route_change_json = ? WHERE area_id = ?",
        (route["id"], json.dumps(change, separators=(",", ":")), area["area_id"]),
    )


@app.get("/api/scenario")
def get_scenario() -> dict[str, Any]:
    if scenario_mode() == "anamizu-7day":
        with connect() as connection:
            area = require_area(connection, AREA_ID)
            metadata = decode_json(area["graph_metadata_json"])
        bounds = metadata.get("bounds") or {}
        return {
            "scenario_id": ANAMIZU_SCENARIO_ID,
            "is_simulation": True,
            "title": "Anamizu Seven-Day Road Exercise",
            "description": "Seven-day simulated exercise on an imported OSM candidate road graph. OSM data does not indicate earthquake damage or current passability.",
            "earthquake": None,
            "areas": [{
                "id": AREA_ID,
                "name": "Anamizu Town (OSM extract bounds)",
                "bbox": [bounds.get("min_lon"), bounds.get("min_lat"), bounds.get("max_lon"), bounds.get("max_lat")],
                "available": True,
                "graph_version": area["graph_version"],
                "coverage_review_status": metadata.get("coverage_review_status"),
            }],
        }
    return {
        "scenario_id": SCENARIO_ID,
        "is_simulation": True,
        "title": "Earthquake Exercise",
        "description": "Simulated earthquake scenario.",
        "earthquake": {
            "magnitude": 7.0,
            "location": [-8.480, 51.900],
            "occurred_at": "2026-01-01T09:30:00Z",
        },
        "areas": [{
            "id": AREA_ID,
            "name": "Rescue Area A",
            "bbox": [-8.49, 51.89, -8.46, 51.91],
            "available": True,
        }],
    }


@app.get("/api/areas/{area_id}/state")
def get_area_state(area_id: str) -> dict[str, Any]:
    with connect() as connection:
        # Keep each field in this response on the same SQLite read snapshot.
        connection.execute("BEGIN")
        try:
            area = require_area(connection, area_id)
            payload = state_payload(connection, area)
            connection.commit()
            return payload
        except BaseException:
            connection.rollback()
            raise


@app.post("/api/areas/{area_id}/routes")
def create_route(area_id: str, body: RouteRequest) -> dict[str, int]:
    with connect() as connection:
        with transaction(connection):
            area = require_area(connection, area_id)
            check_version(area, body.expected_version)
            route, change = compute_and_store_route(
                connection, area, body.start_node_id, body.end_node_id, "user_request", None
            )
            version = save_calculation(connection, area, route, change)
            return {"version": version}


@app.post("/api/areas/{area_id}/reports", status_code=201)
def create_report(area_id: str, body: ReportRequest) -> dict[str, Any]:
    with connect() as connection:
        with transaction(connection):
            area = require_area(connection, area_id)
            check_version(area, body.expected_version)
            edge = connection.execute(
                "SELECT id FROM edges WHERE id = ? AND area_id = ?", (body.edge_id, area_id)
            ).fetchone()
            if edge is None:
                raise ApiError(404, "EDGE_NOT_FOUND", f"Edge '{body.edge_id}' was not found.")
            observed_at = iso_utc(body.observed_at)
            scenario_time = datetime.fromisoformat(area["scenario_time"].replace("Z", "+00:00"))
            if body.observed_at > scenario_time:
                raise ApiError(422, "INVALID_INPUT", "observed_at cannot be later than scenario_time.")
            latest = connection.execute(
                "SELECT observed_at FROM reports WHERE edge_id = ? AND source_type = 'manual' AND source_id = ? "
                "ORDER BY seq DESC LIMIT 1",
                (body.edge_id, body.source_id),
            ).fetchone()
            if latest is not None and body.observed_at <= datetime.fromisoformat(
                latest["observed_at"].replace("Z", "+00:00")
            ):
                raise ApiError(422, "INVALID_INPUT", "observed_at must be later than the previous report from this source on this road.")

            report_id = next_report_id(connection)
            connection.execute(
                "INSERT INTO reports(id, edge_id, status, source_type, source_id, source_name, observed_at, recorded_at, note, graph_version, frame_id) "
                "VALUES (?, ?, ?, 'manual', ?, ?, ?, ?, ?, ?, ?)",
                (report_id, body.edge_id, body.status, body.source_id, body.source_name,
                 observed_at, utc_now_iso(), body.note, area["graph_version"], area["frame_id"]),
            )
            if area["scenario_mode"] == "anamizu-7day":
                next_time = iso_utc(datetime.fromisoformat(area["scenario_time"].replace("Z", "+00:00")) + timedelta(seconds=1))
                connection.execute("UPDATE area_state SET scenario_time = ? WHERE area_id = ?", (next_time, area_id))
                area = require_area(connection, area_id)
            recompute_if_current(connection, area, report_id, "manual_report", frame_id=area["frame_id"])
            version = area["version"] + 1
            connection.execute("UPDATE area_state SET version = ? WHERE area_id = ?", (version, area_id))
            return {"version": version, "report_id": report_id}


@app.post("/api/areas/{area_id}/reports/batch", status_code=201)
def create_reports_batch(area_id: str, body: BatchReportRequest) -> dict[str, Any]:
    with connect() as connection:
        with transaction(connection):
            area = require_area(connection, area_id)
            check_version(area, body.expected_version)
            known = {row["id"] for row in connection.execute(
                "SELECT id FROM edges WHERE area_id = ?", (area_id,)
            ).fetchall()}
            unknown = [edge_id for edge_id in body.edge_ids if edge_id not in known]
            if unknown:
                raise ApiError(404, "EDGE_NOT_FOUND", f"Unknown edge IDs: {', '.join(unknown)}")
            observed_at = iso_utc(body.observed_at)
            scenario_time = datetime.fromisoformat(area["scenario_time"].replace("Z", "+00:00"))
            if body.observed_at > scenario_time:
                raise ApiError(422, "INVALID_INPUT", "observed_at cannot be later than scenario_time.")
            for edge_id in body.edge_ids:
                latest = connection.execute(
                    "SELECT observed_at FROM reports WHERE edge_id = ? AND source_type = 'manual' AND source_id = ? ORDER BY seq DESC LIMIT 1",
                    (edge_id, body.source_id),
                ).fetchone()
                if latest and body.observed_at <= datetime.fromisoformat(latest["observed_at"].replace("Z", "+00:00")):
                    raise ApiError(422, "INVALID_INPUT", f"observed_at must be later than the previous report from this source on {edge_id}.")
            report_ids = []
            for edge_id in body.edge_ids:
                report_id = next_report_id(connection)
                report_ids.append(report_id)
                connection.execute(
                    "INSERT INTO reports(id,edge_id,status,source_type,source_id,source_name,observed_at,recorded_at,note,graph_version,frame_id) "
                    "VALUES(?,?,?,'manual',?,?,?,?,?,?,?)",
                    (report_id, edge_id, body.status, body.source_id, body.source_name, observed_at,
                     utc_now_iso(), body.note, area["graph_version"], area["frame_id"]),
                )
            if area["scenario_mode"] == "anamizu-7day":
                next_time = iso_utc(scenario_time + timedelta(seconds=1))
                connection.execute("UPDATE area_state SET scenario_time = ? WHERE area_id = ?", (next_time, area_id))
                area = require_area(connection, area_id)
            recompute_if_current(connection, area, None, "manual_report_batch", report_ids, area["frame_id"])
            version = area["version"] + 1
            connection.execute("UPDATE area_state SET version = ? WHERE area_id = ?", (version, area_id))
            return {"version": version, "report_ids": report_ids}


@app.post("/api/areas/{area_id}/advance-day")
def advance_day(area_id: str, body: VersionRequest) -> dict[str, Any]:
    with connect() as connection:
        with transaction(connection):
            area = require_area(connection, area_id)
            check_version(area, body.expected_version)
            if area["scenario_mode"] != "anamizu-7day":
                raise ApiError(409, "MODE_MISMATCH", "Daily advancement is available only in anamizu-7day mode.", area["version"])
            if area["day_index"] >= area["day_count"]:
                raise ApiError(409, "DAY_SEQUENCE_COMPLETE", "All seven scenario days have already been played.", area["version"])
            try:
                edge_ids = {row["id"] for row in connection.execute("SELECT id FROM edges WHERE area_id = ?", (area_id,))}
                frames = load_day_templates(day_templates_path(), area["graph_version"], edge_ids)
            except FileNotFoundError as exc:
                raise ApiError(503, "DAY_TEMPLATES_NOT_CONFIGURED", "Integration's seven-day road observation file has not been supplied.", area["version"]) from exc
            except ValueError as exc:
                raise ApiError(422, "INVALID_DAY_TEMPLATES", str(exc), area["version"]) from exc
            next_index = area["day_index"] + 1
            frame = frames[next_index - 1]
            frame_time = frame["scenario_time"]
            if datetime.fromisoformat(frame_time.replace("Z", "+00:00")) <= datetime.fromisoformat(area["scenario_time"].replace("Z", "+00:00")):
                raise ApiError(422, "INVALID_DAY_TEMPLATES", "The next frame time must be later than current scenario_time.", area["version"])
            report_ids = []
            for index, observation in enumerate(frame["road_observations"], start=1):
                report_id = f"day-{next_index}-{frame['frame_id']}-{index}"
                report_ids.append(report_id)
                connection.execute(
                    "INSERT INTO reports(id,edge_id,status,source_type,source_id,source_name,observed_at,recorded_at,note,graph_version,frame_id) "
                    "VALUES(?,?,?,'external_demo',?,?,?,?,?,?,?)",
                    (report_id, observation["edge_id"], observation["status"], frame["observation_source_id"],
                     frame.get("observation_source_name", "Simulated day observation"), frame_time,
                     utc_now_iso(), observation.get("note", ""), area["graph_version"], frame["frame_id"]),
                )
            connection.execute(
                "UPDATE area_state SET scenario_time=?,day_index=?,scenario_date_local=?,frame_id=?,day_frame_json=? WHERE area_id=?",
                (frame_time, next_index, frame["scenario_date_local"], frame["frame_id"],
                 json.dumps(frame, ensure_ascii=False, separators=(",", ":")), area_id),
            )
            refreshed = require_area(connection, area_id)
            recompute_if_current(connection, refreshed, None, "scenario_day", report_ids, frame["frame_id"])
            version = area["version"] + 1
            connection.execute("UPDATE area_state SET version=? WHERE area_id=?", (version, area_id))
            return {"version": version, "day_index": next_index, "scenario_time": frame_time,
                    "scenario_date_local": frame["scenario_date_local"], "frame_id": frame["frame_id"],
                    "report_ids": report_ids}


@app.post("/api/areas/{area_id}/demo-advance")
def advance_demo(area_id: str, body: VersionRequest) -> dict[str, Any]:
    with connect() as connection:
        with transaction(connection):
            area = require_area(connection, area_id)
            check_version(area, body.expected_version)
            if area["scenario_mode"] != "legacy":
                raise ApiError(409, "MODE_MISMATCH", "The one-time legacy demo update is unavailable in anamizu-7day mode.", area["version"])
            if area["demo_advanced"]:
                raise ApiError(409, "DEMO_EXHAUSTED", "The one-time simulated update has already been used.", area["version"])
            scenario_time = "2026-01-01T10:10:00Z"
            report_id = next_report_id(connection)
            connection.execute(
                "INSERT INTO reports(id, edge_id, status, source_type, source_id, source_name, observed_at, recorded_at, note) "
                "VALUES (?, 'road-sa', 'reported_open', 'external_demo', 'external-demo-1', 'Simulated external report', ?, ?, ?)",
                (report_id, scenario_time, utc_now_iso(), "Simulated report says the road may be passable."),
            )
            connection.execute(
                "UPDATE area_state SET scenario_time = ?, demo_advanced = 1 WHERE area_id = ?",
                (scenario_time, area_id),
            )
            refreshed_area = require_area(connection, area_id)
            recompute_if_current(connection, refreshed_area, report_id, "demo_update")
            version = area["version"] + 1
            connection.execute("UPDATE area_state SET version = ? WHERE area_id = ?", (version, area_id))
            return {"version": version, "scenario_time": scenario_time, "report_id": report_id}


def route_answer(route: dict[str, Any]) -> tuple[str, list[str]]:
    if route["status"] == "no_path":
        return (
            "No candidate route is available under the current simulation evidence. Not for real-world navigation.",
            [],
        )
    roads = ", ".join(route["edge_ids"]) if route["edge_ids"] else "no roads"
    return (
        f"The simulated candidate route uses {roads}, totalling {route['distance_m']} metres. Not for real-world navigation.",
        route["edge_ids"],
    )


def why_changed_answer(connection: sqlite3.Connection, area: sqlite3.Row) -> tuple[str, list[str]]:
    change = decode_json(area["route_change_json"])
    current = get_route(connection, area["current_route_id"])
    if current is None:
        return "No route has been calculated yet, so there is no route change to explain.", []
    if not change["has_previous"]:
        return "There is no previous route calculation to compare with the current result.", current["edge_ids"]
    if not change["changed"]:
        return "The most recent route calculation produced the same status and roads as the previous calculation; the route did not change.", current["edge_ids"]

    trigger = current["trigger"]
    if trigger["type"] == "user_request":
        previous_row = connection.execute(
            "SELECT * FROM route_results WHERE id != ? ORDER BY seq DESC LIMIT 1", (current["id"],)
        ).fetchone()
        previous = route_object(previous_row)
        if previous and (previous["start_node_id"], previous["end_node_id"]) != (
            current["start_node_id"], current["end_node_id"]
        ):
            return "The result changed during a user-requested calculation with different start or end nodes.", current["edge_ids"]
        return "The result changed during a user-requested recalculation; no report triggered this calculation.", current["edge_ids"]

    report_ids = trigger.get("report_ids") or ([trigger["report_id"]] if trigger.get("report_id") else [])
    if not report_ids:
        return "The route changed during a recalculation, but the triggering batch contains no report IDs.", current["edge_ids"]
    placeholders = ",".join("?" for _ in report_ids)
    reports = connection.execute(f"SELECT * FROM reports WHERE id IN ({placeholders}) ORDER BY seq", report_ids).fetchall()
    if not reports:
        return "The latest result changed during a recalculation, but its triggering reports are unavailable.", current["edge_ids"]
    affected = change.get("affected_previous_edge_ids", [])
    if affected:
        message = (
            f"The result changed after {len(reports)} report(s) in frame {trigger.get('frame_id') or 'n/a'}. "
            f"Reports touched previous-route roads: {', '.join(affected)}."
        )
    else:
        message = (
            f"The result changed after {len(reports)} report(s) in frame {trigger.get('frame_id') or 'n/a'}, "
            "but those reports did not identify roads on the previous route as affected."
        )
    return message, current["edge_ids"]


def needs_check_answer(connection: sqlite3.Connection, area: sqlite3.Row) -> tuple[str, list[str]]:
    edges = effective_edges(connection, area)
    needs_check = [edge for edge in edges if edge["effective_status"] in {"suspected", "conflict", "unknown"}]
    if not needs_check:
        return "No roads currently have suspected, conflicting, or unknown status in this simulation.", []
    parts = []
    displayed = needs_check[:25]
    for edge in displayed:
        evidence = ", ".join(edge["evidence_report_ids"]) or "no current evidence"
        parts.append(f"{edge['id']} ({edge['effective_status']}; evidence: {evidence})")
    remainder = len(needs_check) - len(displayed)
    suffix = f"; and {remainder} additional roads." if remainder else "."
    message = "Roads needing checking in this simulation: " + "; ".join(parts) + suffix
    return message, [edge["id"] for edge in displayed]


def question_locations(connection: sqlite3.Connection, area_id: str) -> dict[str, str]:
    locations: dict[str, str] = {}
    ambiguous: set[str] = set()
    for node in all_nodes(connection, area_id):
        for name in (node["name"], node["id"]):
            if name in locations and locations[name] != node["id"]:
                ambiguous.add(name)
            else:
                locations[name] = node["id"]
    for name in ambiguous:
        locations.pop(name, None)
    return locations


@app.post("/api/areas/{area_id}/questions")
def ask_question(area_id: str, body: QuestionRequest) -> dict[str, Any]:
    with connect() as connection:
        with transaction(connection):
            area = require_area(connection, area_id)
            check_version(area, body.expected_version)
            parsed = parse_question(body.question, question_locations(connection, area_id))
            intent = parsed["intent"]
            if intent == "route":
                start_node_id = parsed["start_node_id"]
                end_node_id = parsed["end_node_id"]
                if start_node_id is None or end_node_id is None:
                    raise ValueError("A route question must identify both nodes.")
                route, change = compute_and_store_route(
                    connection, area, start_node_id, end_node_id, "user_request", None
                )
                version = save_calculation(connection, area, route, change)
                answer, related = route_answer(route)
            elif intent == "why_changed":
                version = area["version"]
                answer, related = why_changed_answer(connection, area)
            elif intent == "needs_check":
                version = area["version"]
                answer, related = needs_check_answer(connection, area)
            else:
                version = area["version"]
                answer = "I can answer: 'How can I get from Base S to Incident T?', 'Why did the route change?', or 'Which roads need checking?'."
                related = []
            return {"version": version, "intent": intent, "answer": answer, "related_edge_ids": related}

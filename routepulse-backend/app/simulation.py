"""Validation and loading for Integration-owned seven-day observation frames."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ALLOWED_REPORT_STATUSES = {"reported_open", "reported_blocked", "reported_suspected"}


def load_day_templates(path: str | Path, graph_version: str, edge_ids: set[str]) -> list[dict[str, Any]]:
    template_path = Path(path)
    if not template_path.is_file():
        raise FileNotFoundError(f"Seven-day templates are not configured: {template_path}")
    try:
        payload = json.loads(template_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read day templates: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Day template file must contain a JSON object.")
    if payload.get("graph_version") != graph_version:
        raise ValueError("Day template graph_version does not match the imported OSM graph.")
    days = payload.get("days")
    if not isinstance(days, list) or len(days) != 7:
        raise ValueError("Day templates must contain exactly seven days.")

    validated: list[dict[str, Any]] = []
    previous_time: datetime | None = None
    previous_date: date | None = None
    seen_frames: set[str] = set()
    for expected_index, frame in enumerate(days, start=1):
        if not isinstance(frame, dict) or frame.get("day_index") != expected_index:
            raise ValueError(f"Expected day_index {expected_index} in day templates.")
        if frame.get("graph_version") not in (None, graph_version):
            raise ValueError(f"Day {expected_index} has a mismatched graph_version.")
        if frame.get("observations_are_simulated") is not True:
            raise ValueError(f"Day {expected_index} must explicitly mark observations as simulated.")
        frame_id = frame.get("frame_id")
        source_id = frame.get("observation_source_id")
        if not isinstance(frame_id, str) or not frame_id.strip() or frame_id in seen_frames:
            raise ValueError(f"Day {expected_index} needs a unique non-empty frame_id.")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError(f"Day {expected_index} needs observation_source_id.")
        source_name = frame.get("observation_source_name")
        if source_name is not None and (not isinstance(source_name, str) or not source_name.strip()):
            raise ValueError(f"Day {expected_index} has an invalid observation_source_name.")
        seen_frames.add(frame_id)
        try:
            scenario_date = date.fromisoformat(frame["scenario_date_local"])
            scenario_time = datetime.fromisoformat(str(frame["scenario_time"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Day {expected_index} has an invalid date or scenario_time.") from exc
        if scenario_time.tzinfo is None or scenario_time.utcoffset() is None:
            raise ValueError(f"Day {expected_index} scenario_time must include a timezone.")
        scenario_time = scenario_time.astimezone(timezone.utc)
        if previous_date is not None and (scenario_date - previous_date).days != 1:
            raise ValueError("scenario_date_local must advance by exactly one day per frame.")
        if previous_time is not None and scenario_time <= previous_time:
            raise ValueError("Day scenario_time values must be strictly increasing.")
        previous_time = scenario_time
        previous_date = scenario_date

        observations = frame.get("road_observations")
        if not isinstance(observations, list):
            raise ValueError(f"Day {expected_index} road_observations must be a list.")
        seen_edges: set[str] = set()
        for observation in observations:
            if not isinstance(observation, dict):
                raise ValueError(f"Day {expected_index} contains an invalid road observation.")
            edge_id = observation.get("edge_id")
            if not isinstance(edge_id, str) or edge_id not in edge_ids:
                raise ValueError(f"Day {expected_index} references unknown edge {edge_id!r}.")
            if edge_id in seen_edges:
                raise ValueError(f"Day {expected_index} repeats edge {edge_id!r}.")
            if observation.get("status") not in ALLOWED_REPORT_STATUSES:
                raise ValueError(f"Day {expected_index} has an invalid report status.")
            note = observation.get("note", "")
            if not isinstance(note, str):
                raise ValueError(f"Day {expected_index} has a non-text observation note.")
            seen_edges.add(edge_id)

        copied = dict(frame)
        copied["scenario_time"] = scenario_time.isoformat().replace("+00:00", "Z")
        validated.append(copied)
    return validated

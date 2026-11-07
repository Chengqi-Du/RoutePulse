"""Prepare an explicitly fictional seven-day scenario on a real OSM graph."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, TypedDict

from .osm_graph import Graph, GraphEdge, GraphNode, distance_m
from .routing import Edge, RoadStatus, RouteResult, find_route


class Observation(TypedDict):
    edge_id: str
    status: Literal["reported_open", "reported_blocked", "reported_suspected"]
    note: str


class Day(TypedDict):
    graph_version: str
    day_index: int
    scenario_date_local: str
    scenario_time: str
    frame_id: str
    image: None
    observations_are_simulated: Literal[True]
    observation_source_type: Literal["external_demo"]
    observation_source_id: str
    road_observations: list[Observation]
    summary: dict[str, int | float]


_PROFILE = "severe_damage_v2"
_MIN_OPEN_FRACTION = 0.20
_MAX_OPEN_FRACTION = 0.30
_MIN_DAILY_CHANGE_FRACTION = 0.02


@dataclass(frozen=True)
class _Segment:
    key: str
    way_id: str
    index: int
    edges: tuple[GraphEdge, ...]
    route_membership: tuple[bool, bool]


@dataclass(frozen=True)
class _Group:
    key: str
    segments: tuple[_Segment, ...]


def _physical_segments(graph: Graph) -> dict[str, list[GraphEdge]]:
    segments: dict[str, list[GraphEdge]] = {}
    for edge in graph["edges"]:
        prefix, separator, direction = edge["id"].rpartition(":")
        if not separator or direction not in ("f", "r"):
            raise ValueError(f"edge {edge['id']!r} is not a supported OSM segment ID")
        if edge["direction"] != ("forward" if direction == "f" else "reverse"):
            raise ValueError(f"edge {edge['id']!r} has an inconsistent direction")
        segments.setdefault(prefix, []).append(edge)
    for key, edges in segments.items():
        if len(edges) > 2 or len({edge["direction"] for edge in edges}) != len(edges):
            raise ValueError(f"physical segment {key!r} has duplicate directions")
        if len(edges) == 2:
            a, b = edges
            if (
                a["from_node_id"] != b["to_node_id"]
                or a["to_node_id"] != b["from_node_id"]
                or a["length_m"] != b["length_m"]
                or a["geometry"]["coordinates"] != list(reversed(b["geometry"]["coordinates"]))
            ):
                raise ValueError(f"physical segment {key!r} has inconsistent reverse edges")
    return segments


def _road_groups(
    graph: Graph, initial: RouteResult, alternate: RouteResult
) -> tuple[list[_Group], dict[str, str]]:
    primary_keys = {edge_id.rpartition(":")[0] for edge_id in initial["edge_ids"]}
    alternate_keys = {edge_id.rpartition(":")[0] for edge_id in alternate["edge_ids"]}
    by_way: dict[str, list[_Segment]] = {}
    for key, edges in _physical_segments(graph).items():
        way_id = edges[0]["osm_way_id"]
        expected_prefix = f"{graph['graph_version']}:w{way_id}:s"
        if not key.startswith(expected_prefix):
            raise ValueError(f"segment {key!r} does not match its graph version or OSM way")
        try:
            index = int(key[len(expected_prefix):])
        except ValueError as exc:
            raise ValueError(f"segment {key!r} has an invalid index") from exc
        if index < 0:
            raise ValueError(f"segment {key!r} has a negative index")
        by_way.setdefault(way_id, []).append(_Segment(
            key, way_id, index, tuple(edges), (key in primary_keys, key in alternate_keys)
        ))

    groups: list[_Group] = []
    edge_to_group: dict[str, str] = {}
    for way_id, segments in sorted(by_way.items()):
        batch: list[_Segment] = []

        def finish_batch() -> None:
            if not batch:
                return
            key = f"{way_id}:{batch[0].index}-{batch[-1].index}"
            group = _Group(key, tuple(batch))
            groups.append(group)
            for segment in batch:
                for edge in segment.edges:
                    edge_to_group[edge["id"]] = key
            batch.clear()

        for segment in sorted(segments, key=lambda item: item.index):
            if batch and (
                len(batch) >= 6
                or segment.index != batch[-1].index + 1
                or segment.route_membership != batch[-1].route_membership
            ):
                finish_batch()
            batch.append(segment)
        finish_batch()
    return groups, edge_to_group


def _choose_daily_groups(
    graph_version: str,
    day_index: int,
    groups: list[_Group],
    required: set[str],
    forbidden: set[str],
    previous: set[str] | None,
) -> set[str]:
    if required & forbidden:
        raise ValueError(f"day {day_index} has conflicting required and blocked road groups")
    by_id = {group.key: group for group in groups}
    segment_counts = {group.key: len(group.segments) for group in groups}
    edge_counts = {
        group.key: sum(len(segment.edges) for segment in group.segments) for group in groups
    }
    lengths = {
        group.key: math.fsum(segment.edges[0]["length_m"] for segment in group.segments)
        for group in groups
    }
    total_segments = sum(segment_counts.values())
    total_edges = sum(edge_counts.values())
    total_length = math.fsum(lengths.values())
    if total_segments == 0 or total_length <= 0:
        raise ValueError("the graph needs physical segments with positive total length")
    if not required <= by_id.keys() or not forbidden <= by_id.keys():
        raise ValueError("required or blocked road group is missing from graph")
    min_changed = max(1, math.ceil(total_segments * _MIN_DAILY_CHANGE_FRACTION))
    for attempt in range(500):
        rng = random.Random(f"{_PROFILE}:{graph_version}:{day_index}:{attempt}")
        candidates = sorted(by_id.keys() - required - forbidden)
        rng.shuffle(candidates)
        opened = set(required)
        count = sum(segment_counts[key] for key in opened)
        for key in candidates:
            if count >= total_segments * 0.25:
                break
            if count + segment_counts[key] <= total_segments * _MAX_OPEN_FRACTION:
                opened.add(key)
                count += segment_counts[key]
        open_edge_count = sum(edge_counts[key] for key in opened)
        open_length = math.fsum(lengths[key] for key in opened)
        if not all(
            _MIN_OPEN_FRACTION <= fraction <= _MAX_OPEN_FRACTION
            for fraction in (count / total_segments, open_edge_count / total_edges, open_length / total_length)
        ):
            continue
        if previous is not None:
            reopened = sum(segment_counts[key] for key in opened - previous)
            newly_blocked = sum(segment_counts[key] for key in previous - opened)
            if reopened < min_changed or newly_blocked < min_changed:
                continue
        return opened
    raise ValueError(
        f"cannot generate day {day_index} with 20–30% open by segments, directed edges and length, "
        "both daily change directions, and the required demo routes"
    )


def _summarize(
    segments: dict[str, list[GraphEdge]], opened: set[str], previous: set[str] | None
) -> dict[str, int | float]:
    total_length = math.fsum(edges[0]["length_m"] for edges in segments.values())
    open_length = math.fsum(segments[key][0]["length_m"] for key in opened)
    directed_total = sum(len(edges) for edges in segments.values())
    directed_open = sum(len(segments[key]) for key in opened)
    return {
        "physical_segments_total": len(segments),
        "physical_segments_open": len(opened),
        "physical_segments_blocked": len(segments) - len(opened),
        "physical_open_percent": round(100 * len(opened) / len(segments), 2),
        "physical_total_length_m": round(total_length, 3),
        "physical_open_length_m": round(open_length, 3),
        "physical_open_length_percent": round(100 * open_length / total_length, 2),
        "directed_edges_total": directed_total,
        "directed_edges_open": directed_open,
        "directed_edges_blocked": directed_total - directed_open,
        "newly_opened_segments": len(opened - previous) if previous is not None else 0,
        "newly_blocked_segments": len(previous - opened) if previous is not None else 0,
    }


def _validate_severe_profile(graph: Graph, days: list[object]) -> None:
    segments = _physical_segments(graph)
    if not segments:
        raise ValueError("severe simulation needs physical road segments")
    total_length = math.fsum(edges[0]["length_m"] for edges in segments.values())
    if total_length <= 0:
        raise ValueError("severe simulation needs positive total road length")
    total_edges = len(graph["edges"])
    minimum_change = max(1, math.ceil(len(segments) * _MIN_DAILY_CHANGE_FRACTION))
    previous: set[str] | None = None
    for index, day in enumerate(days, start=1):
        if not isinstance(day, dict) or not isinstance(day.get("road_observations"), list):
            raise ValueError(f"day {index} has invalid observations")
        status_by_edge = {obs["edge_id"]: obs["status"] for obs in day["road_observations"]}
        opened: set[str] = set()
        for key, edges in segments.items():
            values = {status_by_edge[edge["id"]] for edge in edges}
            if len(values) != 1 or not values <= {"reported_open", "reported_blocked"}:
                raise ValueError(f"day {index} has inconsistent physical segment status")
            if "reported_open" in values:
                opened.add(key)
        open_length = math.fsum(segments[key][0]["length_m"] for key in opened)
        directed_open = sum(len(segments[key]) for key in opened)
        fractions = (len(opened) / len(segments), open_length / total_length, directed_open / total_edges)
        if not all(_MIN_OPEN_FRACTION <= fraction <= _MAX_OPEN_FRACTION for fraction in fractions):
            raise ValueError(f"day {index} does not have 20–30% open segments, edges and road length")
        if previous is not None and (
            len(opened - previous) < minimum_change or len(previous - opened) < minimum_change
        ):
            raise ValueError(f"day {index} has insufficient reopened or newly blocked road segments")
        if day.get("summary") != _summarize(segments, opened, previous):
            raise ValueError(f"day {index} summary does not match its road observations")
        previous = opened


def validate_seven_day_scenario(graph: Graph, scenario: object) -> None:
    """Reject mismatched, incomplete or malformed daily simulation data."""
    if not isinstance(scenario, dict):
        raise ValueError("scenario must be an object")
    if not graph["graph_version"] or scenario.get("graph_version") != graph["graph_version"]:
        raise ValueError("scenario graph_version does not match the graph")
    if scenario.get("simulation_only") is not True:
        raise ValueError("scenario must be marked simulation_only")
    edge_ids = {edge["id"] for edge in graph["edges"]}
    if not edge_ids or len(edge_ids) != len(graph["edges"]):
        raise ValueError("graph must contain unique edge IDs")
    days = scenario.get("days")
    if not isinstance(days, list) or len(days) != 7:
        raise ValueError("scenario must contain exactly seven days")
    previous_time: datetime | None = None
    source_id: str | None = None
    frames: set[str] = set()
    for index, day in enumerate(days, start=1):
        if not isinstance(day, dict):
            raise ValueError(f"day {index} must be an object")
        day_index = day.get("day_index")
        if day.get("graph_version") != graph["graph_version"] or type(day_index) is not int or day_index != index:
            raise ValueError(f"day {index} has an invalid graph version or day index")
        if day.get("observations_are_simulated") is not True:
            raise ValueError(f"day {index} must be marked simulated")
        day_source = day.get("observation_source_id")
        if (
            day.get("observation_source_type") != "external_demo"
            or not isinstance(day_source, str)
            or not day_source.strip()
            or (source_id is not None and day_source != source_id)
        ):
            raise ValueError(f"day {index} has an invalid observation source")
        source_id = day_source
        frame_id = day.get("frame_id")
        if not isinstance(frame_id, str) or not frame_id.strip() or frame_id in frames:
            raise ValueError(f"day {index} has an invalid or duplicate frame ID")
        frames.add(frame_id)
        timestamp = day.get("scenario_time")
        if not isinstance(timestamp, str):
            raise ValueError(f"day {index} has no scenario time")
        try:
            parsed_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"day {index} has an invalid scenario time") from exc
        if parsed_time.tzinfo is None or parsed_time.utcoffset() != timedelta(0):
            raise ValueError(f"day {index} scenario time must be UTC")
        if previous_time is not None and parsed_time - previous_time != timedelta(days=1):
            raise ValueError(f"day {index} must be one day after the previous day")
        if day.get("scenario_date_local") != (parsed_time + timedelta(hours=9)).date().isoformat():
            raise ValueError(f"day {index} has an invalid JST date")
        previous_time = parsed_time
        observations = day.get("road_observations")
        if not isinstance(observations, list):
            raise ValueError(f"day {index} has no road observations")
        seen: set[str] = set()
        for observation in observations:
            if not isinstance(observation, dict):
                raise ValueError(f"day {index} contains an invalid observation")
            edge_id = observation.get("edge_id")
            if not isinstance(edge_id, str) or edge_id not in edge_ids or edge_id in seen:
                raise ValueError(f"day {index} contains an unknown or duplicate edge ID")
            if observation.get("status") not in ("reported_open", "reported_blocked", "reported_suspected"):
                raise ValueError(f"day {index} contains an invalid observation status")
            if not isinstance(observation.get("note"), str):
                raise ValueError(f"day {index} contains an invalid observation note")
            seen.add(edge_id)
        if seen != edge_ids:
            raise ValueError(f"day {index} does not cover every graph edge")
    profile = scenario.get("scenario_profile")
    if profile == _PROFILE:
        if scenario.get("scenario_version") != f"{_PROFILE}-{graph['graph_version']}":
            raise ValueError("scenario_version does not match the profile and graph")
        _validate_severe_profile(graph, days)
    elif profile == "accessible_demo_v3":
        from .demo_scenario import PROFILE, validate_demo_profile

        if scenario.get("scenario_version") != f"{PROFILE}-{graph['graph_version']}":
            raise ValueError("scenario_version does not match the profile and graph")
        validate_demo_profile(graph, days)
    elif profile is not None:
        raise ValueError(f"unsupported scenario profile: {profile!r}")


def _snapshot_edges(
    edges: list[GraphEdge], overrides: dict[str, RoadStatus]
) -> list[Edge]:
    return [
        {
            "id": edge["id"],
            "from_node_id": edge["from_node_id"],
            "to_node_id": edge["to_node_id"],
            "length_m": edge["length_m"],
            "effective_status": overrides.get(edge["id"], "open"),
        }
        for edge in edges
    ]


def _route(
    graph: Graph, start: str, end: str, overrides: dict[str, RoadStatus] | None = None
) -> RouteResult:
    return find_route(graph["nodes"], _snapshot_edges(graph["edges"], overrides or {}), start, end)


def _find_alternative(
    graph: Graph, start: str, end: str
) -> tuple[RouteResult, str, RouteResult] | None:
    initial = _route(graph, start, end)
    if initial["status"] != "found":
        return None
    for edge_id in initial["edge_ids"]:
        physical_key = edge_id.rpartition(":")[0]
        overrides: dict[str, RoadStatus] = {
            edge["id"]: "blocked"
            for edge in graph["edges"]
            if edge["id"].rpartition(":")[0] == physical_key
        }
        alternate = _route(graph, start, end, overrides)
        if alternate["status"] == "found" and set(alternate["edge_ids"]) - set(initial["edge_ids"]):
            return initial, edge_id, alternate
    return None


def _auto_pair(graph: Graph) -> tuple[GraphNode, GraphNode, RouteResult, str, RouteResult]:
    nodes = graph["nodes"]
    longitudes = [node["coordinates"][0] for node in nodes]
    latitudes = [node["coordinates"][1] for node in nodes]
    center = [(min(longitudes) + max(longitudes)) / 2, (min(latitudes) + max(latitudes)) / 2]
    starts = sorted(nodes, key=lambda node: (distance_m(node["coordinates"], center), node["id"]))[:12]
    for start in starts:
        candidates = [
            node for node in nodes
            if 350 <= distance_m(start["coordinates"], node["coordinates"]) <= 900
        ]
        candidates.sort(key=lambda node: (abs(distance_m(start["coordinates"], node["coordinates"]) - 600), node["id"]))
        for end in candidates[:60]:
            result = _find_alternative(graph, start["id"], end["id"])
            if result is not None:
                initial, primary_id, alternate = result
                return start, end, initial, primary_id, alternate
    raise ValueError(
        "could not automatically find a demo pair with an alternative; "
        "specify existing --start-node and --end-node"
    )


def build_seven_day_scenario(
    graph: Graph, start_node_id: str | None = None, end_node_id: str | None = None
) -> tuple[dict[str, object], dict[str, object]]:
    """Create full daily observations and verify a suggested route demonstration."""
    if (start_node_id is None) != (end_node_id is None):
        raise ValueError("start-node and end-node must be supplied together")
    node_by_id = {node["id"]: node for node in graph["nodes"]}
    if len(node_by_id) != len(graph["nodes"]):
        raise ValueError("duplicate graph node IDs")
    edge_by_id = {edge["id"]: edge for edge in graph["edges"]}
    if len(edge_by_id) != len(graph["edges"]):
        raise ValueError("duplicate graph edge IDs")
    if start_node_id is None:
        start, end, initial, primary_id, alternate = _auto_pair(graph)
        selection_method = "automatic_provisional"
    else:
        if end_node_id is None or start_node_id not in node_by_id or end_node_id not in node_by_id:
            raise ValueError("start-node and end-node must exist in the graph")
        if start_node_id == end_node_id:
            raise ValueError("start-node and end-node must differ")
        start, end = node_by_id[start_node_id], node_by_id[end_node_id]
        result = _find_alternative(graph, start_node_id, end_node_id)
        if result is None:
            raise ValueError("selected nodes do not have a route with an alternative after one edge is blocked")
        initial, primary_id, alternate = result
        selection_method = "user_selected"

    start_id, end_id = start["id"], end["id"]
    alternate_id = next(edge_id for edge_id in alternate["edge_ids"] if edge_id not in initial["edge_ids"])
    cut_ids = sorted(edge["id"] for edge in graph["edges"] if edge["to_node_id"] == end_id)
    if not cut_ids:
        raise ValueError("end node has no incoming edges")
    segments = _physical_segments(graph)
    groups, edge_to_group = _road_groups(graph, initial, alternate)
    primary_groups = {edge_to_group[edge_id] for edge_id in initial["edge_ids"]}
    alternate_groups = {edge_to_group[edge_id] for edge_id in alternate["edge_ids"]}
    primary_block_group = edge_to_group[primary_id]
    cut_groups = {edge_to_group[edge_id] for edge_id in cut_ids}
    if primary_block_group in alternate_groups:
        raise ValueError("the primary closure would also block the verified alternate path")

    daily_groups: list[set[str]] = []
    for day_index in range(1, 8):
        forbidden: set[str] = set()
        if day_index <= 5:
            required = primary_groups | alternate_groups
        elif day_index == 6:
            required = alternate_groups
            forbidden = {primary_block_group}
        else:
            forbidden = cut_groups
            required = alternate_groups - forbidden
        daily_groups.append(_choose_daily_groups(
            graph["graph_version"], day_index, groups, required, forbidden,
            daily_groups[-1] if daily_groups else None,
        ))

    first_day = datetime(2024, 1, 2, 1, 0, tzinfo=timezone.utc)
    days: list[Day] = []
    daily_snapshots: list[dict[str, RoadStatus]] = []
    previous_open_segments: set[str] | None = None
    for index, open_groups in enumerate(daily_groups, start=1):
        time = first_day + timedelta(days=index - 1)
        observations: list[Observation] = []
        snapshot: dict[str, RoadStatus] = {}
        open_segments = {
            segment.key for group in groups if group.key in open_groups for segment in group.segments
        }
        for edge in graph["edges"]:
            is_open = edge_to_group[edge["id"]] in open_groups
            status: Literal["reported_open", "reported_blocked"] = (
                "reported_open" if is_open else "reported_blocked"
            )
            snapshot[edge["id"]] = "open" if is_open else "blocked"
            observations.append({
                "edge_id": edge["id"],
                "status": status,
                "note": f"Scripted simulation: {status.removeprefix('reported_')}; not a real observation.",
            })
        daily_snapshots.append(snapshot)
        days.append({
            "graph_version": graph["graph_version"],
            "day_index": index,
            "scenario_date_local": (time + timedelta(hours=9)).date().isoformat(),
            "scenario_time": time.isoformat().replace("+00:00", "Z"),
            "frame_id": f"day-{index:02d}",
            "image": None,
            "observations_are_simulated": True,
            "observation_source_type": "external_demo",
            "observation_source_id": "scripted-daily-feed",
            "road_observations": observations,
            "summary": _summarize(segments, open_segments, previous_open_segments),
        })
        previous_open_segments = open_segments

    daily_routes = [_route(graph, start_id, end_id, snapshot) for snapshot in daily_snapshots]
    manual_routes = [
        _route(graph, start_id, end_id, {**daily_snapshots[index], primary_id: "conflict"})
        for index in range(3)
    ]
    if any(route["status"] != "found" for route in daily_routes[:6] + manual_routes):
        raise ValueError("generated scenario failed route verification for days 1–6")
    if daily_routes[6]["status"] != "no_path":
        raise ValueError("generated scenario failed route verification")

    scenario: dict[str, object] = {
        "graph_version": graph["graph_version"],
        "scenario_profile": _PROFILE,
        "scenario_version": f"{_PROFILE}-{graph['graph_version']}",
        "simulation_only": True,
        "description": "Scripted observations; not historical disaster reports or satellite analysis.",
        "days": days,
    }
    validate_seven_day_scenario(graph, scenario)
    demo: dict[str, object] = {
        "graph_version": graph["graph_version"],
        "selection_method": selection_method,
        "selection_warning": "Provisional simulated locations, not verified real rescue facilities.",
        "start_node_id": start_id,
        "start_coordinates": start["coordinates"],
        "end_node_id": end_id,
        "end_coordinates": end["coordinates"],
        "primary_edge_id": primary_id,
        "alternate_edge_id": alternate_id,
        "day7_blocked_incoming_edge_ids": cut_ids,
        "daily_routes_without_manual_reports": daily_routes,
        "verified_snapshots": {
            "day1_open": daily_routes[0],
            "day1_manual_block_conflict": manual_routes[0],
            "day2_manual_block_and_daily_update": manual_routes[1],
            "day3_manual_block_and_daily_open_conflict": manual_routes[2],
            "day4_manual_source_reopens": daily_routes[3],
            "day5_daily_update": daily_routes[4],
            "day6_primary_edge_blocked": daily_routes[5],
            "day7_destination_incoming_edges_blocked": daily_routes[6],
        },
        "verification_scope": (
            "Pure routing snapshots only; backend report merging, atomicity, time and HTTP remain untested."
        ),
    }
    return scenario, demo

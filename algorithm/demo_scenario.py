"""Generate a lighter fictional scenario while preserving OSM reachability."""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .osm_graph import Graph, build_graph
from .seven_day import _auto_pair, _physical_segments, _summarize


PROFILE = "accessible_demo_v3"


def _components(graph: Graph, allowed: set[str] | None = None) -> tuple[list[set[str]], dict[str, int]]:
    forward: dict[str, list[str]] = defaultdict(list)
    reverse: dict[str, list[str]] = defaultdict(list)
    for edge in graph["edges"]:
        if allowed is not None and edge["id"] not in allowed:
            continue
        forward[edge["from_node_id"]].append(edge["to_node_id"])
        reverse[edge["to_node_id"]].append(edge["from_node_id"])
    nodes = sorted(node["id"] for node in graph["nodes"])
    seen: set[str] = set()
    order: list[str] = []
    for node in nodes:
        if node in seen:
            continue
        seen.add(node)
        stack = [(node, iter(forward[node]))]
        while stack:
            current, neighbours = stack[-1]
            following = next(neighbours, None)
            if following is None:
                order.append(current)
                stack.pop()
            elif following not in seen:
                seen.add(following)
                stack.append((following, iter(forward[following])))
    groups: list[set[str]] = []
    membership: dict[str, int] = {}
    for node in reversed(order):
        if node in membership:
            continue
        group: set[str] = set()
        group_id = len(groups)
        membership[node] = group_id
        pending = [node]
        while pending:
            current = pending.pop()
            group.add(current)
            for following in reverse[current]:
                if following not in membership:
                    membership[following] = group_id
                    pending.append(following)
        groups.append(group)
    return groups, membership


def _protected_segments(graph: Graph) -> set[str]:
    groups, membership = _components(graph)
    forward: dict[str, list[tuple[str, str]]] = defaultdict(list)
    reverse: dict[str, list[tuple[str, str]]] = defaultdict(list)
    protected: set[str] = set()
    for edge in graph["edges"]:
        start, end = edge["from_node_id"], edge["to_node_id"]
        key = edge["id"].rpartition(":")[0]
        forward[start].append((end, key))
        reverse[end].append((start, key))
        if membership[start] != membership[end]:
            protected.add(key)
    for group in groups:
        root = min(group)
        for adjacency in (forward, reverse):
            reached = {root}
            pending = deque([root])
            while pending:
                node = pending.popleft()
                for following, key in adjacency[node]:
                    if following in group and following not in reached:
                        reached.add(following)
                        pending.append(following)
                        protected.add(key)
            if reached != group:
                raise ValueError("could not construct a directed connectivity backbone")
    return protected


def build_demo_scenario(graph: Graph) -> dict[str, object]:
    segments = _physical_segments(graph)
    protected = _protected_segments(graph)
    _, _, initial, _, alternate = _auto_pair(graph)
    protected.update(edge_id.rpartition(":")[0] for edge_id in initial["edge_ids"] + alternate["edge_ids"])
    candidates = sorted(set(segments) - protected)
    random.Random(f"{PROFILE}:{graph['graph_version']}").shuffle(candidates)
    blocked_count = min(math.ceil(len(segments) * 0.05), len(candidates) // 2)
    minimum_change = max(1, math.ceil(len(segments) * 0.02))
    if blocked_count < minimum_change:
        raise ValueError("not enough redundant road segments for a changing connected demo scenario")

    start = datetime(2024, 1, 2, 1, 0, tzinfo=timezone.utc)
    days: list[dict[str, object]] = []
    previous: set[str] | None = None
    for index in range(1, 8):
        offset = (index - 1) * blocked_count
        blocked = {candidates[(offset + item) % len(candidates)] for item in range(blocked_count)}
        opened = set(segments) - blocked
        time = start + timedelta(days=index - 1)
        days.append({
            "graph_version": graph["graph_version"],
            "day_index": index,
            "scenario_date_local": (time + timedelta(hours=9)).date().isoformat(),
            "scenario_time": time.isoformat().replace("+00:00", "Z"),
            "frame_id": f"accessible-demo-day-{index:02d}",
            "image": None,
            "observations_are_simulated": True,
            "observation_source_type": "external_demo",
            "observation_source_id": "accessible-demo-daily-feed",
            "road_observations": [{
                "edge_id": edge["id"],
                "status": "reported_blocked" if edge["id"].rpartition(":")[0] in blocked else "reported_open",
                "note": "Fictional demo road status; not a real observation.",
            } for edge in graph["edges"]],
            "summary": _summarize(segments, opened, previous),
        })
        previous = opened
    scenario: dict[str, object] = {
        "graph_version": graph["graph_version"],
        "scenario_profile": PROFILE,
        "scenario_version": f"{PROFILE}-{graph['graph_version']}",
        "simulation_only": True,
        "description": "Lighter fictional road closures, preserving the original graph's directed reachability.",
        "days": days,
    }
    validate_demo_profile(graph, days)
    return scenario


def validate_demo_profile(graph: Graph, days: list[object]) -> None:
    segments = _physical_segments(graph)
    if not segments:
        raise ValueError("demo scenario needs physical road segments")
    original_components, membership = _components(graph)
    expected_components = {frozenset(group) for group in original_components}
    minimum_change = max(1, math.ceil(len(segments) * 0.02))
    previous: set[str] | None = None
    for index, day in enumerate(days, start=1):
        if not isinstance(day, dict) or not isinstance(day.get("road_observations"), list):
            raise ValueError(f"day {index} has invalid observations")
        status_by_edge = {obs["edge_id"]: obs["status"] for obs in day["road_observations"]}
        opened: set[str] = set()
        for key, edges in segments.items():
            statuses = {status_by_edge[edge["id"]] for edge in edges}
            if len(statuses) != 1 or not statuses <= {"reported_open", "reported_blocked"}:
                raise ValueError(f"day {index} has inconsistent physical segment status")
            if "reported_open" in statuses:
                opened.add(key)
        blocked_count = len(segments) - len(opened)
        if not 0 < blocked_count <= len(segments) * 0.10:
            raise ValueError(f"day {index} must block more than 0% and at most 10% of physical segments")
        if previous is not None and (
            len(opened - previous) < minimum_change or len(previous - opened) < minimum_change
        ):
            raise ValueError(f"day {index} has insufficient road status changes")
        if day.get("summary") != _summarize(segments, opened, previous):
            raise ValueError(f"day {index} summary does not match its road observations")
        allowed = {edge["id"] for edge in graph["edges"] if edge["id"].rpartition(":")[0] in opened}
        actual_components, _ = _components(graph, allowed)
        if {frozenset(group) for group in actual_components} != expected_components:
            raise ValueError(f"day {index} disconnects an originally strongly connected component")
        if any(edge["id"] not in allowed and membership[edge["from_node_id"]] != membership[edge["to_node_id"]]
               for edge in graph["edges"]):
            raise ValueError(f"day {index} removes an original link between components")
        previous = opened


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("osm_file", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New file; existing files are not overwritten")
    args = parser.parse_args()
    graph, _, _ = build_graph(args.osm_file)
    scenario = build_demo_scenario(graph)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(scenario, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write("\n")
    print(f"Generated {PROFILE} for {graph['graph_version']} at {args.output}")


if __name__ == "__main__":
    main()

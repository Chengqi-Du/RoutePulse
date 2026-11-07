"""Shortest candidate routes over an already-evaluated simulation snapshot."""

from __future__ import annotations

import heapq
import math
from collections.abc import Sequence
from itertools import count
from typing import Literal, TypedDict


RoadStatus = Literal["open", "blocked", "suspected", "conflict", "unknown"]


class Node(TypedDict):
    id: str


class Edge(TypedDict):
    id: str
    from_node_id: str
    to_node_id: str
    length_m: int | float
    effective_status: RoadStatus


class RouteResult(TypedDict):
    status: Literal["found", "no_path"]
    node_ids: list[str]
    edge_ids: list[str]
    distance_m: int | float | None


_STATUSES = frozenset({"open", "blocked", "suspected", "conflict", "unknown"})


def _require_id(value: object, description: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{description} must be a non-empty string")
    return value


def _validate_length(value: object, edge_id: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"edge {edge_id!r} length_m must be a number")
    if value < 0 or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError(f"edge {edge_id!r} length_m must be finite and non-negative")
    return value


def find_route(
    nodes: Sequence[Node],
    edges: Sequence[Edge],
    start_node_id: str,
    end_node_id: str,
) -> RouteResult:
    """Find a shortest route using only open directed edges, with A* h=0.

    The caller provides one evaluated snapshot. Invalid graph data raises
    ValueError; a valid graph with no eligible path returns ``no_path``.
    """
    start = _require_id(start_node_id, "start_node_id")
    end = _require_id(end_node_id, "end_node_id")

    node_ids: set[str] = set()
    for node in nodes:
        node_id = _require_id(node.get("id"), "node id")
        if node_id in node_ids:
            raise ValueError(f"duplicate node id: {node_id!r}")
        node_ids.add(node_id)
    if start not in node_ids or end not in node_ids:
        raise ValueError("start_node_id and end_node_id must exist in nodes")

    adjacency: dict[str, list[tuple[str, str, int | float]]] = {
        node_id: [] for node_id in node_ids
    }
    edge_ids: set[str] = set()
    for edge in edges:
        edge_id = _require_id(edge.get("id"), "edge id")
        if edge_id in edge_ids:
            raise ValueError(f"duplicate edge id: {edge_id!r}")
        edge_ids.add(edge_id)
        source = _require_id(edge.get("from_node_id"), f"edge {edge_id!r} from_node_id")
        target = _require_id(edge.get("to_node_id"), f"edge {edge_id!r} to_node_id")
        if source not in node_ids or target not in node_ids:
            raise ValueError(f"edge {edge_id!r} refers to an unknown node")
        length = _validate_length(edge.get("length_m"), edge_id)
        status = edge.get("effective_status")
        if not isinstance(status, str) or status not in _STATUSES:
            raise ValueError(f"edge {edge_id!r} has an invalid effective_status")
        if status == "open":
            adjacency[source].append((edge_id, target, length))

    for outgoing in adjacency.values():
        outgoing.sort(key=lambda edge: edge[0])

    distances: dict[str, int | float] = {start: 0}
    previous: dict[str, tuple[str, str]] = {}
    serial = count()
    queue: list[tuple[int | float, int, str]] = [(0, next(serial), start)]

    while queue:
        distance, _, current = heapq.heappop(queue)
        if distance != distances[current]:
            continue
        if current == end:
            path_nodes = [end]
            path_edges: list[str] = []
            while current != start:
                parent, edge_id = previous[current]
                path_edges.append(edge_id)
                path_nodes.append(parent)
                current = parent
            return {
                "status": "found",
                "node_ids": list(reversed(path_nodes)),
                "edge_ids": list(reversed(path_edges)),
                "distance_m": distance,
            }

        for edge_id, target, length in adjacency[current]:
            try:
                candidate = distance + length
            except OverflowError as exc:
                raise ValueError("route distance exceeds numeric limits") from exc
            if isinstance(candidate, float) and not math.isfinite(candidate):
                raise ValueError("route distance exceeds numeric limits")
            if target not in distances or candidate < distances[target]:
                distances[target] = candidate
                previous[target] = (current, edge_id)
                heapq.heappush(queue, (candidate, next(serial), target))

    return {"status": "no_path", "node_ids": [], "edge_ids": [], "distance_m": None}

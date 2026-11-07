"""Directed shortest-path search over one immutable backend state snapshot."""

from __future__ import annotations

import heapq
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence


def _length(value: object, edge_id: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"Edge {edge_id!r} has an invalid length_m.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Edge {edge_id!r} has an invalid length_m.") from None
    if not result.is_finite() or result < 0:
        raise ValueError(f"Edge {edge_id!r} length_m must be finite and non-negative.")
    return result


def _json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def find_route(
    nodes: Sequence[Mapping[str, Any]],
    edges: Iterable[Mapping[str, Any]],
    start_node_id: str,
    end_node_id: str,
) -> dict[str, Any]:
    """Return the minimum-distance route using open, directed edges only.

    A* uses h=0 so edge weights can be arbitrary non-negative distances without
    deriving a heuristic from coordinates. Decimal arithmetic preserves
    fractional lengths when comparing alternative paths.
    """
    node_ids = {str(node["id"]) for node in nodes}
    if start_node_id not in node_ids:
        raise ValueError(f"Unknown start node: {start_node_id}")
    if end_node_id not in node_ids:
        raise ValueError(f"Unknown end node: {end_node_id}")
    if start_node_id == end_node_id:
        return {"status": "found", "node_ids": [start_node_id], "edge_ids": [], "distance_m": 0}

    adjacency: dict[str, list[tuple[str, str, Decimal]]] = {}
    for edge in edges:
        try:
            edge_id = str(edge["id"])
            from_node_id = str(edge["from_node_id"])
            to_node_id = str(edge["to_node_id"])
            cost = _length(edge["length_m"], edge_id)
        except KeyError as exc:
            raise ValueError(f"Edge is missing required field {exc.args[0]!r}.") from None
        if from_node_id not in node_ids or to_node_id not in node_ids:
            raise ValueError(f"Edge {edge_id!r} references an unknown node.")
        if edge.get("effective_status") == "open":
            adjacency.setdefault(from_node_id, []).append((to_node_id, edge_id, cost))

    for outgoing in adjacency.values():
        outgoing.sort(key=lambda item: item[1])

    queue: list[tuple[Decimal, int, str]] = [(Decimal(0), 0, start_node_id)]
    distance: dict[str, Decimal] = {start_node_id: Decimal(0)}
    previous: dict[str, tuple[str, str]] = {}
    sequence = 0

    while queue:
        cost, _, node_id = heapq.heappop(queue)
        if cost != distance.get(node_id):
            continue
        if node_id == end_node_id:
            node_ids_result = [end_node_id]
            edge_ids_result: list[str] = []
            cursor = end_node_id
            while cursor != start_node_id:
                parent, edge_id = previous[cursor]
                node_ids_result.append(parent)
                edge_ids_result.append(edge_id)
                cursor = parent
            node_ids_result.reverse()
            edge_ids_result.reverse()
            return {
                "status": "found",
                "node_ids": node_ids_result,
                "edge_ids": edge_ids_result,
                "distance_m": _json_number(cost),
            }

        for next_node, edge_id, edge_cost in adjacency.get(node_id, []):
            next_cost = cost + edge_cost
            if next_cost < distance.get(next_node, Decimal("Infinity")):
                distance[next_node] = next_cost
                previous[next_node] = (node_id, edge_id)
                sequence += 1
                heapq.heappush(queue, (next_cost, sequence, next_node))

    return {"status": "no_path", "node_ids": [], "edge_ids": [], "distance_m": None}

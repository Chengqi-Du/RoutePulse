"""Pure routing and intentionally limited question parsing for RoutePulse."""

from __future__ import annotations

import heapq
import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class RoutePath:
    status: str
    node_ids: list[str]
    edge_ids: list[str]
    distance_m: int | None


def a_star(
    start_node_id: str,
    end_node_id: str,
    edges: Iterable[Mapping[str, object]],
) -> RoutePath:
    """Find a minimum-length directed route over open edges (A* with h=0)."""
    if start_node_id == end_node_id:
        return RoutePath("found", [start_node_id], [], 0)

    adjacency: dict[str, list[tuple[str, str, int]]] = {}
    for edge in edges:
        if edge.get("effective_status") != "open":
            continue
        adjacency.setdefault(str(edge["from_node_id"]), []).append(
            (str(edge["to_node_id"]), str(edge["id"]), int(edge["length_m"]))
        )
    for outgoing in adjacency.values():
        outgoing.sort(key=lambda item: item[1])

    queue: list[tuple[int, int, str]] = [(0, 0, start_node_id)]
    sequence = 0
    distance: dict[str, int] = {start_node_id: 0}
    previous: dict[str, tuple[str, str]] = {}
    while queue:
        cost, _, node_id = heapq.heappop(queue)
        if cost != distance.get(node_id):
            continue
        if node_id == end_node_id:
            node_ids = [end_node_id]
            edge_ids: list[str] = []
            cursor = end_node_id
            while cursor != start_node_id:
                parent, edge_id = previous[cursor]
                node_ids.append(parent)
                edge_ids.append(edge_id)
                cursor = parent
            node_ids.reverse()
            edge_ids.reverse()
            return RoutePath("found", node_ids, edge_ids, cost)

        for next_node, edge_id, length_m in adjacency.get(node_id, []):
            next_cost = cost + length_m
            if next_cost < distance.get(next_node, 2**63 - 1):
                distance[next_node] = next_cost
                previous[next_node] = (node_id, edge_id)
                sequence += 1
                # h=0 is admissible and consistent, so the priority is Dijkstra's cost.
                heapq.heappush(queue, (next_cost, sequence, next_node))

    return RoutePath("no_path", [], [], None)


def _normalize(text: str) -> str:
    return " ".join(text.casefold().strip().rstrip(" .!?。？！").split())


def parse_question(question: str, nodes: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Parse only the three contract phrases; return unsupported otherwise."""
    normalized = _normalize(question)
    if normalized == "why did the route change":
        return {"intent": "why_changed"}
    if normalized == "which roads need checking":
        return {"intent": "needs_check"}

    match = re.fullmatch(r"how can i get from (.+?) to (.+)", normalized)
    if match:
        by_name = {" ".join(str(node["name"]).casefold().split()): str(node["id"]) for node in nodes}
        start = by_name.get(" ".join(match.group(1).split()))
        end = by_name.get(" ".join(match.group(2).split()))
        if start is not None and end is not None:
            return {"intent": "route", "start_node_id": start, "end_node_id": end}
    return {"intent": "unsupported"}

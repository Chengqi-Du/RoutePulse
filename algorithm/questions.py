"""Parse the explicitly supported questions without generating route facts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal, TypedDict


class QuestionResult(TypedDict):
    intent: Literal["route", "why_changed", "needs_check", "unsupported"]
    start_node_id: str | None
    end_node_id: str | None


_ROUTE_QUESTION = re.compile(r"how can i get from (.+?) to (.+)", re.IGNORECASE)


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def parse_question(question: str, locations: Mapping[str, str]) -> QuestionResult:
    """Parse supported English questions using a name-to-node-ID mapping.

    Empty questions and ambiguous or invalid mappings raise ValueError.
    Unsupported questions and unknown location names return ``unsupported``.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")

    normalized_locations: dict[str, str] = {}
    for name, node_id in locations.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("location names must be non-empty strings")
        if not isinstance(node_id, str) or not node_id.strip():
            raise ValueError(f"node ID for location {name!r} must be a non-empty string")
        normalized_name = _normalize(name)
        if normalized_name in normalized_locations and normalized_locations[normalized_name] != node_id:
            raise ValueError(f"location name {name!r} maps to multiple node IDs")
        normalized_locations[normalized_name] = node_id

    normalized_question = _normalize(question.strip().rstrip(" .!?。？！"))
    if normalized_question == "why did the route change":
        return {"intent": "why_changed", "start_node_id": None, "end_node_id": None}
    if normalized_question == "which roads need checking":
        return {"intent": "needs_check", "start_node_id": None, "end_node_id": None}

    match = _ROUTE_QUESTION.fullmatch(normalized_question)
    if match:
        start = normalized_locations.get(_normalize(match.group(1)))
        end = normalized_locations.get(_normalize(match.group(2)))
        if start is not None and end is not None:
            return {"intent": "route", "start_node_id": start, "end_node_id": end}
    return {"intent": "unsupported", "start_node_id": None, "end_node_id": None}

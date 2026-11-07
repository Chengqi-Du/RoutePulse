"""Deterministic parser for the small set of supported exercise questions."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence


def _normalize(text: str) -> str:
    return " ".join(text.casefold().strip().rstrip(" .!?。？！").split())


def parse_question(question: str, nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return an intent and optional node IDs; never infer live facts or answers."""
    result: dict[str, Any] = {"intent": "unsupported", "start_node_id": None, "end_node_id": None}
    normalized = _normalize(question)
    if normalized == "why did the route change":
        result["intent"] = "why_changed"
        return result
    if normalized == "which roads need checking":
        result["intent"] = "needs_check"
        return result

    match = re.fullmatch(r"how can i get from (.+?) to (.+)", normalized)
    if not match:
        return result
    names = {" ".join(str(node["name"]).casefold().split()): str(node["id"]) for node in nodes}
    start_node_id = names.get(" ".join(match.group(1).split()))
    end_node_id = names.get(" ".join(match.group(2).split()))
    if start_node_id is not None and end_node_id is not None:
        result.update({"intent": "route", "start_node_id": start_node_id, "end_node_id": end_node_id})
    return result

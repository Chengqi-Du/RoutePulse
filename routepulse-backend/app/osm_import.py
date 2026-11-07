"""Adapt the shared Integration OSM graph to the backend storage format."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from algorithm.osm_graph import build_graph


def load_osm_graph(path: str | Path) -> dict[str, Any]:
    source_path = Path(path)
    try:
        graph, report, _ = build_graph(source_path)
        root = ET.parse(source_path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"Invalid OSM XML: {exc}") from exc

    node_tags = {
        node.attrib["id"]: {tag.attrib["k"]: tag.attrib["v"] for tag in node.findall("tag")}
        for node in root.findall("node")
    }
    way_tags: dict[str, dict[str, str]] = {}
    node_way_count: Counter[str] = Counter()
    for way in root.findall("way"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        if "highway" in tags:
            way_tags[way.attrib["id"]] = tags
            node_way_count.update({node.attrib["ref"] for node in way.findall("nd")})

    nodes = []
    for node in graph["nodes"]:
        osm_node_id = node["id"].removeprefix("osm-node-")
        tags = node_tags[osm_node_id]
        nodes.append({
            "id": node["id"],
            "name": tags.get("name") or tags.get("name:ja") or node["name"],
            "type": "junction" if node_way_count[osm_node_id] > 1 else "road_node",
            "coordinates": node["coordinates"],
            "osm_node_id": osm_node_id,
            "tags": tags,
        })

    edges = [{
        "id": edge["id"],
        "from_node_id": edge["from_node_id"],
        "to_node_id": edge["to_node_id"],
        "length_m": edge["length_m"],
        "osm_way_id": edge["osm_way_id"],
        "highway": edge["highway"],
        "name": way_tags[edge["osm_way_id"]].get("name") or way_tags[edge["osm_way_id"]].get("name:ja"),
        "direction": "fwd" if edge["direction"] == "forward" else "rev",
        "geometry": edge["geometry"],
        "tags": way_tags[edge["osm_way_id"]],
    } for edge in graph["edges"]]

    bounds = graph["source"]["bounds"]
    counts = report["input_counts"]
    missing_members = report["missing_turn_restriction_members"]
    if not isinstance(counts, dict) or not isinstance(missing_members, list):
        raise ValueError("Invalid quality report from the shared OSM graph builder.")
    metadata = {
        "graph_version": graph["graph_version"],
        "source": {**graph["source"], "format": "osm-xml-0.6"},
        "bounds": {
            "min_lon": bounds["minlon"], "min_lat": bounds["minlat"],
            "max_lon": bounds["maxlon"], "max_lat": bounds["maxlat"],
        } if isinstance(bounds, dict) else None,
        "osm_counts": {
            "nodes": counts["node"],
            "ways": counts["way"],
            "relations": counts["relation"],
            "highway_ways": report["highway_way_count"],
            "highway_types": report["highway_way_counts"],
            "turn_restriction_relations": report["turn_restriction_relation_count"],
            "missing_highway_node_refs": 0,
            "missing_turn_restriction_members": len(missing_members),
        },
        "graph_counts": {"nodes": len(nodes), "directed_edges": len(edges)},
        "coverage_review_status": "not_verified_against_screenshot",
        "turn_restrictions_supported": False,
        "warnings": report["warnings"],
    }
    return {"graph_version": graph["graph_version"], "metadata": metadata, "nodes": nodes, "edges": edges}


def write_graph_package(osm_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    graph = load_osm_graph(osm_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(graph, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return graph

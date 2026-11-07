"""Build a deterministic, routable candidate graph from an OSM XML extract.

This is a geometry/connectivity importer only. OSM tags do not establish
earthquake-day road conditions, and the resulting edges start as unknown.
Screenshot coverage and turn restrictions require separate review.
"""

from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


IMPORTER_VERSION = "osm-graph-v1"
EARTH_RADIUS_M = 6_371_008.8


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlon, dlat = lon2 - lon1, lat2 - lat1
    haversine = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(haversine)))


def _tags(element: ET.Element) -> dict[str, str]:
    return {tag.attrib["k"]: tag.attrib["v"] for tag in element.findall("tag")}


def _directions(tags: dict[str, str]) -> tuple[list[str], str | None]:
    """Return allowed segment directions and any interpretation warning."""
    raw = tags.get("oneway", "").strip().casefold()
    highway = tags.get("highway", "").casefold()
    junction = tags.get("junction", "").casefold()
    if raw in {"yes", "true", "1"} or (not raw and (highway in {"motorway", "motorway_link"} or junction == "roundabout")):
        return ["fwd"], None
    if raw == "-1":
        return ["rev"], None
    if raw in {"", "no", "false", "0"}:
        return ["fwd", "rev"], None
    # Conditional/reversible direction rules need time- and vehicle-aware routing.
    # Keep both as simulation candidates and report the assumption in metadata.
    return ["fwd", "rev"], f"oneway={raw} treated as bidirectional candidate"


def load_osm_graph(path: str | Path) -> dict[str, Any]:
    """Parse highway ways into directed segment edges with stable IDs and geometry."""
    source_path = Path(path)
    if not source_path.is_file():
        raise FileNotFoundError(f"OSM input does not exist: {source_path}")
    raw_bytes = source_path.read_bytes()
    source_hash = hashlib.sha256(raw_bytes).hexdigest()
    graph_version = f"anamizu-{IMPORTER_VERSION}-{source_hash[:16]}"
    root = ET.fromstring(raw_bytes)
    if root.tag != "osm" or root.attrib.get("version") != "0.6":
        raise ValueError("Expected an OSM XML 0.6 document.")

    node_elements = root.findall("node")
    way_elements = root.findall("way")
    relation_elements = root.findall("relation")
    coords: dict[str, tuple[float, float]] = {}
    node_tags: dict[str, dict[str, str]] = {}
    object_times: list[str] = []
    for node in node_elements:
        node_id = node.attrib.get("id")
        if not node_id or node_id in coords:
            raise ValueError(f"Missing or duplicate OSM node id: {node_id!r}")
        lon, lat = float(node.attrib["lon"]), float(node.attrib["lat"])
        if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError(f"Invalid coordinates for OSM node {node_id}.")
        coords[node_id] = (lon, lat)
        node_tags[node_id] = _tags(node)
        if node.attrib.get("timestamp"):
            object_times.append(node.attrib["timestamp"])

    ways_by_id: dict[str, ET.Element] = {}
    highway_ways: list[tuple[ET.Element, dict[str, str], list[str]]] = []
    highway_types: Counter[str] = Counter()
    missing_node_refs: list[tuple[str, str]] = []
    for way in way_elements:
        way_id = way.attrib.get("id")
        if not way_id or way_id in ways_by_id:
            raise ValueError(f"Missing or duplicate OSM way id: {way_id!r}")
        ways_by_id[way_id] = way
        if way.attrib.get("timestamp"):
            object_times.append(way.attrib["timestamp"])
        tags = _tags(way)
        highway = tags.get("highway")
        if not highway:
            continue
        refs = [nd.attrib["ref"] for nd in way.findall("nd")]
        highway_types[highway] += 1
        missing_node_refs.extend((way_id, ref) for ref in refs if ref not in coords)
        highway_ways.append((way, tags, refs))

    if missing_node_refs:
        raise ValueError(f"OSM highway ways contain {len(missing_node_refs)} missing node references.")

    node_way_count: Counter[str] = Counter()
    for _, _, refs in highway_ways:
        node_way_count.update(set(refs))
    used_node_ids = {ref for _, _, refs in highway_ways for ref in refs}
    nodes = []
    for node_id in sorted(used_node_ids, key=lambda value: int(value)):
        tags = node_tags[node_id]
        name = tags.get("name") or tags.get("name:ja") or f"OSM node {node_id}"
        node_type = "junction" if node_way_count[node_id] > 1 else "road_node"
        nodes.append({
            "id": f"osm-node-{node_id}",
            "name": name,
            "type": node_type,
            "coordinates": [coords[node_id][0], coords[node_id][1]],
            "osm_node_id": node_id,
            "tags": tags,
        })

    edges: list[dict[str, Any]] = []
    direction_warnings: set[str] = set()
    for way, tags, refs in highway_ways:
        way_id = way.attrib["id"]
        directions, warning = _directions(tags)
        if warning:
            direction_warnings.add(warning)
        for segment_index, (left_ref, right_ref) in enumerate(zip(refs, refs[1:])):
            if left_ref == right_ref:
                continue
            segment_length = _distance_m(coords[left_ref], coords[right_ref])
            if not math.isfinite(segment_length) or segment_length < 0:
                raise ValueError(f"Invalid segment length in OSM way {way_id}.")
            for suffix in directions:
                if suffix == "fwd":
                    from_ref, to_ref = left_ref, right_ref
                elif suffix == "rev":
                    from_ref, to_ref = right_ref, left_ref
                else:
                    raise ValueError("Unknown direction suffix.")
                edges.append({
                    "id": f"{graph_version}:way/{way_id}/segment/{segment_index}/{suffix}",
                    "from_node_id": f"osm-node-{from_ref}",
                    "to_node_id": f"osm-node-{to_ref}",
                    "length_m": round(segment_length, 3),
                    "osm_way_id": way_id,
                    "highway": tags["highway"],
                    "name": tags.get("name") or tags.get("name:ja"),
                    "direction": suffix,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [list(coords[from_ref]), list(coords[to_ref])],
                    },
                    "tags": tags,
                })

    known_members = {("node", element.attrib["id"]) for element in node_elements}
    known_members |= {("way", way_id) for way_id in ways_by_id}
    restriction_relations = 0
    missing_relation_members = []
    for relation in relation_elements:
        if relation.attrib.get("timestamp"):
            object_times.append(relation.attrib["timestamp"])
        tags = _tags(relation)
        if tags.get("type") == "restriction" or any(key.startswith("restriction") for key in tags):
            restriction_relations += 1
            for member in relation.findall("member"):
                member_key = (member.attrib.get("type", ""), member.attrib.get("ref", ""))
                if member_key not in known_members:
                    missing_relation_members.append((relation.attrib.get("id", ""), member_key))

    bounds_element = root.find("bounds")
    bounds = None
    if bounds_element is not None:
        bounds = {
            "min_lon": float(bounds_element.attrib["minlon"]),
            "min_lat": float(bounds_element.attrib["minlat"]),
            "max_lon": float(bounds_element.attrib["maxlon"]),
            "max_lat": float(bounds_element.attrib["maxlat"]),
        }
    metadata = {
        "graph_version": graph_version,
        "source": {
            "format": "osm-xml-0.6",
            "source_file": source_path.name,
            "sha256": source_hash,
            "dataset_snapshot_at": None,
            "latest_object_edit_at": max(object_times) if object_times else None,
            "is_disaster_road_status": False,
            "attribution": root.attrib.get("attribution", "OpenStreetMap and contributors"),
            "license": root.attrib.get("license", "ODbL"),
        },
        "bounds": bounds,
        "osm_counts": {
            "nodes": len(node_elements),
            "ways": len(way_elements),
            "relations": len(relation_elements),
            "highway_ways": len(highway_ways),
            "highway_types": dict(sorted(highway_types.items())),
            "turn_restriction_relations": restriction_relations,
            "missing_highway_node_refs": 0,
            "missing_turn_restriction_members": len(missing_relation_members),
        },
        "graph_counts": {"nodes": len(nodes), "directed_edges": len(edges)},
        "coverage_review_status": "not_verified_against_screenshot",
        "turn_restrictions_supported": False,
        "warnings": sorted(direction_warnings) + ([
            f"{len(missing_relation_members)} turn-restriction relation members are missing from this extract."
        ] if missing_relation_members else []),
    }
    return {"graph_version": graph_version, "metadata": metadata, "nodes": nodes, "edges": edges}


def write_graph_package(osm_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    graph = load_osm_graph(osm_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(graph, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return graph

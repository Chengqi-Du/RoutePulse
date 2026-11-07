"""Convert OSM XML roads to a reproducible, simulation-only directed graph."""

from __future__ import annotations

import hashlib
import math
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

from .routing import Node


_FORMAT_VERSION = "routepulse-osm-graph-v1"
_EARTH_RADIUS_M = 6_371_008.8
_TAG_KEYS = frozenset({
    "highway", "name", "ref", "oneway", "junction", "access", "vehicle",
    "motor_vehicle", "foot", "bicycle", "bridge", "tunnel", "layer",
    "surface", "area",
})


class GraphNode(Node):
    name: str
    type: Literal["junction"]
    coordinates: list[float]


class LineString(TypedDict):
    type: Literal["LineString"]
    coordinates: list[list[float]]


class GraphEdge(TypedDict):
    id: str
    from_node_id: str
    to_node_id: str
    length_m: float
    osm_way_id: str
    highway: str
    direction: Literal["forward", "reverse"]
    direction_basis: str
    osm_tags: dict[str, str]
    geometry: LineString


class Graph(TypedDict):
    graph_version: str
    source: dict[str, object]
    nodes: list[GraphNode]
    edges: list[GraphEdge]


def _required(element: ET.Element, attribute: str) -> str:
    value = element.get(attribute)
    if value is None or not value.strip():
        raise ValueError(f"{element.tag} is missing {attribute}")
    return value


def _tags(element: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for tag in element.findall("tag"):
        key, value = _required(tag, "k"), _required(tag, "v")
        if key in result:
            raise ValueError(f"{element.tag} {element.get('id')} has duplicate tag {key}")
        result[key] = value
    return result


def _coordinates(node: ET.Element) -> list[float]:
    try:
        lon = float(_required(node, "lon"))
        lat = float(_required(node, "lat"))
    except ValueError as exc:
        raise ValueError(f"invalid coordinates for node {node.get('id')}") from exc
    if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError(f"invalid coordinates for node {node.get('id')}")
    return [lon, lat]


def distance_m(a: list[float], b: list[float]) -> float:
    """Great-circle distance between two [longitude, latitude] coordinates."""
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def _direction(tags: dict[str, str], way_id: str) -> tuple[bool, bool, str]:
    value = tags.get("oneway", "").strip().lower()
    if value in ("yes", "true", "1"):
        return True, False, "explicit_oneway"
    if value == "-1":
        return False, True, "explicit_reverse_oneway"
    if value in ("no", "false", "0"):
        return True, True, "explicit_two_way"
    if value:
        raise ValueError(f"way {way_id} has unsupported oneway value {value!r}")
    if tags.get("junction") in ("roundabout", "circular"):
        return True, False, "implied_junction_oneway"
    if tags["highway"] in ("motorway", "motorway_link"):
        return True, False, "assumed_motorway_oneway"
    return True, True, "assumed_two_way"


def build_graph(path: Path) -> tuple[Graph, dict[str, object], dict[str, object]]:
    """Return a graph, quality report and way-level GeoJSON for manual review."""
    raw = path.read_bytes()
    root = ET.fromstring(raw)
    if root.tag != "osm" or root.get("version") != "0.6":
        raise ValueError("input must be an OSM XML 0.6 document")
    source_hash = hashlib.sha256(raw).hexdigest()
    version_hash = hashlib.sha256(_FORMAT_VERSION.encode() + b"\0" + raw).hexdigest()
    graph_version = f"osm-v1-{version_hash[:24]}"

    objects: dict[str, dict[str, ET.Element]] = {}
    timestamps: list[datetime] = []
    for kind in ("node", "way", "relation"):
        elements: dict[str, ET.Element] = {}
        for element in root.findall(kind):
            object_id = _required(element, "id")
            if object_id in elements:
                raise ValueError(f"duplicate {kind} id {object_id}")
            elements[object_id] = element
            timestamp = element.get("timestamp")
            if timestamp:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError(f"{kind} {object_id} timestamp has no timezone")
                timestamps.append(parsed.astimezone(timezone.utc))
        objects[kind] = elements

    bound_element = root.find("bounds")
    bounds = None
    if bound_element is not None:
        bounds = {key: float(_required(bound_element, key)) for key in ("minlat", "minlon", "maxlat", "maxlon")}
        if not (
            all(math.isfinite(value) for value in bounds.values())
            and -90 <= bounds["minlat"] <= bounds["maxlat"] <= 90
            and -180 <= bounds["minlon"] <= bounds["maxlon"] <= 180
        ):
            raise ValueError("invalid OSM bounds")

    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    features: list[dict[str, object]] = []
    highway_counts: Counter[str] = Counter()
    direction_counts: Counter[str] = Counter()
    excluded_areas: list[str] = []
    complex_direction_ways: list[str] = []

    for way_id, way in sorted(objects["way"].items()):
        tags = _tags(way)
        if "highway" not in tags:
            continue
        highway_counts[tags["highway"]] += 1
        if tags.get("area") == "yes":
            excluded_areas.append(way_id)
            continue
        refs = [_required(nd, "ref") for nd in way.findall("nd")]
        if len(refs) < 2:
            raise ValueError(f"highway way {way_id} has fewer than two nodes")
        for ref in refs:
            node = objects["node"].get(ref)
            if node is None:
                raise ValueError(f"highway way {way_id} references missing node {ref}")
            node_id = f"osm-node-{ref}"
            if node_id not in nodes:
                nodes[node_id] = {
                    "id": node_id,
                    "name": f"OSM node {ref}",
                    "type": "junction",
                    "coordinates": _coordinates(node),
                }
        forward, reverse, basis = _direction(tags, way_id)
        direction_counts[basis] += 1
        if any(key.startswith("oneway:") or key == "junction:conditional" for key in tags):
            complex_direction_ways.append(way_id)
        public_tags = {
            key: value for key, value in sorted(tags.items())
            if key in _TAG_KEYS or key.startswith(("oneway:", "access:", "vehicle:", "motor_vehicle:"))
        }
        way_edge_ids: list[str] = []
        for index, (start_ref, end_ref) in enumerate(zip(refs, refs[1:])):
            start_id, end_id = f"osm-node-{start_ref}", f"osm-node-{end_ref}"
            start_coord, end_coord = nodes[start_id]["coordinates"], nodes[end_id]["coordinates"]
            length = distance_m(start_coord, end_coord)
            for enabled, direction, source, target, coords in (
                (forward, "forward", start_id, end_id, [start_coord, end_coord]),
                (reverse, "reverse", end_id, start_id, [end_coord, start_coord]),
            ):
                if not enabled:
                    continue
                edge_id = f"{graph_version}:w{way_id}:s{index}:{direction[0]}"
                edge: GraphEdge = {
                    "id": edge_id,
                    "from_node_id": source,
                    "to_node_id": target,
                    "length_m": length,
                    "osm_way_id": way_id,
                    "highway": tags["highway"],
                    "direction": direction,
                    "direction_basis": basis,
                    "osm_tags": public_tags,
                    "geometry": {"type": "LineString", "coordinates": coords},
                }
                edges.append(edge)
                way_edge_ids.append(edge_id)
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [nodes[f"osm-node-{ref}"]["coordinates"] for ref in refs],
            },
            "properties": {
                "osm_way_id": way_id,
                "highway": tags["highway"],
                "name": tags.get("name"),
                "direction_basis": basis,
                "edge_ids": way_edge_ids,
                "screenshot_review": "unreviewed",
            },
        })

    if not edges:
        raise ValueError("OSM input has no usable highway edges")
    restriction_relations = []
    missing_members = []
    for relation_id, relation in sorted(objects["relation"].items()):
        if _tags(relation).get("type") != "restriction":
            continue
        restriction_relations.append(relation_id)
        for member in relation.findall("member"):
            kind, ref = _required(member, "type"), _required(member, "ref")
            if kind not in objects or ref not in objects[kind]:
                missing_members.append({
                    "relation_id": relation_id,
                    "type": kind,
                    "ref": ref,
                    "role": member.get("role", ""),
                })

    latest = max(timestamps).isoformat().replace("+00:00", "Z") if timestamps else None
    graph: Graph = {
        "graph_version": graph_version,
        "source": {
            "format": "osm-xml",
            "source_file": path.name,
            "sha256": source_hash,
            "graph_format": _FORMAT_VERSION,
            "dataset_snapshot_at": None,
            "latest_object_edit_at": latest,
            "bounds": bounds,
            "attribution": "© OpenStreetMap contributors",
            "license": "https://opendatacommons.org/licenses/odbl/1-0/",
            "is_disaster_road_status": False,
        },
        "nodes": sorted(nodes.values(), key=lambda node: node["id"]),
        "edges": edges,
    }
    report: dict[str, object] = {
        "graph_version": graph_version,
        "source_sha256": source_hash,
        "declared_bounds": bounds,
        "input_counts": {kind: len(values) for kind, values in objects.items()},
        "highway_way_count": sum(highway_counts.values()),
        "highway_way_counts": dict(sorted(highway_counts.items())),
        "direction_basis_counts": dict(sorted(direction_counts.items())),
        "graph_node_count": len(nodes),
        "directed_edge_count": len(edges),
        "excluded_area_way_ids": excluded_areas,
        "complex_direction_way_ids": complex_direction_ways,
        "turn_restriction_relation_count": len(restriction_relations),
        "missing_turn_restriction_members": missing_members,
        "screenshot_coverage": "not_verified",
        "warnings": [
            "Simulation only; this graph is not for real-world rescue navigation.",
            "Screenshot coverage and road passability are not established by this export.",
            "Turn restrictions and vehicle-specific access are not enforced.",
            "Untagged ordinary ways are assumed two-way; untagged motorway links are assumed one-way.",
            "Conditional and mode-specific direction tags are retained but not enforced.",
            "Object edit timestamps do not establish the dataset snapshot time.",
        ],
    }
    audit: dict[str, object] = {
        "type": "FeatureCollection",
        "graph_version": graph_version,
        "features": features,
    }
    return graph, report, audit

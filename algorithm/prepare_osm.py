"""Export an OSM road graph, review materials and a seven-day simulation."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TextIO

from .osm_graph import Graph, build_graph
from .seven_day import build_seven_day_scenario


def _write_json(path: Path, data: object) -> None:
    with path.open("x", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write("\n")


def _write_way_review(file: TextIO, graph: Graph) -> None:
    writer = csv.writer(file)
    writer.writerow(["graph_version", "osm_way_id", "highway", "screenshot_segment_ids", "review_status", "notes"])
    ways: dict[str, str] = {}
    for edge in graph["edges"]:
        ways[edge["osm_way_id"]] = edge["highway"]
    for way_id, highway in sorted(ways.items()):
        writer.writerow([graph["graph_version"], way_id, highway, "", "unreviewed", ""])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("osm_file", type=Path, help="Local OSM XML 0.6 source")
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory; existing directories are not overwritten")
    parser.add_argument("--start-node", help="Existing graph node ID for the simulated start")
    parser.add_argument("--end-node", help="Existing graph node ID for the simulated destination")
    args = parser.parse_args(argv)
    try:
        graph, report, audit = build_graph(args.osm_file)
        scenario, demo = build_seven_day_scenario(graph, args.start_node, args.end_node)
        args.output_dir.mkdir(parents=True, exist_ok=False)
        _write_json(args.output_dir / "graph.json", graph)
        _write_json(args.output_dir / "quality-report.json", report)
        _write_json(args.output_dir / "roads-for-review.geojson", audit)
        _write_json(args.output_dir / "seven-day-scenario.json", scenario)
        _write_json(args.output_dir / "demo-selection.json", demo)
        with (args.output_dir / "way-review.csv").open("x", encoding="utf-8", newline="") as file:
            _write_way_review(file, graph)
        with (args.output_dir / "screenshot-inventory.csv").open("x", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["screenshot_segment_id", "description", "osm_way_ids", "edge_ids", "review_status", "notes"])
    except (OSError, ValueError, ET.ParseError) as exc:
        print(f"OSM export failed: {exc}", file=sys.stderr)
        return 1
    print(f"Graph version: {graph['graph_version']}")
    print(f"Exported {len(graph['nodes'])} nodes and {len(graph['edges'])} directed edges to {args.output_dir}")
    print("Screenshot coverage is NOT verified; inspect the review files.")
    print("SIMULATION ONLY — Not for real-world rescue navigation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

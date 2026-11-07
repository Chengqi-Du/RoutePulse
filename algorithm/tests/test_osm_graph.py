import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from algorithm import find_route
from algorithm.osm_graph import build_graph, distance_m
from algorithm.tests.osm_fixture import OSM_XML, demo_osm_xml


ROOT = Path(__file__).resolve().parents[2]


class OsmGraphTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "map.osm"
        self.path.write_text(OSM_XML, encoding="utf-8")
        self.graph, self.report, self.audit = build_graph(self.path)

    def test_graph_is_reproducible_and_source_change_changes_version(self):
        other = Path(self.temporary.name) / "copy.osm"
        other.write_text(OSM_XML, encoding="utf-8")
        second, _, _ = build_graph(other)
        self.assertEqual(self.graph["graph_version"], second["graph_version"])
        self.assertEqual(self.graph["edges"], second["edges"])
        other.write_text(OSM_XML + "\n", encoding="utf-8")
        changed, _, _ = build_graph(other)
        self.assertNotEqual(self.graph["graph_version"], changed["graph_version"])

    def test_edges_preserve_direction_length_and_geometry(self):
        nodes = {node["id"]: node for node in self.graph["nodes"]}
        edge_ids = set()
        by_way = {}
        for edge in self.graph["edges"]:
            self.assertNotIn(edge["id"], edge_ids)
            edge_ids.add(edge["id"])
            by_way.setdefault(edge["osm_way_id"], []).append(edge)
            coordinates = edge["geometry"]["coordinates"]
            self.assertEqual(coordinates[0], nodes[edge["from_node_id"]]["coordinates"])
            self.assertEqual(coordinates[-1], nodes[edge["to_node_id"]]["coordinates"])
            self.assertAlmostEqual(edge["length_m"], distance_m(*coordinates))
            self.assertNotIn("effective_status", edge)
        self.assertEqual(len(by_way["10"]), 4)
        self.assertEqual(len(by_way["11"]), 4)
        self.assertEqual([(edge["from_node_id"], edge["to_node_id"]) for edge in by_way["12"]],
                         [("osm-node-6", "osm-node-5")])
        self.assertEqual(len(by_way["13"]), 1)
        self.assertEqual(by_way["13"][0]["direction_basis"], "assumed_motorway_oneway")
        self.assertEqual(len(by_way["14"]), 2)
        self.assertEqual(by_way["14"][0]["direction_basis"], "explicit_two_way")
        self.assertNotIn("15", by_way)

    def test_shared_coordinates_do_not_create_connections(self):
        edges = [{**edge, "effective_status": "open"} for edge in self.graph["edges"]]
        result = find_route(self.graph["nodes"], edges, "osm-node-2", "osm-node-5")
        self.assertEqual(result["status"], "no_path")

    def test_quality_report_and_review_data_do_not_claim_coverage(self):
        self.assertEqual(self.report["highway_way_count"], 6)
        self.assertEqual(self.report["excluded_area_way_ids"], ["15"])
        self.assertEqual(self.report["turn_restriction_relation_count"], 1)
        self.assertEqual(len(self.report["missing_turn_restriction_members"]), 1)
        self.assertEqual(self.report["screenshot_coverage"], "not_verified")
        self.assertEqual(self.graph["source"]["latest_object_edit_at"], "2026-01-01T00:00:00Z")
        self.assertIsNone(self.graph["source"]["dataset_snapshot_at"])
        features = self.audit["features"]
        self.assertEqual(len(features), 5)
        self.assertTrue(all(feature["properties"]["screenshot_review"] == "unreviewed" for feature in features))

    def test_missing_node_and_unsupported_direction_fail(self):
        self.path.write_text(OSM_XML.replace('<nd ref="2"/>', '<nd ref="999"/>', 1), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing node"):
            build_graph(self.path)
        self.path.write_text(OSM_XML.replace('v="-1"', 'v="reversible"'), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unsupported oneway"):
            build_graph(self.path)

    def test_cli_writes_new_export_without_overwriting(self):
        self.path.write_text(demo_osm_xml(), encoding="utf-8")
        output = Path(self.temporary.name) / "export"
        command = [
            sys.executable, "-m", "algorithm.prepare_osm", str(self.path),
            "--output-dir", str(output), "--start-node", "osm-node-1", "--end-node", "osm-node-4",
        ]
        first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(first.returncode, 0, first.stderr)
        graph_path = output / "graph.json"
        original_hash = hashlib.sha256(graph_path.read_bytes()).hexdigest()
        self.assertEqual(len(json.loads((output / "seven-day-scenario.json").read_text())["days"]), 7)
        second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(hashlib.sha256(graph_path.read_bytes()).hexdigest(), original_hash)


if __name__ == "__main__":
    unittest.main()

import copy
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from algorithm.demo_scenario import _components, build_demo_scenario
from algorithm.osm_graph import build_graph
from algorithm.routing import find_route
from algorithm.seven_day import _snapshot_edges, validate_seven_day_scenario


ROOT = Path(__file__).resolve().parents[2]
OSM = ROOT / "routepulse-backend" / "data" / "map.osm"


class DemoScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph, _, _ = build_graph(OSM)
        cls.scenario = build_demo_scenario(cls.graph)

    def test_checked_in_scenario_reproduces_and_changes_daily(self):
        saved = json.loads((ROOT / "data/anamizu-demo/seven-day-scenario.json").read_text())
        self.assertEqual(self.scenario, saved)
        validate_seven_day_scenario(self.graph, saved)
        previous = None
        for day in saved["days"]:
            summary = day["summary"]
            self.assertEqual(summary["physical_segments_blocked"], 95)
            self.assertGreater(summary["physical_open_percent"], 95)
            blocked = {item["edge_id"].rpartition(":")[0] for item in day["road_observations"]
                       if item["status"] == "reported_blocked"}
            self.assertEqual(len(blocked), 95)
            if previous is not None:
                self.assertGreaterEqual(len(blocked - previous), 51)
                self.assertGreaterEqual(len(previous - blocked), 51)
            previous = blocked

    def test_named_choices_can_reach_each_other_every_day(self):
        groups, _ = _components(self.graph)
        largest = max(groups, key=len)
        root = ET.parse(OSM).getroot()
        named = [
            f"osm-node-{node.attrib['id']}" for node in root.findall("node")
            if f"osm-node-{node.attrib['id']}" in largest
            and any(tag.attrib.get("k") in {"name", "name:ja"} for tag in node.findall("tag"))
        ]
        self.assertGreaterEqual(len(named), 9)
        for day in self.scenario["days"]:
            statuses = {item["edge_id"]: item["status"].removeprefix("reported_")
                        for item in day["road_observations"]}
            edges = _snapshot_edges(self.graph["edges"], statuses)
            for start in named:
                for end in named:
                    if start != end:
                        route = find_route(self.graph["nodes"], edges, start, end)
                        self.assertEqual(route["status"], "found", (day["day_index"], start, end))

    def test_rejects_unchanged_or_inconsistent_days(self):
        unchanged = copy.deepcopy(self.scenario)
        unchanged["days"][1]["road_observations"] = copy.deepcopy(unchanged["days"][0]["road_observations"])
        with self.assertRaises(ValueError):
            validate_seven_day_scenario(self.graph, unchanged)
        inconsistent = copy.deepcopy(self.scenario)
        first = inconsistent["days"][0]["road_observations"]
        by_id = {item["edge_id"]: item for item in first}
        forward = next(edge for edge in self.graph["edges"] if edge["id"].endswith(":f")
                       and edge["id"][:-1] + "r" in by_id)
        reverse = by_id[forward["id"][:-1] + "r"]
        reverse["status"] = "reported_open" if reverse["status"] == "reported_blocked" else "reported_blocked"
        with self.assertRaises(ValueError):
            validate_seven_day_scenario(self.graph, inconsistent)


if __name__ == "__main__":
    unittest.main()

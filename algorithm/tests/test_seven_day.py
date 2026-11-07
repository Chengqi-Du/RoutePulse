import copy
import tempfile
import unittest
from pathlib import Path

from algorithm.osm_graph import build_graph
from algorithm.seven_day import build_seven_day_scenario, validate_seven_day_scenario
from algorithm.tests.osm_fixture import demo_osm_xml


class SevenDayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        path = Path(self.temporary.name) / "map.osm"
        path.write_text(demo_osm_xml(), encoding="utf-8")
        self.graph, _, _ = build_graph(path)
        self.scenario, self.demo = build_seven_day_scenario(self.graph, "osm-node-1", "osm-node-4")

    def test_seven_days_cover_each_edge_without_claiming_real_images(self):
        days = self.scenario["days"]
        expected = {edge["id"] for edge in self.graph["edges"]}
        self.assertEqual(len(days), 7)
        for index, day in enumerate(days, start=1):
            self.assertEqual(day["day_index"], index)
            self.assertEqual(day["graph_version"], self.graph["graph_version"])
            self.assertTrue(day["observations_are_simulated"])
            self.assertIsNone(day["image"])
            self.assertEqual({observation["edge_id"] for observation in day["road_observations"]}, expected)
            self.assertEqual(len(day["road_observations"]), len(expected))
        validate_seven_day_scenario(self.graph, self.scenario)

    def test_daily_most_roads_blocked_and_changes_both_ways(self):
        groups = {}
        for edge in self.graph["edges"]:
            group_id = edge["id"].rsplit(":", 1)[0]
            groups.setdefault(group_id, []).append(edge)
        total = len(groups)
        total_length = sum(edges[0]["length_m"] for edges in groups.values())
        previous = None
        for day in self.scenario["days"]:
            statuses = {obs["edge_id"]: obs["status"] for obs in day["road_observations"]}
            physical = {}
            for group_id, edges in groups.items():
                values = {statuses[edge["id"]] for edge in edges}
                self.assertEqual(len(values), 1, f"opposite directions differ on {group_id}")
                physical[group_id] = values.pop()
            opened = {group_id for group_id, status in physical.items() if status == "reported_open"}
            self.assertTrue(0.20 <= len(opened) / total <= 0.30)
            open_length = sum(groups[group_id][0]["length_m"] for group_id in opened)
            self.assertTrue(0.20 <= open_length / total_length <= 0.30)
            if previous is not None:
                self.assertGreaterEqual(len(opened - previous), max(1, int(total * 0.02)))
                self.assertGreaterEqual(len(previous - opened), max(1, int(total * 0.02)))
            previous = opened

    def test_demo_route_changes_and_day_seven_is_unreachable(self):
        snapshots = self.demo["verified_snapshots"]
        primary = self.demo["primary_edge_id"]
        self.assertIn(primary, snapshots["day1_open"]["edge_ids"])
        self.assertNotIn(primary, snapshots["day1_manual_block_conflict"]["edge_ids"])
        self.assertEqual(snapshots["day1_manual_block_conflict"]["status"], "found")
        self.assertEqual(snapshots["day2_manual_block_and_daily_update"]["status"], "found")
        self.assertEqual(snapshots["day7_destination_incoming_edges_blocked"]["status"], "no_path")
        cut = set(self.demo["day7_blocked_incoming_edge_ids"])
        self.assertEqual(
            cut,
            {edge["id"] for edge in self.graph["edges"] if edge["to_node_id"] == self.demo["end_node_id"]},
        )
        day7 = self.scenario["days"][-1]
        self.assertTrue(
            cut <= {obs["edge_id"] for obs in day7["road_observations"] if obs["status"] == "reported_blocked"}
        )

    def test_bad_node_selection_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "supplied together"):
            build_seven_day_scenario(self.graph, "osm-node-1")
        with self.assertRaisesRegex(ValueError, "must exist"):
            build_seven_day_scenario(self.graph, "osm-node-1", "missing")
        with self.assertRaisesRegex(ValueError, "must differ"):
            build_seven_day_scenario(self.graph, "osm-node-1", "osm-node-1")
        with self.assertRaisesRegex(ValueError, "alternative"):
            build_seven_day_scenario(self.graph, "osm-node-1", "osm-node-5")

    def test_invalid_scenarios_are_rejected(self):
        cases = []
        wrong_version = copy.deepcopy(self.scenario)
        wrong_version["graph_version"] = "another-version"
        cases.append(wrong_version)
        missing_day = copy.deepcopy(self.scenario)
        missing_day["days"].pop()
        cases.append(missing_day)
        missing_edge = copy.deepcopy(self.scenario)
        missing_edge["days"][0]["road_observations"].pop()
        cases.append(missing_edge)
        duplicate_edge = copy.deepcopy(self.scenario)
        duplicate_edge["days"][0]["road_observations"].append(
            duplicate_edge["days"][0]["road_observations"][0]
        )
        cases.append(duplicate_edge)
        invalid_status = copy.deepcopy(self.scenario)
        invalid_status["days"][0]["road_observations"][0]["status"] = "open"
        cases.append(invalid_status)
        wrong_time = copy.deepcopy(self.scenario)
        wrong_time["days"][1]["scenario_time"] = wrong_time["days"][0]["scenario_time"]
        cases.append(wrong_time)
        boolean_day = copy.deepcopy(self.scenario)
        boolean_day["days"][0]["day_index"] = True
        cases.append(boolean_day)
        inconsistent_source = copy.deepcopy(self.scenario)
        inconsistent_source["days"][1]["observation_source_id"] = "different-source"
        cases.append(inconsistent_source)
        unchanged_day = copy.deepcopy(self.scenario)
        unchanged_day["days"][3]["road_observations"] = copy.deepcopy(
            unchanged_day["days"][2]["road_observations"]
        )
        cases.append(unchanged_day)
        all_open = copy.deepcopy(self.scenario)
        for observation in all_open["days"][0]["road_observations"]:
            observation["status"] = "reported_open"
        cases.append(all_open)
        inconsistent_directions = copy.deepcopy(self.scenario)
        observations = inconsistent_directions["days"][0]["road_observations"]
        status_by_id = {obs["edge_id"]: obs for obs in observations}
        forward = next(edge for edge in self.graph["edges"] if edge["id"].endswith(":f")
                       and edge["id"][:-1] + "r" in status_by_id)
        reverse = status_by_id[forward["id"][:-1] + "r"]
        reverse["status"] = "reported_open" if reverse["status"] == "reported_blocked" else "reported_blocked"
        cases.append(inconsistent_directions)
        wrong_scenario_version = copy.deepcopy(self.scenario)
        wrong_scenario_version["scenario_version"] = "another-scenario"
        cases.append(wrong_scenario_version)
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                validate_seven_day_scenario(self.graph, case)


if __name__ == "__main__":
    unittest.main()

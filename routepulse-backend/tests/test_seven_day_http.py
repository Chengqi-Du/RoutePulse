import json
import tempfile
import unittest
from pathlib import Path

from algorithm.osm_graph import build_graph
from algorithm.seven_day import build_seven_day_scenario
from test_integration import BACKEND, ROOT, running_backend


DATA = ROOT / "data" / "anamizu-v2"
AREA = "/areas/area-a"


class SevenDayHttpTests(unittest.TestCase):
    def test_canonical_osm_reproduces_checked_in_data(self):
        graph, _, _ = build_graph(BACKEND / "data" / "map.osm")
        scenario, demo = build_seven_day_scenario(graph)
        saved_graph = json.loads((DATA / "graph.json").read_text(encoding="utf-8"))
        saved_scenario = json.loads((DATA / "seven-day-scenario.json").read_text(encoding="utf-8"))
        saved_demo = json.loads((DATA / "demo-selection.json").read_text(encoding="utf-8"))
        self.assertEqual(graph, saved_graph)
        self.assertEqual(scenario, saved_scenario)
        for key in ("graph_version", "start_node_id", "end_node_id", "primary_edge_id", "alternate_edge_id"):
            self.assertEqual(demo[key], saved_demo[key])
        for actual, expected in zip(demo["daily_routes_without_manual_reports"], saved_demo["daily_routes_without_manual_reports"]):
            self.assertEqual(actual["status"], expected["status"])
            self.assertEqual(actual["node_ids"], expected["node_ids"])
            self.assertEqual(actual["edge_ids"], expected["edge_ids"])
            if actual["distance_m"] is None:
                self.assertIsNone(expected["distance_m"])
            else:
                self.assertAlmostEqual(actual["distance_m"], expected["distance_m"], places=8)

    def test_checked_in_graph_seven_days_feedback_and_restart(self):
        graph = json.loads((DATA / "graph.json").read_text(encoding="utf-8"))
        scenario = json.loads((DATA / "seven-day-scenario.json").read_text(encoding="utf-8"))
        demo = json.loads((DATA / "demo-selection.json").read_text(encoding="utf-8"))
        expected_edges = {edge["id"]: edge for edge in graph["edges"]}
        self.assertEqual(len(expected_edges), len(graph["edges"]))

        with tempfile.TemporaryDirectory(prefix="routepulse-seven-day-") as directory:
            db_path = Path(directory) / "scenario.sqlite3"
            options = {
                "ROUTEPULSE_SCENARIO_MODE": "anamizu-7day",
                "ROUTEPULSE_DAY_TEMPLATES_PATH": str(DATA / "seven-day-scenario.json"),
            }
            with running_backend(ROOT, BACKEND, db_path=db_path, extra_env=options) as (client, _, _):
                initial = client.request("GET", AREA + "/state")
                self.assertEqual(initial["graph_version"], graph["graph_version"])
                self.assertEqual(initial["graph_metadata"]["source"]["sha256"], graph["source"]["sha256"])
                self.assertEqual(initial["day_index"], 0)
                self.assertEqual(initial["version"], 1)
                self.assertEqual({node["id"] for node in initial["nodes"]}, {node["id"] for node in graph["nodes"]})
                actual_edges = {edge["id"]: edge for edge in initial["edges"]}
                self.assertEqual(set(actual_edges), set(expected_edges))
                for edge_id, edge in actual_edges.items():
                    expected = expected_edges[edge_id]
                    self.assertEqual(edge["from_node_id"], expected["from_node_id"])
                    self.assertEqual(edge["to_node_id"], expected["to_node_id"])
                    self.assertEqual(edge["geometry"], expected["geometry"])
                    self.assertEqual(edge["length_m"], expected["length_m"])
                    self.assertEqual(edge["effective_status"], "unknown")

                version = initial["version"]
                previous = None
                primary = demo["primary_edge_id"]
                for day in scenario["days"]:
                    index = day["day_index"]
                    result = client.request("POST", AREA + "/advance-day", body={"expected_version": version})
                    version = result["version"]
                    self.assertEqual(result["day_index"], index)
                    self.assertEqual(len(result["report_ids"]), len(expected_edges))
                    state = client.request("GET", AREA + "/state")
                    self.assertEqual((state["day_index"], state["version"]), (index, version))
                    observed = {item["edge_id"]: item["status"] for item in day["road_observations"]}
                    reports = {
                        item["edge_id"]: item["status"] for item in state["reports"]
                        if item["frame_id"] == day["frame_id"] and item["source_type"] == "external_demo"
                    }
                    self.assertEqual(reports, observed)
                    if previous is not None:
                        self.assertTrue(any(previous[edge] == "reported_blocked" and status == "reported_open"
                                            for edge, status in observed.items()))
                        self.assertTrue(any(previous[edge] == "reported_open" and status == "reported_blocked"
                                            for edge, status in observed.items()))
                    previous = observed
                    for edge in state["edges"]:
                        if index == 1 or edge["id"] != primary:
                            self.assertEqual(edge["effective_status"], observed[edge["id"]].removeprefix("reported_"))

                    if index == 1:
                        result = client.request("POST", AREA + "/routes", body={
                            "expected_version": version,
                            "start_node_id": demo["start_node_id"],
                            "end_node_id": demo["end_node_id"],
                        })
                        version = result["version"]
                        state = client.request("GET", AREA + "/state")
                        self.assertEqual(state["current_result"]["node_ids"], demo["daily_routes_without_manual_reports"][0]["node_ids"])
                        self.assertIn(primary, state["current_result"]["edge_ids"])
                        result = client.request("POST", AREA + "/reports", expected_status=201, body={
                            "expected_version": version,
                            "edge_id": primary,
                            "status": "reported_blocked",
                            "source_id": "test-field-team",
                            "source_name": "Test field team",
                            "observed_at": state["scenario_time"],
                        })
                        version = result["version"]
                        state = client.request("GET", AREA + "/state")
                        edge = next(edge for edge in state["edges"] if edge["id"] == primary)
                        self.assertEqual(edge["effective_status"], "conflict")
                        self.assertEqual(state["current_result"]["status"], "found")
                        self.assertNotIn(primary, state["current_result"]["edge_ids"])
                        self.assertTrue(state["history"])

                        bad_batch = {
                            "expected_version": version, "edge_ids": [primary, "unknown-edge"],
                            "status": "reported_blocked", "source_id": "batch-test",
                            "source_name": "Batch test", "observed_at": state["scenario_time"],
                        }
                        error = client.request("POST", AREA + "/reports/batch", body=bad_batch, expected_status=404)
                        self.assertEqual(error["error"]["code"], "EDGE_NOT_FOUND")
                        bad_batch["edge_ids"] = [primary, primary]
                        client.request("POST", AREA + "/reports/batch", body=bad_batch, expected_status=422)
                        error = client.request("POST", AREA + "/advance-day",
                                               body={"expected_version": version - 1}, expected_status=409)
                        self.assertEqual(error["error"]["code"], "VERSION_CONFLICT")
                        unchanged = client.request("GET", AREA + "/state")
                        self.assertEqual(unchanged["version"], version)
                        self.assertEqual(len(unchanged["reports"]), len(state["reports"]))
                    else:
                        self.assertEqual(state["current_result"]["status"],
                                         demo["daily_routes_without_manual_reports"][index - 1]["status"])
                    if index == 2:
                        edge = next(edge for edge in state["edges"] if edge["id"] == primary)
                        self.assertIn(edge["effective_status"], ("blocked", "conflict"))
                    if index == 4:
                        result = client.request("POST", AREA + "/reports", expected_status=201, body={
                            "expected_version": version,
                            "edge_id": primary,
                            "status": "reported_open",
                            "source_id": "test-field-team",
                            "source_name": "Test field team",
                            "observed_at": state["scenario_time"],
                        })
                        version = result["version"]
                        state = client.request("GET", AREA + "/state")
                        self.assertEqual(next(edge for edge in state["edges"] if edge["id"] == primary)["effective_status"], "open")

                self.assertEqual(state["current_result"]["status"], "no_path")
                error = client.request("POST", AREA + "/advance-day",
                                       body={"expected_version": version}, expected_status=409)
                self.assertEqual(error["error"]["code"], "DAY_SEQUENCE_COMPLETE")
                blocked = {edge["id"] for edge in state["edges"] if edge["effective_status"] == "blocked"}
                pair = next(
                    [edge_id, edge_id[:-1] + "r"] for edge_id in blocked
                    if edge_id.endswith(":f") and edge_id[:-1] + "r" in blocked
                )
                result = client.request("POST", AREA + "/reports/batch", expected_status=201, body={
                    "expected_version": version, "edge_ids": pair, "status": "reported_blocked",
                    "source_id": "batch-test", "source_name": "Batch test",
                    "observed_at": state["scenario_time"],
                })
                version = result["version"]
                self.assertEqual(len(result["report_ids"]), 2)
                state = client.request("GET", AREA + "/state")
                self.assertEqual({edge["effective_status"] for edge in state["edges"] if edge["id"] in pair}, {"blocked"})
                self.assertEqual(state["current_result"]["status"], "no_path")

            with running_backend(ROOT, BACKEND, db_path=db_path, extra_env=options) as (client, _, _):
                restored = client.request("GET", AREA + "/state")
                self.assertEqual((restored["day_index"], restored["version"]), (7, version))
                self.assertEqual(restored["current_result"]["status"], "no_path")
                self.assertEqual(len(restored["reports"]), 7 * len(expected_edges) + 4)

    def test_invalid_or_missing_templates_do_not_change_state(self):
        scenario = json.loads((DATA / "seven-day-scenario.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="routepulse-invalid-template-") as directory:
            root = Path(directory)
            mismatch = root / "mismatch.json"
            scenario["graph_version"] = "wrong-version"
            mismatch.write_text(json.dumps(scenario), encoding="utf-8")
            scenario["graph_version"] = json.loads((DATA / "graph.json").read_text(encoding="utf-8"))["graph_version"]
            scenario["days"][6]["road_observations"][0]["edge_id"] = "unknown-edge"
            unknown = root / "unknown.json"
            unknown.write_text(json.dumps(scenario), encoding="utf-8")
            for name, template, status, code in (
                ("missing", root / "missing.json", 503, "DAY_TEMPLATES_NOT_CONFIGURED"),
                ("mismatch", mismatch, 422, "INVALID_DAY_TEMPLATES"),
                ("unknown", unknown, 422, "INVALID_DAY_TEMPLATES"),
            ):
                with self.subTest(name=name):
                    options = {"ROUTEPULSE_SCENARIO_MODE": "anamizu-7day", "ROUTEPULSE_DAY_TEMPLATES_PATH": str(template)}
                    with running_backend(ROOT, BACKEND, extra_env=options) as (client, _, _):
                        error = client.request("POST", AREA + "/advance-day",
                                               body={"expected_version": 1}, expected_status=status)
                        self.assertEqual(error["error"]["code"], code)
                        state = client.request("GET", AREA + "/state")
                        self.assertEqual((state["version"], state["day_index"], len(state["reports"])), (1, 0, 0))

    def test_legacy_restart_preserves_state(self):
        with tempfile.TemporaryDirectory(prefix="routepulse-legacy-restart-") as directory:
            db_path = Path(directory) / "scenario.sqlite3"
            with running_backend(ROOT, BACKEND, db_path=db_path) as (client, _, _):
                client.request("POST", AREA + "/routes", body={
                    "expected_version": 1, "start_node_id": "S", "end_node_id": "T",
                })
                saved = client.request("GET", AREA + "/state")
                client.request("POST", AREA + "/reports", expected_status=201, body={
                    "expected_version": saved["version"], "edge_id": "road-sa",
                    "status": "reported_blocked", "source_id": "legacy-team",
                    "source_name": "Legacy test team", "observed_at": saved["scenario_time"],
                })
                saved = client.request("GET", AREA + "/state")
            with running_backend(ROOT, BACKEND, db_path=db_path) as (client, _, _):
                restored = client.request("GET", AREA + "/state")
                self.assertEqual(restored["version"], saved["version"])
                self.assertEqual(restored["current_result"], saved["current_result"])
                self.assertEqual(restored["reports"], saved["reports"])
                self.assertEqual(restored["history"], saved["history"])

    def test_existing_database_rejects_different_graph_and_mode(self):
        with tempfile.TemporaryDirectory(prefix="routepulse-graph-restart-") as directory:
            root = Path(directory)
            db_path = root / "scenario.sqlite3"
            original = BACKEND / "data" / "map.osm"
            changed = root / "different-map.osm"
            changed.write_bytes(original.read_bytes() + b"\n")
            options = {"ROUTEPULSE_SCENARIO_MODE": "anamizu-7day", "ROUTEPULSE_OSM_PATH": str(changed)}
            with running_backend(ROOT, BACKEND, db_path=db_path, extra_env=options) as (client, _, _):
                old_graph = client.request("GET", AREA + "/state")["graph_version"]
            with self.assertRaisesRegex(RuntimeError, "OSM graph differs from this database"):
                with running_backend(ROOT, BACKEND, db_path=db_path,
                                     extra_env={"ROUTEPULSE_SCENARIO_MODE": "anamizu-7day"}):
                    self.fail("A changed graph must not be loaded into an existing database")
            with self.assertRaisesRegex(RuntimeError, "Database belongs to another scenario mode"):
                with running_backend(ROOT, BACKEND, db_path=db_path):
                    self.fail("A different scenario mode must not reuse this database")
            with running_backend(ROOT, BACKEND, db_path=db_path, extra_env=options) as (client, _, _):
                state = client.request("GET", AREA + "/state")
                self.assertEqual((state["graph_version"], state["version"], state["day_index"]), (old_graph, 1, 0))


if __name__ == "__main__":
    unittest.main()

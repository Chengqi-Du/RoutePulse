import json
import tempfile
import unittest
from pathlib import Path

from test_integration import BACKEND, ROOT, running_backend


AREA = "/areas/area-a"


class DemoHttpTests(unittest.TestCase):
    def test_batch_closes_both_directions_and_reroutes(self):
        demo = json.loads((ROOT / "data/anamizu-v2/demo-selection.json").read_text())
        with running_backend(ROOT, BACKEND, extra_env={"ROUTEPULSE_SCENARIO_MODE": "anamizu-7day"}) as (client, _, _):
            client.request("POST", AREA + "/advance-day", body={"expected_version": 1})
            state = client.request("GET", AREA + "/state")
            client.request("POST", AREA + "/routes", body={
                "expected_version": state["version"], "start_node_id": demo["start_node_id"], "end_node_id": demo["end_node_id"],
            })
            state = client.request("GET", AREA + "/state")
            primary = demo["primary_edge_id"]
            reverse = primary[:-1] + ("r" if primary.endswith(":f") else "f")
            self.assertIn(primary, state["current_result"]["edge_ids"])
            self.assertIn(reverse, {edge["id"] for edge in state["edges"]})
            client.request("POST", AREA + "/reports/batch", expected_status=201, body={
                "expected_version": state["version"], "edge_ids": [reverse, primary],
                "status": "reported_blocked", "source_id": "demo-team", "source_name": "Demo team",
                "observed_at": state["scenario_time"],
            })
            updated = client.request("GET", AREA + "/state")
            statuses = {edge["id"]: edge["effective_status"] for edge in updated["edges"]}
            self.assertNotEqual(statuses[primary], "open")
            self.assertNotEqual(statuses[reverse], "open")
            self.assertEqual(updated["current_result"]["status"], "found")
            self.assertNotIn(primary, updated["current_result"]["edge_ids"])
            self.assertNotEqual(updated["current_result"]["edge_ids"], state["current_result"]["edge_ids"])
            self.assertTrue(updated["route_change"]["changed"])

    def test_default_demo_seven_days_and_manual_reroute(self):
        demo = json.loads((ROOT / "data/anamizu-v2/demo-selection.json").read_text())
        scenario = json.loads((ROOT / "data/anamizu-demo/seven-day-scenario.json").read_text())
        with running_backend(ROOT, BACKEND, extra_env={"ROUTEPULSE_SCENARIO_MODE": "anamizu-7day"}) as (client, _, _):
            state = client.request("GET", AREA + "/state")
            self.assertEqual((state["day_index"], state["version"]), (0, 1))
            version = 1
            for day in scenario["days"]:
                response = client.request("POST", AREA + "/advance-day", body={"expected_version": version})
                version = response["version"]
                state = client.request("GET", AREA + "/state")
                self.assertEqual(state["day_index"], day["day_index"])
                expected = {item["edge_id"]: item["status"].removeprefix("reported_")
                            for item in day["road_observations"]}
                for edge in state["edges"]:
                    if day["day_index"] == 1 or edge["id"] != demo["primary_edge_id"]:
                        self.assertEqual(edge["effective_status"], expected[edge["id"]])
                if day["day_index"] == 1:
                    route = client.request("POST", AREA + "/routes", body={
                        "expected_version": version, "start_node_id": demo["start_node_id"], "end_node_id": demo["end_node_id"],
                    })
                    version = route["version"]
                    state = client.request("GET", AREA + "/state")
                    self.assertIn(demo["primary_edge_id"], state["current_result"]["edge_ids"])
                    report = client.request("POST", AREA + "/reports", expected_status=201, body={
                        "expected_version": version, "edge_id": demo["primary_edge_id"],
                        "status": "reported_blocked", "source_id": "demo-team", "source_name": "Demo team",
                        "observed_at": state["scenario_time"],
                    })
                    version = report["version"]
                    state = client.request("GET", AREA + "/state")
                    self.assertEqual(state["current_result"]["status"], "found")
                    self.assertNotIn(demo["primary_edge_id"], state["current_result"]["edge_ids"])
                else:
                    self.assertEqual(state["current_result"]["status"], "found")
            error = client.request("POST", AREA + "/advance-day", body={"expected_version": version}, expected_status=409)
            self.assertEqual(error["error"]["code"], "DAY_SEQUENCE_COMPLETE")

    def test_switching_scenario_on_existing_database_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="routepulse-scenario-switch-") as directory:
            db = Path(directory) / "scenario.sqlite3"
            old = {
                "ROUTEPULSE_SCENARIO_MODE": "anamizu-7day",
                "ROUTEPULSE_DAY_TEMPLATES_PATH": str(ROOT / "data/anamizu-v2/seven-day-scenario.json"),
            }
            with running_backend(ROOT, BACKEND, db_path=db, extra_env=old) as (client, _, _):
                client.request("POST", AREA + "/advance-day", body={"expected_version": 1})
            with running_backend(ROOT, BACKEND, db_path=db,
                                 extra_env={"ROUTEPULSE_SCENARIO_MODE": "anamizu-7day"}) as (client, _, _):
                error = client.request("POST", AREA + "/advance-day", body={"expected_version": 2}, expected_status=409)
                self.assertEqual(error["error"]["code"], "SCENARIO_MISMATCH")
                state = client.request("GET", AREA + "/state")
                self.assertEqual((state["version"], state["day_index"]), (2, 1))


if __name__ == "__main__":
    unittest.main()

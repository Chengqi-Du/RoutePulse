import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from algorithm.check_backend import ApiClient, CheckError, run_checks


class ScriptedClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def request(self, method, path, *, body=None, expected_status=200):
        self.requests.append((method, path, body, expected_status))
        return next(self.responses)


def state(version, road_sa, road_bt, current, history, change=None):
    return {
        "is_simulation": True,
        "version": version,
        "scenario_time": "2026-01-01T10:00:00Z",
        "current_result": current,
        "history": history,
        "edges": [
            {"id": "road-sa", "effective_status": road_sa},
            {"id": "road-at", "effective_status": "open"},
            {"id": "road-sb", "effective_status": "open"},
            {"id": "road-bt", "effective_status": road_bt},
        ],
        "reports": [{"id": "manual-1"}] if version >= 3 else [],
        "route_change": change,
    }


class BackendCheckTests(unittest.TestCase):
    def test_api_client_reads_successful_json(self):
        response = unittest.mock.MagicMock()
        response.status = 200
        response.read.return_value = b'{"version": 1}'
        response.__enter__.return_value = response
        with patch("algorithm.check_backend.urlopen", return_value=response):
            self.assertEqual(ApiClient("http://localhost:8000/api").request("GET", "/state"), {"version": 1})

    def test_api_client_reads_expected_http_errors(self):
        error = HTTPError(
            "http://localhost:8000/api/state", 409, "Conflict", {},
            io.BytesIO(b'{"error": {"code": "VERSION_CONFLICT"}}'),
        )
        with patch("algorithm.check_backend.urlopen", side_effect=error):
            result = ApiClient("http://localhost:8000/api").request("POST", "/state", expected_status=409)
        self.assertEqual(result["error"]["code"], "VERSION_CONFLICT")

    def test_api_client_reports_network_failure(self):
        with patch("algorithm.check_backend.urlopen", side_effect=URLError("offline")):
            with self.assertRaisesRegex(CheckError, "offline"):
                ApiClient("http://localhost:8000/api").request("GET", "/state")

    def test_refuses_to_mutate_an_existing_scenario(self):
        initial = state(2, "open", "open", None, [])
        client = ScriptedClient([{"is_simulation": True}, initial])
        with self.assertRaisesRegex(CheckError, "fresh disposable"):
            run_checks(client)
        self.assertEqual([request[0] for request in client.requests], ["GET", "GET"])

    def test_expected_sequence_completes(self):
        first = {"status": "found", "edge_ids": ["road-sa", "road-at"], "distance_m": 2000}
        second = {"status": "found", "edge_ids": ["road-sb", "road-bt"], "distance_m": 4000}
        no_path = {"status": "no_path", "edge_ids": []}
        client = ScriptedClient([
            {"is_simulation": True},
            state(1, "open", "open", None, []),
            {"version": 2},
            state(2, "open", "open", first, []),
            {"version": 3, "report_id": "manual-1"},
            state(3, "blocked", "open", second, [first], {
                "changed": True, "affected_previous_route": True, "trigger_report_id": "manual-1"
            }),
            {"version": 3, "intent": "why_changed", "answer": "Simulated closure"},
            {"version": 4, "scenario_time": "2026-01-01T10:10:00Z"},
            state(4, "conflict", "open", second, [first, second], {"changed": False}),
            {"version": 5},
            state(5, "conflict", "suspected", no_path, [first, second]),
            {"version": 5, "intent": "needs_check", "related_edge_ids": ["road-sa", "road-bt"]},
            {"version": 6, "intent": "route", "answer": "No simulated route", "related_edge_ids": []},
            state(6, "conflict", "suspected", no_path, [first, second, no_path]),
            {"error": {"code": "VERSION_CONFLICT"}},
            {"error": {"code": "DEMO_EXHAUSTED"}},
            {"error": {"code": "EDGE_NOT_FOUND"}},
            {"version": 6},
        ])
        run_checks(client)
        self.assertEqual(len(client.requests), 18)
        self.assertEqual(client.requests[0][:2], ("GET", "/scenario"))
        self.assertEqual(client.requests[-1][:2], ("GET", "/areas/area-a/state"))


if __name__ == "__main__":
    unittest.main()

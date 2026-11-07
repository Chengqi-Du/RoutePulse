"""Opt-in contract checks against a disposable running backend."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class CheckError(Exception):
    """The backend did not meet an integration check."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckError(message)


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        expected_status: int = 200,
    ) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urlopen(request, timeout=10) as response:
                status = response.status
                raw = response.read()
        except HTTPError as exc:
            status = exc.code
            try:
                raw = exc.read()
            finally:
                exc.close()
        except URLError as exc:
            raise CheckError(f"{method} {path}: request failed: {exc.reason}") from exc
        _require(
            status == expected_status,
            f"{method} {path}: expected HTTP {expected_status}, got {status}: "
            f"{raw.decode('utf-8', errors='replace')}",
        )
        try:
            result = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CheckError(f"{method} {path}: response is not valid JSON") from exc
        _require(isinstance(result, dict), f"{method} {path}: response must be an object")
        return result


def _edge(state: dict[str, Any], edge_id: str) -> dict[str, Any]:
    matches = [edge for edge in state["edges"] if edge["id"] == edge_id]
    _require(len(matches) == 1, f"expected exactly one edge {edge_id}")
    return matches[0]


def _expect_error(client: ApiClient, path: str, body: dict[str, Any], status: int, code: str) -> None:
    response = client.request("POST", path, body=body, expected_status=status)
    _require(response.get("error", {}).get("code") == code, f"{path}: expected error {code}")


def run_checks(client: ApiClient) -> None:
    """Modify a fresh disposable scenario and check the agreed demo sequence."""
    scenario = client.request("GET", "/scenario")
    _require(scenario.get("is_simulation") is True, "scenario must be marked as simulation")
    path = "/areas/area-a"
    state = client.request("GET", path + "/state")
    _require(state.get("is_simulation") is True, "area must be marked as simulation")
    _require(state.get("version") == 1, "expected a fresh disposable area at version 1")
    _require(state.get("scenario_time") == "2026-01-01T10:00:00Z", "unexpected initial scenario time")
    _require(state.get("current_result") is None and state.get("history") == [], "scenario already has routes")
    _require(
        {edge["id"] for edge in state["edges"]} == {"road-sa", "road-at", "road-sb", "road-bt"},
        "unexpected initial roads",
    )
    _require(all(edge["effective_status"] == "open" for edge in state["edges"]), "initial roads are not open")
    print("PASS: fresh simulated scenario")

    result = client.request("POST", path + "/routes", body={
        "expected_version": 1, "start_node_id": "S", "end_node_id": "T"
    })
    _require(result.get("version") == 2, "route request must advance version to 2")
    state = client.request("GET", path + "/state")
    route = state["current_result"]
    _require(
        route["status"] == "found" and route["edge_ids"] == ["road-sa", "road-at"]
        and route["distance_m"] == 2000,
        "initial route is not S-A-T / 2000 m",
    )
    print("PASS: initial candidate route")

    manual = {
        "expected_version": 2,
        "edge_id": "road-sa",
        "status": "reported_blocked",
        "source_id": "field-team-1",
        "source_name": "Simulated field team 1 via radio",
        "observed_at": "2026-01-01T10:00:00Z",
        "note": "Debris reported on road",
    }
    result = client.request("POST", path + "/reports", body=manual, expected_status=201)
    report_id = result.get("report_id")
    _require(result.get("version") == 3 and isinstance(report_id, str), "manual report was not saved")
    state = client.request("GET", path + "/state")
    _require(_edge(state, "road-sa")["effective_status"] == "blocked", "manual closure not applied")
    _require(
        state["current_result"]["edge_ids"] == ["road-sb", "road-bt"]
        and state["current_result"]["distance_m"] == 4000,
        "closure did not produce the 4000 m alternative",
    )
    _require(state["history"][-1]["edge_ids"] == ["road-sa", "road-at"], "previous route not preserved")
    _require(
        state["route_change"]["changed"] is True
        and state["route_change"]["affected_previous_route"] is True
        and state["route_change"]["trigger_report_id"] == report_id,
        "route change does not identify the manual report",
    )
    print("PASS: manual closure, rerouting and history")

    answer = client.request("POST", path + "/questions", body={
        "expected_version": 3, "question": "Why did the route change?"
    })
    _require(answer.get("intent") == "why_changed" and answer.get("answer"), "change question failed")
    _require(answer.get("version") == 3, "read-only question changed the version")

    update = client.request("POST", path + "/demo-advance", body={"expected_version": 3})
    _require(update.get("version") == 4 and update.get("scenario_time") == "2026-01-01T10:10:00Z",
             "unexpected simulated update")
    state = client.request("GET", path + "/state")
    _require(_edge(state, "road-sa")["effective_status"] == "conflict", "expected conflicting reports")
    _require(any(report["id"] == report_id for report in state["reports"]), "manual report disappeared")
    _require(
        state["current_result"]["edge_ids"] == ["road-sb", "road-bt"]
        and state["route_change"]["changed"] is False,
        "unchanged alternative was incorrectly reported as changed",
    )
    print("PASS: simulated external conflict preserves manual report")

    result = client.request("POST", path + "/reports", expected_status=201, body={
        "expected_version": 4,
        "edge_id": "road-bt",
        "status": "reported_suspected",
        "source_id": "field-team-1",
        "source_name": "Simulated field team 1 via radio",
        "observed_at": "2026-01-01T10:10:00Z",
        "note": "Road needs checking",
    })
    _require(result.get("version") == 5, "suspected report must advance version to 5")
    state = client.request("GET", path + "/state")
    _require(state["current_result"]["status"] == "no_path", "expected no candidate path")
    _require(state["current_result"]["edge_ids"] == [], "no_path must not contain edges")
    _require(state["history"][-1]["edge_ids"] == ["road-sb", "road-bt"], "alternative not in history")
    answer = client.request("POST", path + "/questions", body={
        "expected_version": 5, "question": "Which roads need checking?"
    })
    _require(answer.get("intent") == "needs_check" and answer.get("version") == 5, "checking question failed")
    _require({"road-sa", "road-bt"}.issubset(set(answer.get("related_edge_ids", []))),
             "answer does not identify both roads requiring checks")
    answer = client.request("POST", path + "/questions", body={
        "expected_version": 5, "question": "How can I get from Base S to Incident T?"
    })
    _require(answer.get("intent") == "route" and answer.get("version") == 6, "route question failed")
    _require(answer.get("answer") and answer.get("related_edge_ids") == [], "no-path answer is invalid")
    state = client.request("GET", path + "/state")
    _require(state["current_result"]["status"] == "no_path", "route question returned an unavailable path")
    print("PASS: no path and state-based questions")

    _expect_error(client, path + "/reports", manual, 409, "VERSION_CONFLICT")
    _expect_error(client, path + "/demo-advance", {"expected_version": 6}, 409, "DEMO_EXHAUSTED")
    invalid = dict(manual, expected_version=6, edge_id="road-missing")
    _expect_error(client, path + "/reports", invalid, 404, "EDGE_NOT_FOUND")
    _require(client.request("GET", path + "/state").get("version") == 6, "failed requests changed state")
    print("PASS: explicit errors and unchanged version")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000/api")
    parser.add_argument(
        "--confirm-disposable",
        action="store_true",
        help="confirm that the backend uses a fresh, disposable simulation database",
    )
    args = parser.parse_args()
    if not args.confirm_disposable:
        parser.error("this check modifies data; use --confirm-disposable only with a disposable database")
    try:
        run_checks(ApiClient(args.base_url))
    except (CheckError, KeyError, TypeError, IndexError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("Backend contract checks passed. This does not test the frontend.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

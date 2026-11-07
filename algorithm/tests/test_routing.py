import copy
import json
import random
import unittest
from pathlib import Path

from algorithm import find_route


FIXTURE = Path(__file__).resolve().parents[1] / "demo_scenario.json"


def exhaustive_distance(nodes, edges, start, end):
    """Independent exhaustive simple-path oracle for the small test graphs."""
    best = None

    def visit(current, seen, cost):
        nonlocal best
        if current == end:
            best = cost if best is None else min(best, cost)
            return
        for edge in edges:
            if (
                edge["effective_status"] == "open"
                and edge["from_node_id"] == current
                and edge["to_node_id"] not in seen
            ):
                visit(edge["to_node_id"], seen | {edge["to_node_id"]}, cost + edge["length_m"])

    visit(start, {start}, 0)
    return best


def dijkstra_distance(nodes, edges, start, end):
    """Reference Dijkstra implementation using a linear minimum search."""
    distances = {node["id"]: float("inf") for node in nodes}
    distances[start] = 0
    unsettled = set(distances)
    while unsettled:
        current = min(unsettled, key=lambda node_id: distances[node_id])
        unsettled.remove(current)
        if distances[current] == float("inf"):
            break
        if current == end:
            return distances[current]
        for edge in edges:
            if (
                edge["effective_status"] == "open"
                and edge["from_node_id"] == current
                and edge["to_node_id"] in unsettled
            ):
                target = edge["to_node_id"]
                distances[target] = min(distances[target], distances[current] + edge["length_m"])
    return None


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.scenario = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.nodes = self.scenario["nodes"]
        self.edges = self.scenario["edges"]

    def test_initial_and_blocked_routes(self):
        initial = find_route(self.nodes, self.edges, "S", "T")
        self.assertEqual(initial["node_ids"], ["S", "A", "T"])
        self.assertEqual(initial["edge_ids"], ["road-sa", "road-at"])
        self.assertEqual(initial["distance_m"], 2000)
        self.edges[0]["effective_status"] = "blocked"
        alternate = find_route(self.nodes, self.edges, "S", "T")
        self.assertEqual(alternate["node_ids"], ["S", "B", "T"])
        self.assertEqual(alternate["edge_ids"], ["road-sb", "road-bt"])
        self.assertEqual(alternate["distance_m"], 4000)

    def test_non_open_edges_are_never_used(self):
        for status in ("blocked", "suspected", "conflict", "unknown"):
            with self.subTest(status=status):
                for edge in self.edges:
                    edge["effective_status"] = status
                self.assertEqual(
                    find_route(self.nodes, self.edges, "S", "T"),
                    {"status": "no_path", "node_ids": [], "edge_ids": [], "distance_m": None},
                )

    def test_conflict_and_suspected_leave_no_path(self):
        self.edges[0]["effective_status"] = "conflict"
        self.edges[3]["effective_status"] = "suspected"
        self.assertEqual(find_route(self.nodes, self.edges, "S", "T")["status"], "no_path")

    def test_same_node_and_directed_edges(self):
        self.assertEqual(
            find_route(self.nodes, self.edges, "S", "S"),
            {"status": "found", "node_ids": ["S"], "edge_ids": [], "distance_m": 0},
        )
        self.assertEqual(find_route(self.nodes, self.edges, "T", "S")["status"], "no_path")

    def test_parallel_edges_and_zero_cost_cycle(self):
        nodes = [{"id": "S"}, {"id": "A"}, {"id": "T"}]
        edges = [
            {"id": "slow", "from_node_id": "S", "to_node_id": "A", "length_m": 5, "effective_status": "open"},
            {"id": "fast", "from_node_id": "S", "to_node_id": "A", "length_m": 0, "effective_status": "open"},
            {"id": "back", "from_node_id": "A", "to_node_id": "S", "length_m": 0, "effective_status": "open"},
            {"id": "end", "from_node_id": "A", "to_node_id": "T", "length_m": 1, "effective_status": "open"},
        ]
        route = find_route(nodes, edges, "S", "T")
        self.assertEqual(route["edge_ids"], ["fast", "end"])
        self.assertEqual(route["distance_m"], 1)

    def test_invalid_graph_raises_even_when_start_equals_end(self):
        bad_edges = []
        for value in (-1, float("inf"), float("nan"), True, "1000"):
            edge = copy.deepcopy(self.edges[0])
            edge["length_m"] = value
            bad_edges.append(edge)
        bad_edge = copy.deepcopy(self.edges[0])
        bad_edge["effective_status"] = "unrecognised"
        bad_edges.append(bad_edge)
        bad_edge = copy.deepcopy(self.edges[0])
        bad_edge["effective_status"] = []
        bad_edges.append(bad_edge)
        bad_edge = copy.deepcopy(self.edges[0])
        bad_edge["to_node_id"] = "missing"
        bad_edges.append(bad_edge)
        for edge in bad_edges:
            with self.subTest(edge=edge), self.assertRaises(ValueError):
                find_route(self.nodes, [edge], "S", "S")
        with self.assertRaises(ValueError):
            find_route(self.nodes, self.edges, "missing", "T")
        with self.assertRaises(ValueError):
            find_route(self.nodes + [self.nodes[0]], self.edges, "S", "T")
        with self.assertRaises(ValueError):
            find_route(self.nodes, self.edges + [self.edges[0]], "S", "T")

    def test_small_random_graphs_against_exhaustive_oracle(self):
        rng = random.Random(42)
        nodes = [{"id": str(i)} for i in range(5)]
        for case in range(100):
            edges = []
            for i in range(5):
                for j in range(5):
                    if i != j and rng.random() < 0.35:
                        edges.append({
                            "id": f"{i}-{j}",
                            "from_node_id": str(i),
                            "to_node_id": str(j),
                            "length_m": rng.randrange(6),
                            "effective_status": rng.choice(("open", "open", "blocked")),
                        })
            expected = exhaustive_distance(nodes, edges, "0", "4")
            dijkstra = dijkstra_distance(nodes, edges, "0", "4")
            actual = find_route(nodes, edges, "0", "4")
            with self.subTest(case=case):
                self.assertEqual(dijkstra, expected)
                self.assertEqual(actual["distance_m"], expected)
                self.assertEqual(actual["status"], "found" if expected is not None else "no_path")


if __name__ == "__main__":
    unittest.main()

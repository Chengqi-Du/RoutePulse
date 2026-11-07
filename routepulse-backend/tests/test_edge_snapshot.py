import sqlite3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "routepulse-backend"))

from app.database import _create_schema
from app.main import edge_snapshot


class EdgeSnapshotTests(unittest.TestCase):
    def test_merge_freshness_source_order_and_evidence(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        _create_schema(connection)
        connection.executemany(
            "INSERT INTO edges(id, area_id, from_node_id, to_node_id, length_m) VALUES (?, 'area-a', 'a', 'b', 1)",
            [(f"edge-{index}",) for index in range(11)],
        )
        reports = [
            ("seed-only", 0, "reported_open", "seed", "seed", "2024-01-02T09:59:00Z"),
            ("seed-superseded", 1, "reported_open", "seed", "seed", "2024-01-02T09:59:00Z"),
            ("stale-external", 1, "reported_blocked", "external_demo", "sat", "2024-01-02T08:00:00Z"),
            ("manual-stale-blocked", 2, "reported_blocked", "manual", "team", "2024-01-02T08:00:00Z"),
            ("manual-stale-suspected", 3, "reported_suspected", "manual", "team", "2024-01-02T08:00:00Z"),
            ("conflict-blocked", 4, "reported_blocked", "manual", "team", "2024-01-02T08:00:00Z"),
            ("conflict-open", 4, "reported_open", "external_demo", "sat", "2024-01-02T09:59:00Z"),
            ("old-manual", 5, "reported_blocked", "manual", "team", "2024-01-02T08:00:00Z"),
            ("new-manual", 5, "reported_open", "manual", "team", "2024-01-02T09:59:00Z"),
            ("future", 6, "reported_open", "external_demo", "sat", "2024-01-02T10:00:01Z"),
            ("tie-first", 7, "reported_open", "external_demo", "sat", "2024-01-02T09:59:00Z"),
            ("tie-second", 7, "reported_blocked", "external_demo", "sat", "2024-01-02T09:59:00Z"),
            ("old-seed", 8, "reported_open", "seed", "seed", "2024-01-02T09:29:59Z"),
            ("evidence-blocked", 9, "reported_blocked", "manual", "one", "2024-01-02T09:59:00Z"),
            ("evidence-open", 9, "reported_open", "external_demo", "sat", "2024-01-02T09:59:00Z"),
            ("evidence-suspected", 9, "reported_suspected", "manual", "two", "2024-01-02T09:59:00Z"),
            ("offset-boundary", 10, "reported_open", "external_demo", "sat", "2024-01-02T10:30:00+01:00"),
            ("offset-later", 10, "reported_blocked", "external_demo", "sat", "2024-01-02T09:45:00Z"),
            ("offset-older", 10, "reported_open", "external_demo", "sat", "2024-01-02T09:59:00+01:00"),
        ]
        connection.executemany(
            "INSERT INTO reports(id, edge_id, status, source_type, source_id, source_name, "
            "observed_at, recorded_at, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '')",
            [(report_id, f"edge-{edge}", status, source_type, source_id, source_id, observed, observed)
             for report_id, edge, status, source_type, source_id, observed in reports],
        )
        edges, payloads = edge_snapshot(connection, "area-a", "2024-01-02T10:00:00Z")
        self.assertEqual([edge["effective_status"] for edge in edges], [
            "open", "unknown", "blocked", "suspected", "conflict", "open",
            "unknown", "open", "unknown", "conflict", "blocked",
        ])
        self.assertEqual(edges[4]["evidence_report_ids"], ["conflict-blocked", "conflict-open"])
        self.assertEqual(edges[9]["evidence_report_ids"],
                         ["evidence-blocked", "evidence-open", "evidence-suspected"])
        by_id = {report["id"]: report for report in payloads}
        self.assertFalse(by_id["old-manual"]["is_latest_for_source"])
        self.assertTrue(by_id["new-manual"]["is_latest_for_source"])
        self.assertTrue(by_id["tie-first"]["is_latest_for_source"])
        self.assertFalse(by_id["tie-second"]["is_latest_for_source"])
        self.assertTrue(by_id["offset-boundary"]["is_fresh"])
        self.assertFalse(by_id["future"]["is_fresh"])
        self.assertTrue(by_id["offset-later"]["is_latest_for_source"])
        self.assertFalse(by_id["offset-older"]["is_latest_for_source"])


if __name__ == "__main__":
    unittest.main()

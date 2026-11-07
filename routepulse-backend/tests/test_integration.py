import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from algorithm.check_backend import ApiClient, run_checks


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "routepulse-backend"
SERVER = """
import inspect
import json
import socket

import uvicorn
from app.main import app, find_route, parse_question

listener = socket.socket()
listener.bind(("127.0.0.1", 0))
listener.listen()
print(json.dumps({
    "port": listener.getsockname()[1],
    "routing": inspect.getfile(find_route),
    "questions": inspect.getfile(parse_question),
}), flush=True)
server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
server.run(sockets=[listener])
"""


@contextmanager
def running_backend(cwd, pythonpath, *, db_path=None, extra_env=None):
    with tempfile.TemporaryDirectory(prefix="routepulse-integration-") as directory:
        db_path = db_path or Path(directory) / "scenario.sqlite3"
        env = os.environ.copy()
        for key in ("ROUTEPULSE_SCENARIO_MODE", "ROUTEPULSE_OSM_PATH", "ROUTEPULSE_DAY_TEMPLATES_PATH"):
            env.pop(key, None)
        env.update({
            "PYTHONPATH": str(pythonpath),
            "PYTHONDONTWRITEBYTECODE": "1",
            "ROUTEPULSE_DB_PATH": str(db_path),
        })
        if extra_env:
            env.update(extra_env)
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "-c", SERVER],
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=log,
                text=True,
            )
            try:
                assert process.stdout is not None
                line = process.stdout.readline()
                if not line:
                    log.seek(0)
                    raise RuntimeError(f"Backend failed to start:\n{log.read()}")
                server = json.loads(line)
                base_url = f"http://127.0.0.1:{server['port']}/api"
                deadline = time.monotonic() + 10
                while True:
                    try:
                        with urlopen(base_url + "/scenario", timeout=1) as response:
                            if response.status == 200:
                                break
                    except (URLError, ConnectionResetError):
                        if process.poll() is not None or time.monotonic() >= deadline:
                            log.seek(0)
                            raise RuntimeError(f"Backend did not become ready:\n{log.read()}")
                        time.sleep(0.05)
                yield ApiClient(base_url), db_path, server
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                if process.stdout is not None:
                    process.stdout.close()


def add_fractional_roads(db_path):
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.executemany(
            "INSERT INTO nodes(id, area_id, name, type, longitude, latitude) VALUES (?, ?, ?, ?, ?, ?)",
            [(node, "area-a", node, "junction", 0, 0) for node in ("X", "Y", "Z")],
        )
        edges = [
            ("test-xy", "area-a", "X", "Y", 1.9),
            ("test-yz", "area-a", "Y", "Z", 1.9),
            ("test-xz", "area-a", "X", "Z", 3.2),
        ]
        connection.executemany(
            "INSERT INTO edges(id, area_id, from_node_id, to_node_id, length_m) VALUES (?, ?, ?, ?, ?)",
            edges,
        )
        scenario_time = connection.execute(
            "SELECT scenario_time FROM area_state WHERE area_id = ?", ("area-a",)
        ).fetchone()[0]
        connection.executemany(
            "INSERT INTO reports(id, edge_id, status, source_type, source_id, source_name, "
            "observed_at, recorded_at, note) VALUES (?, ?, 'reported_open', 'seed', 'seed', "
            "'test seed', ?, ?, '')",
            [("seed-" + edge[0], edge[0], scenario_time, scenario_time) for edge in edges],
        )


class BackendIntegrationTests(unittest.TestCase):
    def exercise_backend(self, cwd, pythonpath):
        with running_backend(cwd, pythonpath) as (client, db_path, server):
            self.assertEqual(Path(server["routing"]).resolve(), ROOT / "algorithm" / "routing.py")
            self.assertEqual(Path(server["questions"]).resolve(), ROOT / "algorithm" / "questions.py")

            run_checks(client)
            path = "/areas/area-a"
            answer = client.request("POST", path + "/questions", body={
                "expected_version": 6,
                "question": "How can I get from S to T?",
            })
            self.assertEqual(answer["intent"], "route")
            self.assertEqual(answer["version"], 7)
            self.assertEqual(answer["related_edge_ids"], [])

            answer = client.request("POST", path + "/questions", body={
                "expected_version": 7,
                "question": "  Which   roads need checking？！ ",
            })
            self.assertEqual(answer["intent"], "needs_check")
            self.assertEqual(answer["version"], 7)

            add_fractional_roads(db_path)
            result = client.request("POST", path + "/routes", body={
                "expected_version": 7,
                "start_node_id": "X",
                "end_node_id": "Z",
            })
            self.assertEqual(result["version"], 8)
            route = client.request("GET", path + "/state")["current_result"]
            self.assertEqual(route["edge_ids"], ["test-xz"])
            self.assertEqual(route["distance_m"], 3.2)

            with closing(sqlite3.connect(db_path)) as connection, connection:
                connection.executemany(
                    "UPDATE edges SET length_m = ? WHERE id = ?",
                    [(0.1, "test-xy"), (0.2, "test-yz"), (0.30000000000000004, "test-xz")],
                )
            result = client.request("POST", path + "/routes", body={
                "expected_version": 8,
                "start_node_id": "X",
                "end_node_id": "Z",
            })
            self.assertEqual(result["version"], 9)
            route = client.request("GET", path + "/state")["current_result"]
            self.assertEqual(route["edge_ids"], ["test-xy", "test-yz"])
            self.assertEqual(route["distance_m"], 0.3)

    def test_from_backend_directory(self):
        self.exercise_backend(BACKEND, ROOT)

    def test_from_repository_root(self):
        self.exercise_backend(ROOT, BACKEND)


if __name__ == "__main__":
    unittest.main()

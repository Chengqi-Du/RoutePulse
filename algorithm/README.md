# RoutePulse algorithm and integration helpers

These modules are for the **simulation only**. They do not establish that a real
road is passable or safe and must not be used for real rescue navigation.

## Requirements and import

Python 3.10+; no third-party packages. Start the backend with the `RoutePulse/`
repository root on `PYTHONPATH`, then import:

```python
from algorithm import find_route, parse_question
```

`find_route(nodes, edges, start_node_id, end_node_id)` takes the node and edge
arrays from one evaluated API state snapshot. Each node needs `id`; each edge
needs `id`, `from_node_id`, `to_node_id`, `length_m`, and `effective_status`.
Extra API fields are harmless. Only `open` directed edges are eligible. The
algorithm is A* with `h=0`, which is equivalent to Dijkstra's search. It returns
the route result fields defined in the shared contract. Fractional lengths are
compared using their decimal values without intermediate floating-point
rounding. Invalid graph data raises `ValueError`; a valid graph without a route
returns `no_path`.

```python
result = find_route(nodes, edges, "S", "T")
```

`parse_question(question, locations)` accepts a mapping of display names or
aliases to node IDs. The backend should derive it from its actual nodes:

```python
locations = {node["name"]: node["id"] for node in nodes}
locations.update({node["id"]: node["id"] for node in nodes})
parsed = parse_question("How can I get from Base S to Incident T?", locations)
```

It returns an intent and optional node IDs, **not an answer or route**. Supported
sentences are those in the shared contract; unknown questions and names return
`unsupported`. Empty questions and invalid/ambiguous location mappings raise
`ValueError`. The backend must compute answers using the current snapshot.

## Fixture

`demo_scenario.json` supplies the exact simulated nodes, directed edges,
baseline report input, and one simulated external update from the shared
contract. It is not a complete HTTP state response: the backend must supply
server-generated fields such as `recorded_at`, derive freshness and road
status from reports, and manage versions, history and persistence. The
fixture's initial edge statuses are for algorithm tests, not evidence that
real roads are open.

## Run tests

From `RoutePulse/`:

```bash
python3 -m unittest discover -s algorithm/tests -v
```

The tests cover the demo, no path, directed and parallel edges, invalid input,
the supported questions, and 100 seeded small graphs checked against both an
independent Dijkstra implementation and an exhaustive simple-path oracle.

## Backend integration

1. Load a consistent state snapshot, evaluate the report rules in the backend,
   then call `find_route`; do not pass raw reports to the algorithm.
2. Save the returned route or `no_path`, history, trigger and version in the
   same backend transaction as the update.
3. Use `parse_question` only to determine intent and location IDs; answer from
   the current backend state. Unsupported questions must remain unsupported.
4. To check a running backend against the shared contract, start it using a
   **fresh, disposable** demo database, then from `RoutePulse/` run:

   ```bash
   python3 -m algorithm.check_backend --base-url http://localhost:8000/api --confirm-disposable
   ```

   This command writes simulated reports, route history and scenario time; it
   does not reset them. Never point it at someone else's data. It requires the
   initial fixture state at version 1 and exits nonzero on the first failure.
   The frontend still needs separate end-to-end testing.

The backend and frontend are not part of this directory; module tests do not
prove that their APIs or UI are integrated.

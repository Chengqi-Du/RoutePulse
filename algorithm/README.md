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

## OSM graph and seven-day simulation handoff

The backend and Integration use the same `build_graph` converter and the
repository's canonical `routepulse-backend/data/map.osm`. The backend's default
seven-day template is the checked-in `data/anamizu-demo/seven-day-scenario.json`.
The frontend displays the backend graph, while its separate local OSM
background is not authoritative. The export uses only
Python's standard library. From `RoutePulse/`:

```bash
python3 -m algorithm.prepare_osm routepulse-backend/data/map.osm --output-dir data/anamizu-new
```

The output directory must not already exist. The command never overwrites an
existing export. To use a team-selected start and destination, choose node IDs
from `graph.json` and create a **new** output directory:

```bash
python3 -m algorithm.prepare_osm routepulse-backend/data/map.osm \
  --output-dir data/anamizu-selected \
  --start-node osm-node-REAL_ID --end-node osm-node-REAL_ID
```

Replace both placeholders with actual IDs. If no pair is supplied, the tool
chooses a reproducible **provisional** pair near the graph's center and verifies
that a route and an alternative exist; these are not verified real facilities.
An unsuitable or disconnected chosen pair results in an explicit error.

The output directory contains:

| File | Purpose |
|---|---|
| `graph.json` | Versioned nodes and directed edges, lengths in meters, OSM tags and `[lon, lat]` GeoJSON lines. No inferred road-status claims. |
| `quality-report.json` | Input counts, source SHA-256, bounds, direction assumptions, incomplete turn-restriction references and warnings. |
| `roads-for-review.geojson` | OSM ways and their generated edge IDs for a local GIS viewer or the frontend team's map. |
| `way-review.csv` | Every exported way starts as `unreviewed`; reviewers record screenshot matches and notes. |
| `screenshot-inventory.csv` | Initially empty inventory: record each screenshot road segment, including missing or uncertain matches. |
| `seven-day-scenario.json` | Seven full daily sets of **fictional** external road observations. Images are `null`. |
| `demo-selection.json` | Simulated start/end and edges, plus the results of pure-routing snapshot checks. |

Review the screenshot by enumerating every visible white segment in
`screenshot-inventory.csv`, matching it to the GeoJSON and recording missing or
uncertain segments. Review colored main roads too. Cross-check with
`way-review.csv` and the frontend teammate; do not mark screenshot coverage
complete just because every exported OSM way is listed. Obtain appropriate OSM
data for missing areas and regenerate under a new graph version. The input
bounds alone do not prove the screenshot is covered; some OSM way nodes can
also lie outside the declared download bounds. For each screenshot segment,
use `matched`, `missing` or `uncertain` in `screenshot-inventory.csv`, and
include way/edge IDs when matched. In `way-review.csv`, use `matched`,
`not_visible`, `uncertain` or `unreviewed`; explain ambiguous cases in notes.

For a local visual aid, from `RoutePulse/` run
`python3 -m http.server 8765 --bind 127.0.0.1` and open
`http://127.0.0.1:8765/algorithm/road_review.html`. It loads the default
GeoJSON, permits selecting another export and displays a screenshot chosen
locally. Click an overlay to inspect the way and directed edge IDs, then record
the comparison in the CSV files. The screenshot is not georeferenced, uploaded,
or automatically interpreted. The map component and OSM tiles need network
access; stop the server when finished.

Each adjacent pair of OSM way nodes produces a directed edge for each permitted
simulation direction. OSM node IDs determine connectivity; visual crossings
are not automatically joined. IDs include a graph version derived from the
source bytes and conversion version, way ID, segment index and direction.
When changing any rule that affects graph contents, update the conversion
version so old templates and reports cannot silently refer to the changed graph.
Ordinary ways without `oneway` are assumed two-way; untagged motorways and
motorway links and roundabouts are assumed one-way. Explicit `oneway=-1`,
`yes` and `no` are respected. Conditional or mode-specific restrictions are
preserved but **not enforced**; turn restrictions and vehicle access are not
implemented. Highway areas are excluded and listed in the quality report.
`type: junction` denotes an OSM road node, not proof it is a physical junction.

All daily observations are scripted and include every exported directed edge.
The default `accessible_demo_v3` profile closes 95 of 2,540 physical segments
per day and changes the closed segments every day. It preserves all directed
reachability present in the original graph, but a manual report can still make
a route impossible. Generate a fresh copy without overwriting an existing file:

```bash
python3 -m algorithm.demo_scenario routepulse-backend/data/map.osm \
  --output data/anamizu-demo-new/seven-day-scenario.json
```

Create the parent output directory before running the command. The original
`data/anamizu-v2/seven-day-scenario.json` uses the `severe_damage_v2` profile,
which keeps **20–30% open** by physical segment
count, directed edge count, and physical road length each day; the rest are
blocked. At least 2% of physical segments reopen and another 2% newly close
between each consecutive pair of days. Both directions of a physical segment
share a status. Nearby consecutive pieces of an OSM way are grouped for
simulated closures; the locations and changes are fictional, not inferred from
real evidence. The first six days have a verified candidate route for the
provisional demo pair; Day 7 blocks all incoming edges to that destination
to demonstrate `no_path`.

The suggested Day 1 manual blocked report and Day 4 manual reopening must be
submitted through the backend; they are not fabricated external reports.
The pure-routing checks alone do not test backend report merging or HTTP.
Separate backend tests now exercise the checked-in seven-day file, manual
reports, failures and restart over HTTP. They do not test the product frontend.
The older `data/anamizu-v1` export is preserved as a legacy scenario and does
**not** satisfy the severe-damage requirements.

The seven-day map preview for the new
`data/anamizu-v2` export can be opened at
`http://127.0.0.1:8765/algorithm/seven_day_viewer.html` while the local HTTP
server above is running. It shows simulated open and blocked segments and
daily changes; it is not a satellite image and does not include manual reports.

Before importing a graph and template together, check their versions, daily
sequence, simulated flags and complete, unique edge observations:

```bash
python3 -m algorithm.validate_scenario \
  data/anamizu-v2/graph.json data/anamizu-v2/seven-day-scenario.json
```

The backend can also call `validate_seven_day_scenario(graph, scenario)` from
`algorithm.seven_day`; it raises `ValueError` on validation failure. Importers
still need to validate the graph's nodes, geometry and lengths independently.
Both profiles additionally check their respective percentages, consistent
directions, daily changes and summaries; `accessible_demo_v3` also validates
its connectivity guarantees. Preserve and check `scenario_version`
alongside `graph_version` when importing a scenario: the same road graph can
have different simulated scenarios.

OSM data and graph exports require appropriate OpenStreetMap attribution and
ODbL compliance; see https://www.openstreetmap.org/copyright. Object edit
timestamps do not establish the snapshot date. The OSM file is not verified as
a 2024 disaster-time network. Routes may contain footpaths or steps and must
never be represented as safe or suitable for real vehicles.

# OSM exercise map

`map.osm` is the OSM XML extract supplied for the Anamizu exercise and stored
with the backend so the offline importer can run without a network connection.
The application calculates a SHA-256 fingerprint and exposes it as
`graph_version`; it also reports the extract's declared bounds and available
object metadata.

The extract's bounds are 136.8958100–136.9237900 longitude and
37.2223700–37.2389600 latitude. Its file metadata does not provide a single
snapshot timestamp. The latest object edit timestamp is not the same as the
extract snapshot time. The importer currently sees 16,281 nodes, 2,602 ways,
465 highway ways and 2,527 highway segments before one-way expansion.

The map file is from OpenStreetMap contributors and is made available under the
Open Database License (ODbL). Credit OpenStreetMap contributors when displaying
or redistributing the map. See <https://www.openstreetmap.org/copyright> for
the attribution and license details.

The importer retains OSM highway tags and node-to-node geometry. It does not
verify that every road in the attached screenshot is covered, apply turn
restrictions, or infer earthquake damage, closures, or passability. All
conditions begin as `unknown`; only explicit simulated observations can change
them. Do not present these routes as real-world rescue navigation.

Two-way OSM segments become separate forward and reverse routing edges. A
simulated observation intended to close or open the physical segment in both
directions must include both edge IDs in `road_observations`; a one-way segment
has only its permitted direction. The edge IDs are returned by `/state` and are
bound to the `graph_version`.

The PRD assigns the seven-day observation frames to Integration. No frame file
was supplied with this backend task. Once received, place it here as
`day_templates.json` or configure `ROUTEPULSE_DAY_TEMPLATES_PATH`. It must bind
to the imported `graph_version` so observations cannot accidentally target a
different OSM extract.

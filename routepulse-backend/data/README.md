# OSM exercise map

`map.osm` is the canonical OSM XML source for the backend and Integration.
It is the supplied `rescue-route-map/map.osm`, copied here so a repository
checkout can import it offline. Its SHA-256 is
`3aadb5e0145bd091b9f981b9da28255e758c926f5efbee26cf36901d72d9bc08`.
Both components use `algorithm.osm_graph.build_graph`, which derives
`graph_version` and directed edge IDs from the source bytes and conversion
version. The checked-in `../../data/anamizu-v2` graph and scenario match it.
The separate frontend OSM file has not yet been unified.

The extract's declared bounds are 136.8982500–136.9262300 longitude and
37.2222500–37.2388400 latitude. Its file metadata does not provide a single
snapshot timestamp. The latest object edit timestamp is not the same as the
extract snapshot time. The current graph has 2,339 nodes and 4,993 directed
edges; highway areas are excluded.

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

The default frames are `../../data/anamizu-v2/seven-day-scenario.json`;
`ROUTEPULSE_DAY_TEMPLATES_PATH` selects an alternative. The template must bind
to the imported `graph_version` so observations cannot accidentally target a
different OSM extract. The frames are fictional simulations, not satellite
observations.

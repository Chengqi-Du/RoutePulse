OSM_XML = """\
<osm version="0.6">
  <bounds minlat="37.22" minlon="136.89" maxlat="37.24" maxlon="136.93"/>
  <node id="1" lat="37.2300" lon="136.9000" timestamp="2024-01-01T00:00:00Z"/>
  <node id="2" lat="37.2300" lon="136.9010"/>
  <node id="3" lat="37.2310" lon="136.9000"/>
  <node id="4" lat="37.2310" lon="136.9010" timestamp="2026-01-01T00:00:00Z"/>
  <node id="5" lat="37.2300" lon="136.9010"/>
  <node id="6" lat="37.2300" lon="136.9020"/>
  <node id="7" lat="37.2320" lon="136.9020"/>
  <way id="10"><nd ref="1"/><nd ref="2"/><nd ref="4"/><tag k="highway" v="residential"/></way>
  <way id="11"><nd ref="1"/><nd ref="3"/><nd ref="4"/><tag k="highway" v="footway"/></way>
  <way id="12"><nd ref="5"/><nd ref="6"/><tag k="highway" v="path"/><tag k="oneway" v="-1"/></way>
  <way id="13"><nd ref="6"/><nd ref="7"/><tag k="highway" v="motorway_link"/></way>
  <way id="14"><nd ref="6"/><nd ref="7"/><tag k="highway" v="motorway"/><tag k="oneway" v="no"/></way>
  <way id="15"><nd ref="1"/><nd ref="3"/><nd ref="4"/><nd ref="1"/><tag k="highway" v="pedestrian"/><tag k="area" v="yes"/></way>
  <relation id="20"><member type="way" ref="10" role="from"/><member type="way" ref="999" role="to"/><tag k="type" v="restriction"/></relation>
</osm>
"""


def demo_osm_xml():
    extra = []
    for index in range(70):
        first = 1000 + index * 2
        second = first + 1
        lat = 37.220 + index * 0.0001
        extra.append(f'<node id="{first}" lat="{lat}" lon="136.9000"/>')
        extra.append(f'<node id="{second}" lat="{lat}" lon="136.9010"/>')
        extra.append(
            f'<way id="{2000 + index}"><nd ref="{first}"/><nd ref="{second}"/>'
            '<tag k="highway" v="residential"/></way>'
        )
    return OSM_XML.replace("</osm>", "\n".join(extra) + "\n</osm>")

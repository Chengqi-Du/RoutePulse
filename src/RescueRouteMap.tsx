import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { GeoJsonObject } from 'geojson'
import type { AreaState, Edge, EffectiveStatus, Node } from './api'
import mapUrl from './map.osm?url'
import { renderOsm } from './osmMap'

const colors: Record<EffectiveStatus, string> = {
  open: '#208258', blocked: '#c83e49', suspected: '#d4871e', conflict: '#9b44a8', unknown: '#6f7a86',
}

function edgePoints(edge: Edge, nodes: Map<string, Node>): L.LatLngExpression[] {
  const coordinates = edge.geometry?.coordinates || [nodes.get(edge.from_node_id)?.coordinates, nodes.get(edge.to_node_id)?.coordinates]
  return coordinates.filter((point): point is [number, number] => !!point).map(([longitude, latitude]) => [latitude, longitude])
}

export default function RescueRouteMap({ state, selectedEdge, onSelectEdge, choices }: {
  state: AreaState; selectedEdge: string; onSelectEdge: (id: string) => void; choices: Node[]
}) {
  const element = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const boundsRef = useRef<L.LatLngBounds | null>(null)
  const boundaryRef = useRef<L.GeoJSON | null>(null)
  const [boundaryReady, setBoundaryReady] = useState(false)
  const [mapStatus, setMapStatus] = useState('Loading local OSM map…')
  const [boundaryStatus, setBoundaryStatus] = useState('')

  useEffect(() => {
    if (!element.current) return
    const controller = new AbortController()
    const map = L.map(element.current).setView([37.23111, 136.90830], 16)
    mapRef.current = map
    map.createPane('network').style.zIndex = '450'
    map.createPane('routeHighlight').style.zIndex = '460'
    map.attributionControl.addAttribution('&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>')
    L.control.scale({ imperial: false }).addTo(map)
    fetch(mapUrl, { signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error(); return response.text() })
      .then(xml => { if (!controller.signal.aborted) { renderOsm(xml, map); setMapStatus('') } })
      .catch(() => { if (!controller.signal.aborted) setMapStatus('The local OSM background could not be loaded.') })
    fetch(`${import.meta.env.BASE_URL}src/rescue-route-map/data/anamizu-boundary.geojson`, { signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error(); return response.json() as Promise<GeoJsonObject> })
      .then(data => {
        if (controller.signal.aborted) return
        const boundary = L.geoJSON(data, { style: { color: '#b02035', weight: 3, opacity: 0.9, dashArray: '8 6' }, interactive: false })
        if (!boundary.getBounds().isValid()) throw new Error()
        boundary.addTo(map); boundaryRef.current = boundary
        L.control.layers(undefined, { 'Anamizu boundary': boundary }).addTo(map); setBoundaryReady(true)
      })
      .catch(() => { if (!controller.signal.aborted) setBoundaryStatus('The Anamizu boundary could not be loaded.') })
    return () => { controller.abort(); map.remove(); mapRef.current = null; boundsRef.current = null; boundaryRef.current = null }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const bounds = L.latLngBounds(state.nodes.map(node => [node.coordinates[1], node.coordinates[0]] as L.LatLngExpression))
    if (bounds.isValid()) { boundsRef.current = bounds; map.fitBounds(bounds, { padding: [20, 20] }) }
  }, [state.area_id, state.nodes.length])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const nodes = new Map(state.nodes.map(node => [node.id, node]))
    const renderer = L.canvas({ padding: 0.5, pane: 'network' })
    const layer = L.layerGroup().addTo(map)
    for (const edge of state.edges) {
      const points = edgePoints(edge, nodes)
      if (points.length < 2) continue
      L.polyline(points, { renderer, color: colors[edge.effective_status], weight: 4, opacity: 0.85 })
        .on('click', () => onSelectEdge(edge.id)).addTo(layer)
    }
    for (const node of choices) {
      L.circleMarker([node.coordinates[1], node.coordinates[0]], { pane: 'routeHighlight', radius: 4, color: '#1e405e', fillColor: '#fff', fillOpacity: 1, weight: 2, interactive: false }).addTo(layer)
    }
    return () => { layer.remove(); renderer.remove() }
  }, [state.nodes, state.edges, choices, onSelectEdge])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const nodes = new Map(state.nodes.map(node => [node.id, node]))
    const layer = L.layerGroup().addTo(map)
    const routeIds = new Set(state.current_result?.edge_ids || [])
    for (const edge of state.edges) {
      if (!routeIds.has(edge.id) && edge.id !== selectedEdge) continue
      const points = edgePoints(edge, nodes)
      if (points.length < 2) continue
      L.polyline(points, { pane: 'routeHighlight', color: edge.id === selectedEdge ? '#ffe400' : '#1268ed', weight: edge.id === selectedEdge ? 8 : 6, opacity: 0.95, interactive: false }).addTo(layer)
    }
    return () => { layer.remove() }
  }, [state.nodes, state.edges, state.current_result, selectedEdge])

  return <section className="map-frame route-map-frame" aria-label="Exercise road network map">
    <div className="map-toolbar"><div><span className="eyebrow">SIMULATED ROAD NETWORK</span><p>Click a road to report it. Colors show directed road status; blue is the candidate route, yellow is selected. Two directions may overlap.</p><p>Green: open · red: blocked · orange: suspected · purple: conflict · gray: unknown.</p></div><div className="map-actions"><button type="button" onClick={() => { if (mapRef.current && boundsRef.current) mapRef.current.fitBounds(boundsRef.current, { padding: [20, 20] }) }}>Reset view</button><button type="button" onClick={() => { if (mapRef.current && boundaryRef.current) { boundaryRef.current.addTo(mapRef.current); mapRef.current.fitBounds(boundaryRef.current.getBounds(), { padding: [20, 20] }) } }} disabled={!boundaryReady}>Show boundary</button></div></div>
    {(mapStatus || boundaryStatus) && <p className="map-status" role="status">{mapStatus} {boundaryStatus}</p>}
    <div ref={element} className="leaflet-map rescue-leaflet-map" aria-label="Road network with simulated statuses" />
  </section>
}

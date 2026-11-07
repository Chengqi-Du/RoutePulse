import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { GeoJsonObject } from 'geojson'
import mapUrl from './map.osm?url'
import { renderOsm } from './osmMap'

const center: L.LatLngExpression = [37.23111, 136.90830]
const zoom = 16

export default function RescueRouteMap() {
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
    const map = L.map(element.current).setView(center, zoom)
    mapRef.current = map
    map.attributionControl.addAttribution('&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>')
    L.control.scale({ imperial: false }).addTo(map)

    fetch(mapUrl, { signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.text() })
      .then(xml => {
        if (controller.signal.aborted) return
        const bounds = renderOsm(xml, map)
        boundsRef.current = bounds
        map.fitBounds(bounds, { padding: [20, 20] })
        setMapStatus('')
      })
      .catch(() => { if (!controller.signal.aborted) setMapStatus('The local OSM map could not be loaded or rendered.') })

    fetch(`${import.meta.env.BASE_URL}src/rescue-route-map/data/anamizu-boundary.geojson`, { signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json() as Promise<GeoJsonObject> })
      .then(data => {
        if (controller.signal.aborted) return
        const boundary = L.geoJSON(data, { style: { color: '#b02035', weight: 3, opacity: 0.9, dashArray: '8 6' } })
        if (!boundary.getBounds().isValid()) throw new Error('Invalid boundary')
        boundary.addTo(map)
        boundaryRef.current = boundary
        L.control.layers(undefined, { 'Anamizu boundary': boundary }).addTo(map)
        setBoundaryReady(true)
      })
      .catch(() => { if (!controller.signal.aborted) setBoundaryStatus('The Anamizu boundary could not be loaded.') })

    return () => { controller.abort(); map.remove(); mapRef.current = null; boundsRef.current = null; boundaryRef.current = null }
  }, [])

  function showBoundary() {
    if (!mapRef.current || !boundaryRef.current) return
    boundaryRef.current.addTo(mapRef.current)
    mapRef.current.fitBounds(boundaryRef.current.getBounds(), { padding: [20, 20] })
  }

  return <section className="map-frame route-map-frame" aria-label="Anamizu rescue area map">
    <div className="map-toolbar"><div><span className="eyebrow">ANAMIZU / LOCAL OSM MAP</span><p>Local OpenStreetMap extract, not live or 2024 road conditions. Mock routes and reports are not shown on this map.</p></div><div className="map-actions"><button type="button" onClick={() => { if (mapRef.current && boundsRef.current) mapRef.current.fitBounds(boundsRef.current, { padding: [20, 20] }) }}>Reset view</button><button type="button" onClick={showBoundary} disabled={!boundaryReady}>Show boundary</button></div></div>
    {(mapStatus || boundaryStatus) && <p className="map-status" role="status">{mapStatus} {boundaryStatus}</p>}
    <div ref={element} className="leaflet-map rescue-leaflet-map" aria-label="Anamizu local OpenStreetMap extract" />
  </section>
}

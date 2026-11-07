import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import DOMPurify from 'dompurify'
import 'leaflet/dist/leaflet.css'
import type { GeoJsonObject } from 'geojson'

const layers = [
  ['Emergency restored sections', 'emergency_restored_section', true, 0],
  ['Recovery points', 'recovery_point', true, 0],
  ['Damage and recovery comparison', 'keikai', true, 8000],
  ['Recovery aerial photography', 'recovery_situation_aerial_photography', true, 7000],
  ['Restored road usage', 'riyou', true, 9000],
  ['Roadside station status', 'michinoeki', false, 6000],
  ['Road clearance videos', 'douga', false, 5000],
  ['Municipal road investigation', 'municipal_road_investigation', false, 4000],
  ['Major damaged locations', 'damaged_area', false, 3000],
  ['Damage 360° images and 3D data', 'spherical_image', false, 3000],
  ['Damage aerial photography', 'damage_situation_aerial_photography', false, 2000],
  ['Intercity travel times', 'intercity_travel_time', false, 10000],
  ['ETC2.0 average speed', 'ETC2.0_speed_data', false, 0],
  ['Population mesh', 'population_mesh_data', false, 0],
] as const

const assetRoot = `${import.meta.env.BASE_URL}src/noto-road-map/`

function propertiesToOptions(properties: Record<string, unknown>) {
  return Object.fromEntries(Object.entries(properties)
    .filter(([key]) => key.startsWith('_') && key !== '_markerType' && !(properties._markerType === 'Circle' && key === '_radius'))
    .map(([key, value]) => [key.slice(1), value]))
}

function popupContent(properties: Record<string, unknown>) {
  const content = document.createElement('div')
  for (const [key, value] of Object.entries(properties)) {
    if (key.startsWith('_')) continue
    const row = document.createElement('div')
    const label = document.createElement('strong')
    label.textContent = `${key}: `
    row.append(label)
    const detail = document.createElement('span')
    detail.innerHTML = DOMPurify.sanitize(String(value ?? ''), { ADD_TAGS: ['iframe'], ADD_ATTR: ['allow', 'allowfullscreen', 'frameborder'] })
    detail.querySelectorAll('[src], [href]').forEach(node => {
      for (const attribute of ['src', 'href']) {
        const value = node.getAttribute(attribute)
        if (value?.startsWith('./img/')) node.setAttribute(attribute, `${assetRoot}${value.slice(2)}`)
      }
    })
    detail.querySelectorAll('iframe').forEach(frame => {
      try {
        const url = new URL(frame.src)
        if (url.protocol !== 'https:' || !['www.youtube.com', 'www.youtube-nocookie.com'].includes(url.hostname) || !url.pathname.startsWith('/embed/')) frame.remove()
        else { frame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-presentation'); frame.title ||= 'Historical road clearance video' }
      } catch { frame.remove() }
    })
    row.append(detail)
    content.append(row)
  }
  return content
}

export default function NotoRoadMap() {
  const element = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState('Loading historical road layers…')
  const [tileError, setTileError] = useState(false)

  useEffect(() => {
    if (!element.current) return
    const controller = new AbortController()
    const map = L.map(element.current).setView([37.282030, 137.000610], 10)
    const base = L.tileLayer('https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png', {
      attribution: '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noopener noreferrer">Geospatial Information Authority of Japan</a>',
      maxNativeZoom: 18, maxZoom: 18,
    }).addTo(map)
    base.on('tileerror', () => setTileError(true))
    const photo = L.tileLayer('https://cyberjapandata.gsi.go.jp/xyz/20240102noto_0405_0426do/{z}/{x}/{y}.png', { maxNativeZoom: 18, maxZoom: 18 })
    const layerControl = L.control.layers({ 'GSI standard map': base }, { 'Aerial imagery (April 5–26, 2024)': photo }, { collapsed: true, autoZIndex: false }).addTo(map)
    L.control.scale({ imperial: false }).addTo(map)

    Promise.allSettled(layers.map(async ([name, file, checked, zIndex], index) => {
      const response = await fetch(`${assetRoot}json/${file}.geojson`, { signal: controller.signal })
      if (!response.ok) throw new Error(name)
      const data = await response.json() as GeoJsonObject
      if (controller.signal.aborted) return
      const layer = L.geoJSON(data, {
        pointToLayer(feature, latlng) {
          const properties = (feature.properties || {}) as Record<string, unknown>
          const options = propertiesToOptions(properties)
          if (properties._markerType === 'Icon') return L.marker(latlng, { icon: L.icon(options as unknown as L.IconOptions), zIndexOffset: zIndex })
          if (properties._markerType === 'DivIcon') return L.marker(latlng, { icon: L.divIcon(options as L.DivIconOptions), zIndexOffset: zIndex })
          if (properties._markerType === 'Circle') return L.circle(latlng, { ...options, radius: Number(properties._radius) } as L.CircleMarkerOptions & { radius: number })
          return L.circleMarker(latlng, options as L.CircleMarkerOptions)
        },
        style(feature) { return propertiesToOptions((feature?.properties || {}) as Record<string, unknown>) as L.PathOptions },
        onEachFeature(feature, featureLayer) { featureLayer.bindPopup(() => popupContent((feature.properties || {}) as Record<string, unknown>)) },
      })
      layerControl.addOverlay(layer, `${String(index + 1).padStart(2, '0')}. ${name}`)
      if (checked) layer.addTo(map)
    })).then(results => {
      if (controller.signal.aborted) return
      const failed = results.filter(result => result.status === 'rejected').length
      setStatus(failed ? `${failed} historical map layer(s) could not be loaded.` : '')
    })
    return () => { controller.abort(); map.remove() }
  }, [])

  return <section className="map-frame overview-map-frame" aria-label="Noto historical road recovery map">
    <div className="map-toolbar"><div><span className="eyebrow">NOTO / HISTORICAL DISASTER MAP</span><p>Historical 2024 earthquake and recovery data, not live conditions. Independent of the simulated exercise.</p></div></div>
    {(status || tileError) && <p className="map-status" role="status">{status} {tileError && 'Some map tiles could not be loaded. Check your connection.'}</p>}
    <div ref={element} className="leaflet-map noto-leaflet-map" aria-label="Noto historical road recovery map" />
  </section>
}

import L from 'leaflet'

type Tags = Record<string, string>
type Way = { refs: string[]; tags: Tags }
type FeatureStyle = { order: number; style: L.PathOptions; area: boolean }

function tagsOf(element: Element): Tags {
  return Object.fromEntries(Array.from(element.children)
    .filter(child => child.tagName === 'tag')
    .map(tag => [tag.getAttribute('k') || '', tag.getAttribute('v') || '']))
}

function featureStyle(tags: Tags, closed: boolean): FeatureStyle | null {
  const area = closed && tags.area !== 'no'
  if (area && (tags.natural === 'water' || tags.waterway === 'riverbank' || tags.landuse === 'reservoir')) return { order: 0, area, style: { color: '#91b9c9', weight: 1, fillColor: '#a7cbd8', fillOpacity: 1 } }
  if (area && (tags.natural === 'wood' || tags.landuse === 'forest')) return { order: 0, area, style: { color: '#b8ccad', weight: 1, fillColor: '#c5d9bb', fillOpacity: 1 } }
  if (area && ['grass', 'farmland', 'meadow', 'orchard'].includes(tags.landuse)) return { order: 0, area, style: { color: '#d1dcc2', weight: 1, fillColor: '#dfe9d2', fillOpacity: 1 } }
  if (area && (tags.building || tags['building:part'])) return { order: 1, area, style: { color: '#b4aaa0', weight: 1, fillColor: '#d4c9bd', fillOpacity: 1 } }
  if (area && (tags.amenity === 'parking' || tags.highway === 'pedestrian')) return { order: 1, area, style: { color: '#d0cdc4', weight: 1, fillColor: '#e5e2d9', fillOpacity: 1 } }
  if (tags.waterway) return { order: 2, area: false, style: { color: '#8eb8c9', weight: tags.waterway === 'river' ? 3 : 1.5 } }
  if (tags.natural === 'coastline') return { order: 2, area: false, style: { color: '#83aab8', weight: 2 } }
  if (tags.railway && !['platform', 'station'].includes(tags.railway)) return { order: 3, area: false, style: { color: '#858482', weight: 2, dashArray: '5 5' } }
  if (tags.highway) {
    const major = ['motorway', 'trunk', 'primary', 'secondary'].includes(tags.highway)
    const minor = ['footway', 'path', 'steps', 'track', 'cycleway'].includes(tags.highway)
    return { order: 4, area: false, style: { color: major ? '#e5ab6a' : minor ? '#c1b6a8' : '#fff', weight: major ? 4 : minor ? 1.5 : 2.5, ...(minor ? { dashArray: '4 3' } : {}) } }
  }
  return null
}

function joinRings(parts: string[][]): string[][] {
  const pending = parts.map(part => [...part])
  const rings: string[][] = []
  while (pending.length) {
    const ring = pending.pop()!
    let joined = true
    while (ring[0] !== ring[ring.length - 1] && joined) {
      joined = false
      const end = ring[ring.length - 1]
      const index = pending.findIndex(part => part[0] === end || part[part.length - 1] === end)
      if (index >= 0) {
        const part = pending.splice(index, 1)[0]
        if (part[part.length - 1] === end) part.reverse()
        ring.push(...part.slice(1))
        joined = true
      }
    }
    if (ring.length >= 4 && ring[0] === ring[ring.length - 1]) rings.push(ring)
  }
  return rings
}

function contains(ring: L.LatLngExpression[], point: L.LatLngExpression): boolean {
  const vertices = ring.map(vertex => L.latLng(vertex))
  const target = L.latLng(point)
  let inside = false
  for (let index = 0, previous = vertices.length - 1; index < vertices.length; previous = index++) {
    const a = vertices[index], b = vertices[previous]
    if ((a.lat > target.lat) !== (b.lat > target.lat) && target.lng < (b.lng - a.lng) * (target.lat - a.lat) / (b.lat - a.lat) + a.lng) inside = !inside
  }
  return inside
}

export function renderOsm(xml: string, map: L.Map): L.LatLngBounds {
  const document = new DOMParser().parseFromString(xml, 'application/xml')
  if (document.querySelector('parsererror') || document.documentElement.tagName !== 'osm') throw new Error('Invalid OSM XML')
  const boundsElement = document.querySelector('osm > bounds')
  if (!boundsElement) throw new Error('OSM bounds are missing')
  const boundsValues = ['minlat', 'minlon', 'maxlat', 'maxlon'].map(name => Number(boundsElement.getAttribute(name)))
  if (boundsValues.some(value => !Number.isFinite(value))) throw new Error('Invalid OSM bounds')
  const bounds = L.latLngBounds([boundsValues[0], boundsValues[1]], [boundsValues[2], boundsValues[3]])
  const nodes = new Map<string, L.LatLngExpression>()
  const labels: { position: L.LatLngExpression; name: string }[] = []
  for (const node of document.querySelectorAll('osm > node')) {
    const id = node.getAttribute('id'), lat = Number(node.getAttribute('lat')), lon = Number(node.getAttribute('lon'))
    if (id && Number.isFinite(lat) && Number.isFinite(lon)) {
      const position: L.LatLngExpression = [lat, lon]
      nodes.set(id, position)
      if (node.children.length) {
        const tags = tagsOf(node)
        if (tags.name && (tags.place || tags.railway === 'station' || ['hospital', 'school', 'police', 'townhall'].includes(tags.amenity))) labels.push({ position, name: tags['name:en'] || tags.name })
      }
    }
  }
  const ways = new Map<string, Way>()
  for (const way of document.querySelectorAll('osm > way')) {
    const id = way.getAttribute('id')
    if (id) ways.set(id, { refs: Array.from(way.querySelectorAll(':scope > nd'), node => node.getAttribute('ref') || ''), tags: tagsOf(way) })
  }
  const coordinates = (refs: string[]): L.LatLngExpression[] | null => {
    const result = refs.map(ref => nodes.get(ref))
    return result.every((point): point is L.LatLngExpression => point !== undefined) ? result : null
  }
  const renderer = L.canvas({ padding: 0.5 })
  const layers: { order: number; layer: L.Path }[] = []
  for (const way of ways.values()) {
    const closed = way.refs.length >= 4 && way.refs[0] === way.refs[way.refs.length - 1]
    const feature = featureStyle(way.tags, closed), points = coordinates(way.refs)
    if (!feature || !points || points.length < 2) continue
    const options = { ...feature.style, renderer, interactive: false }
    layers.push({ order: feature.order, layer: feature.area ? L.polygon(points, options) : L.polyline(points, options) })
  }
  for (const relation of document.querySelectorAll('osm > relation')) {
    const tags = tagsOf(relation)
    if (tags.type !== 'multipolygon') continue
    const feature = featureStyle(tags, true)
    if (!feature?.area) continue
    const members = Array.from(relation.querySelectorAll(':scope > member')).filter(member => member.getAttribute('type') === 'way')
    const ringsFor = (role: string) => joinRings(members.filter(member => (member.getAttribute('role') || 'outer') === role).map(member => ways.get(member.getAttribute('ref') || '')?.refs).filter((refs): refs is string[] => !!refs))
      .map(coordinates).filter((ring): ring is L.LatLngExpression[] => ring !== null)
    const outer = ringsFor('outer'), inner = ringsFor('inner')
    for (const ring of outer) layers.push({ order: feature.order, layer: L.polygon([ring, ...inner.filter(hole => contains(ring, hole[0]))], { ...feature.style, renderer, interactive: false }) })
  }
  if (!layers.length) throw new Error('No supported map features found')
  layers.sort((first, second) => first.order - second.order).forEach(({ layer }) => layer.addTo(map))
  for (const label of labels) {
    const text = window.document.createElement('span')
    text.textContent = label.name
    L.marker(label.position, { interactive: false, keyboard: false, icon: L.divIcon({ className: 'osm-map-label', html: text, iconSize: [0, 0] }) }).addTo(map)
  }
  return bounds
}

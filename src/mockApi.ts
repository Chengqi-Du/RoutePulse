export type NodeId = 'S' | 'A' | 'B' | 'T'
export type ReportStatus = 'reported_open' | 'reported_blocked' | 'reported_suspected'
export type EffectiveStatus = 'open' | 'blocked' | 'suspected' | 'conflict' | 'unknown'
export type Report = {
  id: string; edge_id: string; status: ReportStatus; source_type: 'seed' | 'manual' | 'external_demo'
  source_id: string; source_name: string; observed_at: string; recorded_at: string; note: string
  is_latest_for_source: boolean; is_fresh: boolean
}
export type Edge = { id: string; from_node_id: NodeId; to_node_id: NodeId; length_m: number; effective_status: EffectiveStatus }
export type Route = {
  id: string; status: 'found' | 'no_path'; start_node_id: NodeId; end_node_id: NodeId
  node_ids: NodeId[]; edge_ids: string[]; distance_m: number | null; computed_at: string
  trigger: { type: 'user_request' | 'manual_report' | 'demo_update'; report_id: string | null }
}
export type AreaState = { version: number; scenario_time: string; edges: Edge[]; reports: Report[]; current_route: Route | null; route_history: Route[]; demo_advanced: boolean }
export type ManualReport = { edge_id: string; status: ReportStatus; source_id: string; source_name: string; observed_at: string; note: string }

export const nodes: { id: NodeId; name: string }[] = [
  { id: 'S', name: 'Base S' }, { id: 'A', name: 'Junction A' },
  { id: 'B', name: 'Junction B' }, { id: 'T', name: 'Incident T' },
]
export const reportLabels: Record<ReportStatus, string> = {
  reported_open: 'Reported open', reported_blocked: 'Reported blocked', reported_suspected: 'Reported suspected',
}
export const statusLabels: Record<EffectiveStatus, string> = {
  open: 'Open', blocked: 'Blocked', suspected: 'Suspected', conflict: 'Conflict', unknown: 'Unknown',
}

const startTime = '2026-01-01T10:00:00Z'
const edges: Edge[] = [
  { id: 'road-sa', from_node_id: 'S', to_node_id: 'A', length_m: 1000, effective_status: 'open' },
  { id: 'road-at', from_node_id: 'A', to_node_id: 'T', length_m: 1000, effective_status: 'open' },
  { id: 'road-sb', from_node_id: 'S', to_node_id: 'B', length_m: 2000, effective_status: 'open' },
  { id: 'road-bt', from_node_id: 'B', to_node_id: 'T', length_m: 2000, effective_status: 'open' },
]
const initialReports: Report[] = edges.map((edge, index) => ({
  id: `report-00${index + 1}`, edge_id: edge.id, status: 'reported_open', source_type: 'seed',
  source_id: 'initial-exercise', source_name: 'Initial simulated exercise data', observed_at: startTime,
  recorded_at: startTime, note: '', is_latest_for_source: true, is_fresh: true,
}))
let state: AreaState = { version: 1, scenario_time: startTime, edges, reports: initialReports, current_route: null, route_history: [], demo_advanced: false }
let sequence = 5

function snapshot(): AreaState { return structuredClone(state) }
function checkVersion(version: number) {
  if (version !== state.version) throw new Error('VERSION_CONFLICT: The area state changed. Refresh and try again.')
}
function updateEdges() {
  state.reports = state.reports.map(report => ({ ...report,
    is_fresh: Date.parse(state.scenario_time) - Date.parse(report.observed_at) <= 30 * 60 * 1000,
    is_latest_for_source: !state.reports.some(other => other.edge_id === report.edge_id && other.source_id === report.source_id && (other.observed_at > report.observed_at || (other.observed_at === report.observed_at && other.id > report.id))),
  }))
  state.edges = state.edges.map(edge => {
    const active = state.reports.filter(report => report.edge_id === edge.id && report.is_latest_for_source)
    const concerns = active.filter(report => report.status !== 'reported_open' && (report.is_fresh || report.source_type === 'manual'))
    const opens = active.filter(report => report.status === 'reported_open' && report.is_fresh)
    const newestConcern = concerns.reduce((latest, report) => Math.max(latest, Date.parse(report.observed_at)), -Infinity)
    const hasNewerOpen = opens.some(report => Date.parse(report.observed_at) > newestConcern)
    let effective_status: EffectiveStatus = 'unknown'
    if (concerns.length && hasNewerOpen) effective_status = 'conflict'
    else if (concerns.some(report => report.status === 'reported_blocked')) effective_status = 'blocked'
    else if (concerns.length) effective_status = 'suspected'
    else if (opens.length) effective_status = 'open'
    return { ...edge, effective_status }
  })
}
function compute(start: NodeId, end: NodeId, trigger: Route['trigger']): Route {
  const pending: { node: NodeId; distance: number; path: NodeId[]; roads: string[] }[] = [{ node: start, distance: 0, path: [start], roads: [] }]
  const visited = new Set<NodeId>()
  while (pending.length) {
    pending.sort((left, right) => left.distance - right.distance)
    const current = pending.shift()!
    if (visited.has(current.node)) continue
    visited.add(current.node)
    if (current.node === end) return { id: `route-${sequence++}`, status: 'found', start_node_id: start, end_node_id: end, node_ids: current.path, edge_ids: current.roads, distance_m: current.distance, computed_at: state.scenario_time, trigger }
    state.edges.filter(edge => edge.from_node_id === current.node && edge.effective_status === 'open').forEach(edge => pending.push({ node: edge.to_node_id, distance: current.distance + edge.length_m, path: [...current.path, edge.to_node_id], roads: [...current.roads, edge.id] }))
  }
  return { id: `route-${sequence++}`, status: 'no_path', start_node_id: start, end_node_id: end, node_ids: [], edge_ids: [], distance_m: null, computed_at: state.scenario_time, trigger }
}
function saveRoute(route: Route) {
  if (state.current_route) state.route_history = [state.current_route, ...state.route_history]
  state.current_route = route
}
function recalculate(trigger: Route['trigger']) {
  if (state.current_route) saveRoute(compute(state.current_route.start_node_id, state.current_route.end_node_id, trigger))
}
function addReport(report: Omit<Report, 'id' | 'recorded_at' | 'is_latest_for_source' | 'is_fresh'>) {
  const id = `report-${String(sequence++).padStart(3, '0')}`
  state.reports = [...state.reports, { ...report, id, recorded_at: new Date().toISOString(), is_latest_for_source: true, is_fresh: true }]
  updateEdges()
  return id
}

export const mockApi = {
  async getScenario() { return { id: 'EQ-01', area_id: 'area-a', scenario_time: state.scenario_time } },
  async getState() { return snapshot() },
  async calculate(start: NodeId, end: NodeId, version: number) {
    checkVersion(version); saveRoute(compute(start, end, { type: 'user_request', report_id: null })); state.version++; return snapshot()
  },
  async report(input: ManualReport, version: number) {
    checkVersion(version)
    if (!state.edges.some(edge => edge.id === input.edge_id)) throw new Error('Road not found.')
    if (!input.source_id.trim() || !input.source_name.trim()) throw new Error('Source ID and name are required.')
    if (!Number.isFinite(Date.parse(input.observed_at)) || Date.parse(input.observed_at) > Date.parse(state.scenario_time)) throw new Error('Observation time must not be later than scenario time.')
    if (state.reports.some(report => report.edge_id === input.edge_id && report.source_id === input.source_id && report.observed_at > input.observed_at)) throw new Error('Observation time is earlier than the latest report from this source.')
    const reportId = addReport({ ...input, source_type: 'manual' })
    recalculate({ type: 'manual_report', report_id: reportId }); state.version++; return snapshot()
  },
  async advance(version: number) {
    checkVersion(version)
    if (state.demo_advanced) throw new Error('The simulated external update has already been played.')
    state.scenario_time = '2026-01-01T10:10:00Z'; state.demo_advanced = true
    const reportId = addReport({ edge_id: 'road-sa', status: 'reported_open', source_type: 'external_demo', source_id: 'external-demo', source_name: 'Simulated external report', observed_at: state.scenario_time, note: 'Preset exercise update' })
    recalculate({ type: 'demo_update', report_id: reportId }); state.version++; return snapshot()
  },
  async ask(question: string, version: number) {
    checkVersion(version)
    const normalized = question.toLowerCase().replace(/[^a-z0-9\s]/g, '').replace(/\s+/g, ' ').trim()
    let answer: string
    let related_edge_ids: string[] = []
    if (normalized.includes('why') && normalized.includes('route') && normalized.includes('chang')) {
      const routes = state.current_route ? [state.current_route, ...state.route_history] : []
      const changed = routes.find((route, index) => {
        const previous = routes[index + 1]
        return previous && (route.status !== previous.status || route.node_ids.join() !== previous.node_ids.join())
      })
      if (!changed) answer = 'There is no recorded route change yet.'
      else { const report = state.reports.find(item => item.id === changed.trigger.report_id); answer = report ? `The route changed after a ${reportLabels[report.status].toLowerCase()} update for ${report.edge_id} from ${report.source_name}. Only roads marked open are used.` : 'The route changed after a new route request.'; related_edge_ids = report ? [report.edge_id] : [] }
    } else if (normalized.includes('roads') && (normalized.includes('checking') || normalized.includes('check'))) {
      const roads = state.edges.filter(edge => ['suspected', 'conflict', 'unknown'].includes(edge.effective_status)); related_edge_ids = roads.map(road => road.id)
      answer = roads.length ? `Roads needing review: ${roads.map(road => `${road.id} (${statusLabels[road.effective_status]}; ${state.reports.filter(report => report.edge_id === road.id && report.is_latest_for_source).map(report => report.source_name).join(', ') || 'no report'})`).join('; ')}.` : 'No roads are currently marked suspected, conflict, or unknown.'
    } else if (normalized.includes('base s') && normalized.includes('incident t')) {
      const route = compute('S', 'T', { type: 'user_request', report_id: null }); saveRoute(route); state.version++
      related_edge_ids = route.edge_ids
      answer = route.status === 'found' ? `The simulated candidate route is ${route.node_ids.join(' → ')} via ${route.edge_ids.join(' and ')}. Distance: ${route.distance_m?.toLocaleString()} metres. This is not for real-world navigation.` : 'There is no candidate route under the current exercise conditions.'
    } else answer = 'This demo supports questions about candidate routes, route changes, and roads that need checking.'
    return { answer, related_edge_ids, state: snapshot() }
  },
}

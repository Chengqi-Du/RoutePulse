export type ReportStatus = 'reported_open' | 'reported_blocked' | 'reported_suspected'
export type EffectiveStatus = 'open' | 'blocked' | 'suspected' | 'conflict' | 'unknown'
export type Node = { id: string; name: string; type: string; coordinates: [number, number]; osm_node_id?: string }
export type Edge = {
  id: string; from_node_id: string; to_node_id: string; length_m: number; effective_status: EffectiveStatus
  name: string | null; osm_way_id: string | null; direction: string | null; geometry: { type: 'LineString'; coordinates: [number, number][] } | null
  evidence_report_ids: string[]
}
export type Report = {
  id: string; edge_id: string; status: ReportStatus; source_type: string; source_id: string; source_name: string
  observed_at: string; recorded_at: string; note: string; is_latest_for_source: boolean; is_fresh: boolean
}
export type Route = {
  id: string; status: 'found' | 'no_path'; start_node_id: string; end_node_id: string
  node_ids: string[]; edge_ids: string[]; distance_m: number | null; computed_at: string
  trigger: { type: string; report_id: string | null; report_ids: string[]; frame_id: string | null }
}
export type AreaState = {
  area_id: string; scenario_id: string; is_simulation: boolean; version: number; scenario_time: string
  scenario_mode: 'legacy' | 'anamizu-7day'; day_index: number; day_count: number; scenario_date_local: string | null
  nodes: Node[]; edges: Edge[]; reports: Report[]; current_result: Route | null; history: Route[]
  route_change: { has_previous: boolean; changed: boolean; affected_previous_route: boolean }
}
export type ManualReport = { edge_id: string; status: ReportStatus; source_id: string; source_name: string; observed_at: string; note: string }
type Scenario = { areas: { id: string; available: boolean }[] }
type QuestionResult = { version: number; intent: string; answer: string; related_edge_ids: string[] }

export const reportLabels: Record<ReportStatus, string> = {
  reported_open: 'Reported open', reported_blocked: 'Reported blocked', reported_suspected: 'Reported suspected',
}
export const statusLabels: Record<EffectiveStatus, string> = {
  open: 'Open', blocked: 'Blocked', suspected: 'Suspected', conflict: 'Conflict', unknown: 'Unknown',
}

export class ApiError extends Error {
  constructor(message: string, public code: string, public status: number) { super(message) }
}

const baseUrl = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(baseUrl + path, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  if (!response.ok) {
    const data = await response.json().catch(() => null) as { error?: { code?: string; message?: string } } | null
    throw new ApiError(data?.error?.message || `Request failed (HTTP ${response.status}).`, data?.error?.code || 'HTTP_ERROR', response.status)
  }
  return response.json() as Promise<T>
}

const areaPath = (areaId: string) => `/areas/${encodeURIComponent(areaId)}`

async function mutate(areaId: string, path: string, body: object): Promise<AreaState> {
  await request(areaPath(areaId) + path, body)
  try { return await api.getState(areaId) }
  catch { throw new ApiError('The update was saved, but refreshing the state failed. Refresh before trying again.', 'REFRESH_FAILED', 0) }
}

export const api = {
  async initialState() {
    const scenario = await request<Scenario>('/scenario')
    const area = scenario.areas.find(item => item.available)
    if (!area) throw new Error('No available exercise area was returned by the backend.')
    return api.getState(area.id)
  },
  getState: (areaId: string) => request<AreaState>(areaPath(areaId) + '/state'),
  calculate: (areaId: string, start: string, end: string, version: number) => mutate(areaId, '/routes', { expected_version: version, start_node_id: start, end_node_id: end }),
  report: (areaId: string, input: ManualReport, version: number) => mutate(areaId, '/reports', { ...input, expected_version: version }),
  advance: (areaId: string, version: number, mode: AreaState['scenario_mode']) => mutate(areaId, mode === 'anamizu-7day' ? '/advance-day' : '/demo-advance', { expected_version: version }),
  async ask(areaId: string, question: string, version: number) {
    const result = await request<QuestionResult>(areaPath(areaId) + '/questions', { expected_version: version, question })
    try { return { ...result, state: await api.getState(areaId) } }
    catch { throw new ApiError('The question was processed, but refreshing the state failed. Refresh before trying again.', 'REFRESH_FAILED', 0) }
  },
}

import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { api, ApiError, reportLabels, statusLabels, type AreaState, type ManualReport, type ReportStatus, type Route } from './api'
import NotoRoadMap from './NotoRoadMap'
import RescueRouteMap from './RescueRouteMap'

const time = (value: string) => new Date(value).toISOString().slice(11, 16) + ' UTC'
const routeName = (route: Route | null) => !route ? 'No route calculated' : route.status === 'no_path' ? 'No candidate route' : `${route.start_node_id} → ${route.end_node_id} (${route.edge_ids.length} roads)`
const routeDistance = (route: Route) => route.distance_m === null ? 'No path available' : `${route.distance_m.toLocaleString()} m`
const examples = ['Why did the route change?', 'Which roads need checking?']

function Overview({ state, enter }: { state: AreaState; enter: () => void }) {
  return <main className="overview page-content">
    <div className="page-heading"><div><div className="eyebrow">ACTIVE SCENARIO / 01</div><h1>Post-earthquake response area overview</h1><p>Simulated earthquake event · desktop rescue exercise</p></div><div className="heading-meta"><span className="eyebrow">SCENARIO TIME</span><span>{time(state.scenario_time)} · exercise time</span></div></div>
    <div className="overview-grid"><NotoRoadMap /><aside className="overview-side">
      <section className="card event-card"><div className="eyebrow accent">● SIMULATED EVENT</div><h2>{state.scenario_id}</h2><p className="muted">Scenario summary</p><p>This is exercise data, not a live incident.</p><div className="card-rule status-row"><span className="eyebrow">STATUS</span><span className="eyebrow accent">● EXERCISE ACTIVE</span></div></section>
      <section className="card sector-card"><h3>Rescue area</h3><p className="muted">Selected exercise area</p><div className="card-rule"><span className="eyebrow">NETWORK</span><p>{state.edges.length} directed roads · {state.nodes.length} nodes</p><span className="eyebrow">AREA ID / {state.area_id}</span></div></section>
      <button className="area-link" onClick={enter}><span><span className="eyebrow">AVAILABLE AREA / 01</span><strong>Open rescue area</strong></span><span className="arrow">→</span></button>
    </aside></div>
    <div className="overview-bottom"><span className="eyebrow">EXERCISE REPORTS ARE SIMULATED · HISTORICAL MAP IS FOR REFERENCE ONLY</span><button className="primary-button" onClick={enter}>Enter exercise area <span>→</span></button></div>
  </main>
}

function RouteDisplay({ state }: { state: AreaState }) {
  const route = state.current_result
  const previous = state.history[state.history.length - 1]
  const changed = state.route_change.changed
  const triggerReport = route && state.reports.find(report => report.id === route.trigger.report_id)
  return <section className="card current-route"><div className="card-heading"><span className="eyebrow">CURRENT CANDIDATE ROUTE</span><span className={`eyebrow ${route?.status === 'found' ? 'positive' : 'accent'}`}>{route ? route.status === 'found' ? '● AVAILABLE' : '▲ NO PATH' : 'NOT CALCULATED'}</span></div>
    {route ? <><div className="route-path">{routeName(route)}</div>{route.status === 'found' ? <div className="distance"><strong>{route.distance_m?.toLocaleString()}</strong><span>METRES · SIMULATED NETWORK</span></div> : <p className="route-message">No candidate route under the current exercise conditions.</p>}
      {triggerReport && <p className="route-reason">{changed ? 'Route changed' : 'Route unchanged'} after {triggerReport.edge_id}: {reportLabels[triggerReport.status].toLowerCase()}.</p>}</> : <p className="route-message">Select a start and destination to calculate a candidate route.</p>}
    <div className="previous-route"><span>Previous route</span><strong>{previous ? `${routeName(previous)} · ${routeDistance(previous)}` : 'No history yet'}</strong></div>
  </section>
}

function ReportForm({ state, selectedEdge, selectEdge, submit, busy }: { state: AreaState; selectedEdge: string; selectEdge: (id: string) => void; submit: (report: ManualReport) => void; busy: boolean }) {
  const [status, setStatus] = useState<ReportStatus>('reported_blocked')
  const [sourceId, setSourceId] = useState('field-team-1')
  const [sourceName, setSourceName] = useState('Simulated field team 1 via radio')
  const [observed, setObserved] = useState(state.scenario_time.slice(0, 19))
  const [note, setNote] = useState('')
  useEffect(() => { setObserved(state.scenario_time.slice(0, 19)) }, [state.scenario_time])
  const selected = state.edges.find(edge => edge.id === selectedEdge)
  const directions = selected ? state.edges.filter(edge => edge.id === selected.id || (selected.osm_way_id && edge.osm_way_id === selected.osm_way_id && edge.from_node_id === selected.to_node_id && edge.to_node_id === selected.from_node_id)) : []
  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!selected || busy || (state.scenario_mode === 'anamizu-7day' && state.day_index === 0)) return
    submit({ edge_id: selected.id, status, source_id: sourceId.trim(), source_name: sourceName.trim(), observed_at: `${observed}Z`, note: note.trim() })
  }
  return <form className="card report-form" onSubmit={onSubmit}><div className="eyebrow">ADD MANUAL REPORT</div>
    {state.scenario_mode === 'anamizu-7day' && state.day_index === 0 && <p className="muted">Advance to Day 1 before submitting feedback: Day 0 reports can prevent the first frame from loading.</p>}
    <label>Road direction<select value={selectedEdge} onChange={event => selectEdge(event.target.value)}><option value="">Select a road on the map</option>{directions.map(edge => <option key={edge.id} value={edge.id}>{edge.name || 'Unnamed road'} · {edge.from_node_id} → {edge.to_node_id} · {statusLabels[edge.effective_status]}</option>)}</select></label>
    <p className="muted">Feedback applies to the selected direction only. For the reverse direction, select it separately.</p>
    <label>Status<select value={status} onChange={event => setStatus(event.target.value as ReportStatus)}>{Object.entries(reportLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <div className="form-two"><label>Source ID<input required value={sourceId} onChange={event => setSourceId(event.target.value)} /></label><label>Source name<input required value={sourceName} onChange={event => setSourceName(event.target.value)} /></label></div>
    <label>Observed at · scenario time (UTC)<input type="datetime-local" step="1" required max={state.scenario_time.slice(0, 19)} value={observed} onChange={event => setObserved(event.target.value)} /></label>
    <label>Note <span className="optional">/ optional</span><input value={note} onChange={event => setNote(event.target.value)} placeholder="Add an observation" /></label>
    <button className="secondary-button" disabled={busy || !selected || (state.scenario_mode === 'anamizu-7day' && state.day_index === 0)} type="submit">Submit report & recalculate <span>→</span></button>
  </form>
}

function FloatingPanel({ id, label, icon, open, onToggle, children }: { id: string; label: string; icon: string; open: boolean; onToggle: () => void; children: ReactNode }) {
  return <section className={`floating-panel ${open ? 'is-open' : 'is-closed'}`}>
    <button className="panel-toggle" type="button" aria-expanded={open} aria-controls={id} aria-label={`${open ? 'Collapse' : 'Expand'} ${label}`} onClick={onToggle}>
      <span className="panel-icon" aria-hidden="true">{icon}</span><span className="panel-name">{label}</span><span className="panel-indicator" aria-hidden="true">{open ? '−' : '+'}</span>
    </button>
    <div id={id} className="panel-content" hidden={!open}>{children}</div>
  </section>
}

function QuestionPanel({ ask, answer, busy }: { ask: (question: string) => void; answer: string; busy: boolean }) {
  const [question, setQuestion] = useState('')
  function onAsk(event: FormEvent) { event.preventDefault(); if (question.trim()) ask(question.trim()) }
  return <section><div className="eyebrow sidebar-kicker">SUPPORTED EXERCISE QUESTIONS</div>
      <form className="ask-box" onSubmit={onAsk}><label htmlFor="question" className="eyebrow">ASK ROUTEPULSE</label><p>Ask about a route or reported road status.</p><div className="ask-input"><input id="question" value={question} onChange={event => setQuestion(event.target.value)} placeholder="Type a question..." /><button disabled={busy || !question.trim()} aria-label="Submit question">↗</button></div>
        <div className="suggestions">{examples.map(example => <button key={example} type="button" disabled={busy} onClick={() => { setQuestion(example); ask(example) }}>{example}</button>)}</div>
        {answer && <div className="answer" aria-live="polite"><span className="eyebrow">SIMULATED ANSWER</span><p>{answer}</p></div>}
      </form>
    </section>
}

function RoadReports({ state, related, selectedEdge }: { state: AreaState; related: string[]; selectedEdge: string }) {
  const visible = selectedEdge ? state.edges.filter(edge => edge.id === selectedEdge) : state.edges.filter(edge => related.includes(edge.id)).slice(0, 25)
  const reports = (selectedEdge ? state.reports.filter(report => report.edge_id === selectedEdge) : state.reports).slice(-50).reverse()
  return <section><div className="section-heading"><span className="eyebrow">ROAD STATUS</span><span className="eyebrow">{state.reports.length} REPORTS</span></div>
      <div className="road-statuses">{visible.length ? visible.map(edge => <div key={edge.id} className={`road-status ${related.includes(edge.id) ? 'related' : ''}`}><span className={`status-dot ${edge.effective_status}`}>●</span><strong>{edge.name || edge.id}</strong><span>{statusLabels[edge.effective_status]}</span></div>) : <p className="muted">Select a road on the map to inspect its status.</p>}</div>
      <p className="muted">{selectedEdge ? 'Selected direction' : 'All roads'}: showing up to 50 most recent reports.</p>
      <div className="report-list">{reports.length === 0 ? <p className="muted">No reports yet.</p> : reports.map(report => <div className={`report-item ${related.includes(report.edge_id) ? 'related' : ''}`} key={report.id}><span className={`status-dot ${report.status.replace('reported_', '')}`}>●</span><div><strong>{report.edge_id} · {reportLabels[report.status]}</strong><p>Simulated source: {report.source_name}</p>{report.note && <p>{report.note}</p>}<p>{report.is_latest_for_source ? 'Latest from source' : 'Historical'} · {report.is_fresh ? 'Within 30 minutes' : 'Outside 30-minute window'}</p></div><time>{time(report.observed_at)}</time></div>)}</div>
    </section>
}

function RouteHistory({ state }: { state: AreaState }) {
  return <><div className="history-list">{state.current_result && <div className="history-item"><span className="history-tag">NOW</span><div><strong>{routeName(state.current_result)}</strong><p>{routeDistance(state.current_result)} · Current candidate route</p></div></div>}{state.history.length ? [...state.history].reverse().map(route => <div className="history-item" key={route.id}><span className="history-tag">PAST</span><div><strong>{routeName(route)}</strong><p>{routeDistance(route)} · {time(route.computed_at)} scenario time</p></div></div>) : <p className="muted history-empty">No previous routes yet.</p>}</div>
    <div className="status-note"><span className="eyebrow">STATUS LABELS</span><p>Open, blocked, suspected, conflict and unknown describe simulated reports—not real-world safety.</p></div>
  </>
}

export default function App() {
  const [page, setPage] = useState<'overview' | 'route'>('overview')
  const [state, setState] = useState<AreaState | null>(null)
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [selectedEdge, setSelectedEdge] = useState('')
  const [answer, setAnswer] = useState('')
  const [related, setRelated] = useState<string[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [lastRefresh, setLastRefresh] = useState('')
  const [stale, setStale] = useState(false)
  const choices = useMemo(() => state ? state.nodes.filter(node => !node.osm_node_id || node.name !== `OSM node ${node.osm_node_id}`).slice(0, 50) : [], [state?.nodes])
  const [panels, setPanels] = useState(() => {
    const expanded = window.matchMedia('(min-width: 900px)').matches
    return { route: expanded, report: expanded, reports: expanded, ask: expanded, history: expanded }
  })

  function togglePanel(panel: keyof typeof panels) {
    setPanels(current => {
      if (!current[panel] && window.matchMedia('(max-width: 760px)').matches) {
        return { route: false, report: false, reports: false, ask: false, history: false, [panel]: true }
      }
      return { ...current, [panel]: !current[panel] }
    })
  }
  function toggleRail(side: 'left' | 'right') {
    setPanels(current => {
      const open = side === 'left' ? !(current.route || current.report) : !(current.reports || current.ask)
      const next = open && window.matchMedia('(max-width: 760px)').matches
        ? { route: false, report: false, reports: false, ask: false, history: false }
        : current
      return side === 'left' ? { ...next, route: open, report: open } : { ...next, reports: open, ask: open }
    })
  }

  function applyState(next: AreaState) {
    setState(next); setStale(false); setLastRefresh(new Date().toLocaleTimeString())
    const available = next.nodes.filter(node => !node.osm_node_id || node.name !== `OSM node ${node.osm_node_id}`).slice(0, 50)
    setStart(current => available.some(node => node.id === current) ? current : available[0]?.id || '')
    setEnd(current => available.some(node => node.id === current) ? current : available[1]?.id || '')
    setSelectedEdge(current => next.edges.some(edge => edge.id === current) ? current : '')
  }
  const selectEdge = useCallback((id: string) => { setSelectedEdge(id); setPanels(current => ({ ...current, report: true })) }, [])
  useEffect(() => { api.initialState().then(applyState).catch(failure => setError(failure instanceof Error ? failure.message : 'Unable to load exercise data.')) }, [])
  async function handleFailure(failure: unknown) {
    setStale(true)
    setError(failure instanceof Error ? failure.message : 'The request failed. Refresh before trying again.')
    if (failure instanceof ApiError && failure.code === 'VERSION_CONFLICT' && state) {
      try { applyState(await api.getState(state.area_id)); setError('The exercise state changed and was refreshed. Review it and retry your action.') } catch { setStale(true) }
    }
  }
  async function run(action: () => Promise<AreaState>) {
    setBusy(true); setError(''); setAnswer(''); setRelated([])
    try { applyState(await action()) } catch (failure) { await handleFailure(failure) } finally { setBusy(false) }
  }
  async function ask(question: string) {
    if (!state) return
    setBusy(true); setError(''); setAnswer(''); setRelated([])
    try { const result = await api.ask(state.area_id, question, state.version); applyState(result.state); setAnswer(result.answer); setRelated(result.related_edge_ids) }
    catch (failure) { await handleFailure(failure) }
    finally { setBusy(false) }
  }
  return <div className={`app-shell ${page === 'route' ? 'route-shell' : ''}`}><header className="topbar"><button className="brand" onClick={() => setPage('overview')} aria-label="RoutePulse overview">ROUTE<span>PULSE</span><i> / EXERCISE PLATFORM</i></button><nav aria-label="Main navigation"><button className={page === 'overview' ? 'active' : ''} onClick={() => setPage('overview')}>Overview</button><button className={page === 'route' ? 'active' : ''} onClick={() => setPage('route')}>Rescue Route</button></nav><div className="topbar-right"><span className="simulation-badge">SIMULATION {page === 'route' && '/ AREA A'}</span><span className="avatar">OP</span></div></header>
    {!state ? <div className="loading" role="status">{error || 'Loading simulated exercise data…'} {error && <button onClick={() => { setError(''); api.initialState().then(applyState).catch(failure => setError(failure instanceof Error ? failure.message : 'Unable to load exercise data.')) }}>Retry</button>}</div> : page === 'overview' ? <Overview state={state} enter={() => setPage('route')} /> : <main className="route-workspace">
      <RescueRouteMap state={stale ? { ...state, current_result: null } : state} selectedEdge={selectedEdge} onSelectEdge={selectEdge} choices={choices} />
      <div className="route-search-bar"><div className="route-search-title"><span className="eyebrow">{state.area_id} / ROUTE PLANNING</span><h1>Rescue route</h1><span className="refresh-label">Scenario time · {time(state.scenario_time)}</span></div><div className="route-controls"><label className="select-card"><span className="eyebrow">START</span><select value={start} onChange={event => setStart(event.target.value)}>{choices.map(node => <option key={node.id} value={node.id}>{node.name} ({node.id})</option>)}</select></label><label className="select-card"><span className="eyebrow">DESTINATION</span><select value={end} onChange={event => setEnd(event.target.value)}>{choices.map(node => <option key={node.id} value={node.id}>{node.name} ({node.id})</option>)}</select></label><button className="primary-button calculate" disabled={busy || stale || !start || !end || start === end} onClick={() => run(() => api.calculate(state.area_id, start, end, state.version))}>Calculate route <span>→</span></button></div></div>
      <div className="route-notices"><div className="warning"><strong>!</strong><span>Simulation only · Not for real-world rescue navigation. Map and reports do not represent live road conditions.</span></div>{error && <div className="error" role="alert">{error} <button onClick={() => run(() => api.getState(state.area_id))}>Refresh state</button></div>}{stale && <div className="error">Current route may be out of date. Refresh the exercise state.</div>}</div>
      <aside className="floating-rail left-rail" aria-label="Route tools">
        <FloatingPanel id="route-panel" label="Route" icon="⌖" open={panels.route} onToggle={() => togglePanel('route')}>{stale ? <div className="card current-route"><span className="eyebrow">CURRENT ROUTE UNAVAILABLE</span><p className="route-message">Refresh the exercise state to see the current route.</p></div> : <RouteDisplay state={state} />}</FloatingPanel>
        <FloatingPanel id="report-panel" label="Manual report" icon="+" open={panels.report} onToggle={() => togglePanel('report')}><ReportForm state={state} selectedEdge={selectedEdge} selectEdge={selectEdge} busy={busy || stale} submit={report => run(() => api.report(state.area_id, report, state.version))} /></FloatingPanel>
        {!panels.history && <button className="history-tab" aria-expanded="false" aria-controls="history-panel" onClick={() => togglePanel('history')}><span aria-hidden="true">↶</span> HISTORY</button>}
        <button className="rail-toggle" onClick={() => toggleRail('left')}>{panels.route || panels.report ? 'Collapse panels −' : 'Expand panels +'}</button>
      </aside>
      <aside className="floating-rail right-rail" aria-label="Reports and questions">
        <FloatingPanel id="reports-panel" label="Road reports" icon="≡" open={panels.reports} onToggle={() => togglePanel('reports')}><RoadReports state={state} related={related} selectedEdge={selectedEdge} /><div className="demo-control"><div><span className="eyebrow">EXERCISE CONTROLS</span><p>{state.scenario_mode === 'anamizu-7day' ? `Day ${state.day_index} / ${state.day_count}${state.scenario_date_local ? ` · ${state.scenario_date_local}` : ''}` : 'Preset update, not live data.'}</p></div><button className="outline-button" disabled={busy || stale || (state.scenario_mode === 'anamizu-7day' ? state.day_index >= state.day_count : state.reports.some(report => report.source_type === 'external_demo'))} onClick={() => run(() => api.advance(state.area_id, state.version, state.scenario_mode))}>{state.scenario_mode === 'anamizu-7day' ? (state.day_index >= state.day_count ? 'Exercise complete' : 'Next day') : 'Advance simulation'} →</button></div></FloatingPanel>
        <FloatingPanel id="ask-panel" label="Ask RoutePulse" icon="?" open={panels.ask} onToggle={() => togglePanel('ask')}><QuestionPanel ask={ask} answer={answer} busy={busy || stale} /></FloatingPanel>
        {!panels.history && <button className="history-tab" aria-expanded="false" aria-controls="history-panel" onClick={() => togglePanel('history')}><span aria-hidden="true">↶</span> HISTORY</button>}
        <button className="rail-toggle" onClick={() => toggleRail('right')}>{panels.reports || panels.ask ? 'Collapse panels −' : 'Expand panels +'}</button>
      </aside>
      <section id="history-panel" className="floating-history" hidden={!panels.history}><div className="history-heading"><div><span className="eyebrow">SCENARIO TIME · {time(state.scenario_time)}</span><h2>Route history</h2><span className="refresh-label">Last refresh: {lastRefresh}</span></div><button className="history-close" aria-label="Collapse route history" aria-expanded="true" aria-controls="history-panel" onClick={() => togglePanel('history')}>−</button></div><RouteHistory state={stale ? { ...state, current_result: null } : state} /></section>
    </main>}
  </div>
}

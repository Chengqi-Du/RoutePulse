import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { mockApi, nodes, reportLabels, statusLabels, type AreaState, type ManualReport, type NodeId, type ReportStatus, type Route } from './mockApi'
import NotoRoadMap from './NotoRoadMap'
import RescueRouteMap from './RescueRouteMap'

const time = (value: string) => new Date(value).toISOString().slice(11, 16) + ' UTC'
const routeName = (route: Route | null) => !route ? 'No route calculated' : route.status === 'no_path' ? 'No candidate route' : route.node_ids.join(' → ')
const routeDistance = (route: Route) => route.distance_m === null ? 'No path available' : `${route.distance_m.toLocaleString()} m`
const examples = ['How can I get from Base S to Incident T?', 'Why did the route change?', 'Which roads need checking?']

function Overview({ scenarioTime, enter }: { scenarioTime: string; enter: () => void }) {
  return <main className="overview page-content">
    <div className="page-heading"><div><div className="eyebrow">ACTIVE SCENARIO / 01</div><h1>Post-earthquake response area overview</h1><p>Simulated earthquake event · desktop rescue exercise</p></div><div className="heading-meta"><span className="eyebrow">SCENARIO TIME</span><span>{time(scenarioTime)} · exercise time</span></div></div>
    <div className="overview-grid"><NotoRoadMap /><aside className="overview-side">
      <section className="card event-card"><div className="eyebrow accent">● SIMULATED EVENT</div><h2>Earthquake event / EQ-01</h2><p className="muted">Scenario summary</p><p>Preconfigured event details appear here.<br />This is exercise data, not a live incident.</p><div className="card-rule status-row"><span className="eyebrow">STATUS</span><span className="eyebrow accent">● EXERCISE ACTIVE</span></div></section>
      <section className="card sector-card"><h3>Rescue Sector A</h3><p className="muted">Selected exercise area</p><div className="card-rule"><span className="eyebrow">NETWORK</span><p>4 roads · 4 nodes · 1 target</p><span className="eyebrow">AREA ID / AREA-A</span></div></section>
      <button className="area-link" onClick={enter}><span><span className="eyebrow">AVAILABLE AREA / 01</span><strong>Open rescue area</strong></span><span className="arrow">→</span></button>
    </aside></div>
    <div className="overview-bottom"><span className="eyebrow">EXERCISE REPORTS ARE SIMULATED · HISTORICAL MAP IS FOR REFERENCE ONLY</span><button className="primary-button" onClick={enter}>Enter exercise area <span>→</span></button></div>
  </main>
}

function RouteDisplay({ state }: { state: AreaState }) {
  const route = state.current_route
  const previous = state.route_history[0]
  const changed = route && previous && (route.status !== previous.status || route.node_ids.join() !== previous.node_ids.join())
  const triggerReport = route && state.reports.find(report => report.id === route.trigger.report_id)
  return <section className="card current-route"><div className="card-heading"><span className="eyebrow">CURRENT CANDIDATE ROUTE</span><span className={`eyebrow ${route?.status === 'found' ? 'positive' : 'accent'}`}>{route ? route.status === 'found' ? '● AVAILABLE' : '▲ NO PATH' : 'NOT CALCULATED'}</span></div>
    {route ? <><div className="route-path">{routeName(route)}</div>{route.status === 'found' ? <div className="distance"><strong>{route.distance_m?.toLocaleString()}</strong><span>METRES · SIMULATED NETWORK</span></div> : <p className="route-message">No candidate route under the current exercise conditions.</p>}
      {triggerReport && <p className="route-reason">{changed ? 'Route changed' : 'Route unchanged'} after {triggerReport.edge_id}: {reportLabels[triggerReport.status].toLowerCase()}.</p>}</> : <p className="route-message">Select a start and destination to calculate a candidate route.</p>}
    <div className="previous-route"><span>Previous route</span><strong>{previous ? `${routeName(previous)} · ${routeDistance(previous)}` : 'No history yet'}</strong></div>
  </section>
}

function ReportForm({ state, submit, busy }: { state: AreaState; submit: (report: ManualReport) => void; busy: boolean }) {
  const [road, setRoad] = useState('road-sa')
  const [status, setStatus] = useState<ReportStatus>('reported_blocked')
  const [sourceId, setSourceId] = useState('field-team-1')
  const [sourceName, setSourceName] = useState('Simulated field team 1 via radio')
  const [observed, setObserved] = useState(state.scenario_time.slice(0, 16))
  const [note, setNote] = useState('')
  function onSubmit(event: FormEvent) {
    event.preventDefault()
    submit({ edge_id: road, status, source_id: sourceId.trim(), source_name: sourceName.trim(), observed_at: `${observed}:00Z`, note: note.trim() })
  }
  return <form className="card report-form" onSubmit={onSubmit}><div className="eyebrow">ADD MANUAL REPORT</div>
    <label>Road<select value={road} onChange={event => setRoad(event.target.value)}>{state.edges.map(edge => <option key={edge.id} value={edge.id}>{edge.id} · {edge.from_node_id} → {edge.to_node_id}</option>)}</select></label>
    <label>Status<select value={status} onChange={event => setStatus(event.target.value as ReportStatus)}>{Object.entries(reportLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <div className="form-two"><label>Source ID<input required value={sourceId} onChange={event => setSourceId(event.target.value)} /></label><label>Source name<input required value={sourceName} onChange={event => setSourceName(event.target.value)} /></label></div>
    <label>Observed at · scenario time (UTC)<input type="datetime-local" required max={state.scenario_time.slice(0, 16)} value={observed} onChange={event => setObserved(event.target.value)} /></label>
    <label>Note <span className="optional">/ optional</span><input value={note} onChange={event => setNote(event.target.value)} placeholder="Add an observation" /></label>
    <button className="secondary-button" disabled={busy} type="submit">Submit report & recalculate <span>→</span></button>
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
        <div className="suggestions">{examples.map(example => <button key={example} type="button" onClick={() => { setQuestion(example); ask(example) }}>{example}</button>)}</div>
        {answer && <div className="answer" aria-live="polite"><span className="eyebrow">SIMULATED ANSWER</span><p>{answer}</p></div>}
      </form>
    </section>
}

function RoadReports({ state, related }: { state: AreaState; related: string[] }) {
  return <section><div className="section-heading"><span className="eyebrow">ROAD STATUS</span><span className="eyebrow">{state.reports.length} REPORTS</span></div>
      <div className="road-statuses">{state.edges.map(edge => <div key={edge.id} className={`road-status ${related.includes(edge.id) ? 'related' : ''}`}><span className={`status-dot ${edge.effective_status}`}>●</span><strong>{edge.id}</strong><span>{statusLabels[edge.effective_status]}</span></div>)}</div>
      <div className="report-list">{state.reports.length === 0 ? <p className="muted">No reports yet.</p> : [...state.reports].reverse().map(report => <div className={`report-item ${related.includes(report.edge_id) ? 'related' : ''}`} key={report.id}><span className={`status-dot ${report.status.replace('reported_', '')}`}>●</span><div><strong>{report.edge_id} · {reportLabels[report.status]}</strong><p>Simulated source: {report.source_name}</p>{report.note && <p>{report.note}</p>}<p>{report.is_latest_for_source ? 'Latest from source' : 'Historical'} · {report.is_fresh ? 'Fresh' : 'Expired'}</p></div><time>{time(report.observed_at)}</time></div>)}</div>
    </section>
}

function RouteHistory({ state }: { state: AreaState }) {
  return <><div className="history-list">{state.current_route && <div className="history-item"><span className="history-tag">NOW</span><div><strong>{routeName(state.current_route)}</strong><p>{routeDistance(state.current_route)} · Current candidate route</p></div></div>}{state.route_history.length ? state.route_history.map(route => <div className="history-item" key={route.id}><span className="history-tag">PAST</span><div><strong>{routeName(route)}</strong><p>{routeDistance(route)} · {time(route.computed_at)} scenario time</p></div></div>) : <p className="muted history-empty">No previous routes yet.</p>}</div>
    <div className="status-note"><span className="eyebrow">STATUS LABELS</span><p>Open, blocked, suspected, conflict and unknown describe simulated reports—not real-world safety.</p></div>
  </>
}

export default function App() {
  const [page, setPage] = useState<'overview' | 'route'>('overview')
  const [state, setState] = useState<AreaState | null>(null)
  const [start, setStart] = useState<NodeId>('S')
  const [end, setEnd] = useState<NodeId>('T')
  const [answer, setAnswer] = useState('')
  const [related, setRelated] = useState<string[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [lastRefresh, setLastRefresh] = useState('')
  const [stale, setStale] = useState(false)
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

  function applyState(next: AreaState) { setState(next); setStale(false); setLastRefresh(new Date().toLocaleTimeString()) }
  useEffect(() => { mockApi.getState().then(applyState).catch(() => setError('Unable to load exercise data.')) }, [])
  async function run(action: () => Promise<AreaState>) {
    setBusy(true); setError(''); setAnswer(''); setRelated([])
    try { applyState(await action()) } catch (failure) {
      setStale(true); setError(failure instanceof Error ? failure.message : 'The request failed. Refresh and try again.')
      if (failure instanceof Error && failure.message.startsWith('VERSION_CONFLICT')) { try { applyState(await mockApi.getState()) } catch { setStale(true) } }
    } finally { setBusy(false) }
  }
  async function ask(question: string) {
    if (!state) return
    setBusy(true); setError(''); setAnswer(''); setRelated([])
    try { const result = await mockApi.ask(question, state.version); applyState(result.state); setAnswer(result.answer); setRelated(result.related_edge_ids) }
    catch (failure) { setStale(true); setError(failure instanceof Error ? failure.message : 'Unable to answer the question.') }
    finally { setBusy(false) }
  }
  return <div className={`app-shell ${page === 'route' ? 'route-shell' : ''}`}><header className="topbar"><button className="brand" onClick={() => setPage('overview')} aria-label="RoutePulse overview">ROUTE<span>PULSE</span><i> / EXERCISE PLATFORM</i></button><nav aria-label="Main navigation"><button className={page === 'overview' ? 'active' : ''} onClick={() => setPage('overview')}>Overview</button><button className={page === 'route' ? 'active' : ''} onClick={() => setPage('route')}>Rescue Route</button></nav><div className="topbar-right"><span className="simulation-badge">SIMULATION {page === 'route' && '/ AREA A'}</span><span className="avatar">OP</span></div></header>
    {!state ? <div className="loading" role="status">{error || 'Loading simulated exercise data…'}</div> : page === 'overview' ? <Overview scenarioTime={state.scenario_time} enter={() => setPage('route')} /> : <main className="route-workspace">
      <RescueRouteMap />
      <div className="route-search-bar"><div className="route-search-title"><span className="eyebrow">AREA-A / ROUTE PLANNING</span><h1>Rescue route</h1><span className="refresh-label">Scenario time · {time(state.scenario_time)}</span></div><div className="route-controls"><label className="select-card"><span className="eyebrow">START</span><select value={start} onChange={event => setStart(event.target.value as NodeId)}>{nodes.map(node => <option key={node.id} value={node.id}>{node.name}</option>)}</select></label><label className="select-card"><span className="eyebrow">DESTINATION</span><select value={end} onChange={event => setEnd(event.target.value as NodeId)}>{nodes.map(node => <option key={node.id} value={node.id}>{node.name}</option>)}</select></label><button className="primary-button calculate" disabled={busy} onClick={() => run(() => mockApi.calculate(start, end, state.version))}>Calculate route <span>→</span></button></div></div>
      <div className="route-notices"><div className="warning"><strong>!</strong><span>Simulation only · Not for real-world rescue navigation. Mock routes are not shown on the map.</span></div>{error && <div className="error" role="alert">{error} <button onClick={() => run(() => mockApi.getState())}>Refresh state</button></div>}{stale && <div className="error">Current route may be out of date. Refresh the exercise state.</div>}</div>
      <aside className="floating-rail left-rail" aria-label="Route tools">
        <FloatingPanel id="route-panel" label="Route" icon="⌖" open={panels.route} onToggle={() => togglePanel('route')}>{stale ? <div className="card current-route"><span className="eyebrow">CURRENT ROUTE UNAVAILABLE</span><p className="route-message">Refresh the exercise state to see the current route.</p></div> : <RouteDisplay state={state} />}</FloatingPanel>
        <FloatingPanel id="report-panel" label="Manual report" icon="+" open={panels.report} onToggle={() => togglePanel('report')}><ReportForm state={state} busy={busy} submit={report => run(() => mockApi.report(report, state.version))} /></FloatingPanel>
        {!panels.history && <button className="history-tab" aria-expanded="false" aria-controls="history-panel" onClick={() => togglePanel('history')}><span aria-hidden="true">↶</span> HISTORY</button>}
        <button className="rail-toggle" onClick={() => toggleRail('left')}>{panels.route || panels.report ? 'Collapse panels −' : 'Expand panels +'}</button>
      </aside>
      <aside className="floating-rail right-rail" aria-label="Reports and questions">
        <FloatingPanel id="reports-panel" label="Road reports" icon="≡" open={panels.reports} onToggle={() => togglePanel('reports')}><RoadReports state={state} related={related} /><div className="demo-control"><div><span className="eyebrow">EXERCISE CONTROLS</span><p>Preset update, not live data.</p></div><button className="outline-button" disabled={busy || state.demo_advanced} onClick={() => run(() => mockApi.advance(state.version))}>{state.demo_advanced ? 'Update played' : 'Advance simulation'} →</button></div></FloatingPanel>
        <FloatingPanel id="ask-panel" label="Ask RoutePulse" icon="?" open={panels.ask} onToggle={() => togglePanel('ask')}><QuestionPanel ask={ask} answer={answer} busy={busy} /></FloatingPanel>
        {!panels.history && <button className="history-tab" aria-expanded="false" aria-controls="history-panel" onClick={() => togglePanel('history')}><span aria-hidden="true">↶</span> HISTORY</button>}
        <button className="rail-toggle" onClick={() => toggleRail('right')}>{panels.reports || panels.ask ? 'Collapse panels −' : 'Expand panels +'}</button>
      </aside>
      <section id="history-panel" className="floating-history" hidden={!panels.history}><div className="history-heading"><div><span className="eyebrow">SCENARIO TIME · {time(state.scenario_time)}</span><h2>Route history</h2><span className="refresh-label">Last refresh: {lastRefresh}</span></div><button className="history-close" aria-label="Collapse route history" aria-expanded="true" aria-controls="history-panel" onClick={() => togglePanel('history')}>−</button></div><RouteHistory state={stale ? { ...state, current_route: null } : state} /></section>
    </main>}
  </div>
}

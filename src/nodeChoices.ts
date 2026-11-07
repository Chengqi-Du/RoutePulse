import type { AreaState, Node } from './api'

function reachable(start: string, links: Map<string, string[]>): Set<string> {
  const seen = new Set([start])
  const pending = [start]
  while (pending.length) {
    const node = pending.pop()!
    for (const next of links.get(node) || []) {
      if (!seen.has(next)) { seen.add(next); pending.push(next) }
    }
  }
  return seen
}

export function selectableNodes(state: AreaState): Node[] {
  const candidates = state.nodes.filter(node => !node.osm_node_id || node.name !== `OSM node ${node.osm_node_id}`).slice(0, 50)
  if (state.scenario_mode !== 'anamizu-7day' || candidates.length < 2) return candidates
  const forward = new Map<string, string[]>()
  const reverse = new Map<string, string[]>()
  for (const edge of state.edges) {
    forward.set(edge.from_node_id, [...(forward.get(edge.from_node_id) || []), edge.to_node_id])
    reverse.set(edge.to_node_id, [...(reverse.get(edge.to_node_id) || []), edge.from_node_id])
  }
  let best: Node[] = []
  for (const candidate of candidates) {
    const from = reachable(candidate.id, forward)
    const to = reachable(candidate.id, reverse)
    const group = candidates.filter(node => from.has(node.id) && to.has(node.id))
    if (group.length > best.length) best = group
  }
  return best.length >= 2 ? best : candidates
}

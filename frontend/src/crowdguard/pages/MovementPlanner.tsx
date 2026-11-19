import { CheckCircle2, Navigation, XCircle } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { Badge, Button, Card, ErrorBox, PageHeader } from '../../components/ui'
import { cx } from '../../lib/cx'
import { cgResult } from '../api'
import { useCrowd } from '../store'
import type { RouteCheck, RouteOption, RoutePlan } from '../types'
import { VenueMap } from '../VenueMap'
import { PlaybackBar, SafetyNotice, SimGate } from '../widgets'

export function MovementPlannerPage() {
  return <SimGate><MovementPlanner /></SimGate>
}

function Checks({ checks }: { checks: RouteCheck[] }) {
  return (
    <ul className="space-y-1">
      {checks.map((c) => (
        <li key={c.name} className="flex items-start gap-1.5 text-xs">
          {c.passed ? <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-good-ink" aria-label="passed" /> : <XCircle className="mt-0.5 size-3.5 shrink-0 text-critical-ink" aria-label="failed" />}
          <span><span className="font-medium text-ink">{c.name}</span> <span className="text-muted">— {c.detail}</span></span>
        </li>
      ))}
    </ul>
  )
}

function RouteRow({ r, active, onClick, recommended }: { r: RouteOption; active: boolean; onClick: () => void; recommended?: boolean }) {
  return (
    <button onClick={onClick} className={cx('w-full rounded-lg border p-2.5 text-left transition', active ? 'border-[#0ea5e9] bg-[#0ea5e9]/5' : 'border-line hover:bg-surface-2')}>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-xs font-bold">{r.id}</span>
        {recommended && <Badge tone="good">recommended</Badge>}
        <span className="text-xs text-ink">{r.names.join(' → ')}</span>
      </div>
      <p className="mt-1 text-[11px] text-muted">{r.length_m} m · ~{Math.round(r.est_travel_s / 6) / 10} min walk · bottleneck {Math.round(r.bottleneck_capacity_ppm ?? 0)}/min · max occupancy on path {r.max_zone_pct_on_path ?? '—'}% · score {r.safety_score}/100 (heuristic)</p>
    </button>
  )
}

function MovementPlanner() {
  const { venue, frame, tick } = useCrowd()
  const [source, setSource] = useState('main_stage')
  const [purpose, setPurpose] = useState<'relieve' | 'egress'>('relieve')
  const [group, setGroup] = useState(1200)
  const [blockedEdges, setBlockedEdges] = useState<Set<string>>(new Set())
  const [blockedNodes, setBlockedNodes] = useState<Set<string>>(new Set())
  const [plan, setPlan] = useState<RoutePlan | null>(null)
  const [shown, setShown] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const run = useCallback(async () => {
    setBusy(true)
    setErr(null)
    try {
      const { result } = await cgResult<RoutePlan>('/route', { source, purpose, group_size: group, tick,
        blocked_edges: [...blockedEdges], blocked_nodes: [...blockedNodes], k: 3 })
      setPlan(result)
      setShown(result.recommended?.id ?? null)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
      setPlan(null)
    } finally {
      setBusy(false)
    }
  }, [source, purpose, group, tick, blockedEdges, blockedNodes])

  useEffect(() => {
    const id = window.setTimeout(() => { void run() }, 150)
    return () => window.clearTimeout(id)
  }, [run])

  if (!venue || !frame) return null
  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, id: string) => {
    const next = new Set(set)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setter(next)
  }
  const routes = plan ? [plan.recommended, ...(plan.alternatives ?? [])].filter(Boolean) as RouteOption[] : []
  const shownRoute = routes.find((r) => r.id === shown) ?? null
  const sources = [...venue.zones.map((z) => ({ id: z.id, name: z.name }))]

  return (
    <div className="space-y-4">
      <PageHeader title="Movement Planner" icon={<Navigation className="mt-1 size-6 text-[var(--accent)]" />}
        description="Safety-weighted routing on the venue graph (NetworkX). Travel time depends on density, corridor load, destination capacity and live-data availability. Routes never pass through overcrowded zones, and the distance-shortest path is assessed separately rather than assumed safe." />
      <PlaybackBar />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="space-y-2">
          <VenueMap venue={venue} readings={frame.readings} edgeFlows={frame.edge_flows} exitStatus={frame.exit_status}
            route={shownRoute} altRoutes={routes.filter((r) => r.id !== shown)} blockedEdges={blockedEdges} blockedNodes={blockedNodes}
            onToggleEdge={(id) => toggle(blockedEdges, setBlockedEdges, id)} onToggleNode={(id) => toggle(blockedNodes, setBlockedNodes, id)}
            onSelect={setSource} selected={source} label="Click a zone to set the source · click a corridor or exit to mark it blocked" />
          <SafetyNotice />
        </div>
        <div className="space-y-3">
          <Card title="Plan">
            <div className="grid grid-cols-2 gap-2">
              <label className="col-span-2 text-xs font-medium text-ink-2">From
                <select value={source} onChange={(e) => setSource(e.target.value)} className="mt-1 block w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm">
                  {sources.map((s) => <option key={s.id} value={s.id}>{s.name} ({frame.readings[s.id]?.occupancy_pct ?? '—'}%)</option>)}
                </select>
              </label>
              <label className="text-xs font-medium text-ink-2">Purpose
                <select value={purpose} onChange={(e) => setPurpose(e.target.value as 'relieve' | 'egress')} className="mt-1 block w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm">
                  <option value="relieve">Relieve zone (redistribute)</option>
                  <option value="egress">Egress to an exit</option>
                </select>
              </label>
              <label className="text-xs font-medium text-ink-2">People to move
                <input type="number" min={1} max={100000} step={50} value={group} onChange={(e) => setGroup(Math.max(1, Number(e.target.value)))}
                  className="mt-1 block w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" />
              </label>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-ink-2">
              <span>Blocked by you:</span>
              {[...blockedEdges, ...blockedNodes].length === 0 && <span className="text-muted">none</span>}
              {[...blockedEdges].map((e) => <button key={e} onClick={() => toggle(blockedEdges, setBlockedEdges, e)}><Badge tone="bad">{e} ✕</Badge></button>)}
              {[...blockedNodes].map((n) => <button key={n} onClick={() => toggle(blockedNodes, setBlockedNodes, n)}><Badge tone="bad">{n} ✕</Badge></button>)}
              {Object.entries(frame.exit_status).filter(([, s]) => s === 'blocked').map(([x]) => <Badge key={x} tone="bad">{x} (reported blocked)</Badge>)}
            </div>
            <div className="mt-2"><Button size="sm" onClick={run} busy={busy}>Re-plan</Button></div>
            {err && <div className="mt-2"><ErrorBox>{err}</ErrorBox></div>}
          </Card>
          {plan && (
            <Card title={plan.recommended ? 'Route options' : 'No safe route'} subtitle={`Conditions from ${frame.clock}`}>
              <div className="space-y-2">
                {routes.map((r, i) => <RouteRow key={r.id} r={r} active={shown === r.id} recommended={i === 0} onClick={() => setShown(r.id)} />)}
                {!plan.recommended && <p className="text-sm text-critical-ink">Do not move people: no option satisfies every hard safety rule.</p>}
              </div>
              {shownRoute && <div className="mt-3 border-t border-line pt-2"><p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Checks for {shownRoute.id}</p><Checks checks={shownRoute.checks} /></div>}
            </Card>
          )}
        </div>
      </div>
      {plan && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card title="Why this recommendation">
            <ul className="list-disc space-y-1 pl-4 text-xs text-ink-2">{plan.explanation.map((e) => <li key={e}>{e}</li>)}</ul>
            {plan.allocation.length > 0 && (
              <div className="mt-2 border-t border-line pt-2 text-xs">
                <p className="mb-1 font-semibold">Allocation (destination capacity validated on the upper estimate)</p>
                {plan.allocation.map((a) => <p key={a.destination}>~{a.people.toLocaleString()} → {a.destination_name} via {a.via.join(', ') || 'direct'} ({a.route_id})</p>)}
                {plan.unallocated > 0 && <p className="text-critical-ink">{plan.unallocated.toLocaleString()} cannot be placed safely</p>}
              </div>
            )}
          </Card>
          <Card title="Distance-shortest path (assessed, not assumed safe)" subtitle={`${plan.shortest_path.names.join(' → ')} · ${plan.shortest_path.length_m} m`}>
            <Badge tone={plan.shortest_path.safe ? 'good' : 'bad'}>{plan.shortest_path.safe ? 'passes hard checks' : 'rejected'}</Badge>
            <div className="mt-2"><Checks checks={plan.shortest_path.checks} /></div>
          </Card>
          <Card title="Destinations not used">
            {plan.rejected_destinations.length === 0 ? <p className="text-xs text-muted">None rejected.</p> : (
              <ul className="space-y-1 text-xs">{plan.rejected_destinations.map((d) => <li key={d.id}><span className="font-medium">{d.name}</span> <span className="text-muted">— {d.reason}</span></li>)}</ul>
            )}
            <p className="mt-2 text-[11px] text-muted">{plan.advisory}</p>
          </Card>
        </div>
      )}
    </div>
  )
}

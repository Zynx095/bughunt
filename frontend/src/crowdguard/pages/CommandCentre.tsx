import { Bot, Radio } from 'lucide-react'
import { useMemo, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { Badge, Button, Card, PageHeader } from '../../components/ui'
import { useDarkMode } from '../../lib/hooks'
import { cgResult } from '../api'
import { fmtInt, useCrowd } from '../store'
import { VenueMap } from '../VenueMap'
import { AlertList, Kpi, PlaybackBar, RecommendationCard, SafetyNotice, SimGate } from '../widgets'

export function CommandCentrePage() {
  return <SimGate><CommandCentre /></SimGate>
}

function CommandCentre() {
  const { venue, sim, frame, tick } = useCrowd()
  const [routeRecId, setRouteRecId] = useState<string | null>(null)
  const [brief, setBrief] = useState<{ text: string; provider: string; fallback: boolean; tick: number } | null>(null)
  const [briefBusy, setBriefBusy] = useState(false)
  const [briefErr, setBriefErr] = useState<string | null>(null)
  const dark = useDarkMode()
  const trend = useMemo(() => {
    if (!sim || !venue) return []
    const cap = venue.zones.find((z) => z.id === 'main_stage')?.safe_capacity ?? 1
    return sim.frames.slice(0, tick + 1).map((f, i) => ({
      clock: f.clock,
      main_stage: f.readings.main_stage.occupancy_pct,
      second_stage: f.readings.second_stage.occupancy_pct,
      food_court: f.readings.food_court.occupancy_pct,
      no_intervention: Math.round((sim.counterfactual.main_stage[i] / cap) * 1000) / 10,
    }))
  }, [sim, tick, venue])
  if (!venue || !sim || !frame) return null
  const s = frame.summary
  const routable = frame.recommendations.filter((r) => r.route?.recommended)
  const shown = routable.find((r) => r.id === routeRecId) ?? routable.find((r) => r.action_type === 'relieve_zone') ?? routable[0]
  const pastEvents = sim.events.filter((e) => e.tick <= tick).slice(-5).reverse()
  const ms = frame.readings.main_stage


  async function briefing() {
    setBriefBusy(true)
    setBriefErr(null)
    try {
      const { result, env } = await cgResult<{ explanation: string }>('/explain', { tick, audience: 'executive' })
      setBrief({ text: result.explanation, provider: String(env.metadata.provider ?? 'unknown'), fallback: Boolean(env.metadata.fallback), tick })
    } catch (e) {
      setBriefErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBriefBusy(false)
    }
  }

  const ax = { stroke: dark ? '#383835' : '#c3c2b7', tick: { fill: '#898781', fontSize: 11 }, tickLine: false }
  return (
    <div className="space-y-4">
      <PageHeader title="Event Safety Command Centre" icon={<Radio className="mt-1 size-6 text-[var(--accent)]" />}
        description={<>{venue.name}. Zone occupancy estimates, alerts, forecasts and advisory routes, recomputed by the backend for every minute of the scenario.</>} />
      <PlaybackBar />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-3">
          <VenueMap venue={venue} readings={frame.readings} edgeFlows={frame.edge_flows} exitStatus={frame.exit_status}
            route={shown?.route?.recommended ?? null} label={`Venue map · ${frame.clock}${frame.intervention_active ? ' · intervention active' : ''}`} />
          {shown?.route?.recommended && (
            <div className="rounded-lg border border-[#0ea5e9]/40 bg-[#0ea5e9]/5 px-3 py-2 text-xs text-ink-2">
              <span className="font-semibold text-ink">Route on map ({shown.route.recommended.id}):</span> {shown.route.recommended.names.join(' → ')} ·{' '}
              {shown.route.recommended.length_m} m · bottleneck {Math.round(shown.route.recommended.bottleneck_capacity_ppm ?? 0)} people/min.{' '}
              {shown.route.explanation.slice(-1)[0]}
            </div>
          )}
          <SafetyNotice />
        </div>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <Kpi label="Estimated attendance" value={fmtInt(s.estimated_attendance)} sub={`interval ${fmtInt(s.attendance_lower)}–${fmtInt(s.attendance_upper)}`} />
            <Kpi label="Main Stage" value={`${ms.occupancy_pct ?? '—'}%`} sub={`${fmtInt(ms.estimate)} of ${fmtInt(ms.safe_capacity)} · ${ms.band}`}
              tone={ms.band === 'critical' || ms.band === 'high' ? 'bad' : ms.band === 'elevated' ? 'warn' : 'good'} />
            <Kpi label="Critical / high alerts" value={`${s.alerts_critical} / ${s.alerts_high}`} tone={s.alerts_critical ? 'bad' : s.alerts_high ? 'warn' : 'good'} sub={`${s.alerts_total} active`} />
            <Kpi label="Exits available" value={`${s.exits_available} / ${s.exits_total}`} tone={s.exits_available < s.exits_total ? 'bad' : 'good'}
              sub={Object.entries(frame.exit_status).filter(([, v]) => v === 'blocked').map(([k]) => k).join(', ') || 'all open'} />
            <Kpi label="Zones high / critical" value={s.zones_high_or_critical} tone={s.zones_high_or_critical ? 'bad' : 'good'} />
            <Kpi label="Zones without live data" value={s.zones_without_live_data} tone={s.zones_without_live_data ? 'warn' : 'good'}
              sub={s.zones_without_live_data ? 'unknown, not empty' : 'all feeds live'} />
          </div>
          <Card title="Active alerts" subtitle="Configurable rules evaluated by the decision engine" actions={<Badge>{frame.alerts.length}</Badge>}>
            <div className="max-h-64 overflow-y-auto"><AlertList alerts={frame.alerts} max={10} /></div>
          </Card>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Card title="Recommended actions" subtitle="Advisory: each needs a human organiser's decision">
          {frame.recommendations.length === 0 ? <p className="text-sm text-good-ink">✔ No action recommended at {frame.clock}.</p> : (
            <div className="grid gap-2 md:grid-cols-2">
              {frame.recommendations.slice(0, 6).map((r) => (
                <RecommendationCard key={r.id} rec={r} active={shown?.id === r.id} onShowRoute={() => setRouteRecId(r.id)} />
              ))}
            </div>
          )}
        </Card>
        <div className="space-y-3">
          <Card title="Scenario log" subtitle="Simulated events (labelled)">
            <ul className="space-y-1.5 text-xs">
              {pastEvents.map((e) => (
                <li key={`${e.tick}-${e.text}`} className="flex gap-2"><span className="tabular font-mono text-muted">{sim.frames[e.tick]?.clock}</span>
                  <span className={e.kind === 'hazard' ? 'text-critical-ink' : e.kind === 'action' ? 'text-good-ink' : 'text-ink-2'}>{e.text}</span></li>
              ))}
            </ul>
            {frame.incidents.length > 0 && (
              <div className="mt-3 border-t border-line pt-2">
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Incidents (simulated lifecycle)</p>
                {frame.incidents.map((i) => <p key={i.id} className="flex items-center justify-between text-xs"><span>{i.id} {i.title}</span><Badge tone={i.status === 'resolved' ? 'good' : 'warn'}>{i.status}</Badge></p>)}
              </div>
            )}
          </Card>
          <Card title="Organiser briefing" subtitle="AI engine: Gemini if configured, otherwise the labelled local fallback"
            actions={<Button size="sm" onClick={briefing} busy={briefBusy}><Bot className="size-3.5" />Brief me</Button>}>
            {briefErr && <p className="text-xs text-critical-ink">{briefErr}</p>}
            {brief ? (
              <div>
                <p className="whitespace-pre-line text-sm text-ink">{brief.text}</p>
                <p className="mt-2 text-[11px] text-muted">Source: {brief.provider}{brief.fallback ? ' (deterministic local fallback — no LLM used)' : ''} · for {sim.frames[brief.tick]?.clock}</p>
              </div>
            ) : <p className="text-xs text-muted">Generates a plain-language summary of the current minute from backend facts only.</p>}
          </Card>
        </div>
      </div>

      <Card title="Occupancy trend (% of safe capacity)" subtitle={`Estimates up to ${frame.clock}. Dashed: same synthetic scenario with no organiser intervention (counterfactual, peak ${sim.counterfactual.peak_pct}%).`}>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={trend} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={dark ? '#2c2c2a' : '#e1e0d9'} vertical={false} />
            <XAxis dataKey="clock" {...ax} minTickGap={30} />
            <YAxis {...ax} width={40} domain={[0, 'auto']} unit="%" />
            <Tooltip contentStyle={{ background: 'var(--color-surface)', border: '1px solid var(--color-line)', fontSize: 12 }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <ReferenceLine y={100} stroke="#ef4444" strokeDasharray="4 4" label={{ value: 'safe capacity', fill: '#ef4444', fontSize: 11, position: 'insideTopRight' }} />
            <ReferenceLine y={85} stroke="#f97316" strokeDasharray="2 4" />
            <Line dataKey="main_stage" name="Main Stage" stroke="#ef4444" strokeWidth={2.5} dot={false} isAnimationActive={false} />
            <Line dataKey="no_intervention" name="Main Stage, no intervention (counterfactual)" stroke="#ef4444" strokeOpacity={0.45} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
            <Line dataKey="second_stage" name="Second Stage" stroke="#3b82f6" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="food_court" name="Food Court" stroke="#10b981" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
          </LineChart>
        </ResponsiveContainer>
      </Card>
    </div>
  )
}

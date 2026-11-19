import { BarChart3 } from 'lucide-react'
import { useMemo } from 'react'

import { ChartCard } from '../../components/charts'
import { DataTable } from '../../components/table'
import { Button, Card, PageHeader } from '../../components/ui'
import { useApp } from '../../context'
import type { ChartSpec } from '../../lib/types'
import { fmtInt, useCrowd } from '../store'
import { Kpi, SimGate, SyntheticBadge } from '../widgets'

export function CrowdAnalyticsPage() {
  return <SimGate><CrowdAnalytics /></SimGate>
}

function CrowdAnalytics() {
  const { venue, sim } = useCrowd()
  const { navigate } = useApp()
  const charts = useMemo<ChartSpec[]>(() => {
    if (!sim || !venue) return []
    const cap = Object.fromEntries(venue.zones.map((z) => [z.id, z.safe_capacity]))
    const f = sim.frames
    return [
      { type: 'line', title: 'Estimated attendance vs synthetic truth', x: 'clock',
        data: f.map((fr) => ({ clock: fr.clock, estimate: fr.summary.estimated_attendance, lower: fr.summary.attendance_lower, upper: fr.summary.attendance_upper,
          truth: Object.values(fr.readings).reduce((s, r) => s + (r.synthetic_truth ?? 0), 0) })),
        series: [{ key: 'estimate', label: 'Estimate (known zones)' }, { key: 'truth', label: 'Synthetic truth' }, { key: 'lower', label: 'Lower' }, { key: 'upper', label: 'Upper' }] },
      { type: 'line', title: 'Occupancy by zone (% of safe capacity)', x: 'clock',
        data: f.map((fr) => ({ clock: fr.clock, ...Object.fromEntries(venue.zones.map((z) => [z.id, fr.readings[z.id].occupancy_pct])) })),
        series: venue.zones.map((z) => ({ key: z.id, label: z.name })), reference_lines: [{ y: 100, label: 'safe capacity' }, { y: 85, label: 'high' }] },
      { type: 'line', title: 'Main Stage: with intervention vs counterfactual (no intervention)', x: 'clock',
        data: f.map((fr, i) => ({ clock: fr.clock, with_intervention: fr.readings.main_stage.estimate, no_intervention: sim.counterfactual.main_stage[i] })),
        series: [{ key: 'with_intervention', label: 'Estimate (organisers acted)' }, { key: 'no_intervention', label: 'No intervention (synthetic truth)' }],
        reference_lines: [{ y: cap.main_stage, label: 'safe capacity' }] },
      { type: 'line', title: 'Active alerts per minute by severity', x: 'clock',
        data: f.map((fr) => ({ clock: fr.clock, critical: fr.alerts.filter((a) => a.severity === 'critical').length, high: fr.alerts.filter((a) => a.severity === 'high').length,
          medium: fr.alerts.filter((a) => a.severity === 'medium').length })),
        series: [{ key: 'critical', label: 'Critical' }, { key: 'high', label: 'High' }, { key: 'medium', label: 'Medium' }] },
      { type: 'line', title: 'Arrivals per minute at the gates', x: 'clock',
        data: f.map((fr) => ({ clock: fr.clock, ...fr.arrivals_ppm })), series: Object.keys(f[0].arrivals_ppm).map((k) => ({ key: k, label: k.replace('_', ' ') })) },
      { type: 'line', title: 'Busiest corridor load (% of flow capacity) and Main Stage walking speed', x: 'clock',
        data: f.map((fr) => ({ clock: fr.clock, max_corridor_pct: Math.round(Math.max(0, ...fr.edge_flows.map((e) => e.utilisation)) * 100),
          main_stage_speed_cms: Math.round((fr.flows.main_stage?.mean_speed ?? 0) * 100) })),
        series: [{ key: 'max_corridor_pct', label: 'Busiest corridor % of capacity' }, { key: 'main_stage_speed_cms', label: 'Main Stage speed (cm/s)' }],
        reference_lines: [{ y: 90, label: 'bottleneck' }] },
    ]
  }, [sim, venue])
  if (!sim || !venue) return null
  const ev = sim.evaluation
  const bt = ev.main_stage_forecast_backtest
  const errRows = venue.zones.map((z) => ({ zone: z.name, ...(ev.estimation_error_vs_synthetic_truth[z.id] ?? {}) }))
  const ms = Object.entries(ev.milestones).map(([k, v]) => ({ milestone: k.replace(/_/g, ' '), clock: v?.clock ?? '—' }))
  return (
    <div className="space-y-4">
      <PageHeader title="Crowd Analytics" icon={<BarChart3 className="mt-1 size-6 text-[var(--accent)]" />}
        description="Whole-scenario trends and honest evaluation: estimation error against the simulator's hidden truth, forecast error against a persistence baseline, and the effect of the organisers' intervention."
        actions={<><SyntheticBadge /><Button size="sm" onClick={() => navigate('analytics')}>Platform telemetry →</Button></>} />
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <Kpi label="Main Stage peak (estimate)" value={`${ev.main_stage_peak.pct}%`} sub={`${fmtInt(ev.main_stage_peak.estimate)} at ${ev.main_stage_peak.clock}`} tone="bad" />
        <Kpi label="Peak with no intervention" value={`${sim.counterfactual.peak_pct}%`} sub={`${fmtInt(sim.counterfactual.peak)} (counterfactual)`} tone="bad" />
        <Kpi label="Forecast MAE (10-min, Main Stage)" value={bt.available ? fmtInt(bt.mae) : 'n/a'} sub={bt.available ? `persistence ${fmtInt(bt.baseline_mae)} · ${bt.beats_baseline ? 'beats' : 'does not beat'} baseline` : ''} tone={bt.beats_baseline ? 'good' : 'warn'} />
        <Kpi label="First warning" value={ev.milestones.first_rapid_build_up_alert?.clock ?? '—'} sub={`overcrowded at ${ev.milestones.first_overcrowded_alert?.clock ?? '—'}`} tone="warn" />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">{charts.map((c) => <ChartCard key={c.title} spec={c} />)}</div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Estimation error vs synthetic truth" subtitle={ev.note}>
          <DataTable columns={[{ key: 'zone', label: 'Zone' }, { key: 'mae', label: 'MAE (people)' }, { key: 'bias', label: 'Bias' }, { key: 'mape_pct', label: 'MAPE %' }]} rows={errRows} enableExport={false} />
        </Card>
        <Card title="Scenario milestones" subtitle="First minute each alert type fired (computed from backend alerts)">
          <DataTable columns={[{ key: 'milestone', label: 'Milestone' }, { key: 'clock', label: 'Clock' }]} rows={ms} enableFilter={false} enableExport={false} />
        </Card>
      </div>
    </div>
  )
}

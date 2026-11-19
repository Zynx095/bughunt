import { Layers } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { Card, PageHeader } from '../../components/ui'
import { cx } from '../../lib/cx'
import { useDarkMode } from '../../lib/hooks'
import { fmtInt, useCrowd } from '../store'
import { VenueMap } from '../VenueMap'
import { AlertList, BandPill, PlaybackBar, SimGate } from '../widgets'

export function ZoneIntelligencePage() {
  return <SimGate><ZoneIntelligence /></SimGate>
}

function ZoneIntelligence() {
  const { venue, sim, frame, tick } = useCrowd()
  const [sel, setSel] = useState('main_stage')
  const dark = useDarkMode()
  const zone = venue?.zones.find((z) => z.id === sel)
  const history = useMemo(() => (sim ? sim.frames.slice(0, tick + 1).map((f) => {
    const r = f.readings[sel]
    return { clock: f.clock, estimate: r.feed_status === 'ok' ? r.estimate : null, carried: r.carried_forward ? r.estimate : null,
      band: r.lower != null && r.upper != null ? [r.lower, r.upper] : null, observed: r.observed_count, truth: r.synthetic_truth }
  }) : []), [sim, tick, sel])
  if (!venue || !frame || !zone) return null
  const r = frame.readings[sel]
  const flow = frame.flows[sel] ?? {}
  const fc = frame.forecasts[sel]
  const zoneAlerts = frame.alerts.filter((a) => a.target === sel)
  const ax = { stroke: dark ? '#383835' : '#c3c2b7', tick: { fill: '#898781', fontSize: 11 }, tickLine: false }

  return (
    <div className="space-y-4">
      <PageHeader title="Zone Intelligence" icon={<Layers className="mt-1 size-6 text-[var(--accent)]" />}
        description="Per-zone population estimates with uncertainty, density, level of service, feed health and data quality. Observed counts, occlusion-corrected estimates and synthetic truth are kept separate." />
      <PlaybackBar />
      <div className="overflow-x-auto rounded-xl border border-line bg-surface">
        <table className="w-full min-w-[980px] text-left text-xs">
          <thead><tr className="border-b border-line text-muted">
            {['Zone', 'Band', 'Observed', 'Estimate (interval)', 'Safe cap.', 'Occupancy', 'Density p/m²', 'LOS', 'Trend', 'Forecast peak', 'Feed', 'Confidence', 'Quality'].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}
          </tr></thead>
          <tbody>
            {venue.zones.map((z) => {
              const zr = frame.readings[z.id]
              const zf = frame.forecasts[z.id]
              const prev = sim?.frames[Math.max(0, tick - 5)]?.readings[z.id]
              const delta = zr.occupancy_pct != null && prev?.occupancy_pct != null ? zr.occupancy_pct - prev.occupancy_pct : null
              return (
                <tr key={z.id} onClick={() => setSel(z.id)} className={cx('cursor-pointer border-b border-line/60 hover:bg-surface-2', sel === z.id && 'bg-[var(--accent)]/5')}>
                  <td className="px-3 py-2 font-medium text-ink">{z.name}</td>
                  <td className="px-3 py-2"><BandPill band={zr.band} /></td>
                  <td className="tabular px-3 py-2">{fmtInt(zr.observed_count)}</td>
                  <td className="tabular px-3 py-2">{zr.estimate != null ? `${fmtInt(zr.estimate)} (${fmtInt(zr.lower)}–${fmtInt(zr.upper)})` : 'unknown'}{zr.carried_forward && <span className="ml-1 text-warn-ink">carried</span>}</td>
                  <td className="tabular px-3 py-2">{fmtInt(z.safe_capacity)}</td>
                  <td className="tabular px-3 py-2 font-semibold">{zr.occupancy_pct != null ? `${zr.occupancy_pct}%` : '—'}</td>
                  <td className="tabular px-3 py-2">{zr.density_ppm2 ?? '—'}</td>
                  <td className="px-3 py-2">{zr.level_of_service ?? '—'}</td>
                  <td className="tabular px-3 py-2">{delta != null ? `${delta > 0 ? '▲' : delta < 0 ? '▼' : '■'} ${delta > 0 ? '+' : ''}${delta.toFixed(1)} pts / 5 min` : '—'}</td>
                  <td className="tabular px-3 py-2">{zf?.available ? `${zf.peak_pct}%${zf.minutes_to_capacity ? ` · cap in ${zf.minutes_to_capacity} min` : ''}` : '—'}</td>
                  <td className="px-3 py-2">{zr.feed_status}</td>
                  <td className="tabular px-3 py-2">{zr.confidence}</td>
                  <td className="px-3 py-2">{zr.data_quality}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 xl:grid-cols-[420px_minmax(0,1fr)]">
        <div className="space-y-3">
          <VenueMap venue={venue} readings={frame.readings} edgeFlows={frame.edge_flows} exitStatus={frame.exit_status} selected={sel} onSelect={setSel} compact showFlows={false} />
          <Card title={zone.name} subtitle={`${zone.kind} · ${zone.area_m2.toLocaleString()} m² · safe capacity ${fmtInt(zone.safe_capacity)} (${(zone.safe_capacity / zone.area_m2).toFixed(2)} p/m²) · camera ${zone.camera_id}`}>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
              <dt className="text-muted">Observed (sensor)</dt><dd className="tabular">{fmtInt(r.observed_count)} <span className="text-muted">({r.value_kind})</span></dd>
              <dt className="text-muted">Estimate</dt><dd className="tabular font-semibold">{fmtInt(r.estimate)} [{fmtInt(r.lower)}–{fmtInt(r.upper)}]</dd>
              <dt className="text-muted">Assumed detector recall</dt><dd className="tabular">{r.recall_assumed ?? '—'}</dd>
              <dt className="text-muted">Spare capacity (upper)</dt><dd className="tabular">{fmtInt(r.spare_capacity)}</dd>
              <dt className="text-muted">Method</dt><dd>{r.method}</dd>
              <dt className="text-muted">Inflow / outflow</dt><dd className="tabular">{flow.inflow_ppm ?? '—'} / {flow.outflow_ppm ?? '—'} per min</dd>
              <dt className="text-muted">Net movement</dt><dd>{flow.net_ppm != null ? `${flow.net_ppm > 0 ? '+' : ''}${flow.net_ppm}/min` : '—'} {flow.direction ? `towards ${flow.direction}` : ''}</dd>
              <dt className="text-muted">Mean walking speed</dt><dd className="tabular">{flow.mean_speed ?? '—'} m/s</dd>
              {r.synthetic_truth != null && <><dt className="text-muted">Synthetic truth</dt><dd className="tabular">{fmtInt(r.synthetic_truth)} <span className="text-muted">(simulator only)</span></dd></>}
              {fc?.available && <><dt className="text-muted">15-min forecast</dt><dd className="tabular">{fc.predicted_end_pct}% ({fc.method})</dd></>}
            </dl>
            {r.notes.length > 0 && <ul className="mt-2 list-disc pl-4 text-[11px] text-warn-ink">{r.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
          </Card>
        </div>
        <div className="space-y-3">
          <Card title={`${zone.name}: estimate history`} subtitle="Shaded = estimate interval; grey dashed = raw sensor count; dotted = synthetic truth (simulator only)">
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={history} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={dark ? '#2c2c2a' : '#e1e0d9'} vertical={false} />
                <XAxis dataKey="clock" {...ax} minTickGap={30} />
                <YAxis {...ax} width={52} />
                <Tooltip contentStyle={{ background: 'var(--color-surface)', border: '1px solid var(--color-line)', fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Area dataKey="band" name="interval" stroke="none" fill="#0ea5e9" fillOpacity={0.18} isAnimationActive={false} />
                <ReferenceLine y={zone.safe_capacity} stroke="#ef4444" strokeDasharray="4 4" label={{ value: 'safe capacity', fill: '#ef4444', fontSize: 11, position: 'insideTopRight' }} />
                <Line dataKey="estimate" name="estimate" stroke="#0ea5e9" strokeWidth={2.5} dot={false} isAnimationActive={false} />
                <Line dataKey="carried" name="carried forward (stale)" stroke="#f59e0b" strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
                <Line dataKey="observed" name="observed (sensor)" stroke="#9ca3af" strokeDasharray="4 3" dot={false} isAnimationActive={false} />
                <Line dataKey="truth" name="synthetic truth" stroke="var(--color-ink-2)" strokeDasharray="1 3" dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </Card>
          <Card title="Alerts for this zone"><AlertList alerts={zoneAlerts} empty="No alerts for this zone" /></Card>
        </div>
      </div>
    </div>
  )
}

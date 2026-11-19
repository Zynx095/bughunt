import { TrendingUp } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { Badge, Card, ErrorBox, PageHeader, Spinner } from '../../components/ui'
import { useDarkMode } from '../../lib/hooks'
import { cgResult } from '../api'
import { fmtInt, useCrowd } from '../store'
import type { ZoneForecast } from '../types'
import { BandPill, PlaybackBar, SimGate } from '../widgets'

interface MlForecast { forecast: number[]; lower: number[]; upper: number[]; selected_model: string; peak_pct: number; minutes_to_capacity: number | null
  backtest: { holdout_points: number; model_mae: number; baseline: string; baseline_mae: number; beats_baseline: boolean }; interval_note?: string }
interface ForecastResp { zone_id: string; capacity: number; history: number[]; deterministic: ZoneForecast; ml_engine: MlForecast | null
  rolling_backtest: { available: boolean; mae?: number; baseline_mae?: number; beats_baseline?: boolean; origins?: number; horizon?: number; reason?: string } }

export function ForecastingPage() {
  return <SimGate><Forecasting /></SimGate>
}

function Forecasting() {
  const { venue, sim, frame, tick } = useCrowd()
  const [zone, setZone] = useState('main_stage')
  const [hindsight, setHindsight] = useState(false)
  const [ml, setMl] = useState<ForecastResp | null>(null)
  const [mlWarn, setMlWarn] = useState<string[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const dark = useDarkMode()

  useEffect(() => {
    let cancelled = false
    const id = window.setTimeout(() => {
      setBusy(true)
      setErr(null)
      cgResult<ForecastResp>('/forecast', { zone_id: zone, tick, horizon: 15 })
        .then(({ result, env }) => { if (!cancelled) { setMl(result); setMlWarn(env.warnings) } })
        .catch((e) => { if (!cancelled) setErr(e instanceof Error ? e.message : String(e)) })
        .finally(() => { if (!cancelled) setBusy(false) })
    }, 250)
    return () => { cancelled = true; window.clearTimeout(id) }
  }, [zone, tick])

  const z = venue?.zones.find((x) => x.id === zone)
  const fc = frame?.forecasts[zone]
  const data = useMemo(() => {
    if (!sim || !fc || !z) return []
    const rows: Record<string, unknown>[] = sim.frames.slice(0, tick + 1).map((f) => ({ clock: f.clock, history: f.readings[zone].estimate }))
    const n = sim.frames.length
    for (let h = 1; h <= (fc.available ? fc.horizon : 0); h++) {
      const i = tick + h
      const clock = i < n ? sim.frames[i].clock : `+${h}m`
      const mlv = ml?.ml_engine && ml.history.length ? ml.ml_engine : null
      rows.push({
        clock, det: fc.forecast[h - 1], band: [fc.lower[h - 1], fc.upper[h - 1]],
        ml: mlv?.forecast[h - 1] != null ? Math.round(mlv.forecast[h - 1]) : null,
        actual: hindsight && i < n ? sim.frames[i].readings[zone].estimate : null,
      })
    }
    return rows
  }, [sim, fc, z, tick, zone, ml, hindsight])

  if (!venue || !frame || !z || !fc) return null
  const ax = { stroke: dark ? '#383835' : '#c3c2b7', tick: { fill: '#898781', fontSize: 11 }, tickLine: false }
  const mle = ml?.ml_engine

  return (
    <div className="space-y-4">
      <PageHeader title="Crowd Forecasting" icon={<TrendingUp className="mt-1 size-6 text-[var(--accent)]" />}
        description="15-minute occupancy forecasts per zone, using only data up to the current minute. A deterministic damped-trend method (with fallbacks for short history) drives the alerts; the ML engine's backtested model selection is shown alongside with its error against a naive baseline." />
      <PlaybackBar />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card title={`${z.name}: forecast from ${frame.clock}`} subtitle="Shaded = 95% band of the deterministic forecast (widens with horizon)"
          actions={<>
            <select value={zone} onChange={(e) => setZone(e.target.value)} className="rounded-md border border-line bg-surface px-2 py-1 text-xs" aria-label="Zone">
              {venue.zones.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
            <label className="flex items-center gap-1 text-xs text-ink-2" title="Reveal what the synthetic scenario actually did next"><input type="checkbox" checked={hindsight} onChange={(e) => setHindsight(e.target.checked)} />Hindsight</label>
          </>}>
          <ResponsiveContainer width="100%" height={320}>
            <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid stroke={dark ? '#2c2c2a' : '#e1e0d9'} vertical={false} />
              <XAxis dataKey="clock" {...ax} minTickGap={28} />
              <YAxis {...ax} width={52} />
              <Tooltip contentStyle={{ background: 'var(--color-surface)', border: '1px solid var(--color-line)', fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Area dataKey="band" name="95% band" stroke="none" fill="#f97316" fillOpacity={0.15} isAnimationActive={false} />
              <ReferenceLine y={z.safe_capacity} stroke="#ef4444" strokeDasharray="4 4" label={{ value: `safe capacity ${fmtInt(z.safe_capacity)}`, fill: '#ef4444', fontSize: 11, position: 'insideTopLeft' }} />
              <ReferenceLine x={frame.clock} stroke="var(--color-muted)" label={{ value: 'now', fill: '#898781', fontSize: 11, position: 'top' }} />
              <Line dataKey="history" name="estimate (history)" stroke="#0ea5e9" strokeWidth={2.5} dot={false} isAnimationActive={false} />
              <Line dataKey="det" name={`deterministic: ${fc.method}`} stroke="#f97316" strokeWidth={2.5} strokeDasharray="6 3" dot={false} isAnimationActive={false} />
              <Line dataKey="ml" name={mle ? `ML engine: ${mle.selected_model}` : 'ML engine (n/a)'} stroke="#a855f7" strokeWidth={2} strokeDasharray="2 3" dot={false} isAnimationActive={false} />
              {hindsight && <Line dataKey="actual" name="what happened (synthetic)" stroke="var(--color-ink)" strokeWidth={1.5} dot={{ r: 2 }} isAnimationActive={false} />}
            </ComposedChart>
          </ResponsiveContainer>
          {busy && <Spinner label="Asking the ML engine" />}
          {err && <ErrorBox>{err}</ErrorBox>}
          {mlWarn.length > 0 && <p className="mt-1 text-[11px] text-muted">{mlWarn.join(' ')}</p>}
        </Card>
        <div className="space-y-3">
          <Card title="Prediction vs current">
            {fc.available ? (
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
                <dt className="text-muted">Now</dt><dd className="tabular font-semibold">{fmtInt(fc.current)} ({fc.current_pct}%)</dd>
                <dt className="text-muted">In {fc.horizon} min</dt><dd className="tabular font-semibold">{fmtInt(fc.predicted_end)} ({fc.predicted_end_pct}%)</dd>
                <dt className="text-muted">Change</dt><dd className="tabular">{fc.delta_vs_current > 0 ? '+' : ''}{fmtInt(fc.delta_vs_current)}</dd>
                <dt className="text-muted">Band at horizon</dt><dd className="tabular">{fmtInt(fc.lower.at(-1))}–{fmtInt(fc.upper.at(-1))}</dd>
                <dt className="text-muted">Reaches capacity</dt><dd className="tabular">{fc.current_pct >= 100 ? 'already above safe capacity' : fc.minutes_to_capacity ? `in ~${fc.minutes_to_capacity} min` : 'not within horizon'}</dd>
                <dt className="text-muted">Possible breach (upper band)</dt><dd className="tabular">{fc.minutes_to_possible_breach ? `in ~${fc.minutes_to_possible_breach} min` : 'no'}</dd>
                <dt className="text-muted">P(exceed) at horizon</dt><dd className="tabular">{fc.p_exceed_at_horizon} <span className="text-muted">heuristic</span></dd>
                <dt className="text-muted">Method</dt><dd>{fc.method} ({fc.history_points} pts)</dd>
              </dl>
            ) : <p className="text-xs text-muted">{fc.reason}</p>}
          </Card>
          <Card title="ML engine (ml.forecast)" subtitle="Backtested model selection; scored on an untouched window">
            {mle ? (
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
                <dt className="text-muted">Selected model</dt><dd>{mle.selected_model}</dd>
                <dt className="text-muted">Backtest MAE</dt><dd className="tabular">{mle.backtest.model_mae.toFixed(0)} people</dd>
                <dt className="text-muted">Baseline ({mle.backtest.baseline})</dt><dd className="tabular">{mle.backtest.baseline_mae.toFixed(0)} people</dd>
                <dt className="text-muted">Beats baseline</dt><dd><Badge tone={mle.backtest.beats_baseline ? 'good' : 'warn'}>{mle.backtest.beats_baseline ? 'yes' : 'no'}</Badge></dd>
                <dt className="text-muted">Peak forecast</dt><dd className="tabular">{mle.peak_pct}%</dd>
                <dt className="text-muted">Reaches capacity</dt><dd className="tabular">{mle.minutes_to_capacity ? `in ~${mle.minutes_to_capacity} min` : 'no'}</dd>
              </dl>
            ) : <p className="text-xs text-muted">Not enough history yet (needs ≥ 16 minutes); the deterministic fallback is used alone.</p>}
            {ml?.rolling_backtest.available && (
              <p className="mt-2 border-t border-line pt-2 text-[11px] text-ink-2">Rolling-origin check of the deterministic method ({ml.rolling_backtest.origins} origins, {ml.rolling_backtest.horizon}-min horizon): MAE {ml.rolling_backtest.mae} vs persistence {ml.rolling_backtest.baseline_mae} — {ml.rolling_backtest.beats_baseline ? 'beats' : 'does not beat'} the baseline.</p>
            )}
          </Card>
        </div>
      </div>
      <Card title="All zones: forecast summary" subtitle={`From ${frame.clock}; horizon ${fc.horizon} min`}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead><tr className="border-b border-line text-muted">{['Zone', 'Band now', 'Now', 'Predicted', 'Peak', 'Reaches capacity', 'Possible breach', 'P(exceed)', 'Method'].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {venue.zones.map((x) => {
                const f = frame.forecasts[x.id]
                return (
                  <tr key={x.id} className="cursor-pointer border-b border-line/60 hover:bg-surface-2" onClick={() => setZone(x.id)}>
                    <td className="px-2 py-1.5 font-medium">{x.name}</td>
                    <td className="px-2 py-1.5"><BandPill band={frame.readings[x.id].band} /></td>
                    <td className="tabular px-2 py-1.5">{f.available ? `${f.current_pct}%` : '—'}</td>
                    <td className="tabular px-2 py-1.5">{f.available ? `${f.predicted_end_pct}%` : '—'}</td>
                    <td className="tabular px-2 py-1.5">{f.available ? `${f.peak_pct}%` : '—'}</td>
                    <td className="tabular px-2 py-1.5">{f.available && f.current_pct >= 100 ? 'already above' : f.minutes_to_capacity ? `${f.minutes_to_capacity} min` : '—'}</td>
                    <td className="tabular px-2 py-1.5">{f.minutes_to_possible_breach ? `${f.minutes_to_possible_breach} min` : '—'}</td>
                    <td className="tabular px-2 py-1.5">{f.available ? f.p_exceed_at_horizon : '—'}</td>
                    <td className="px-2 py-1.5 text-muted">{f.method}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

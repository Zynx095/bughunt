import { AlertTriangle, ChevronLeft, ChevronRight, FlaskConical, Pause, Play, RotateCcw, ShieldAlert, UserCheck, XCircle } from 'lucide-react'
import type { ReactNode } from 'react'

import { Badge, Button, ErrorBox, Spinner } from '../components/ui'
import { cx } from '../lib/cx'
import { BAND_COLOR, BAND_LABEL, SEVERITY_TONE, useCrowd } from './store'
import type { Alert, Recommendation } from './types'

export function SyntheticBadge() {
  return (
    <Badge tone="warn" title="Deterministic simulation output; not real crowd data">
      <FlaskConical className="size-3" aria-hidden /> SYNTHETIC SIMULATION
    </Badge>
  )
}

export function SafetyNotice({ className }: { className?: string }) {
  return (
    <p className={cx('flex items-start gap-1.5 text-[11px] leading-snug text-muted', className)}>
      <ShieldAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      Estimates, not ground truth. CROWDGUARD does not certify event safety; organisers make every intervention decision, and no software recommendation may close an emergency exit.
    </p>
  )
}

export function BandPill({ band }: { band: string }) {
  const c = BAND_COLOR[band] ?? BAND_COLOR.unknown
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px] font-semibold"
      style={{ borderColor: `${c}66`, background: `${c}1f`, color: 'var(--color-ink)' }}>
      <span className="inline-block size-2 rounded-full" style={{ background: c }} aria-hidden />
      {BAND_LABEL[band] ?? band}
    </span>
  )
}

export function SeverityBadge({ severity }: { severity: string }) {
  const Icon = severity === 'critical' || severity === 'high' ? XCircle : AlertTriangle
  return <Badge tone={SEVERITY_TONE[severity] ?? 'neutral'}><Icon className="size-3" aria-hidden />{severity}</Badge>
}

/** Loads the shared simulation on first use and shows its state. */
export function SimGate({ children }: { children: ReactNode }) {
  const { sim, venue, loading, error, load } = useCrowd()
  if (error) return <ErrorBox><p>Could not load the CROWDGUARD simulation: {error}</p><button className="mt-1 underline" onClick={load}>Retry</button></ErrorBox>
  if (!sim || !venue) return <Spinner label={loading ? 'Running deterministic event simulation' : 'Preparing'} />
  return <>{children}</>
}

export function PlaybackBar() {
  const { sim, frame, tick, setTick, playing, setPlaying, speedMs, setSpeedMs, options, setOptions, loading } = useCrowd()
  if (!sim || !frame) return null
  const last = sim.frames.length - 1
  const m = sim.evaluation.milestones
  const marks: { label: string; tick?: number }[] = [
    { label: 'Build-up detected', tick: m.first_rapid_build_up_alert?.tick },
    { label: 'Forecast breach', tick: m.first_forecast_breach_alert?.tick },
    { label: 'Overcrowded', tick: m.first_overcrowded_alert?.tick },
    { label: 'Exit blocked', tick: m.exit_blocked_alert?.tick },
    { label: 'Feed lost', tick: m.stale_feed_alert?.tick },
  ]
  return (
    <div className="rounded-xl border border-line bg-surface p-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-[92px]">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted">Event clock</p>
          <p className="tabular font-mono text-2xl font-bold text-ink">{frame.clock}</p>
        </div>
        <div className="flex items-center gap-1">
          <Button size="sm" onClick={() => setTick(tick - 1)} disabled={tick <= 0} title="Previous minute"><ChevronLeft className="size-4" /></Button>
          <Button size="sm" variant="primary" onClick={() => { if (tick >= last) setTick(0); setPlaying(!playing) }} title={playing ? 'Pause' : 'Play'}>
            {playing ? <Pause className="size-4" /> : <Play className="size-4" />}{playing ? 'Pause' : 'Play'}
          </Button>
          <Button size="sm" onClick={() => setTick(tick + 1)} disabled={tick >= last} title="Next minute"><ChevronRight className="size-4" /></Button>
          <Button size="sm" variant="ghost" onClick={() => { setPlaying(false); setTick(0) }} title="Restart"><RotateCcw className="size-4" /></Button>
        </div>
        <label className="flex items-center gap-1.5 text-xs text-ink-2">Speed
          <select value={speedMs} onChange={(e) => setSpeedMs(Number(e.target.value))} className="rounded-md border border-line bg-surface px-1.5 py-1 text-xs">
            <option value={1500}>slow</option><option value={900}>normal</option><option value={350}>fast</option>
          </select>
        </label>
        <div className="ml-auto flex flex-wrap items-center gap-3 text-xs text-ink-2">
          <label className="flex items-center gap-1.5" title="Re-runs the deterministic scenario with or without the organisers acting on the recommendation">
            <input type="checkbox" checked={options.intervention} onChange={(e) => setOptions({ ...options, intervention: e.target.checked })} />
            Organisers act on recommendation
          </label>
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={options.exit_blockage} onChange={(e) => setOptions({ ...options, exit_blockage: e.target.checked })} />Exit blockage</label>
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={options.feed_outage} onChange={(e) => setOptions({ ...options, feed_outage: e.target.checked })} />Camera outage</label>
          {loading && <span className="text-muted">re-simulating…</span>}
          <SyntheticBadge />
        </div>
      </div>
      <div className="mt-3">
        <input type="range" min={0} max={last} value={tick} onChange={(e) => { setPlaying(false); setTick(Number(e.target.value)) }}
          className="w-full accent-[var(--accent)]" aria-label="Simulation minute" />
        <div className="mt-1 flex flex-wrap gap-1.5">
          {marks.filter((x) => x.tick !== undefined).map((x) => (
            <button key={x.label} onClick={() => { setPlaying(false); setTick(x.tick as number) }}
              className={cx('rounded-md border px-2 py-0.5 text-[11px] transition', tick === x.tick ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-ink' : 'border-line text-ink-2 hover:bg-surface-2')}>
              {x.label} · {sim.frames[x.tick as number]?.clock}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

export function AlertList({ alerts, max = 8, empty = 'No active alerts' }: { alerts: Alert[]; max?: number; empty?: string }) {
  if (!alerts.length) return <p className="py-3 text-sm text-good-ink">✔ {empty}</p>
  return (
    <ul className="divide-y divide-line">
      {alerts.slice(0, max).map((a) => (
        <li key={a.id} className="flex items-start gap-2 py-2">
          <SeverityBadge severity={a.severity} />
          <div className="min-w-0 flex-1">
            <p className="text-sm text-ink">{a.message}</p>
            <p className="text-[11px] text-muted">{a.rule_description} · rule <code className="font-mono">{a.rule}</code>{a.confidence != null && ` · confidence ${a.confidence}`}</p>
          </div>
        </li>
      ))}
      {alerts.length > max && <li className="py-1.5 text-[11px] text-muted">+{alerts.length - max} more</li>}
    </ul>
  )
}

export function RecommendationCard({ rec, onShowRoute, active }: { rec: Recommendation; onShowRoute?: () => void; active?: boolean }) {
  return (
    <div className={cx('rounded-lg border p-3', active ? 'border-[#0ea5e9] bg-[#0ea5e9]/5' : 'border-line')}>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="tabular text-xs font-bold text-muted">#{rec.priority}</span>
        <SeverityBadge severity={rec.severity} />
        <Badge tone="info"><UserCheck className="size-3" aria-hidden />human decision</Badge>
        {!rec.permitted && <Badge tone="bad">refused by guard</Badge>}
      </div>
      <p className="mt-1.5 text-sm font-semibold text-ink">{rec.title}</p>
      <p className="mt-0.5 text-xs text-ink-2">{rec.detail}</p>
      {rec.rationale.length > 0 && (
        <details className="mt-1.5 text-xs text-ink-2">
          <summary className="cursor-pointer text-muted">Why ({rec.rationale.length})</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">{rec.rationale.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </details>
      )}
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="text-[11px] text-muted">{rec.confidence != null ? `data confidence ${rec.confidence}` : 'confidence n/a'}</span>
        {onShowRoute && rec.route?.recommended && <Button size="sm" onClick={onShowRoute}>{active ? 'Shown on map' : 'Show route'}</Button>}
      </div>
    </div>
  )
}

export function Kpi({ label, value, sub, tone = 'neutral' }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'neutral' | 'good' | 'warn' | 'bad' }) {
  const bar = { neutral: 'bg-line', good: 'bg-good', warn: 'bg-warn', bad: 'bg-critical' }[tone]
  const Icon = tone === 'bad' ? XCircle : tone === 'warn' ? AlertTriangle : null
  return (
    <div className="relative overflow-hidden rounded-xl border border-line bg-surface px-3 py-2.5">
      <span className={cx('absolute inset-y-0 left-0 w-1', bar)} aria-hidden />
      <p className="flex items-center gap-1 text-[11px] font-medium text-muted">{Icon && <Icon className="size-3" aria-label={tone} />}{label}</p>
      <p className="tabular mt-0.5 text-xl font-bold text-ink">{value}</p>
      {sub && <p className="truncate text-[11px] text-muted">{sub}</p>}
    </div>
  )
}

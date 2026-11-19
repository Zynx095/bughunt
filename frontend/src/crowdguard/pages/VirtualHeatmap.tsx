import { Columns2, Crosshair, Flame, Pause, Play, RotateCcw, StepForward } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { Badge, Button, Card, ErrorBox, PageHeader, Spinner, Tabs, WarnBox } from '../../components/ui'
import { useApp } from '../../context'
import { get } from '../../lib/api'
import { cx } from '../../lib/cx'
import { cg, cgResult } from '../api'
import { SafetyNotice } from '../widgets'

type ViewId = 'camera' | 'birdseye' | 'heatmap' | 'movement' | 'digital_twin'
type Views = Partial<Record<ViewId, string | null>> & { frame_idx?: number | null }
interface Pt { x: number; y: number }
type Quad = Record<'top_left' | 'top_right' | 'bottom_right' | 'bottom_left', Pt>
interface CalibrationCfg { source_points: Quad; target_width_px: number; target_height_px: number; ground_width_meters: number; ground_height_meters: number; venue_name?: string }
interface ZoneMetric { zone_id: string; zone_name: string; population: number; capacity: number; occupancy_pct: number; area_sq_meters: number; density_per_sq_meter: number; avg_speed_mps: number; risk_level: string; status_message: string }
interface VAlert { id: string; alert_type: string; severity: string; message: string; recommendation: string }
interface Telemetry { frame_idx: number; timestamp_s: number; total_detected: number; active_tracks: number; peak_density: number; mean_density: number
  high_density_area_m2: number; latency_ms: number; zone_metrics: ZoneMetric[]; alerts: VAlert[]; detection_failed?: boolean }
interface Presets { calibration: CalibrationCfg; calibration_result: Record<string, unknown> | null; calibration_source: string; default_calibration: CalibrationCfg
  scenarios: { id: string; name: string; description: string }[]; heatmap_modes: string[]; detector: { backend: string; verified: boolean; model?: string } }
interface StepResult { telemetry: Record<string, unknown> & { frame_idx: number; timestamp_s: number; total_detected: number; active_tracks_count: number; peak_density_per_sq_meter: number
  mean_density_per_sq_meter: number; high_density_area_sq_meters: number; processing_latency_ms: number; zone_metrics: ZoneMetric[]; alerts: VAlert[]; tracker: string }
  views: Views; label: string; calibration_source: string; fps: number }
interface JobSummary { id: string; status: string; filename: string; kind: string; created: number }
interface Keyframe { t: number; frame_index: number; views: Views; telemetry: Telemetry }
interface JobResult { kind: string; source_kind: string; frame_size: [number, number]; detector: { backend: string }; tracker: { tracker: string }
  calibration: { source: string }; keyframes: Keyframe[]; quality: Record<string, unknown>; document: { filename: string; sha256: string }; warnings: string[] }

const VIEWS: { id: ViewId; label: string }[] = [
  { id: 'camera', label: 'Camera' }, { id: 'birdseye', label: "Bird's-eye" }, { id: 'heatmap', label: 'Density heatmap' },
  { id: 'movement', label: 'Movement' }, { id: 'digital_twin', label: 'Digital twin' },
]
const RISK_TONE: Record<string, 'good' | 'warn' | 'bad' | 'neutral'> = { low: 'good', moderate: 'warn', high: 'bad', critical: 'bad' }
const CORNERS: (keyof Quad)[] = ['top_left', 'top_right', 'bottom_right', 'bottom_left']
const SYNTH_FRAME: [number, number] = [1280, 720]

function fromStep(r: StepResult): Telemetry {
  const t = r.telemetry
  return { frame_idx: t.frame_idx, timestamp_s: t.timestamp_s, total_detected: t.total_detected, active_tracks: t.active_tracks_count,
    peak_density: t.peak_density_per_sq_meter, mean_density: t.mean_density_per_sq_meter, high_density_area_m2: t.high_density_area_sq_meters,
    latency_ms: t.processing_latency_ms, zone_metrics: t.zone_metrics, alerts: t.alerts }
}

export function VirtualHeatmapPage() {
  const { param, navigate } = useApp()
  const [source, setSource] = useState<'synthetic' | 'recorded'>(param ? 'recorded' : 'synthetic')
  const [presets, setPresets] = useState<Presets | null>(null)
  const [scenario, setScenario] = useState('plaza_normal')
  const [mode, setMode] = useState('gaussian')
  const [sigma, setSigma] = useState(28)
  const [playing, setPlaying] = useState(false)
  const [rate, setRate] = useState(400)
  const [step, setStep] = useState<StepResult | null>(null)
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [jobId, setJobId] = useState<string | null>(param)
  const [job, setJob] = useState<JobResult | null>(null)
  const [kfIndex, setKfIndex] = useState(0)
  const [view, setView] = useState<ViewId>('heatmap')
  const [sideBySide, setSideBySide] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const busy = useRef(false)

  const doStep = useCallback(async (reset = false) => {
    if (busy.current) return
    busy.current = true
    try {
      const env = await cg<StepResult>(`/simulation/${reset ? 'reset' : 'step'}?scenario=${scenario}&mode=${mode}&sigma=${sigma}`, {})
      if (!env.success) throw new Error(env.error?.message ?? 'step failed')
      setStep(env.result)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setPlaying(false)
    } finally {
      busy.current = false
    }
  }, [scenario, mode, sigma])

  useEffect(() => {
    const id = window.setTimeout(() => {
      cgResult<Presets>('/presets').then(({ result }) => setPresets(result)).catch((e) => setError(String(e)))
      get<JobSummary[]>('/api/crowdguard/media/jobs').then((j) => setJobs(j.filter((x) => x.status === 'completed' && x.kind === 'video'))).catch(() => undefined)
    }, 0)
    return () => window.clearTimeout(id)
  }, [])

  // Synthetic: re-render when controls change; play loop when playing.
  useEffect(() => {
    if (source !== 'synthetic') return undefined
    const id = window.setTimeout(() => { void doStep(false) }, 0)
    return () => window.clearTimeout(id)
  }, [source, doStep])
  useEffect(() => {
    if (source !== 'synthetic' || !playing) return undefined
    const id = window.setInterval(() => { void doStep(false) }, rate)
    return () => window.clearInterval(id)
  }, [source, playing, rate, doStep])

  // Recorded: load the chosen job; play steps through its key frames.
  useEffect(() => {
    if (source !== 'recorded' || !jobId) return undefined
    let cancelled = false
    get<{ status: string; response?: { success: boolean; result: JobResult; error?: { message: string } } }>(`/api/crowdguard/media/jobs/${jobId}`)
      .then((j) => {
        if (cancelled) return
        if (j.response?.success) { setJob(j.response.result); setKfIndex(0) } else setError(j.response?.error?.message ?? `Job is ${j.status}`)
      })
      .catch((e) => !cancelled && setError(String(e)))
    return () => { cancelled = true }
  }, [source, jobId])
  useEffect(() => {
    if (source !== 'recorded' || !playing || !job) return undefined
    const id = window.setInterval(() => setKfIndex((i) => (i + 1) % job.keyframes.length), Math.max(rate, 600))
    return () => window.clearInterval(id)
  }, [source, playing, job, rate])

  const kf = job?.keyframes[Math.min(kfIndex, (job?.keyframes.length ?? 1) - 1)]
  const views: Views | null = source === 'synthetic' ? step?.views ?? null : kf?.views ?? null
  const tel: Telemetry | null = source === 'synthetic' ? (step ? fromStep(step) : null) : kf?.telemetry ?? null
  const frameSize: [number, number] = source === 'synthetic' ? SYNTH_FRAME : job?.frame_size ?? SYNTH_FRAME

  return (
    <div className="space-y-4">
      <PageHeader title="Virtual Heatmap" icon={<Flame className="mt-1 size-6 text-[var(--accent)]" />}
        description="A calibrated four-point homography maps each person's ground-contact point from the camera onto a top-down plane, where density (Gaussian KDE, persons/m²), movement vectors and a digital twin are computed. Every view shown together comes from the same frame." />

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface p-3">
        <Tabs value={source} onChange={(v) => { setPlaying(false); setSource(v) }}
          options={[{ id: 'synthetic', label: 'Synthetic scenario' }, { id: 'recorded', label: 'Recorded video' }]} />
        {source === 'synthetic' ? (
          <>
            <select value={scenario} onChange={(e) => setScenario(e.target.value)} aria-label="Scenario" className="rounded-md border border-line bg-surface px-2 py-1 text-xs">
              {presets?.scenarios.map((s) => <option key={s.id} value={s.id} title={s.description}>{s.name}</option>)}
            </select>
            <Button size="sm" variant="primary" onClick={() => setPlaying(!playing)}>{playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}{playing ? 'Pause' : 'Play'}</Button>
            <Button size="sm" onClick={() => void doStep(false)} disabled={playing}><StepForward className="size-3.5" />Step</Button>
            <Button size="sm" variant="ghost" onClick={() => void doStep(true)}><RotateCcw className="size-3.5" />Reset</Button>
            <Badge tone="warn">SYNTHETIC · simulated pedestrians, no detector</Badge>
          </>
        ) : (
          <>
            <select value={jobId ?? ''} onChange={(e) => setJobId(e.target.value || null)} aria-label="Analysed recording" className="max-w-[260px] rounded-md border border-line bg-surface px-2 py-1 text-xs">
              <option value="">Select an analysed recording…</option>
              {jobs.map((j) => <option key={j.id} value={j.id}>{j.filename} · {new Date(j.created * 1000).toLocaleTimeString()}</option>)}
              {jobId && !jobs.some((j) => j.id === jobId) && <option value={jobId}>{jobId}</option>}
            </select>
            {job && (
              <>
                <Button size="sm" variant="primary" onClick={() => setPlaying(!playing)}>{playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}{playing ? 'Pause' : 'Play key frames'}</Button>
                <input type="range" min={0} max={job.keyframes.length - 1} value={kfIndex} onChange={(e) => { setPlaying(false); setKfIndex(Number(e.target.value)) }}
                  className="w-40 accent-[var(--accent)]" aria-label="Key frame" />
                <span className="tabular text-xs text-muted">{kf ? `${kf.t.toFixed(1)} s · frame ${kf.frame_index}` : ''}</span>
                <Badge tone="info">RECORDED VIDEO · {job.detector.backend.toUpperCase()} + {job.tracker.tracker}</Badge>
              </>
            )}
            <Button size="sm" variant="ghost" onClick={() => navigate('cg-live')}>Analyse a recording →</Button>
          </>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2 text-xs text-ink-2">
          <label className="flex items-center gap-1">Heatmap
            <select value={mode} onChange={(e) => setMode(e.target.value)} disabled={source === 'recorded'} className="rounded-md border border-line bg-surface px-1.5 py-1 text-xs">
              {(presets?.heatmap_modes ?? ['gaussian']).map((m) => <option key={m}>{m}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-1" title="Gaussian KDE bandwidth (bird's-eye pixels)">σ
            <input type="range" min={8} max={60} value={sigma} onChange={(e) => setSigma(Number(e.target.value))} disabled={source === 'recorded'} className="w-20 accent-[var(--accent)]" />
            <span className="tabular w-6">{sigma}</span>
          </label>
          <label className="flex items-center gap-1">Speed
            <select value={rate} onChange={(e) => setRate(Number(e.target.value))} className="rounded-md border border-line bg-surface px-1.5 py-1 text-xs">
              <option value={800}>slow</option><option value={400}>normal</option><option value={200}>fast</option>
            </select>
          </label>
          <Button size="sm" variant="ghost" onClick={() => setSideBySide(!sideBySide)} title="Toggle side-by-side comparison"><Columns2 className="size-3.5" />{sideBySide ? 'Side by side' : 'Single view'}</Button>
        </div>
      </div>

      {error && <ErrorBox>{error}</ErrorBox>}
      {source === 'recorded' && job?.warnings.length ? <WarnBox><ul className="list-disc pl-4">{job.warnings.map((w) => <li key={w}>{w}</li>)}</ul></WarnBox> : null}
      {source === 'recorded' && !jobId && (
        <Card><p className="text-sm text-ink-2">No recording selected. Analyse a video (or the sample clip) in <button className="font-medium text-[var(--accent)] underline" onClick={() => navigate('cg-live')}>Live Monitoring</button>; it then appears here with all five views per key frame.</p></Card>
      )}

      {views ? (
        <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="space-y-3">
            <div className={cx('grid gap-3', sideBySide ? 'lg:grid-cols-2' : '')}>
              {(sideBySide ? (['camera', view === 'camera' ? 'heatmap' : view] as ViewId[]) : [view]).map((v) => (
                <ViewPanel key={v} id={v} src={views[v] ?? null} frameIdx={views.frame_idx ?? null}
                  calibrate={v === 'camera' && source === 'synthetic' && presets ? { presets, frameSize, onDone: (p) => { setPresets(p); void doStep(true) } } : null}
                  onPickView={sideBySide && v !== 'camera' ? setView : undefined} active={view} />
              ))}
            </div>
            <div className="grid grid-cols-5 gap-2">
              {VIEWS.map((v) => (
                <button key={v.id} onClick={() => setView(v.id === 'camera' && sideBySide ? 'heatmap' : v.id)}
                  className={cx('overflow-hidden rounded-md border text-left', view === v.id ? 'border-[var(--accent)] ring-1 ring-[var(--accent)]' : 'border-line hover:border-ink-2')}>
                  {views[v.id] ? <img src={views[v.id] as string} alt="" className="aspect-video w-full object-cover" /> : <div className="aspect-video bg-surface-2" />}
                  <span className="block truncate px-1.5 py-1 text-[11px] text-ink-2">{v.label}</span>
                </button>
              ))}
            </div>
            <SafetyNotice />
          </div>
          <div className="space-y-3">
            <TelemetryCard tel={tel} source={source} step={step} job={job} presets={presets} />
            <ZonesCard tel={tel} />
            <AlertsCard tel={tel} />
          </div>
        </div>
      ) : (source === 'synthetic' || jobId) && !error ? <Spinner label="Rendering the first frame" /> : null}
    </div>
  )
}

function ViewPanel({ id, src, frameIdx, calibrate, onPickView, active }: {
  id: ViewId; src: string | null; frameIdx: number | null
  calibrate: { presets: Presets; frameSize: [number, number]; onDone: (p: Presets) => void } | null
  onPickView?: (v: ViewId) => void; active: ViewId
}) {
  const [picking, setPicking] = useState(false)
  const [pts, setPts] = useState<Pt[]>([])
  const [msg, setMsg] = useState<string | null>(null)
  const label = VIEWS.find((v) => v.id === id)?.label
  const quad = calibrate?.presets.calibration.source_points

  async function click(e: React.MouseEvent<HTMLImageElement>) {
    if (!picking || !calibrate) return
    const r = e.currentTarget.getBoundingClientRect()
    const [W, H] = calibrate.frameSize
    const next = [...pts, { x: Math.round(((e.clientX - r.left) / r.width) * W), y: Math.round(((e.clientY - r.top) / r.height) * H) }]
    setPts(next)
    if (next.length === 4) {
      setPicking(false)
      const cfg = calibrate.presets.calibration
      const env = await cg<Record<string, unknown>>('/calibration', { ...cfg, source_points: Object.fromEntries(CORNERS.map((c, i) => [c, next[i]])) })
      if (!env.success) { setMsg(env.error?.message ?? 'Calibration rejected'); setPts([]); return }
      setMsg(`Calibrated: ${(env.result.ground_area_sq_meters as number | undefined)?.toFixed?.(0) ?? '?'} m² ground plane. Applies to this view and to recordings analysed from now on.`)
      setPts([])
      const p = await cgResult<Presets>('/presets')
      calibrate.onDone(p.result)
    }
  }

  return (
    <figure className="overflow-hidden rounded-xl border border-line bg-surface">
      <figcaption className="flex items-center justify-between gap-2 border-b border-line px-3 py-1.5 text-xs">
        <span className="font-medium text-ink">{label}{frameIdx != null && <span className="ml-2 font-normal text-muted tabular">frame {frameIdx}</span>}</span>
        <span className="flex items-center gap-1.5">
          {onPickView && (
            <select value={active} onChange={(e) => onPickView(e.target.value as ViewId)} aria-label="Transformed view" className="rounded border border-line bg-surface px-1 py-0.5 text-[11px]">
              {VIEWS.filter((v) => v.id !== 'camera').map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
            </select>
          )}
          {calibrate && (
            <Button size="sm" variant={picking ? 'primary' : 'ghost'} onClick={() => { setPicking(!picking); setPts([]); setMsg(null) }}
              title="Click the four ground-plane corners: top-left, top-right, bottom-right, bottom-left">
              <Crosshair className="size-3.5" />{picking ? `Click corner ${pts.length + 1}/4` : 'Calibrate'}
            </Button>
          )}
        </span>
      </figcaption>
      <div className="relative bg-black">
        {src ? <img src={src} alt={`${label} view`} onClick={click} className={cx('block h-auto w-full select-none', picking && 'cursor-crosshair')} draggable={false} />
          : <div className="flex aspect-video items-center justify-center text-xs text-muted">No image</div>}
        {calibrate && (picking || pts.length > 0) && (
          <svg viewBox={`0 0 ${calibrate.frameSize[0]} ${calibrate.frameSize[1]}`} className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
            {pts.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r={10} fill="#facc15" stroke="black" strokeWidth={2} />)}
            {pts.length > 1 && <polyline points={pts.map((p) => `${p.x},${p.y}`).join(' ')} fill="none" stroke="#facc15" strokeWidth={3} />}
          </svg>
        )}
      </div>
      {calibrate && quad && (
        <p className="border-t border-line px-3 py-1.5 font-mono text-[10.5px] text-muted">
          quad {CORNERS.map((c) => `${Math.round(quad[c].x)},${Math.round(quad[c].y)}`).join(' · ')} · {calibrate.presets.calibration.ground_width_meters}×{calibrate.presets.calibration.ground_height_meters} m · {calibrate.presets.calibration_source}
        </p>
      )}
      {msg && <p className="border-t border-line px-3 py-1.5 text-[11px] text-ink-2">{msg}</p>}
    </figure>
  )
}

function TelemetryCard({ tel, source, step, job, presets }: { tel: Telemetry | null; source: string; step: StepResult | null; job: JobResult | null; presets: Presets | null }) {
  const rows = useMemo(() => tel ? [
    ['Frame / time', `${tel.frame_idx} · ${tel.timestamp_s.toFixed(1)} s`],
    ['Detected / tracked', `${tel.total_detected} / ${tel.active_tracks}`],
    ['Peak density', `${tel.peak_density.toFixed(2)} p/m²`],
    ['Mean density', `${tel.mean_density.toFixed(3)} p/m²`],
    ['High-density area (≥1.5 p/m²)', `${tel.high_density_area_m2.toFixed(1)} m²`],
    ['Processing latency', `${tel.latency_ms.toFixed(0)} ms`],
  ] : [], [tel])
  return (
    <Card title="Telemetry" subtitle={source === 'synthetic' ? 'Live synthetic pipeline' : job ? `${job.document.filename} · sha256 ${job.document.sha256.slice(0, 12)}…` : ''}>
      {tel ? (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
          {rows.map(([k, v]) => <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="tabular text-right font-medium text-ink">{v}</dd></div>)}
          <dt className="text-muted">Detector</dt><dd className="text-right">{source === 'synthetic' ? 'none (ground-truth boxes)' : job?.detector.backend}</dd>
          <dt className="text-muted">Identity / kinematics</dt><dd className="text-right">{source === 'synthetic' ? step?.telemetry.tracker : `${job?.tracker.tracker} + ground-plane Kalman`}</dd>
          <dt className="text-muted">Calibration</dt><dd className="text-right">{source === 'synthetic' ? presets?.calibration_source : job?.calibration.source}</dd>
          {tel.detection_failed && <><dt className="text-critical-ink">Detection</dt><dd className="text-right text-critical-ink">failed on this frame (unknown, not empty)</dd></>}
        </dl>
      ) : <p className="text-xs text-muted">Waiting for a frame…</p>}
    </Card>
  )
}

function ZonesCard({ tel }: { tel: Telemetry | null }) {
  return (
    <Card title="Ground-plane zones" subtitle="Point-in-polygon on the bird's-eye plane">
      {!tel?.zone_metrics.length ? <p className="text-xs text-muted">No zones.</p> : (
        <table className="w-full text-left text-xs">
          <thead><tr className="text-muted"><th className="py-1 font-medium">Zone</th><th className="py-1 text-right font-medium">People</th><th className="py-1 text-right font-medium">p/m²</th><th className="py-1 text-right font-medium">m/s</th><th className="py-1 text-right font-medium">Risk</th></tr></thead>
          <tbody>
            {tel.zone_metrics.map((z) => (
              <tr key={z.zone_id} className="border-t border-line" title={z.status_message}>
                <td className="py-1 pr-2">{z.zone_name}</td>
                <td className="tabular py-1 text-right">{z.population}/{z.capacity}</td>
                <td className="tabular py-1 text-right">{z.density_per_sq_meter.toFixed(2)}</td>
                <td className="tabular py-1 text-right">{z.avg_speed_mps.toFixed(2)}</td>
                <td className="py-1 text-right"><Badge tone={RISK_TONE[z.risk_level] ?? 'neutral'}>{z.risk_level}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}

function AlertsCard({ tel }: { tel: Telemetry | null }) {
  return (
    <Card title="Movement alerts" subtitle="Bottlenecks, counter-flow and severe density (advisory)">
      {!tel?.alerts.length ? <p className="text-xs text-good-ink">✔ No movement alerts in this frame.</p> : (
        <ul className="space-y-2">
          {tel.alerts.slice(0, 6).map((a) => (
            <li key={a.id} className="text-xs">
              <div className="flex items-center gap-1.5"><Badge tone={a.severity === 'critical' || a.severity === 'high' ? 'bad' : 'warn'}>{a.severity}</Badge><span className="font-medium text-ink">{a.alert_type.replace('_', ' ')}</span></div>
              <p className="mt-0.5 text-ink-2">{a.message}</p>
              <p className="text-muted">→ {a.recommendation}</p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

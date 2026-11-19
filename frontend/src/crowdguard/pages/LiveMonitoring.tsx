import { Camera, Film, Upload } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { Badge, Button, Card, ErrorBox, PageHeader, Spinner, WarnBox } from '../../components/ui'
import { get } from '../../lib/api'
import { useDarkMode } from '../../lib/hooks'
import { cgResult } from '../api'
import { fmtInt, useCrowd } from '../store'
import type { Alert, Reading, Recommendation, Summary } from '../types'
import { VenueMap } from '../VenueMap'
import { AlertList, BandPill, SafetyNotice } from '../widgets'

interface Box { id: number | null; box: [number, number, number, number]; conf: number; zone: string | null; confirmed: boolean }
interface MediaZone {
  zone_id: string; name: string; venue_zone: string | null; area_m2: number; safe_capacity: number
  current_observed: number | null; peak_observed: number | null; mean_observed: number | null; unique_people: number | null
  reading: Reading; flow: { n: number; mean_speed: number | null; dominant_direction: string | null; coherence: number | null; stationary_fraction: number | null; counterflow_fraction: number | null }
  series: { t: number; count: number | null }[]
}
interface MediaResult {
  kind: 'image' | 'video'
  detector: Record<string, unknown> & { backend: string; verified?: boolean; model?: string; weights_path?: string }
  tracker: Record<string, unknown> & { tracker: string }
  frame_size: [number, number]
  layout: { zones: { id: string; name: string; polygon: [number, number][] }[]; meters_per_pixel: number | null }
  zones: MediaZone[]
  observations: { camera_zone: string; venue_zone: string | null; observed_count: number | null; feed_status: string }[]
  venue_observations: { zone_id: string; observed_count: number; feed_status: string; coverage: number; detector_confidence: number | null; tracking_stability: number | null; source: string }[]
  totals: { series: { t: number; detections: number | null; tracked: number | null }[]; unique_people: number | null; transitions: Record<string, number>; frame_estimate: { estimate: number; lower: number; upper: number } }
  flow: { unit: string; overall: MediaZone['flow']; direction_histogram: { direction: string; count: number }[] }
  keyframes: { t: number; frame_index: number; image: string; width: number; height: number; boxes: Box[] }[]
  trails: Record<string, [number, number][]>
  quality: Record<string, number | boolean | null>
  warnings: string[]
  elapsed_s: number
  document: { id: string; filename: string; sha256: string; kind: string; size: number }
}
interface Job { id: string; status: string; progress: { done?: number; total?: number }; provenance?: { label: string } | null; response?: { success: boolean; result: MediaResult; error: { message: string } | null; warnings: string[] }; filename: string }

const ZONE_COLOURS = ['#0ea5e9', '#f59e0b', '#a855f7', '#10b981', '#ef4444']

export function LiveMonitoringPage() {
  const { venue, load, sim } = useCrowd()
  const [layoutName, setLayoutName] = useState('default_two_zone')
  const [custom, setCustom] = useState('')
  const [venueZone, setVenueZone] = useState('main_stage')
  const [coverage, setCoverage] = useState(0.02)
  const [file, setFile] = useState<File | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const timer = useRef<number | null>(null)

  useEffect(() => { if (!venue && !sim) load() }, [venue, sim, load])
  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current) }, [])

  function poll(id: string) {
    if (timer.current) window.clearInterval(timer.current)
    timer.current = window.setInterval(async () => {
      try {
        const j = await get<Job>(`/api/crowdguard/media/jobs/${id}`)
        setJob(j)
        if (j.status === 'completed' || j.status === 'failed') {
          if (timer.current) window.clearInterval(timer.current)
          setBusy(false)
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        if (timer.current) window.clearInterval(timer.current)
        setBusy(false)
      }
    }, 700)
  }

  function headers(): Record<string, string> {
    try {
      const raw = localStorage.getItem('omniforge.identity')
      const id = raw ? JSON.parse(raw) as { role: string; actor: string } : { role: 'analyst', actor: 'demo-analyst' }
      return { 'X-Omniforge-Role': id.role, 'X-Omniforge-Actor': id.actor }
    } catch {
      return {}
    }
  }

  async function start(kind: 'upload' | 'sample') {
    setError(null)
    setBusy(true)
    setJob(null)
    try {
      let res: Response
      if (kind === 'upload') {
        if (!file) throw new Error('Choose an image or video first')
        const form = new FormData()
        form.append('file', file)
        if (custom.trim()) form.append('custom_layout', custom.trim())
        else form.append('layout', layoutName)
        if (venueZone) { form.append('venue_zone', venueZone); form.append('coverage', String(coverage)) }
        res = await fetch('/api/crowdguard/media', { method: 'POST', body: form, headers: headers() })
      } else {
        const body: Record<string, unknown> = custom.trim() ? { custom_layout: JSON.parse(custom) } : { layout: layoutName }
        if (venueZone) { body.venue_zone = venueZone; body.coverage = coverage }
        res = await fetch('/api/crowdguard/media/sample', { method: 'POST', body: JSON.stringify(body), headers: { ...headers(), 'Content-Type': 'application/json' } })
      }
      const data = await res.json()
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? data))
      setJob({ id: data.job_id, status: 'queued', progress: {}, provenance: data.provenance, filename: data.document.filename })
      poll(data.job_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  const layouts = venue?.camera_layouts ?? {}
  const result = job?.response?.success ? job.response.result : null
  return (
    <div className="space-y-4">
      <PageHeader title="Live Monitoring · Camera ingestion" icon={<Camera className="mt-1 size-6 text-[var(--accent)]" />}
        description="Upload a video or image. The backend detects people (YOLO when local weights exist, otherwise OpenCV HOG), tracks them across frames so nobody is counted twice, assigns each person's foot point to a polygon zone and measures movement." />
      <Card title="Ingest footage" subtitle="Files are content-sniffed, size-capped and stored by SHA-256. Track ids are ephemeral; no identity or face recognition is used.">
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-3">
            <label className="block text-xs font-medium text-ink-2">Video (MP4/MOV/WebM/AVI) or image (JPEG/PNG/WEBP)
              <input type="file" accept="video/*,image/jpeg,image/png,image/webp" onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="mt-1 block w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" />
            </label>
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => start('upload')} busy={busy && !!file} disabled={!file || busy}><Upload className="size-4" />Analyse upload</Button>
              <Button onClick={() => start('sample')} busy={busy && !file} disabled={busy}><Film className="size-4" />Use sample test clip</Button>
            </div>
            <p className="text-[11px] text-muted">The sample clip is a camera pan synthesised from the Ultralytics sample photo: detections are real, motion is artificial. It is labelled as such in the results.</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-medium text-ink-2">Camera zone layout
              <select value={layoutName} onChange={(e) => setLayoutName(e.target.value)} className="mt-1 block w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm">
                {Object.keys(layouts).map((k) => <option key={k} value={k}>{k}</option>)}
              </select>
              <span className="mt-1 block text-[11px] font-normal text-muted">{layouts[layoutName]?.description}</span>
            </label>
            <label className="text-xs font-medium text-ink-2">Camera observes venue zone
              <select value={venueZone} onChange={(e) => setVenueZone(e.target.value)} className="mt-1 block w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm">
                <option value="">— none (camera zones only) —</option>
                {venue?.zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
              </select>
            </label>
            <label className="text-xs font-medium text-ink-2">Share of that zone in view
              <input type="number" min={0.005} max={1} step={0.005} value={coverage} onChange={(e) => setCoverage(Number(e.target.value))}
                className="mt-1 block w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" />
              <span className="mt-1 block text-[11px] font-normal text-muted">Below 1 the venue estimate is an extrapolation with a wider interval.</span>
            </label>
            <label className="text-xs font-medium text-ink-2 sm:col-span-2">Custom layout JSON (optional, overrides the layout)
              <textarea value={custom} onChange={(e) => setCustom(e.target.value)} rows={3} spellCheck={false}
                placeholder='{"meters_per_pixel": null, "zones": [{"id": "gate_lane", "name": "Gate lane", "polygon": [[0,0.3],[1,0.3],[1,1],[0,1]], "area_m2": 80, "safe_capacity": 160}]}'
                className="mt-1 block w-full rounded-lg border border-line bg-surface px-2 py-1.5 font-mono text-[11px]" />
            </label>
          </div>
        </div>
        {error && <div className="mt-3"><ErrorBox>{error}</ErrorBox></div>}
        {job && job.status !== 'completed' && job.status !== 'failed' && (
          <div className="mt-3 flex items-center gap-3 text-sm text-ink-2">
            <Spinner label={`Analysing ${job.filename}: ${job.progress.done ?? 0}/${job.progress.total ?? '?'} frames`} />
          </div>
        )}
        {job?.status === 'failed' && <div className="mt-3"><ErrorBox>Analysis failed: {job.response?.error?.message ?? 'unknown error'}</ErrorBox></div>}
      </Card>
      {result && <MediaResults result={result} provenance={job?.provenance?.label} />}
    </div>
  )
}

function KeyframeViewer({ result }: { result: MediaResult }) {
  const [i, setI] = useState(result.keyframes.length - 1)
  const kf = result.keyframes[Math.min(i, result.keyframes.length - 1)]
  if (!kf) return null
  const { width: w, height: h } = kf
  const zoneIdx = Object.fromEntries(result.layout.zones.map((z, k) => [z.id, k]))
  const last = i === result.keyframes.length - 1
  return (
    <div>
      <div className="relative overflow-hidden rounded-lg border border-line bg-black">
        <img src={kf.image} alt={`Analysed frame at ${kf.t} s`} className="block h-auto w-full" />
        <svg viewBox={`0 0 ${w} ${h}`} className="absolute inset-0 h-full w-full" aria-hidden>
          {result.layout.zones.map((z, k) => (
            <g key={z.id}>
              <polygon points={z.polygon.map(([x, y]) => `${x * w},${y * h}`).join(' ')} fill={ZONE_COLOURS[k % 5]} fillOpacity={0.12} stroke={ZONE_COLOURS[k % 5]} strokeWidth={2} strokeDasharray="6 4" />
              <text x={z.polygon[0][0] * w + 6} y={z.polygon[0][1] * h + 16} fontSize={13} fontWeight={700} fill={ZONE_COLOURS[k % 5]} stroke="black" strokeWidth={0.5}>{z.name}</text>
            </g>
          ))}
          {last && Object.entries(result.trails).map(([tid, pts]) => (
            <polyline key={tid} points={pts.map(([x, y]) => `${x * w},${y * h}`).join(' ')} fill="none" stroke="#facc15" strokeWidth={2} strokeOpacity={0.8} />
          ))}
          {kf.boxes.map((b, k) => {
            const c = b.zone ? ZONE_COLOURS[(zoneIdx[b.zone] ?? 0) % 5] : '#9ca3af'
            const [x1, y1, x2, y2] = b.box
            return (
              <g key={k}>
                <rect x={x1 * w} y={y1 * h} width={(x2 - x1) * w} height={(y2 - y1) * h} fill="none" stroke={c} strokeWidth={b.confirmed ? 2.5 : 1.5} strokeDasharray={b.confirmed ? undefined : '4 3'} />
                <rect x={x1 * w} y={y1 * h - 16} width={64} height={16} fill={c} />
                <text x={x1 * w + 3} y={y1 * h - 4} fontSize={11} fontWeight={700} fill="black">{b.id != null ? `#${b.id}` : 'det'} {Math.round(b.conf * 100)}%</text>
                <circle cx={((x1 + x2) / 2) * w} cy={y2 * h} r={3.5} fill={c} stroke="black" />
              </g>
            )
          })}
        </svg>
      </div>
      {result.keyframes.length > 1 && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {result.keyframes.map((k, j) => (
            <button key={k.frame_index} onClick={() => setI(j)} className={`rounded-md border px-2 py-0.5 text-[11px] ${j === i ? 'border-[var(--accent)] text-ink' : 'border-line text-muted'}`}>{k.t.toFixed(1)} s</button>
          ))}
          <span className="text-[11px] text-muted">Boxes: #track id + confidence; dot = foot point used for zone assignment; yellow = track trails (last frame).</span>
        </div>
      )}
    </div>
  )
}

function MediaResults({ result, provenance }: { result: MediaResult; provenance?: string }) {
  const { venue } = useCrowd()
  const dark = useDarkMode()
  const [assess, setAssess] = useState<{ readings: Record<string, Reading>; alerts: Alert[]; recommendations: Recommendation[]; summary: Summary } | null>(null)
  const [assessErr, setAssessErr] = useState<string | null>(null)
  const q = result.quality
  const series = result.totals.series.map((r, k) => {
    const row: Record<string, unknown> = { t: r.t.toFixed(1), detections: r.detections, tracked: r.tracked }
    result.zones.forEach((z) => { row[z.zone_id] = z.series[k]?.count })
    return row
  })
  const ax = { stroke: dark ? '#383835' : '#c3c2b7', tick: { fill: '#898781', fontSize: 11 }, tickLine: false }

  async function runAssess() {
    setAssessErr(null)
    try {
      const { result: snap } = await cgResult<{ readings: Record<string, Reading>; alerts: Alert[]; recommendations: Recommendation[]; summary: Summary }>('/assess', {
        observations: result.venue_observations.map((o) => ({ zone_id: o.zone_id, observed_count: o.feed_status === 'ok' ? o.observed_count : null,
          feed_status: o.feed_status === 'ok' ? 'ok' : 'detector_error', coverage: o.coverage, detector_confidence: o.detector_confidence,
          tracking_stability: o.tracking_stability, source: o.source === 'image' ? 'image' : 'video' })),
      })
      setAssess(snap)
    } catch (e) {
      setAssessErr(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="space-y-4">
      {provenance && <WarnBox>{provenance}</WarnBox>}
      {result.warnings.length > 0 && <WarnBox><ul className="list-disc pl-4">{result.warnings.map((w) => <li key={w}>{w}</li>)}</ul></WarnBox>}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        <Card title={`Analysed ${result.kind}: ${result.document.filename}`} subtitle={`SHA-256 ${result.document.sha256.slice(0, 16)}… · ${q.frames_processed} frame(s) in ${result.elapsed_s} s`}>
          <KeyframeViewer result={result} />
        </Card>
        <div className="space-y-3">
          <Card title="Detection & tracking quality" subtitle="Reported by the backend for this file">
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
              <dt className="text-muted">Detector</dt><dd className="font-medium">{result.detector.backend}{result.detector.verified ? ' (verified)' : ''}</dd>
              <dt className="text-muted">Model</dt><dd className="truncate font-mono text-[11px]" title={String(result.detector.weights_path ?? '')}>{String(result.detector.model ?? '—')}</dd>
              <dt className="text-muted">Tracker</dt><dd>{result.tracker.tracker}</dd>
              <dt className="text-muted">Frames ok / errors</dt><dd className="tabular">{String(q.frames_ok)} / {String(q.frames_detector_error)}</dd>
              <dt className="text-muted">Mean detection conf.</dt><dd className="tabular">{q.mean_detection_confidence ?? '—'}</dd>
              <dt className="text-muted">Unique people (tracks)</dt><dd className="tabular">{result.totals.unique_people ?? '—'}</dd>
              <dt className="text-muted">Track fragmentation</dt><dd className="tabular">{q.track_fragmentation ?? '—'}</dd>
              <dt className="text-muted">Processed rate</dt><dd className="tabular">{q.processed_fps ? `${q.processed_fps} fps` : 'single frame'}</dd>
              <dt className="text-muted">Whole-frame estimate</dt><dd className="tabular">{result.totals.frame_estimate.estimate} ({result.totals.frame_estimate.lower}–{result.totals.frame_estimate.upper})</dd>
            </dl>
          </Card>
          <Card title="Movement" subtitle={`Speeds in ${result.flow.unit}${result.layout.meters_per_pixel ? '' : ' (uncalibrated)'}`}>
            {result.kind === 'image' ? <p className="text-xs text-muted">Movement needs video: a single image has no motion.</p> : (
              <>
                <p className="text-xs text-ink-2">Dominant direction <b>{result.flow.overall.dominant_direction ?? '—'}</b> · coherence {result.flow.overall.coherence ?? '—'} · mean speed {result.flow.overall.mean_speed ?? '—'} · stationary {result.flow.overall.stationary_fraction ?? '—'} · counter-flow {result.flow.overall.counterflow_fraction ?? '—'}</p>
                <ResponsiveContainer width="100%" height={130}>
                  <BarChart data={result.flow.direction_histogram}><XAxis dataKey="direction" {...ax} /><YAxis {...ax} width={24} allowDecimals={false} /><Tooltip /><Bar dataKey="count" name="tracks" fill="#0ea5e9" isAnimationActive={false} /></BarChart>
                </ResponsiveContainer>
              </>
            )}
          </Card>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {result.zones.map((z, k) => (
          <div key={z.zone_id} className="rounded-xl border border-line bg-surface p-3">
            <div className="flex items-center justify-between"><p className="text-sm font-semibold" style={{ color: ZONE_COLOURS[k % 5] }}>{z.name}</p><BandPill band={z.reading.band} /></div>
            <div className="mt-2 grid grid-cols-3 gap-2 text-center">
              <div><p className="text-[10px] uppercase text-muted">Observed now</p><p className="tabular text-xl font-bold">{z.current_observed ?? '—'}</p><p className="text-[10px] text-muted">actual detections</p></div>
              <div><p className="text-[10px] uppercase text-muted">Estimate</p><p className="tabular text-xl font-bold">{z.reading.estimate ?? '—'}</p><p className="text-[10px] text-muted">{z.reading.lower}–{z.reading.upper} (occlusion)</p></div>
              <div><p className="text-[10px] uppercase text-muted">Unique people</p><p className="tabular text-xl font-bold">{z.unique_people ?? '—'}</p><p className="text-[10px] text-muted">distinct track ids</p></div>
            </div>
            <p className="mt-2 text-[11px] text-ink-2">{z.reading.occupancy_pct}% of {z.safe_capacity} · {z.reading.density_ppm2} p/m² (LOS {z.reading.level_of_service}) · confidence {z.reading.confidence} ({z.reading.data_quality})</p>
            {result.kind === 'video' && <p className="text-[11px] text-muted">Flow: {z.flow.dominant_direction ?? '—'} · speed {z.flow.mean_speed ?? '—'} {result.flow.unit} · stationary {z.flow.stationary_fraction ?? '—'}</p>}
          </div>
        ))}
      </div>

      {result.kind === 'video' && (
        <Card title="People per zone over time" subtitle="Confirmed tracks inside each zone per processed frame (repeated detections of one person count once)">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={series}><CartesianGrid stroke={dark ? '#2c2c2a' : '#e1e0d9'} vertical={false} /><XAxis dataKey="t" {...ax} unit="s" /><YAxis {...ax} width={28} allowDecimals={false} /><Tooltip /><Legend wrapperStyle={{ fontSize: 12 }} />
              {result.zones.map((z, k) => <Line key={z.zone_id} dataKey={z.zone_id} name={z.name} stroke={ZONE_COLOURS[k % 5]} strokeWidth={2} dot={false} isAnimationActive={false} />)}
              <Line dataKey="detections" name="raw detections (all)" stroke="#9ca3af" strokeDasharray="4 3" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      )}

      {venue && result.venue_observations.length > 0 && (
        <Card title="Feed this camera into the venue assessment" subtitle="Zones without a camera are reported as UNKNOWN, never as empty"
          actions={<Button size="sm" variant="primary" onClick={runAssess}>Assess venue</Button>}>
          {assessErr && <ErrorBox>{assessErr}</ErrorBox>}
          {assess ? (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
              <VenueMap venue={venue} readings={assess.readings} showFlows={false} label="Camera-derived assessment" />
              <div className="space-y-2">
                <p className="text-xs text-ink-2">{assess.summary.zones_without_live_data} of {assess.summary.zones_total} zones have no live data. Known attendance ≈ {fmtInt(assess.summary.estimated_attendance)} (excludes unknown zones).</p>
                <AlertList alerts={assess.alerts} max={8} />
                <SafetyNotice />
              </div>
            </div>
          ) : <p className="text-xs text-muted">Maps {result.venue_observations.map((o) => `${o.observed_count} observed → ${o.zone_id} (coverage ${o.coverage})`).join('; ')}. <Badge tone="info">measured</Badge></p>}
        </Card>
      )}
    </div>
  )
}

import { RefreshCw, Square } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { cx } from '../lib/cx'
import { Button, Field, Note, inputCls } from '../ui/primitives'
import { live } from './client'
import { useLive } from './context'
import type { CameraInfo, Recording, SourceSpec } from './types'

type Tab = 'camera' | 'stream' | 'recording' | 'simulation'
const SCENARIOS = [
  { id: 'plaza_normal', label: 'Plaza, mixed movement' },
  { id: 'bottleneck', label: 'Corridor bottleneck' },
  { id: 'counterflow', label: 'Opposing streams' },
  { id: 'surge_gate', label: 'Surge at the north gate' },
]

/** Choose what to monitor. Each kind is labelled for what it is: live camera, recording or simulation. */
export function SourcePicker() {
  const { status, snapshot } = useLive()
  const running = (snapshot?.status ?? status?.status) && !['idle', 'error'].includes((snapshot?.status ?? status?.status) as string)
  const [tab, setTab] = useState<Tab>('camera')
  const [cams, setCams] = useState<CameraInfo[] | null>(null)
  const [probing, setProbing] = useState(false)
  const [camIndex, setCamIndex] = useState(0)
  const [url, setUrl] = useState('')
  const [recs, setRecs] = useState<Recording[]>([])
  const [recId, setRecId] = useState('')
  const [scenario, setScenario] = useState('bottleneck')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const probe = useCallback(async () => {
    setProbing(true)
    setError(null)
    try {
      const list = await live.cameras()
      setCams(list)
      const firstOk = list.find((c) => c.status !== 'no_frames')
      if (firstOk) setCamIndex(firstOk.index)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setProbing(false)
    }
  }, [])

  const loadRecs = useCallback(async () => {
    const r = await live.recordings().catch(() => [] as Recording[])
    setRecs(r)
    if (r[0]) setRecId((cur) => cur || r[0].id)
  }, [])

  useEffect(() => {
    const id = window.setTimeout(() => {
      if (tab === 'camera' && cams === null) void probe()
      if (tab === 'recording') void loadRecs()
    }, 0)
    return () => window.clearTimeout(id)
  }, [tab, cams, probe, loadRecs])

  async function start(spec: SourceSpec) {
    setBusy(true)
    setError(null)
    try {
      await live.start(spec)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function stop() {
    setBusy(true)
    try {
      await live.stop()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function uploadFile(f: File) {
    setBusy(true)
    setError(null)
    try {
      const doc = await live.uploadRecording(f)
      await loadRecs()
      setRecId(doc.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function sample() {
    setBusy(true)
    try {
      const doc = await live.sampleRecording()
      await loadRecs()
      setRecId(doc.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'camera', label: 'Camera' }, { id: 'stream', label: 'Stream' }, { id: 'recording', label: 'Recording' }, { id: 'simulation', label: 'Simulation' },
  ]

  return (
    <div className="space-y-3">
      {running && (snapshot?.source ?? status?.source) && (
        <p className="text-[12.5px] text-ink-2">Now monitoring: <span className="text-ink">{(snapshot?.source ?? status?.source)?.label}</span></p>
      )}
      <div className="grid grid-cols-2 gap-0.5 rounded-[5px] border border-line p-0.5 text-[12.5px]" role="tablist" aria-label="Source type">
        {tabs.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
            className={cx('rounded-[4px] py-1', tab === t.id ? 'bg-raised font-medium text-ink shadow-[0_0_0_1px_var(--color-line)]' : 'text-ink-2 hover:text-ink')}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'camera' && (
        <div className="space-y-2">
          <div className="flex items-end gap-2">
            <Field label="Camera on this computer">
              <select className={inputCls} value={camIndex} onChange={(e) => setCamIndex(Number(e.target.value))} disabled={!cams?.length}>
                {!cams && <option>Searching…</option>}
                {cams?.length === 0 && <option>No camera found</option>}
                {cams?.map((c) => (
                  <option key={c.index} value={c.index} disabled={c.status === 'no_frames'}>
                    {c.label}{c.status === 'no_frames' ? ', unavailable' : c.status === 'in_use_by_crowdguard' ? ', in use here' : ''}
                  </option>
                ))}
              </select>
            </Field>
            <Button variant="quiet" onClick={probe} busy={probing} title="Search for cameras again"><RefreshCw className="size-3.5" /></Button>
          </div>
          {cams?.some((c) => c.status === 'no_frames') && <Note tone="warn">{cams.find((c) => c.status === 'no_frames')?.detail}</Note>}
          <Button variant="primary" className="w-full" busy={busy} disabled={!cams?.some((c) => c.index === camIndex && c.status !== 'no_frames')}
            onClick={() => start({ kind: 'webcam', index: camIndex })}>Start camera</Button>
        </div>
      )}

      {tab === 'stream' && (
        <div className="space-y-2">
          <Field label="Network camera address" hint="RTSP or HTTP. Credentials stay on the server and are not displayed.">
            <input className={inputCls} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="rtsp://camera.local:554/stream1" spellCheck={false} />
          </Field>
          <Button variant="primary" className="w-full" busy={busy} disabled={!url.trim()} onClick={() => start({ kind: 'stream', url: url.trim() })}>Connect stream</Button>
        </div>
      )}

      {tab === 'recording' && (
        <div className="space-y-2">
          <Field label="Recorded video">
            <select className={inputCls} value={recId} onChange={(e) => setRecId(e.target.value)}>
              {recs.length === 0 && <option value="">No recordings yet</option>}
              {recs.map((r) => <option key={r.id} value={r.id}>{r.filename}</option>)}
            </select>
          </Field>
          <div className="flex gap-2">
            <label className={cx('inline-flex h-8 flex-1 cursor-pointer items-center justify-center rounded-[5px] border border-line bg-raised px-2 text-[13px] text-ink hover:border-line-strong')}>
              Upload video
              <input type="file" accept="video/*" className="sr-only" onChange={(e) => { const f = e.target.files?.[0]; if (f) void uploadFile(f) }} />
            </label>
            <Button className="flex-1" onClick={sample} busy={busy}>Add test clip</Button>
          </div>
          <Note>Played back at its own speed and always marked as a recording, never as live.</Note>
          <Button variant="primary" className="w-full" busy={busy} disabled={!recId} onClick={() => start({ kind: 'file', document_id: recId })}>Play recording</Button>
        </div>
      )}

      {tab === 'simulation' && (
        <div className="space-y-2">
          <Field label="Simulated scene">
            <select className={inputCls} value={scenario} onChange={(e) => setScenario(e.target.value)}>
              {SCENARIOS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </Field>
          <Note>Simulated pedestrians with known positions: useful without a camera, always labelled as simulation.</Note>
          <Button variant="primary" className="w-full" busy={busy} onClick={() => start({ kind: 'synthetic', scenario })}>Run simulation</Button>
        </div>
      )}

      {running && <Button variant="danger" className="w-full" onClick={stop} busy={busy}><Square className="size-3" />Stop monitoring</Button>}
      {(error || status?.error) && <Note tone="bad">{error ?? status?.error?.message}</Note>}
    </div>
  )
}

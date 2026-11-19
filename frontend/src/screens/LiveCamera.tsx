import { Crosshair } from 'lucide-react'
import { useEffect, useState } from 'react'

import { cx } from '../lib/cx'
import { live } from '../live/client'
import { useLive } from '../live/context'
import { SourcePicker } from '../live/SourcePicker'
import type { Pt } from '../live/types'
import { SiteMap } from '../map/SiteMap'
import { Button, Field, KV, Note, Section, inputCls } from '../ui/primitives'

const CORNER_HINT = ['far left', 'far right', 'near right', 'near left']

export function LiveCamera() {
  const { frame, snapshot, site, layers, setWantFrames, status } = useLive()
  const [picking, setPicking] = useState(false)
  const [pts, setPts] = useState<Pt[]>([])
  const [width, setWidth] = useState('')
  const [depth, setDepth] = useState('')
  const [measured, setMeasured] = useState(false)
  const [msg, setMsg] = useState<{ tone: 'muted' | 'bad'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setWantFrames(true)
    return () => setWantFrames(false)
  }, [setWantFrames])

  const src = snapshot?.source ?? status?.source
  const fw = frame?.width ?? snapshot?.frame.width ?? 1280
  const fh = frame?.height ?? snapshot?.frame.height ?? 720
  const cal = snapshot?.calibration
  const running = !!src && snapshot?.status !== 'idle'

  function click(e: React.MouseEvent<HTMLDivElement>) {
    if (!picking) return
    const r = e.currentTarget.getBoundingClientRect()
    const p: Pt = [((e.clientX - r.left) / r.width) * fw, ((e.clientY - r.top) / r.height) * fh]
    const next = [...pts, p]
    setPts(next)
    if (next.length === 4) setPicking(false)
  }

  async function apply() {
    setBusy(true)
    setMsg(null)
    try {
      const w = Number(width)
      const d = Number(depth)
      const res = await live.calibrate({ image_points: pts.map((p) => [Math.round(p[0] * 10) / 10, Math.round(p[1] * 10) / 10]),
        ...(w > 0 && d > 0 ? { width_m: w, height_m: d } : {}), confirmed: measured })
      setMsg({ tone: 'muted', text: res.metric ? 'Calibrated: densities and speeds are now in real units.' : 'Calibrated with assumed dimensions: densities stay relative.' })
      setPts([])
    } catch (e) {
      setMsg({ tone: 'bad', text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }

  const quad = picking || pts.length ? pts : cal?.image_points ?? []
  const synthetic = src?.kind === 'synthetic'

  return (
    <div className="grid h-full min-h-0 grid-cols-[264px_minmax(0,1fr)_340px]">
      <aside className="min-h-0 overflow-y-auto border-r border-line bg-panel" aria-label="Camera controls">
        <Section title="Source"><SourcePicker /></Section>
        <Section title="Floor calibration" aside={cal && <span>{cal.metric ? 'real units' : 'relative'}</span>}>
          {synthetic ? <Note>The simulated camera is exactly calibrated already.</Note> : !running ? <Note>Start a camera or recording to calibrate it.</Note> : (
            <div className="space-y-2.5">
              <p className="text-[12.5px] text-ink-2">Mark a rectangle on the floor (tape, tiles, a rug). Click its corners in order: far left, far right, near right, near left. Then give its real size.</p>
              <Button variant={picking ? 'primary' : 'plain'} className="w-full" onClick={() => { setPts([]); setPicking(!picking); setMsg(null) }}>
                <Crosshair className="size-3.5" />{picking ? `Click the ${CORNER_HINT[pts.length]} corner` : 'Mark floor corners'}
              </Button>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Width (m)"><input className={inputCls} inputMode="decimal" value={width} onChange={(e) => setWidth(e.target.value)} placeholder="e.g. 4" /></Field>
                <Field label="Depth (m)"><input className={inputCls} inputMode="decimal" value={depth} onChange={(e) => setDepth(e.target.value)} placeholder="e.g. 3" /></Field>
              </div>
              <label className="flex items-start gap-2 text-[12.5px] text-ink-2">
                <input type="checkbox" className="mt-0.5" checked={measured} onChange={(e) => setMeasured(e.target.checked)} />
                I measured these distances on the floor
              </label>
              <Button variant="primary" className="w-full" disabled={pts.length !== 4 || (measured && !(Number(width) > 0 && Number(depth) > 0))} busy={busy} onClick={apply}>
                Apply calibration
              </Button>
              {msg && <Note tone={msg.tone}>{msg.text}</Note>}
              {cal && <Note>Current: {cal.source}. {Math.round(cal.visible_fraction * 100)}% of the mapped floor is in view.</Note>}
            </div>
          )}
        </Section>
      </aside>

      <section className="flex min-h-0 flex-col bg-base p-3" aria-label="Camera view">
        <div className="mb-2 flex items-baseline justify-between gap-3 text-[13px]">
          <span className="font-semibold text-ink">{src?.label ?? 'No source'}</span>
          <span className="text-ink-2">
            {src ? (src.kind === 'live_camera' ? 'Live camera' : src.kind === 'recorded_video' ? 'Recorded video, not live' : 'Simulation, not camera data') : ''}
            {snapshot && <> {' '}| detector {snapshot.detector} | tracker {snapshot.tracker}</>}
          </span>
        </div>
        <div className="relative flex min-h-0 flex-1 items-center justify-center">
          {frame ? (
            <div className={cx('relative max-h-full max-w-full', picking && 'cursor-crosshair')} style={{ aspectRatio: `${fw} / ${fh}`, height: '100%' }} onClick={click}>
              <img src={frame.image} alt="Latest analysed camera frame" className="block h-full w-full select-none rounded-[4px] object-contain" draggable={false} />
              <svg viewBox={`0 0 ${fw} ${fh}`} preserveAspectRatio="none" className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
                {quad.length > 0 && (
                  <polygon points={quad.map((p) => p.join(',')).join(' ')} fill="color-mix(in srgb, var(--color-accent) 10%, transparent)"
                    stroke="var(--color-accent)" strokeWidth={2} strokeDasharray={picking ? '6 4' : undefined} vectorEffect="non-scaling-stroke" />
                )}
                {quad.map((p, i) => (
                  <g key={i}>
                    <circle cx={p[0]} cy={p[1]} r={fw / 120} fill="var(--color-accent)" stroke="#fff" strokeWidth={2} vectorEffect="non-scaling-stroke" />
                    <text x={p[0] + fw / 90} y={p[1] - fw / 110} fontSize={fw / 55} fill="#fff" stroke="#000" strokeWidth={fw / 500} paintOrder="stroke">{i + 1}</text>
                  </g>
                ))}
                {snapshot?.tracks.filter((t) => !t.predicted).map((t) => {
                  const [x1, y1, x2, y2] = t.box
                  return (
                    <g key={t.id}>
                      <rect x={x1 * fw} y={y1 * fh} width={(x2 - x1) * fw} height={(y2 - y1) * fh} fill="none" stroke="var(--color-accent-2)" strokeWidth={2} vectorEffect="non-scaling-stroke" />
                      <text x={x1 * fw + 3} y={y1 * fh - 5} fontSize={fw / 70} fill="#fff" stroke="#000" strokeWidth={fw / 600} paintOrder="stroke">#{t.id} {Math.round(t.conf * 100)}%</text>
                      <circle cx={t.foot_px[0]} cy={t.foot_px[1]} r={fw / 220} fill="var(--color-elevated)" />
                    </g>
                  )
                })}
              </svg>
            </div>
          ) : (
            <div className="max-w-sm text-center text-[13px] text-ink-2">
              {running ? 'Waiting for the first frame…' : 'Choose a camera, a recording or the simulation on the left. Frames are shown here at reduced size; analysis runs on full frames.'}
            </div>
          )}
        </div>
        {frame && snapshot && (
          <p className="mt-2 text-[12px] text-muted">
            Boxes: people the detector found in this frame, with track number and confidence. The yellow dot is the foot point mapped to the floor.
            Preview is about four frames a second; the map updates at the processing rate.
          </p>
        )}
      </section>

      <aside className="flex min-h-0 flex-col overflow-y-auto border-l border-line bg-panel" aria-label="Top-down view">
        <Section title="Top-down view">
          <div className="h-[230px]">{site && <SiteMap site={site} snapshot={snapshot?.status === 'idle' ? null : snapshot} layers={layers} compact />}</div>
        </Section>
        <Section title="Tracked people" aside={<span>{snapshot?.tracks.length ?? 0}</span>}>
          {!snapshot?.tracks.length ? <Note>No one is tracked right now.</Note> : (
            <table className="w-full text-[12.5px]">
              <thead><tr className="text-left text-muted"><th className="pb-1 font-normal">Id</th><th className="pb-1 font-normal">Position (m)</th><th className="pb-1 font-normal">Speed</th><th className="pb-1 text-right font-normal">State</th></tr></thead>
              <tbody>
                {snapshot.tracks.slice(0, 40).map((t) => (
                  <tr key={t.id} className="border-t border-line">
                    <td className="py-1 tabular">#{t.id}</td>
                    <td className="py-1 tabular">{t.ground[0].toFixed(1)}, {t.ground[1].toFixed(1)} <span className="text-muted">±{t.uncertainty_m}</span></td>
                    <td className="py-1 tabular">{t.speed.toFixed(2)}</td>
                    <td className="py-1 text-right text-ink-2">{t.predicted ? `estimated ${t.seen_ago_s.toFixed(1)} s` : t.in_view ? 'seen' : 'off map'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Section>
        {snapshot && (
          <Section title="Processing">
            <KV rows={[
              ['Analysed', `${snapshot.stats.fps.toFixed(1)} fps`], ['Camera delivers', `${snapshot.stats.capture_fps.toFixed(1)} fps`],
              ['Per frame', snapshot.stats.proc_ms != null ? `${snapshot.stats.proc_ms} ms` : '—'],
              ['Capture to result', snapshot.stats.e2e_ms != null ? `${snapshot.stats.e2e_ms} ms` : '—'],
              ['Frames skipped to stay current', snapshot.stats.skipped], ['Reconnects', snapshot.stats.reconnects],
            ]} />
          </Section>
        )}
      </aside>
    </div>
  )
}

import { MousePointer2, Pause, Play, RotateCcw, Square, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'

import { CrowdGuardProvider } from '../crowdguard/state'
import { BAND_LABEL, fmtInt, useCrowd } from '../crowdguard/store'
import { VenueMap as EventMap } from '../crowdguard/VenueMap'
import { cx } from '../lib/cx'
import { live } from '../live/client'
import { useLive } from '../live/context'
import type { Pt, SiteConfig, SiteGeometry } from '../live/types'
import { BAND_VAR } from '../map/palette'
import { SiteMap } from '../map/SiteMap'
import { Button, Field, KV, Note, Section, StatusText, inputCls } from '../ui/primitives'

type Tab = 'area' | 'event'

export function VenueMapScreen() {
  const [tab, setTab] = useState<Tab>('area')
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-10 shrink-0 items-end gap-1 border-b border-line bg-panel px-4" role="tablist">
        {([['area', 'Monitored area layout'], ['event', 'Event zones (simulated event)']] as [Tab, string][]).map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
            className={cx('relative px-3 pb-2 text-[13px]', tab === id ? 'font-semibold text-ink' : 'text-ink-2 hover:text-ink')}>
            {label}{tab === id && <span className="absolute inset-x-3 bottom-0 h-[2px] rounded-full bg-accent" aria-hidden />}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1">{tab === 'area' ? <AreaEditor /> : <CrowdGuardProvider active><EventModel /></CrowdGuardProvider>}</div>
    </div>
  )
}

// ---------------------------------------------------------------- monitored-area editor
type Tool = 'select' | 'obstacle' | 'zone' | 'exit' | 'walkable'
type Sel = { kind: 'obstacle' | 'zone' | 'portal'; id: string } | null

const TOOLS: { id: Tool; label: string; hint: string }[] = [
  { id: 'select', label: 'Select', hint: 'Click an item on the map or in the list to edit it.' },
  { id: 'zone', label: 'Zone', hint: 'Drag a rectangle to add a zone people are counted in.' },
  { id: 'obstacle', label: 'Obstacle', hint: 'Drag a rectangle over a wall, stage, barrier or kiosk.' },
  { id: 'exit', label: 'Exit', hint: 'Drag along a doorway to add an exit.' },
  { id: 'walkable', label: 'Walkable area', hint: 'Drag the outline of the floor people can use.' },
]

function toConfig(g: SiteGeometry): SiteConfig {
  const { rows: _r, cols: _c, blocked: _b, portal_capacity_ppm: _p, zone_area_m2: _z, ...cfg } = g
  return cfg
}

function rect(a: Pt, b: Pt): Pt[] {
  const r = (v: number) => Math.round(v * 10) / 10
  const [x1, x2] = [Math.min(a[0], b[0]), Math.max(a[0], b[0])].map(r)
  const [y1, y2] = [Math.min(a[1], b[1]), Math.max(a[1], b[1])].map(r)
  return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
}

function AreaEditor() {
  const { site, refreshSite, snapshot } = useLive()
  const [draftState, setDraftState] = useState<SiteConfig | null>(null)
  // Until the operator edits something, the draft is the saved layout.
  const draft = draftState ?? (site ? toConfig(site) : null)
  const setDraft = (next: SiteConfig | ((cur: SiteConfig | null) => SiteConfig | null)) =>
    setDraftState((prev) => (typeof next === 'function' ? next(prev ?? (site ? toConfig(site) : null)) : next))
  const [tool, setTool] = useState<Tool>('select')
  const [sel, setSel] = useState<Sel>(null)
  const [drag, setDrag] = useState<{ a: Pt; b: Pt } | null>(null)
  const [msg, setMsg] = useState<{ tone: 'muted' | 'bad'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  const dirty = useMemo(() => !!(site && draft && JSON.stringify(toConfig(site)) !== JSON.stringify(draft)), [site, draft])
  if (!site || !draft) return <p className="p-6 text-[13px] text-muted">Loading the site layout…</p>

  // The editor previews the draft on the same map renderer (blocked cells are recomputed on save).
  const preview: SiteGeometry = { ...site, ...draft }
  const nextId = (p: string) => `${p}-${Math.random().toString(36).slice(2, 6)}`

  function onPointer(kind: 'down' | 'move' | 'up', p: Pt) {
    if (tool === 'select') return
    if (kind === 'down') setDrag({ a: p, b: p })
    else if (kind === 'move' && drag) setDrag({ ...drag, b: p })
    else if (kind === 'up' && drag) {
      const d = { ...drag, b: p }
      setDrag(null)
      if (Math.hypot(d.b[0] - d.a[0], d.b[1] - d.a[1]) < 0.4) return
      setDraft((cur) => {
        if (!cur) return cur
        if (tool === 'obstacle') {
          const id = nextId('obstacle')
          setSel({ kind: 'obstacle', id })
          return { ...cur, obstacles: [...cur.obstacles, { id, name: `Obstacle ${cur.obstacles.length + 1}`, polygon: rect(d.a, d.b) }] }
        }
        if (tool === 'zone') {
          const id = nextId('zone')
          setSel({ kind: 'zone', id })
          return { ...cur, zones: [...cur.zones, { id, name: `Zone ${cur.zones.length + 1}`, polygon: rect(d.a, d.b), capacity: null, restricted: false }] }
        }
        if (tool === 'exit') {
          const id = nextId('exit')
          setSel({ kind: 'portal', id })
          const r = (v: number) => Math.round(v * 10) / 10
          return { ...cur, portals: [...cur.portals, { id, name: `Exit ${cur.portals.length + 1}`, kind: 'exit', a: [r(d.a[0]), r(d.a[1])], b: [r(d.b[0]), r(d.b[1])], available: true }] }
        }
        return { ...cur, walkable: rect(d.a, d.b) }
      })
    }
  }

  async function save() {
    if (!draft) return
    setBusy(true)
    setMsg(null)
    try {
      await live.saveSite(draft)
      await refreshSite()
      setDraftState(null)
      setMsg({ tone: 'muted', text: 'Layout saved. Monitoring now uses it.' })
    } catch (e) {
      setMsg({ tone: 'bad', text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }

  const selZone = sel?.kind === 'zone' ? draft.zones.find((z) => z.id === sel.id) : undefined
  const selObs = sel?.kind === 'obstacle' ? draft.obstacles.find((o) => o.id === sel.id) : undefined
  const selPortal = sel?.kind === 'portal' ? draft.portals.find((p) => p.id === sel.id) : undefined
  const remove = () => {
    if (!sel) return
    setDraft({ ...draft, zones: draft.zones.filter((z) => z.id !== sel.id), obstacles: draft.obstacles.filter((o) => o.id !== sel.id),
      portals: draft.portals.filter((p) => p.id !== sel.id) })
    setSel(null)
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-[264px_minmax(0,1fr)_300px]">
      <aside className="min-h-0 overflow-y-auto border-r border-line bg-panel">
        <Section title="Draw">
          <div className="grid grid-cols-2 gap-1.5">
            {TOOLS.map((t) => (
              <button key={t.id} type="button" onClick={() => setTool(t.id)} aria-pressed={tool === t.id}
                className={cx('flex h-8 items-center gap-1.5 rounded-[5px] border px-2 text-[13px]', tool === t.id ? 'border-accent bg-raised text-ink' : 'border-line text-ink-2 hover:text-ink')}>
                {t.id === 'select' ? <MousePointer2 className="size-3.5" /> : <Square className="size-3.5" />}{t.label}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[12.5px] text-ink-2">{TOOLS.find((t) => t.id === tool)?.hint}</p>
        </Section>
        <Section title="Items" collapsible>
          <ul className="-mx-2 text-[13px]">
            {[...draft.zones.map((z) => ({ kind: 'zone' as const, id: z.id, name: z.name, extra: z.restricted ? 'restricted' : 'zone' })),
              ...draft.obstacles.map((o) => ({ kind: 'obstacle' as const, id: o.id, name: o.name, extra: 'obstacle' })),
              ...draft.portals.map((p) => ({ kind: 'portal' as const, id: p.id, name: p.name, extra: p.kind.replace('_', ' ') }))].map((it) => (
              <li key={it.id}>
                <button type="button" onClick={() => { setTool('select'); setSel({ kind: it.kind, id: it.id }) }}
                  className={cx('flex w-full justify-between rounded-[5px] px-2 py-1 text-left', sel?.id === it.id ? 'bg-raised' : 'hover:bg-raised')}>
                  <span className="truncate">{it.name}</span><span className="text-muted">{it.extra}</span>
                </button>
              </li>
            ))}
          </ul>
        </Section>
        <Section title="Area and grid" collapsible defaultOpen={false}>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Width (m)"><input className={inputCls} type="number" min={2} step={0.5} value={draft.width_m} onChange={(e) => setDraft({ ...draft, width_m: Number(e.target.value) })} /></Field>
            <Field label="Depth (m)"><input className={inputCls} type="number" min={2} step={0.5} value={draft.height_m} onChange={(e) => setDraft({ ...draft, height_m: Number(e.target.value) })} /></Field>
            <Field label="Grid cell (m)"><input className={inputCls} type="number" min={0.25} max={5} step={0.25} value={draft.cell_m} onChange={(e) => setDraft({ ...draft, cell_m: Number(e.target.value) })} /></Field>
            <Field label="Density spread (m)"><input className={inputCls} type="number" min={0.2} max={5} step={0.1} value={draft.kde_sigma_m} onChange={(e) => setDraft({ ...draft, kde_sigma_m: Number(e.target.value) })} /></Field>
            <Field label="Occupied from (p/m²)"><input className={inputCls} type="number" min={0.1} step={0.1} value={draft.occupied_density} onChange={(e) => setDraft({ ...draft, occupied_density: Number(e.target.value) })} /></Field>
            <Field label="Congested from (p/m²)"><input className={inputCls} type="number" min={0.2} step={0.1} value={draft.congested_density} onChange={(e) => setDraft({ ...draft, congested_density: Number(e.target.value) })} /></Field>
          </div>
          <p className="mt-2 text-[12px] text-muted">Changing the size does not move items; a measured camera calibration rescales the whole layout instead.</p>
        </Section>
      </aside>

      <section className="relative min-h-0 bg-base p-3">
        <SiteMap site={preview} snapshot={snapshot && snapshot.grid.rows === site.rows && snapshot.grid.cols === site.cols && !dirty ? snapshot : null}
          layers={{ heat: false, free: false, people: false, vectors: false, route: false, zones: true }}
          onSelect={(s) => { if (tool === 'select' && s?.kind === 'zone') setSel({ kind: 'zone', id: s.id }) }}
          onPointer={(k, p) => onPointer(k, p)}
          overlay={() => (
            <>
              {drag && tool !== 'exit' && (
                <polygon points={rect(drag.a, drag.b).map((p) => p.join(',')).join(' ')} fill="color-mix(in srgb, var(--color-accent) 15%, transparent)"
                  stroke="var(--color-accent)" strokeDasharray="4 3" strokeWidth={1.5} vectorEffect="non-scaling-stroke" pointerEvents="none" />
              )}
              {drag && tool === 'exit' && (
                <line x1={drag.a[0]} y1={drag.a[1]} x2={drag.b[0]} y2={drag.b[1]} stroke="var(--color-accent)" strokeWidth={5} strokeLinecap="round" vectorEffect="non-scaling-stroke" pointerEvents="none" />
              )}
              {sel && (selObs || selZone) && (
                <polygon points={(selObs ?? selZone)!.polygon.map((p) => p.join(',')).join(' ')} fill="none" stroke="var(--color-accent-2)" strokeWidth={2.5}
                  vectorEffect="non-scaling-stroke" pointerEvents="none" />
              )}
            </>
          )} />
      </section>

      <aside className="min-h-0 overflow-y-auto border-l border-line bg-panel">
        <Section title={selZone ? 'Zone' : selObs ? 'Obstacle' : selPortal ? 'Exit or entrance' : 'Selection'}
          aside={sel && <button type="button" onClick={remove} className="flex items-center gap-1 hover:text-critical"><Trash2 className="size-3.5" />Delete</button>}>
          {!sel && <Note>Nothing selected. Use the drawing tools, or pick an item from the list.</Note>}
          {selZone && (
            <div className="space-y-2">
              <Field label="Name"><input className={inputCls} value={selZone.name} onChange={(e) => setDraft({ ...draft, zones: draft.zones.map((z) => z.id === selZone.id ? { ...z, name: e.target.value } : z) })} /></Field>
              <Field label="Capacity (people)" hint="Leave empty to use 2 people per m².">
                <input className={inputCls} type="number" min={1} value={selZone.capacity ?? ''} onChange={(e) => setDraft({ ...draft, zones: draft.zones.map((z) => z.id === selZone.id ? { ...z, capacity: e.target.value ? Number(e.target.value) : null } : z) })} />
              </Field>
              <label className="flex items-center gap-2 text-[13px] text-ink-2">
                <input type="checkbox" checked={selZone.restricted} onChange={(e) => setDraft({ ...draft, zones: draft.zones.map((z) => z.id === selZone.id ? { ...z, restricted: e.target.checked } : z) })} />
                Restricted: never route people through it
              </label>
            </div>
          )}
          {selObs && <Field label="Name"><input className={inputCls} value={selObs.name} onChange={(e) => setDraft({ ...draft, obstacles: draft.obstacles.map((o) => o.id === selObs.id ? { ...o, name: e.target.value } : o) })} /></Field>}
          {selPortal && (
            <div className="space-y-2">
              <Field label="Name"><input className={inputCls} value={selPortal.name} onChange={(e) => setDraft({ ...draft, portals: draft.portals.map((p) => p.id === selPortal.id ? { ...p, name: e.target.value } : p) })} /></Field>
              <Field label="Type">
                <select className={inputCls} value={selPortal.kind} onChange={(e) => setDraft({ ...draft, portals: draft.portals.map((p) => p.id === selPortal.id ? { ...p, kind: e.target.value as typeof p.kind } : p) })}>
                  <option value="exit">Exit</option><option value="emergency_exit">Emergency exit</option><option value="entrance">Entrance</option>
                </select>
              </Field>
              <p className="text-[12.5px] text-muted">Width {Math.hypot(selPortal.b[0] - selPortal.a[0], selPortal.b[1] - selPortal.a[1]).toFixed(1)} m, about {Math.round(Math.hypot(selPortal.b[0] - selPortal.a[0], selPortal.b[1] - selPortal.a[1]) * 82)} people per minute.</p>
            </div>
          )}
        </Section>
        <Section title="Save">
          <div className="flex gap-2">
            <Button variant="primary" className="flex-1" disabled={!dirty} busy={busy} onClick={save}>Save layout</Button>
            <Button disabled={!dirty} onClick={() => { setDraftState(null); setSel(null) }}><RotateCcw className="size-3.5" />Discard</Button>
          </div>
          {dirty && <Note tone="warn">Unsaved changes: the map shows the draft; monitoring still uses the saved layout.</Note>}
          {msg && <Note tone={msg.tone}>{msg.text}</Note>}
        </Section>
      </aside>
    </div>
  )
}

// ---------------------------------------------------------------- zone-level simulated event
function EventModel() {
  const { venue, sim, frame, tick, setTick, playing, setPlaying, loading, error } = useCrowd()
  const [sel, setSel] = useState('main_stage')
  if (error) return <p className="p-6 text-[13px] text-critical">{error}</p>
  if (!venue || !sim || !frame) return <p className="p-6 text-[13px] text-muted">{loading ? 'Running the event simulation…' : 'Preparing…'}</p>
  const r = frame.readings[sel]
  const fc = frame.forecasts[sel]
  const zone = venue.zones.find((z) => z.id === sel)
  const relieve = frame.recommendations.find((x) => x.route?.recommended && x.target === sel) ?? frame.recommendations.find((x) => x.route?.recommended)
  const last = sim.frames.length - 1
  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_320px]">
      <section className="flex min-h-0 flex-col gap-2 bg-base p-3">
        <div className="flex flex-wrap items-center gap-3 text-[13px]">
          <Button variant="primary" onClick={() => { if (tick >= last) setTick(0); setPlaying(!playing) }}>
            {playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}{playing ? 'Pause' : 'Play'}
          </Button>
          <span className="font-display text-[20px] font-semibold tabular">{frame.clock}</span>
          <input type="range" min={0} max={last} value={tick} onChange={(e) => { setPlaying(false); setTick(Number(e.target.value)) }}
            className="min-w-[200px] flex-1 accent-[var(--color-accent)]" aria-label="Event minute" />
          <span className="text-ink-2">Simulated festival, zone counts only. Not camera data.</span>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          <EventMap venue={venue} readings={frame.readings} edgeFlows={frame.edge_flows} exitStatus={frame.exit_status}
            route={relieve?.route?.recommended ?? null} selected={sel} onSelect={setSel} />
        </div>
      </section>
      <aside className="min-h-0 overflow-y-auto border-l border-line bg-panel">
        <Section title={zone?.name ?? 'Zone'}>
          {r && (
            <div className="space-y-2">
              <div className="flex items-baseline justify-between">
                <span className="font-display text-[28px] font-semibold leading-none tabular">{fmtInt(r.estimate)}</span>
                <StatusText colour={BAND_VAR[r.band]}>{BAND_LABEL[r.band] ?? r.band}</StatusText>
              </div>
              <KV rows={[
                ['Estimate range', r.estimate == null ? 'unknown' : `${fmtInt(r.lower)} to ${fmtInt(r.upper)}`],
                ['Safe capacity', fmtInt(r.safe_capacity)], ['Occupancy', r.occupancy_pct == null ? 'unknown' : `${r.occupancy_pct}%`],
                ['Camera feed', r.feed_status === 'ok' ? 'live (simulated)' : r.feed_status],
                ['In 15 minutes', fc?.available ? `${fc.predicted_end_pct}% (${fc.method})` : '—'],
                ['Reaches capacity', fc?.available ? (fc.current_pct >= 100 ? 'already above' : fc.minutes_to_capacity ? `in about ${fc.minutes_to_capacity} min` : 'not within 15 min') : '—'],
              ]} />
            </div>
          )}
        </Section>
        <Section title="Recommended action">
          {relieve ? (
            <div className="space-y-1.5 text-[13px]">
              <p className="font-semibold">{relieve.title}</p>
              <p className="text-ink-2">{relieve.detail}</p>
              <ul className="list-disc space-y-1 pl-4 text-[12.5px] text-ink-2">{relieve.rationale.slice(0, 4).map((x) => <li key={x}>{x}</li>)}</ul>
              <p className="text-[12px] text-muted">Advisory: an organiser decides.</p>
            </div>
          ) : <Note>No action recommended at {frame.clock}.</Note>}
        </Section>
        <Section title="Alerts" aside={<span>{frame.alerts.length}</span>}>
          {frame.alerts.length === 0 ? <Note>None at this minute.</Note> : (
            <ul className="space-y-1.5 text-[13px]">{frame.alerts.slice(0, 6).map((a) => <li key={a.id}><span className="font-medium">{a.severity}</span> {a.message}</li>)}</ul>
          )}
        </Section>
      </aside>
    </div>
  )
}

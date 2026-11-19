import { Crosshair, LocateFixed, PanelRightClose, PanelRightOpen } from 'lucide-react'
import { useMemo, useState } from 'react'

import { cx } from '../lib/cx'
import { fmtClock } from '../lib/format'
import { live } from '../live/client'
import { useLive } from '../live/context'
import { SourcePicker } from '../live/SourcePicker'
import type { Alert, Snapshot, Track, ZoneState } from '../live/types'
import { BAND_TEXT, BAND_VAR, SEVERITY_VAR } from '../map/palette'
import { SiteMap, type Selection } from '../map/SiteMap'
import { Button, KV, Note, Section, StatusText, Toggle } from '../ui/primitives'

export function CommandCentre() {
  const { site, snapshot, layers, setLayers, status } = useLive()
  const [selection, setSelection] = useState<Selection>(null)
  const [picking, setPicking] = useState(false)
  const [rightOpen, setRightOpen] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const idle = !snapshot || snapshot.status === 'idle'

  async function setOrigin(body: Parameters<typeof live.origin>[0]) {
    setErr(null)
    try {
      await live.origin(body)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }

  async function toggleExit(id: string, available: boolean) {
    setErr(null)
    try {
      await live.portal(id, available)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }

  const origin = status?.origin
  return (
    <div className={cx('grid h-full min-h-0', rightOpen ? 'grid-cols-[264px_minmax(0,1fr)_320px]' : 'grid-cols-[264px_minmax(0,1fr)]')}>
      <aside className="min-h-0 overflow-y-auto border-r border-line bg-panel" aria-label="Monitoring controls">
        <Section title="Source"><SourcePicker /></Section>
        <Section title="Map layers" collapsible>
          <Toggle checked={layers.heat} onChange={(v) => setLayers({ ...layers, heat: v })} label="Crowd density"
            swatch={<span className="h-2 w-5 rounded-sm bg-gradient-to-r from-elevated via-high to-critical" aria-hidden />} />
          <Toggle checked={layers.free} onChange={(v) => setLayers({ ...layers, free: v })} label="Open floor"
            swatch={<span className="h-2 w-5 rounded-sm bg-[color-mix(in_srgb,var(--color-map-free)_45%,transparent)]" aria-hidden />} />
          <Toggle checked={layers.people} onChange={(v) => setLayers({ ...layers, people: v })} label="People" />
          <Toggle checked={layers.vectors} onChange={(v) => setLayers({ ...layers, vectors: v })} label="Movement" />
          <Toggle checked={layers.route} onChange={(v) => setLayers({ ...layers, route: v })} label="Recommended route"
            swatch={<span className="h-1 w-5 rounded-full bg-gradient-to-r from-accent to-accent-2" aria-hidden />} />
          <Toggle checked={layers.zones} onChange={(v) => setLayers({ ...layers, zones: v })} label="Zones" />
        </Section>
        {site && (
          <Section title="Zones" collapsible aside={<span>{site.zones.length}</span>}>
            <ul className="-mx-2">
              {site.zones.map((z) => {
                const zs = snapshot?.zones.find((x) => x.id === z.id)
                const band = z.restricted ? 'restricted' : zs?.band ?? 'unknown'
                const sel = selection?.kind === 'zone' && selection.id === z.id
                return (
                  <li key={z.id}>
                    <button type="button" onClick={() => setSelection({ kind: 'zone', id: z.id })}
                      className={cx('flex w-full items-center justify-between gap-2 rounded-[5px] px-2 py-1.5 text-left text-[13px]', sel ? 'bg-raised' : 'hover:bg-raised')}>
                      <StatusText colour={BAND_VAR[band]} title={BAND_TEXT[band]}>{z.name}</StatusText>
                      <span className="text-ink-2 tabular">{z.restricted ? 'restricted' : zs?.population == null ? '—' : `${Math.round(zs.population)}/${zs.capacity}`}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </Section>
        )}
        {site && (
          <Section title="Exits" collapsible aside={<span>reported by staff</span>}>
            <ul className="space-y-1">
              {site.portals.filter((p) => p.kind !== 'entrance').map((p) => (
                <li key={p.id} className="flex items-center justify-between gap-2 text-[13px]">
                  <span className="truncate">{p.name}{p.kind === 'emergency_exit' && <span className="text-muted"> (emergency)</span>}</span>
                  <button type="button" onClick={() => toggleExit(p.id, !p.available)}
                    className={cx('rounded-[4px] border px-1.5 py-0.5 text-[12px]', p.available ? 'border-line text-ink-2 hover:text-ink' : 'border-critical text-critical')}>
                    {p.available ? 'Open' : 'Blocked'}
                  </button>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[12px] text-muted">Mark an exit blocked only when staff confirm an obstruction. Guidance avoids it; nothing here closes an exit.</p>
          </Section>
        )}
      </aside>

      <section className="relative min-h-0 bg-base p-3" aria-label="Map">
        {site ? (
          <SiteMap site={site} snapshot={idle ? null : snapshot} layers={layers} selection={selection} onSelect={setSelection}
            pickPoint={picking} onPickPoint={(p) => { setPicking(false); void setOrigin({ mode: 'point', x: p[0], y: p[1] }) }} />
        ) : <p className="p-6 text-[13px] text-muted">Loading the site layout…</p>}
        {idle && site && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <div className="pointer-events-auto max-w-sm rounded-[8px] border border-line bg-raised/95 p-5 text-center shadow-lg">
              <p className="font-display text-[18px] font-semibold">Nothing is being monitored</p>
              <p className="mt-1 text-[13px] text-ink-2">Start a camera, play a recording or run the simulation from the panel on the left. Until then every part of the floor is shown as not observed.</p>
            </div>
          </div>
        )}
        <div className="absolute right-4 top-4 flex gap-1.5">
          <Button variant={picking ? 'primary' : 'plain'} onClick={() => setPicking(!picking)} title="Choose where the route starts">
            <Crosshair className="size-3.5" />{picking ? 'Click the map' : 'Route from a point'}
          </Button>
          {origin && origin.mode !== 'auto' && (
            <Button onClick={() => setOrigin({ mode: 'auto' })} title="Start routes from the busiest zone"><LocateFixed className="size-3.5" />Busiest zone</Button>
          )}
          <Button variant="quiet" onClick={() => setRightOpen(!rightOpen)} title={rightOpen ? 'Hide details' : 'Show details'}>
            {rightOpen ? <PanelRightClose className="size-4" /> : <PanelRightOpen className="size-4" />}
          </Button>
        </div>
        {err && <p className="absolute bottom-14 left-1/2 -translate-x-1/2 rounded bg-raised px-3 py-1.5 text-[13px] text-critical shadow">{err}</p>}
      </section>

      {rightOpen && (
        <aside className="min-h-0 overflow-y-auto border-l border-line bg-panel" aria-label="Details">
          <Context snapshot={idle ? null : snapshot} selection={selection} onClear={() => setSelection(null)}
            onRouteFromZone={(id) => setOrigin({ mode: 'zone', zone_id: id })} />
          <AlertsSection alerts={idle ? [] : snapshot?.alerts ?? []} />
          <RouteSection snapshot={idle ? null : snapshot} />
        </aside>
      )}
    </div>
  )
}

function Sparkline({ values, capacity }: { values: number[]; capacity: number }) {
  if (values.length < 2) return <p className="text-[12px] text-muted">Trend appears after a few seconds of observation.</p>
  const max = Math.max(capacity, ...values) * 1.05
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 100},${30 - (v / max) * 30}`).join(' ')
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="h-10 w-full" role="img" aria-label="Population over the last minute">
      <line x1={0} x2={100} y1={30 - (capacity / max) * 30} y2={30 - (capacity / max) * 30} stroke="var(--color-critical)" strokeDasharray="2 2" strokeWidth={0.6} />
      <polyline points={pts} fill="none" stroke="var(--color-accent)" strokeWidth={1.4} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

function Context({ snapshot, selection, onClear, onRouteFromZone }: {
  snapshot: Snapshot | null; selection: Selection; onClear: () => void; onRouteFromZone: (id: string) => void
}) {
  const metric = !!snapshot?.calibration?.metric
  if (selection?.kind === 'zone') {
    const z: ZoneState | undefined = snapshot?.zones.find((x) => x.id === selection.id)
    return (
      <Section title={z?.name ?? 'Zone'} aside={<button type="button" className="hover:text-ink" onClick={onClear}>Clear</button>}>
        {!z ? <Note>No observation for this zone yet.</Note> : (
          <div className="space-y-3">
            <div className="flex items-baseline justify-between">
              <span className="font-display text-[28px] font-semibold leading-none tabular">{z.population == null ? '—' : Math.round(z.population)}</span>
              <StatusText colour={BAND_VAR[z.band]}>{BAND_TEXT[z.band]}</StatusText>
            </div>
            <KV rows={[
              ['Capacity', z.capacity],
              ['Occupancy', z.occupancy_pct == null ? 'unknown' : `${z.occupancy_pct}%`],
              [metric ? 'Density' : 'Density index', z.population == null ? '—' : metric ? `${z.density} p/m²` : `${z.density_index} (1 = congested)`],
              ['Walking speed', z.mean_speed == null ? '—' : `${z.mean_speed} m/s${metric ? '' : ' (assumed scale)'}`],
              ['Area', `${z.area_m2} m²`],
              ['In camera view', `${Math.round(z.visible_fraction * 100)}%`],
            ]} />
            {z.note && <Note tone="warn">{z.note}</Note>}
            <Sparkline values={snapshot?.zone_history[z.id] ?? []} capacity={z.capacity} />
            {!z.restricted && <Button onClick={() => onRouteFromZone(z.id)}>Guide people from this zone</Button>}
          </div>
        )}
      </Section>
    )
  }
  if (selection?.kind === 'track') {
    const t: Track | undefined = snapshot?.tracks.find((x) => x.id === selection.id)
    return (
      <Section title={`Person #${selection.id}`} aside={<button type="button" className="hover:text-ink" onClick={onClear}>Clear</button>}>
        {!t ? <Note>This person is no longer tracked.</Note> : (
          <KV rows={[
            ['Status', t.predicted ? `estimated, last seen ${t.seen_ago_s.toFixed(1)} s ago` : 'detected now'],
            ['Detection confidence', t.conf.toFixed(2)],
            ['Position', `${t.ground[0].toFixed(1)}, ${t.ground[1].toFixed(1)} m`],
            ['Position uncertainty', `± ${t.uncertainty_m} m`],
            ['Speed', `${t.speed.toFixed(2)} m/s${metric ? '' : ' (assumed scale)'}`],
            ['Last seen', fmtClock(t.last_seen, true)],
          ]} />
        )}
      </Section>
    )
  }
  if (!snapshot) {
    return <Section title="Area"><Note>Details appear here once a source is running. Select a zone or a person on the map to inspect it.</Note></Section>
  }
  const s = snapshot.space
  const parts: [string, number, string][] = [
    ['Open', s.available_m2, 'color-mix(in srgb, var(--color-map-free) 55%, transparent)'], ['Occupied', s.occupied_m2, 'var(--color-ink-2)'],
    ['Congested', s.congested_m2, 'var(--color-critical)'], ['Not observed', s.unknown_m2, 'var(--color-unknown)'],
  ]
  const total = parts.reduce((a, p) => a + p[1], 0) || 1
  return (
    <Section title="Area" aside={<span>{snapshot.calibration?.source}</span>}>
      <div className="flex items-baseline justify-between">
        <span className="font-display text-[28px] font-semibold leading-none tabular">{s.people_in_view ?? '—'}</span>
        <span className="text-[13px] text-ink-2">people in view</span>
      </div>
      <div className="mt-3 flex h-2.5 overflow-hidden rounded-full" role="img" aria-label="Walkable floor by state">
        {parts.map(([k, v, c]) => v > 0 && <span key={k} style={{ width: `${(v / total) * 100}%`, background: c }} title={`${k}: ${v} m²`} />)}
      </div>
      <ul className="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[12.5px]">
        {parts.map(([k, v, c]) => (
          <li key={k} className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-ink-2"><span className="inline-block size-2 rounded-sm" style={{ background: c }} aria-hidden />{k}</span>
            <span className="tabular">{v} m²</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[12.5px] text-ink-2">Usable free floor: <span className="text-ink tabular">{s.free_space_m2} m²</span>{snapshot.calibration?.metric ? '' : ' (assumed scale)'}</p>
      {snapshot.detection_failed && <Note tone="bad">Detection failed on the latest frame: the area is shown as not observed.</Note>}
    </Section>
  )
}

const KIND_TEXT: Record<string, string> = {
  zone_capacity_exceeded: 'Capacity exceeded', zone_near_capacity: 'Near capacity', rapid_accumulation: 'Rapid build-up',
  corridor_congestion: 'Congestion', camera_disconnected: 'Camera disconnected', camera_reconnected: 'Camera back', detection_degraded: 'Detection degraded',
  exit_unavailable: 'Exit unavailable', route_changed: 'Route changed', flow_slowed: 'Flow slowed', camera_slow: 'Camera slow',
}

function placeOf(a: Alert): string {
  return Object.entries(a.location).filter(([k, v]) => !k.endsWith('_id') && typeof v === 'string' && v).map(([, v]) => v).join(', ')
}

function AlertsSection({ alerts }: { alerts: Alert[] }) {
  return (
    <Section title="Alerts" collapsible aside={<span>{alerts.length ? `${alerts.length} active` : 'none'}</span>}>
      {alerts.length === 0 ? <Note>No active alerts.</Note> : (
        <ul className="space-y-3">
          {alerts.map((a) => (
            <li key={a.id} className="border-l-2 pl-2.5" style={{ borderColor: SEVERITY_VAR[a.severity] }}>
              <div className="flex items-baseline justify-between gap-2 text-[12.5px]">
                <span className="font-semibold" style={{ color: SEVERITY_VAR[a.severity] }}>{KIND_TEXT[a.kind] ?? a.kind}</span>
                <span className="text-muted tabular">{fmtClock(a.raised_at)}</span>
              </div>
              <p className="text-[13px] text-ink">{a.observation}</p>
              <p className="text-[12.5px] text-ink-2">{a.action}</p>
              {placeOf(a) && <p className="text-[12px] text-muted">{placeOf(a)}</p>}
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}

function RouteSection({ snapshot }: { snapshot: Snapshot | null }) {
  const r = snapshot?.route
  const rows = useMemo(() => (r?.available ? [
    ['From', r.origin], ['To', `${r.exit_name}${r.exit_kind === 'emergency_exit' ? ' (emergency exit)' : ''}`],
    ['Distance', `${r.length_m} m${snapshot?.calibration?.metric ? '' : ' (assumed scale)'}`], ['Walking time', `about ${Math.max(1, Math.round((r.walk_s ?? 0) / 60))} min`],
    ['Held for', `${Math.round(r.held_s ?? 0)} s`],
  ] as [string, string | undefined][] : []), [r, snapshot?.calibration?.metric])
  return (
    <Section title="Recommended route" collapsible>
      {!r ? <Note>Routes appear once a source is running.</Note> : !r.available ? <Note tone="warn">{r.reason}</Note> : (
        <div className="space-y-2.5">
          <KV rows={rows.map(([k, v]) => [k, v ?? '—'])} />
          {r.pending_switch ? <Note>A better route has been cheaper for {r.pending_switch} update(s); it is adopted only if that holds.</Note> : null}
          {(r.reasons ?? []).length > 0 && (
            <ul className="list-disc space-y-1 pl-4 text-[12.5px] text-ink-2">{r.reasons!.map((x) => <li key={x}>{x}</li>)}</ul>
          )}
          <p className="text-[12px] text-muted">{r.advisory}</p>
        </div>
      )}
    </Section>
  )
}

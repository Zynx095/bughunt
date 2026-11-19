import { ShieldCheck, ShieldX, Siren } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { Badge, Button, Card, ErrorBox, PageHeader, Spinner, Tabs } from '../../components/ui'
import { useApp } from '../../context'
import { short } from '../../lib/format'
import { cg, cgResult } from '../api'
import { useCrowd } from '../store'
import type { Incident } from '../types'
import { PlaybackBar, SeverityBadge, SimGate, SyntheticBadge } from '../widgets'

const ACTIONS: Record<string, string[]> = {
  detected: ['acknowledge', 'note'],
  acknowledged: ['respond', 'resolve', 'note'],
  responding: ['monitor', 'resolve', 'note'],
  monitoring: ['respond', 'resolve', 'note'],
  resolved: ['close', 'respond', 'note'],
  closed: [],
}
const STEPS = ['detected', 'acknowledged', 'responding', 'monitoring', 'resolved', 'closed']

export function IncidentsPage() {
  return <SimGate><Incidents /></SimGate>
}

function Lifecycle({ status }: { status: string }) {
  const idx = STEPS.indexOf(status)
  return (
    <ol className="flex flex-wrap items-center gap-1 text-[10px] font-semibold uppercase tracking-wide">
      {STEPS.map((s, i) => (
        <li key={s} className={i <= idx ? 'rounded bg-[var(--accent)]/15 px-1.5 py-0.5 text-ink' : 'rounded px-1.5 py-0.5 text-muted'}>{i <= idx ? '●' : '○'} {s}</li>
      ))}
    </ol>
  )
}

function Incidents() {
  const { sim, frame, tick } = useCrowd()
  const { identity } = useApp()
  const [view, setView] = useState<'live' | 'sim'>('live')
  const [list, setList] = useState<Incident[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [verify, setVerify] = useState<Record<string, { valid: boolean; checks: { check: string; passed: boolean }[] }>>({})
  const [busy, setBusy] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const { result } = await cgResult<{ incidents: Incident[] }>('/incidents')
      setList(result.incidents)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }, [])
  useEffect(() => {
    const id = window.setTimeout(() => { void reload() }, 0)
    return () => window.clearTimeout(id)
  }, [reload])

  if (!sim || !frame) return null

  async function openFrom(alertId: string) {
    const a = frame!.alerts.find((x) => x.id === alertId)
    if (!a) return
    setBusy(alertId)
    setErr(null)
    const evidence = { alert: a, clock: frame!.clock, tick, summary: frame!.summary, data_label: 'SYNTHETIC simulation snapshot',
      readings: Object.fromEntries(Object.entries(frame!.readings).map(([k, r]) => [k, { estimate: r.estimate, lower: r.lower, upper: r.upper, occupancy_pct: r.occupancy_pct, band: r.band, feed: r.feed_status }])) }
    const env = await cg<Incident>('/incidents', { title: a.message, zone_id: a.target, severity: a.severity === 'info' ? 'low' : a.severity,
      source: 'simulation', alert_id: a.id, evidence, note: `Opened from alert ${a.rule} at ${frame!.clock}` })
    if (!env.success) setErr(env.error?.message ?? 'Could not open incident')
    setBusy(null)
    await reload()
  }

  async function act(inc: Incident, action: string) {
    setBusy(inc.id + action)
    setErr(null)
    const env = await cg<Incident>(`/incidents/${inc.id}/actions`, { action, note: notes[inc.id] ?? '' })
    if (!env.success) setErr(`${env.error?.code}: ${env.error?.message}`)
    else setNotes({ ...notes, [inc.id]: '' })
    setBusy(null)
    await reload()
  }

  async function doVerify(inc: Incident) {
    const { result } = await cgResult<{ valid: boolean; checks: { check: string; passed: boolean }[] }>(`/incidents/${inc.id}/verify`)
    setVerify({ ...verify, [inc.id]: result })
  }

  const openAlertIds = new Set((list ?? []).filter((i) => i.status !== 'closed').map((i) => i.alert_id))
  return (
    <div className="space-y-4">
      <PageHeader title="Incident Management" icon={<Siren className="mt-1 size-6 text-[var(--accent)]" />}
        description="Alerts become incidents only when a person opens them. Every lifecycle step is a human action, hash-chained to the evidence snapshot and to the previous step; closing seals the timeline under a Merkle root and needs a second person (four-eyes)."
        actions={<Tabs value={view} onChange={setView} options={[{ id: 'live', label: 'Operator incidents (persisted)' }, { id: 'sim', label: 'Scenario timeline (simulated)' }]} />} />
      {err && <ErrorBox>{err}</ErrorBox>}
      {view === 'live' ? (
        <>
          <PlaybackBar />
          <Card title={`Alerts at ${frame.clock}`} subtitle={`Open an incident as ${identity.actor} (${identity.role}). Evidence is the current snapshot, hashed by the crypto engine.`}>
            {frame.alerts.length === 0 ? <p className="text-sm text-muted">No alerts at this minute.</p> : (
              <ul className="divide-y divide-line">
                {frame.alerts.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center gap-2 py-2">
                    <SeverityBadge severity={a.severity} /><span className="min-w-0 flex-1 text-sm">{a.message}</span>
                    {openAlertIds.has(a.id) ? <Badge tone="info">incident open</Badge> :
                      <Button size="sm" onClick={() => openFrom(a.id)} busy={busy === a.id}>Open incident</Button>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          {!list ? <Spinner /> : list.length === 0 ? <p className="text-sm text-muted">No operator incidents yet.</p> : (
            <div className="space-y-3">
              {list.map((inc) => (
                <Card key={inc.id} title={<span className="flex flex-wrap items-center gap-2"><span className="font-mono">{inc.id}</span><SeverityBadge severity={inc.severity} />{inc.title}</span>}
                  subtitle={`opened by ${inc.created_by} · ${inc.source} · evidence ${short(inc.evidence_hash, 16)}${inc.sealed_root ? ` · sealed root ${short(inc.sealed_root, 16)}` : ''}`}
                  actions={<Button size="sm" variant="ghost" onClick={() => doVerify(inc)}>Verify</Button>}>
                  <Lifecycle status={inc.status} />
                  {verify[inc.id] && (
                    <div className={`mt-2 flex flex-wrap items-center gap-2 rounded-lg border px-2 py-1.5 text-xs ${verify[inc.id].valid ? 'border-good/30 text-good-ink' : 'border-critical/30 text-critical-ink'}`}>
                      {verify[inc.id].valid ? <ShieldCheck className="size-4" /> : <ShieldX className="size-4" />}
                      {verify[inc.id].checks.map((c) => <span key={c.check}>{c.passed ? '✔' : '✖'} {c.check}</span>)}
                    </div>
                  )}
                  <ol className="mt-2 space-y-1 border-l border-line pl-3 text-xs">
                    {inc.events.map((e) => (
                      <li key={e.seq}><span className="font-mono text-muted">{new Date(e.ts).toLocaleTimeString()}</span> <b>{e.action}</b> → {e.status} by {e.actor} ({e.role}){e.note ? `: ${e.note}` : ''} <span className="font-mono text-[10px] text-muted" title={`prev ${e.prev_hash}`}>#{short(e.hash, 10)}</span></li>
                    ))}
                  </ol>
                  {ACTIONS[inc.status]?.length > 0 && (
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <input value={notes[inc.id] ?? ''} onChange={(e) => setNotes({ ...notes, [inc.id]: e.target.value })} placeholder="Decision note (recorded in the chain)"
                        className="min-w-[220px] flex-1 rounded-lg border border-line bg-surface px-2 py-1 text-xs" />
                      {ACTIONS[inc.status].map((a) => <Button key={a} size="sm" variant={a === 'close' ? 'primary' : 'secondary'} onClick={() => act(inc, a)} busy={busy === inc.id + a}>{a}</Button>)}
                    </div>
                  )}
                  {inc.status === 'resolved' && inc.created_by === identity.actor && <p className="mt-1 text-[11px] text-warn-ink">Four-eyes rule: switch actor in the header (e.g. a reviewer) to close an incident you opened.</p>}
                </Card>
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="space-y-3">
          <p className="flex items-center gap-2 text-xs text-muted"><SyntheticBadge /> Organiser actions in this timeline are scripted parts of the demonstration scenario, not real decisions.</p>
          {sim.incidents.map((inc) => (
            <Card key={inc.id} title={<span className="flex items-center gap-2"><span className="font-mono">{inc.id}</span><SeverityBadge severity={inc.severity} />{inc.title}</span>}>
              <Lifecycle status={inc.events.filter((e) => e.tick <= tick).at(-1)?.status ?? 'pending'} />
              <ol className="mt-2 space-y-1 border-l border-line pl-3 text-xs">
                {inc.events.map((e, i) => (
                  <li key={i} className={e.tick > tick ? 'opacity-40' : ''}><span className="font-mono text-muted">{e.clock}</span> <b>{e.status}</b> — {e.note} <span className="text-muted">({e.actor})</span></li>
                ))}
              </ol>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

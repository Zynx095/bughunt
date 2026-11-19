import { ShieldCheck, ShieldX } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { cg, cgResult } from '../crowdguard/api'
import type { Incident } from '../crowdguard/types'
import { get, loadIdentity } from '../lib/api'
import { cx } from '../lib/cx'
import { fmtClock, short } from '../lib/format'
import { live } from '../live/client'
import { useLive } from '../live/context'
import type { Alert } from '../live/types'
import { SEVERITY_VAR } from '../map/palette'
import { Button, Note, Section, inputCls } from '../ui/primitives'

const NEXT: Record<string, { action: string; label: string }[]> = {
  detected: [{ action: 'acknowledge', label: 'Acknowledge' }],
  acknowledged: [{ action: 'respond', label: 'Start response' }, { action: 'resolve', label: 'Resolve' }],
  responding: [{ action: 'monitor', label: 'Monitor' }, { action: 'resolve', label: 'Resolve' }],
  monitoring: [{ action: 'respond', label: 'Respond again' }, { action: 'resolve', label: 'Resolve' }],
  resolved: [{ action: 'close', label: 'Close and seal' }, { action: 'respond', label: 'Reopen' }],
  closed: [],
}
const STEPS = ['detected', 'acknowledged', 'responding', 'monitoring', 'resolved', 'closed']

interface Chain { valid: boolean; checked: number; broken_at_id?: number; head?: string }

export function Incidents() {
  const { snapshot } = useLive()
  const [incidents, setIncidents] = useState<Incident[] | null>(null)
  const [history, setHistory] = useState<Alert[]>([])
  const [chain, setChain] = useState<Chain | null>(null)
  const [verify, setVerify] = useState<Record<string, boolean>>({})
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [err, setErr] = useState<string | null>(null)
  const me = loadIdentity()

  const load = useCallback(async () => {
    try {
      const [inc, al, ch] = await Promise.all([
        cgResult<{ incidents: Incident[] }>('/incidents'), live.alerts(150), get<Chain>('/api/audit/verify'),
      ])
      setIncidents(inc.result.incidents)
      setHistory(al.history as Alert[])
      setChain(ch)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }, [])
  useEffect(() => {
    const id = window.setTimeout(() => { void load() }, 0)
    return () => window.clearTimeout(id)
  }, [load])

  async function openFrom(a: Alert) {
    setErr(null)
    const sev = a.severity === 'info' || a.severity === 'low' ? 'low' : a.severity
    const env = await cg<Incident>('/incidents', {
      title: a.observation.slice(0, 250), zone_id: (a.location.zone_id as string) ?? null, severity: sev,
      source: snapshot?.source?.kind === 'live_camera' ? 'live' : snapshot?.source?.kind === 'recorded_video' ? 'video' : 'simulation',
      alert_id: a.id, note: a.action,
      evidence: { alert: a, source: snapshot?.source, frame: snapshot?.frame, calibration: snapshot?.calibration?.source, zones: snapshot?.zones },
    })
    if (!env.success) setErr(env.error?.message ?? 'Could not open the incident')
    await load()
  }

  async function act(inc: Incident, action: string) {
    setErr(null)
    const env = await cg<Incident>(`/incidents/${inc.id}/actions`, { action, note: notes[inc.id] ?? '' })
    if (!env.success) setErr(env.error?.message ?? 'Action refused')
    else setNotes({ ...notes, [inc.id]: '' })
    await load()
  }

  async function check(inc: Incident) {
    const { result } = await cgResult<{ valid: boolean }>(`/incidents/${inc.id}/verify`)
    setVerify({ ...verify, [inc.id]: result.valid })
  }

  const linked = new Set((incidents ?? []).filter((i) => i.status !== 'closed').map((i) => i.alert_id))
  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_380px]">
      <section className="min-h-0 overflow-y-auto">
        <Section title="Incidents" aside={<span>opened by people, never automatically</span>}>
          {err && <Note tone="bad">{err}</Note>}
          {!incidents ? <Note>Loading…</Note> : incidents.length === 0 ? (
            <Note>No incidents yet. Open one from an alert on the right when it needs a coordinated response.</Note>
          ) : (
            <ul className="divide-y divide-line">
              {incidents.map((inc) => (
                <li key={inc.id} className="py-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <p className="text-[14px] font-semibold text-ink">{inc.title}</p>
                    <span className="text-[12.5px] text-muted tabular">{inc.id} opened by {inc.created_by}</span>
                  </div>
                  <ol className="mt-1.5 flex flex-wrap gap-x-3 text-[12.5px]" aria-label="Lifecycle">
                    {STEPS.map((s, i) => {
                      const done = STEPS.indexOf(inc.status) >= i
                      return <li key={s} className={done ? 'text-ink' : 'text-muted'}>{done ? '●' : '○'} {s}</li>
                    })}
                  </ol>
                  <ol className="mt-2 space-y-0.5 border-l border-line pl-3 text-[12.5px] text-ink-2">
                    {inc.events.map((e) => (
                      <li key={e.seq}>
                        <span className="text-muted tabular">{new Date(e.ts).toLocaleTimeString(undefined, { hour12: false })}</span> {e.action} by {e.actor}
                        {e.note && <>: {e.note}</>} <span className="text-muted" title={`hash ${e.hash}`}>#{short(e.hash, 8)}</span>
                      </li>
                    ))}
                  </ol>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    {NEXT[inc.status].length > 0 && (
                      <>
                        <input className={cx(inputCls, 'w-64')} placeholder="Decision note (kept in the record)" value={notes[inc.id] ?? ''}
                          onChange={(e) => setNotes({ ...notes, [inc.id]: e.target.value })} />
                        {NEXT[inc.status].map((n) => <Button key={n.action} variant={n.action === 'close' ? 'primary' : 'plain'} onClick={() => act(inc, n.action)}>{n.label}</Button>)}
                      </>
                    )}
                    <Button variant="quiet" onClick={() => check(inc)}>Check record</Button>
                    {inc.id in verify && (
                      <span className={cx('flex items-center gap-1 text-[12.5px]', verify[inc.id] ? 'text-normal' : 'text-critical')}>
                        {verify[inc.id] ? <ShieldCheck className="size-3.5" /> : <ShieldX className="size-3.5" />}{verify[inc.id] ? 'Record intact' : 'Record altered'}
                      </span>
                    )}
                  </div>
                  {inc.status === 'resolved' && inc.created_by === me.actor && (
                    <p className="mt-1 text-[12px] text-muted">Closing needs a second person: switch the operator name in Settings.</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Section>
        <Section title="Audit trail">
          {chain ? (
            <p className={cx('flex items-center gap-2 text-[13px]', chain.valid ? 'text-ink' : 'text-critical')}>
              {chain.valid ? <ShieldCheck className="size-4 text-normal" /> : <ShieldX className="size-4" />}
              {chain.valid ? `All ${chain.checked} recorded actions verify against their hash chain.` : `The chain breaks at event ${chain.broken_at_id}: the log was altered.`}
            </p>
          ) : <Note>Checking…</Note>}
        </Section>
      </section>
      <aside className="min-h-0 overflow-y-auto border-l border-line bg-panel">
        <Section title="Alert history" aside={<button type="button" className="hover:text-ink" onClick={load}>Refresh</button>}>
          {history.length === 0 ? <Note>No alerts since monitoring started.</Note> : (
            <ul className="space-y-3">
              {history.map((a) => (
                <li key={a.id} className="border-l-2 pl-2.5" style={{ borderColor: SEVERITY_VAR[a.severity] }}>
                  <div className="flex items-baseline justify-between text-[12.5px]">
                    <span className="font-semibold" style={{ color: SEVERITY_VAR[a.severity] }}>{a.severity}</span>
                    <span className="text-muted tabular">{fmtClock(a.raised_at)}{a.status === 'cleared' ? ', cleared' : a.status === 'active' ? ', active' : ''}</span>
                  </div>
                  <p className="text-[13px] text-ink">{a.observation}</p>
                  <p className="text-[12.5px] text-ink-2">{a.action}</p>
                  {a.status !== 'event' && !linked.has(a.id) && a.severity !== 'info' && (
                    <button type="button" onClick={() => openFrom(a)} className="mt-1 text-[12.5px] font-medium text-accent hover:underline">Open incident</button>
                  )}
                  {linked.has(a.id) && <p className="mt-1 text-[12px] text-muted">Incident open</p>}
                </li>
              ))}
            </ul>
          )}
        </Section>
      </aside>
    </div>
  )
}

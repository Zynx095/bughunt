import { CheckCircle2, CircleDashed, ShieldCheck, ShieldX, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Badge, Button, Card, ErrorBox, PageHeader, Spinner } from '../../components/ui'
import { get } from '../../lib/api'
import { fmtTime, short } from '../../lib/format'
import type { AuditEvent, ChainStatus } from '../../lib/types'
import { cgResult } from '../api'
import type { Incident } from '../types'

interface Status {
  detector: { backend: string; available: boolean; verified: boolean; model?: string; weights_path?: string; weights_bytes?: number; attempts: { backend: string; ok: boolean; reason?: string }[]; limitation?: string; weights_searched?: string[] }
  tracker: { tracker: string; available: boolean; fallback_reason?: string }
  routing: { library: string; version: string }
  ai: { active: string; preference: string; providers?: { name: string; configured: boolean; model?: string | null; verified?: boolean }[] } | null
  venue: { id: string; name: string; synthetic: boolean }
  limits: Record<string, number>
  safety: string
}

function Row({ ok, label, detail, partial }: { ok: boolean; label: string; detail: string; partial?: boolean }) {
  const Icon = ok ? CheckCircle2 : partial ? CircleDashed : XCircle
  return (
    <li className="flex items-start gap-2 py-1.5">
      <Icon className={`mt-0.5 size-4 shrink-0 ${ok ? 'text-good-ink' : partial ? 'text-warn-ink' : 'text-critical-ink'}`} aria-label={ok ? 'verified' : partial ? 'fallback' : 'unavailable'} />
      <div className="min-w-0"><p className="text-sm font-medium text-ink">{label}</p><p className="break-words text-xs text-muted">{detail}</p></div>
    </li>
  )
}

export function AuditVerificationPage() {
  const [status, setStatus] = useState<Status | null>(null)
  const [chain, setChain] = useState<ChainStatus | null>(null)
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [checks, setChecks] = useState<Record<string, boolean>>({})
  const [err, setErr] = useState<string | null>(null)

  async function load() {
    setErr(null)
    try {
      const [s, c, inc, ev1, ev2] = await Promise.all([
        cgResult<Status>('/status'), get<ChainStatus>('/api/audit/verify'), cgResult<{ incidents: Incident[] }>('/incidents'),
        get<AuditEvent[]>('/api/audit?limit=40&category=incident'), get<AuditEvent[]>('/api/audit?limit=20&category=data'),
      ])
      setStatus(s.result)
      setChain(c)
      setIncidents(inc.result.incidents)
      setEvents([...ev1, ...ev2].sort((a, b) => b.id - a.id))
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }
  useEffect(() => {
    const id = window.setTimeout(() => { void load() }, 0)
    return () => window.clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function verifyAll() {
    const out: Record<string, boolean> = {}
    for (const inc of incidents) {
      const { result } = await cgResult<{ valid: boolean }>(`/incidents/${inc.id}/verify`)
      out[inc.id] = result.valid
    }
    setChecks(out)
  }

  const ai = status?.ai
  const llm = ai && ai.active !== 'local-fallback'
  return (
    <div className="space-y-4">
      <PageHeader title="Audit & Verification" icon={<ShieldCheck className="mt-1 size-6 text-[var(--accent)]" />}
        description="What is real, what is a fallback and what is synthetic — verified by the backend at request time — plus tamper-evidence for the audit log and incident records."
        actions={<Button size="sm" onClick={load}>Re-check</Button>} />
      {err && <ErrorBox>{err}</ErrorBox>}
      {!status ? <Spinner label="Verifying capabilities (loads the detector once)" /> : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Capability verification" subtitle="Checked live; nothing here is assumed">
            <ul className="divide-y divide-line">
              <Row ok={status.detector.backend === 'yolo' && status.detector.verified} partial={status.detector.backend === 'hog'}
                label={`Person detector: ${status.detector.backend.toUpperCase()}${status.detector.verified ? ' (test inference passed)' : ''}`}
                detail={status.detector.backend === 'yolo' ? `${status.detector.model} · ${status.detector.weights_path} · ${((status.detector.weights_bytes ?? 0) / 1e6).toFixed(1)} MB · downloads disabled`
                  : status.detector.limitation ?? (status.detector.attempts.map((a) => `${a.backend}: ${a.reason ?? 'ok'}`).join('; '))} />
              <Row ok={status.tracker.available && !status.tracker.fallback_reason} partial={!!status.tracker.fallback_reason}
                label={`Tracker: ${status.tracker.tracker}`} detail={status.tracker.fallback_reason ?? 'Two-stage association; ids are ephemeral, no re-identification'} />
              <Row ok label={`Routing: ${status.routing.library} ${status.routing.version}`} detail="Safety-weighted Dijkstra + k-shortest simple paths" />
              <Row ok={!!llm} partial={!llm} label={`AI explanations: ${ai?.active ?? 'unknown'}`}
                detail={llm ? 'Live LLM provider configured (run Settings → Test live call to verify credentials)' : 'No LLM key configured: briefings use the deterministic local template fallback, labelled in the UI'} />
              <Row ok={false} partial label={`Venue & scenario: ${status.venue.name}`} detail="Synthetic demo venue and deterministic simulation (seed 2026) — labelled SYNTHETIC wherever shown" />
            </ul>
          </Card>
          <Card title="Data provenance labels" subtitle="How to read every number">
            <ul className="space-y-2 text-xs text-ink-2">
              <li><Badge tone="info">observed</Badge> people a detector actually saw in a frame (a measurement, not ground truth).</li>
              <li><Badge tone="accent">estimate</Badge> observed count corrected for expected occlusion, always with an interval and a confidence.</li>
              <li><Badge tone="warn">synthetic</Badge> produced by the simulator; the hidden "truth" exists only there, for evaluation.</li>
              <li><Badge>unknown</Badge> stale, missing or failed feed: never shown or treated as zero; routes avoid sending people there.</li>
              <li><Badge tone="good">advisory</Badge> every recommendation requires a human decision; emergency exits cannot be restricted by software.</li>
            </ul>
            <p className="mt-3 text-[11px] text-muted">{status.safety}</p>
          </Card>
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Audit chain" subtitle="SHA-256 hash chain over every audit event (tamper-evident, not tamper-proof)">
          {chain ? (
            <div className="flex items-center gap-3">
              {chain.valid ? <ShieldCheck className="size-8 text-good-ink" /> : <ShieldX className="size-8 text-critical-ink" />}
              <div><p className="text-sm font-semibold">{chain.valid ? 'Chain intact' : `Broken at event #${chain.broken_at_id}`}</p>
                <p className="font-mono text-[11px] text-muted">{chain.checked} events · head {short(chain.head ?? '', 24)}</p></div>
            </div>
          ) : <Spinner />}
        </Card>
        <Card title="Incident integrity" subtitle="Evidence hash, event chain and Merkle seal recomputed per incident"
          actions={<Button size="sm" onClick={verifyAll} disabled={!incidents.length}>Verify all</Button>}>
          {incidents.length === 0 ? <p className="text-xs text-muted">No operator incidents recorded yet.</p> : (
            <ul className="space-y-1 text-xs">
              {incidents.map((i) => (
                <li key={i.id} className="flex items-center justify-between gap-2"><span className="font-mono">{i.id}</span><span className="min-w-0 flex-1 truncate">{i.title}</span>
                  <Badge tone={i.sealed_root ? 'good' : 'neutral'}>{i.sealed_root ? 'sealed' : i.status}</Badge>
                  {i.id in checks && <Badge tone={checks[i.id] ? 'good' : 'bad'}>{checks[i.id] ? 'valid' : 'TAMPERED'}</Badge>}</li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <Card title="Recent CROWDGUARD audit events" subtitle="Incident actions and media uploads">
        {events.length === 0 ? <p className="text-xs text-muted">None yet.</p> : (
          <div className="max-h-80 overflow-auto">
            <table className="w-full text-left text-xs">
              <thead><tr className="border-b border-line text-muted"><th className="px-2 py-1.5">#</th><th className="px-2 py-1.5">Time</th><th className="px-2 py-1.5">Action</th><th className="px-2 py-1.5">Actor</th><th className="px-2 py-1.5">Detail</th><th className="px-2 py-1.5">Hash</th></tr></thead>
              <tbody>{events.map((e) => (
                <tr key={e.id} className="border-b border-line/60 align-top"><td className="px-2 py-1 text-muted">{e.id}</td><td className="whitespace-nowrap px-2 py-1 text-muted">{fmtTime(e.ts)}</td>
                  <td className="px-2 py-1 font-medium">{e.action}{e.severity !== 'info' && <span className="ml-1 text-warn-ink">({e.severity})</span>}</td><td className="px-2 py-1">{e.actor}</td>
                  <td className="max-w-md px-2 py-1 font-mono text-[11px] text-ink-2"><span className="line-clamp-2 break-all">{JSON.stringify(e.detail)}</span></td>
                  <td className="px-2 py-1 font-mono text-[11px] text-muted">{short(e.hash, 10)}</td></tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

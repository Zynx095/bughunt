import { ShieldCheck, ShieldX } from 'lucide-react'
import { useState } from 'react'

import { DataTable } from '../components/table'
import { Badge, Button, Card, ErrorBox, PageHeader, Spinner, Tabs } from '../components/ui'
import { fmtTime, short } from '../lib/format'
import { useApi } from '../lib/hooks'
import type { AuditEvent, ChainStatus } from '../lib/types'

const CATEGORIES = ['all', 'security', 'pipeline', 'engine', 'crypto', 'approval', 'data', 'settings', 'system'] as const

export function AuditPage() {
  const [view, setView] = useState<'events' | 'executions'>('events')
  const [cat, setCat] = useState<(typeof CATEGORIES)[number]>('all')
  const events = useApi<AuditEvent[]>(`/api/audit?limit=300${cat !== 'all' ? `&category=${cat}` : ''}`)
  const chain = useApi<ChainStatus>('/api/audit/verify')
  const execs = useApi<Record<string, unknown>[]>(view === 'executions' ? '/api/executions?limit=300' : null)

  return (
    <div className="space-y-5">
      <PageHeader title="Audit log" description="Append-only events, each hash-chained to the previous one (SHA-256). Verification recomputes the whole chain: any edited or deleted event is detected. Tamper-evident, not tamper-proof."
        actions={<Tabs value={view} onChange={setView} options={[{ id: 'events', label: 'Audit events' }, { id: 'executions', label: 'Engine executions' }]} />} />

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          {chain.data ? (
            <div className="flex items-center gap-3">
              {chain.data.valid ? <ShieldCheck className="size-7 text-good-ink" aria-hidden /> : <ShieldX className="size-7 text-critical-ink" aria-hidden />}
              <div>
                <p className="text-sm font-semibold">{chain.data.valid ? 'Chain intact' : `Chain broken at event #${chain.data.broken_at_id} (${chain.data.reason})`}</p>
                <p className="font-mono text-[11px] text-muted">{chain.data.checked} events verified{chain.data.head ? ` · head ${short(chain.data.head, 24)}` : ''}</p>
              </div>
            </div>
          ) : <Spinner label="Verifying" />}
          <Button size="sm" onClick={() => { void chain.reload(); void events.reload() }}>Re-verify</Button>
        </div>
      </Card>

      {view === 'events' && (
        <Card title="Events" actions={
          <select value={cat} onChange={(e) => setCat(e.target.value as typeof cat)} aria-label="Category" className="rounded-lg border border-line bg-surface px-2 py-1 text-xs">
            {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
          </select>}>
          {events.loading && !events.data && <Spinner />}
          {events.error && <ErrorBox>{events.error}</ErrorBox>}
          {events.data && (
            <div className="max-h-[60vh] overflow-auto">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 bg-surface"><tr className="border-b border-line text-muted">
                  <th className="px-2 py-2 font-medium">#</th><th className="px-2 py-2 font-medium">Time</th><th className="px-2 py-2 font-medium">Category</th>
                  <th className="px-2 py-2 font-medium">Action</th><th className="px-2 py-2 font-medium">Actor</th><th className="px-2 py-2 font-medium">Detail</th><th className="px-2 py-2 font-medium">Hash</th>
                </tr></thead>
                <tbody>
                  {events.data.map((e) => (
                    <tr key={e.id} className="border-b border-line/70 align-top">
                      <td className="tabular px-2 py-1.5 text-muted">{e.id}</td>
                      <td className="whitespace-nowrap px-2 py-1.5 text-muted">{fmtTime(e.ts)}</td>
                      <td className="px-2 py-1.5"><Badge tone={e.category === 'security' ? 'warn' : 'neutral'}>{e.category}</Badge></td>
                      <td className="px-2 py-1.5 font-medium text-ink">{e.action}{e.severity !== 'info' && <span className="ml-1 text-warn-ink">({e.severity})</span>}</td>
                      <td className="whitespace-nowrap px-2 py-1.5 text-ink-2">{e.actor} <span className="text-muted">({e.role})</span></td>
                      <td className="max-w-md px-2 py-1.5 font-mono text-[11px] text-ink-2"><span className="line-clamp-2 break-all">{JSON.stringify(e.detail)}</span></td>
                      <td className="px-2 py-1.5 font-mono text-[11px] text-muted" title={`hash ${e.hash}\nprev ${e.prev_hash}`}>{short(e.hash, 10)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {view === 'executions' && (
        <Card title="Engine executions" subtitle="Every registry call, including denied ones">
          {execs.loading && <Spinner />}
          {execs.data && (
            <div className="max-h-[60vh] overflow-auto">
              <DataTable maxRows={300} columns={[{ key: 'id', label: '#' }, { key: 'when', label: 'Time' }, { key: 'op', label: 'Operation' }, { key: 'access', label: 'Access' },
                { key: 'ok', label: 'Outcome' }, { key: 'execution_time_ms', label: 'ms' }, { key: 'who', label: 'Actor' }, { key: 'run_id', label: 'Run' }]}
                rows={execs.data.map((x) => ({ ...x, when: fmtTime(x.created_at as string), op: `${x.engine}.${x.operation}`,
                  ok: x.success ? 'success' : x.error_code, who: `${x.actor} (${x.role}${x.actor_type !== 'human' ? `, ${x.actor_type}` : ''})` }))} />
            </div>
          )}
        </Card>
      )}
    </div>
  )
}

import { Copy, RotateCcw, Search, ShieldCheck, ShieldX } from 'lucide-react'
import { useMemo, useState } from 'react'

import { JSONInspector } from '../components/JSONInspector'
import { DataTable } from '../components/table'
import { Badge, Button, Card, ErrorBox, PageHeader, Spinner, Tabs } from '../components/ui'
import { cx } from '../lib/cx'
import { fmtTime, short } from '../lib/format'
import { useApi } from '../lib/hooks'
import type { AuditEvent, ChainStatus } from '../lib/types'

const CATEGORIES = [
  'all',
  'security',
  'pipeline',
  'engine',
  'crypto',
  'approval',
  'data',
  'settings',
  'system',
] as const

export function AuditPage() {
  const [view, setView] = useState<'events' | 'executions'>('events')
  const [cat, setCat] = useState<(typeof CATEGORIES)[number]>('all')
  const [search, setSearch] = useState('')
  const [selectedEvent, setSelectedEvent] = useState<AuditEvent | null>(null)
  const [copiedHash, setCopiedHash] = useState<string | null>(null)

  const events = useApi<AuditEvent[]>(
    `/api/audit?limit=300${cat !== 'all' ? `&category=${cat}` : ''}`
  )
  const chain = useApi<ChainStatus>('/api/audit/verify')
  const execs = useApi<Record<string, unknown>[]>(
    view === 'executions' ? '/api/executions?limit=300' : null
  )

  const copy = async (text: string, key: string) => {
    await navigator.clipboard.writeText(text)
    setCopiedHash(key)
    setTimeout(() => setCopiedHash(null), 2000)
  }

  const filteredEvents = useMemo(() => {
    if (!events.data) return []
    if (!search.trim()) return events.data
    const q = search.toLowerCase().trim()
    return events.data.filter(
      (e) =>
        e.action.toLowerCase().includes(q) ||
        e.actor.toLowerCase().includes(q) ||
        e.category.toLowerCase().includes(q) ||
        JSON.stringify(e.detail).toLowerCase().includes(q)
    )
  }, [events.data, search])

  return (
    <div className="space-y-5">
      <PageHeader
        title="Cryptographic Audit Log"
        description="Append-only audit ledger with SHA-256 hash chaining. Every state change, execution, document upload, and approval is bound to its predecessor. Any modification or deletion of historical events invalidates the entire chain."
        actions={
          <Tabs
            value={view}
            onChange={setView}
            options={[
              { id: 'events', label: 'Hash-Chained Audit Events' },
              { id: 'executions', label: 'Engine Executions Log' },
            ]}
          />
        }
      />

      {/* Verification Card */}
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-4">
          {chain.data ? (
            <div className="flex items-center gap-3.5">
              <div className="rounded-xl bg-surface-2 p-2.5">
                {chain.data.valid ? (
                  <ShieldCheck className="size-7 text-good-ink" aria-hidden />
                ) : (
                  <ShieldX className="size-7 text-critical-ink" aria-hidden />
                )}
              </div>
              <div>
                <h3 className="text-sm font-bold text-ink">
                  {chain.data.valid
                    ? 'Cryptographic Chain Integrity: VALID & INTACT'
                    : `Integrity Check Failed: Broken at Event #${chain.data.broken_at_id}`}
                </h3>
                <p className="font-mono text-xs text-muted mt-0.5">
                  {chain.data.checked} sequential events verified
                  {chain.data.head && ` · Chain Head: ${short(chain.data.head, 24)}`}
                </p>
              </div>
            </div>
          ) : (
            <Spinner label="Recomputing SHA-256 Chain Hashes" />
          )}

          <Button
            size="sm"
            onClick={() => {
              void chain.reload()
              void events.reload()
            }}
          >
            <RotateCcw className="size-3.5" /> Re-Verify Entire Chain
          </Button>
        </div>
      </Card>

      {/* Main View */}
      {view === 'events' && (
        <Card
          title="Audit Ledger"
          subtitle="Chronological sequence of verified tamper-evident records"
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted" />
                <input
                  type="text"
                  placeholder="Search actions, actors…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="h-8 w-44 rounded-md border border-line bg-surface px-2.5 pl-8 text-xs text-ink outline-none focus:border-[var(--accent)]"
                />
              </div>

              <select
                value={cat}
                onChange={(e) => setCat(e.target.value as typeof cat)}
                aria-label="Category Filter"
                className="h-8 rounded-md border border-line bg-surface px-2.5 text-xs text-ink outline-none"
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c === 'all' ? 'All Categories' : c}
                  </option>
                ))}
              </select>
            </div>
          }
          pad={false}
        >
          {events.loading && !events.data && <div className="p-8"><Spinner /></div>}
          {events.error && <div className="p-4"><ErrorBox>{events.error}</ErrorBox></div>}

          {filteredEvents.length > 0 && (
            <div className="max-h-[65vh] overflow-auto">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 bg-surface border-b border-line text-muted">
                  <tr>
                    <th className="px-3 py-2 font-medium">#</th>
                    <th className="px-3 py-2 font-medium">Timestamp</th>
                    <th className="px-3 py-2 font-medium">Category</th>
                    <th className="px-3 py-2 font-medium">Action</th>
                    <th className="px-3 py-2 font-medium">Actor</th>
                    <th className="px-3 py-2 font-medium">Details</th>
                    <th className="px-3 py-2 font-medium text-right">SHA-256 Hash</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/60">
                  {filteredEvents.map((e) => (
                    <tr
                      key={e.id}
                      onClick={() => setSelectedEvent(e)}
                      className={cx(
                        'cursor-pointer hover:bg-surface-2 transition-colors',
                        selectedEvent?.id === e.id && 'bg-[var(--accent)]/[0.05]'
                      )}
                    >
                      <td className="tabular px-3 py-2 font-mono text-muted">{e.id}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-muted">{fmtTime(e.ts)}</td>
                      <td className="px-3 py-2">
                        <Badge tone={e.category === 'security' ? 'warn' : 'neutral'}>
                          {e.category}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 font-semibold text-ink">
                        {e.action}
                        {e.severity !== 'info' && (
                          <span className="ml-1.5 text-amber-600 dark:text-amber-400 font-mono text-[10px]">
                            ({e.severity})
                          </span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-ink-2">
                        {e.actor} <span className="text-muted">({e.role})</span>
                      </td>
                      <td className="max-w-xs px-3 py-2 font-mono text-[11px] text-muted truncate">
                        {JSON.stringify(e.detail)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-[11px] text-muted">
                        <div className="inline-flex items-center gap-1">
                          <span title={`Current Hash: ${e.hash}\nPrevious Hash: ${e.prev_hash}`}>
                            {short(e.hash, 10)}
                          </span>
                          <button
                            type="button"
                            onClick={(ev) => {
                              ev.stopPropagation()
                              void copy(e.hash, `hash-${e.id}`)
                            }}
                            className="text-muted hover:text-ink"
                            title="Copy SHA-256 Hash"
                          >
                            {copiedHash === `hash-${e.id}` ? (
                              <span className="text-good-ink text-[10px]">Copied</span>
                            ) : (
                              <Copy className="size-3" />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Selected event details drawer/box */}
          {selectedEvent && (
            <div className="border-t border-line p-4 bg-surface-2/40">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-ink">
                  Event #{selectedEvent.id} Detail: {selectedEvent.action}
                </span>
                <button
                  type="button"
                  onClick={() => setSelectedEvent(null)}
                  className="text-xs text-muted hover:text-ink"
                >
                  Close
                </button>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 mb-3 text-xs font-mono">
                <div className="rounded bg-surface p-2 border border-line">
                  <span className="text-muted block text-[10px]">CURRENT SHA-256 HASH:</span>
                  <span className="break-all text-cyan-600 dark:text-cyan-400">{selectedEvent.hash}</span>
                </div>
                <div className="rounded bg-surface p-2 border border-line">
                  <span className="text-muted block text-[10px]">PREVIOUS SHA-256 HASH:</span>
                  <span className="break-all text-muted">{selectedEvent.prev_hash}</span>
                </div>
              </div>
              <JSONInspector title="Event Detail Attributes" value={selectedEvent.detail} />
            </div>
          )}
        </Card>
      )}

      {/* Executions View */}
      {view === 'executions' && (
        <Card
          title="Engine Execution Registry"
          subtitle="Complete invocation audit trail, including RBAC approvals, denied attempts, and latency measurements"
        >
          {execs.loading && <Spinner />}
          {execs.data && (
            <div className="max-h-[65vh] overflow-auto">
              <DataTable
                maxRows={300}
                columns={[
                  { key: 'id', label: '#' },
                  { key: 'when', label: 'Time' },
                  { key: 'op', label: 'Engine Operation' },
                  { key: 'access', label: 'Access' },
                  { key: 'ok', label: 'Outcome' },
                  { key: 'execution_time_ms', label: 'Latency (ms)' },
                  { key: 'who', label: 'Actor & Identity' },
                  { key: 'run_id', label: 'Pipeline Run' },
                ]}
                rows={execs.data.map((x) => ({
                  ...x,
                  when: fmtTime(x.created_at as string),
                  op: `${x.engine}.${x.operation}`,
                  ok: x.success ? 'success' : x.error_code,
                  who: `${x.actor} (${x.role}${x.actor_type !== 'human' ? `, ${x.actor_type}` : ''})`,
                }))}
              />
            </div>
          )}
        </Card>
      )}
    </div>
  )
}

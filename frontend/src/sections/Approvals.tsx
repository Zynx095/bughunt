import { Check, CheckCircle2, ClipboardCheck, Clock, ExternalLink, ShieldAlert, User, X, XCircle } from 'lucide-react'
import { useState } from 'react'

import { JSONInspector } from '../components/JSONInspector'
import { Badge, Button, Card, Empty, ErrorBox, PageHeader, Spinner, StatusBadge, Tabs } from '../components/ui'
import { useApp } from '../context'
import { send } from '../lib/api'
import { fmtTime } from '../lib/format'
import { useApi } from '../lib/hooks'
import type { Approval, EngineResponse } from '../lib/types'

export function ApprovalsPage() {
  const { identity, navigate } = useApp()
  const [filter, setFilter] = useState<'pending' | 'all'>('pending')
  const list = useApi<Approval[]>(`/api/approvals${filter === 'pending' ? '?status=pending' : ''}`)
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)

  const decide = async (a: Approval, decision: 'approve' | 'reject') => {
    setBusy(a.id + decision)
    try {
      const r = await send<EngineResponse>('POST', `/api/approvals/${a.id}/decision`, {
        decision,
        note: notes[a.id] || null,
      })
      if (!r.success) {
        setErrors((e) => ({ ...e, [a.id]: `${r.error?.code}: ${r.error?.message}` }))
      } else {
        setErrors((e) => ({ ...e, [a.id]: '' }))
        await list.reload()
      }
    } catch (e) {
      setErrors((x) => ({ ...x, [a.id]: (e as Error).message }))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Human Governance & Approvals"
        description={
          <>
            Sensitive actions gated by deterministic engine policies pause here for human authorization.
            Requires the <code className="font-mono text-ink">approval:decide</code> permission (reviewer or admin). Requesters cannot approve their own actions, and AI actors are barred from deciding. Acting as:{' '}
            <strong className="text-ink">{identity.actor}</strong> ({identity.role}).
          </>
        }
        actions={
          <Tabs
            value={filter}
            onChange={setFilter}
            options={[
              { id: 'pending', label: 'Pending Review' },
              { id: 'all', label: 'All History' },
            ]}
          />
        }
      />

      {list.loading && !list.data && <div className="py-12"><Spinner label="Loading Approval Queue" /></div>}
      {list.error && <ErrorBox>{list.error}</ErrorBox>}

      {list.data?.length === 0 && (
        <Empty
          icon={<ClipboardCheck className="size-8 text-muted" />}
          title={filter === 'pending' ? 'Approval queue is clear' : 'No approval requests logged'}
        >
          {filter === 'pending'
            ? 'There are currently no operations awaiting human intervention. Executing high-risk transactions in the Finance or Healthcare domains will enqueue review holds here.'
            : 'No actions have required manual authorization.'}
        </Empty>
      )}

      <div className="space-y-4">
        {list.data?.map((a) => {
          const isPending = a.status === 'pending'
          const isSameActor = a.requested_by === identity.actor
          return (
            <Card key={a.id}>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-base font-semibold text-ink">{a.title}</h3>
                    <StatusBadge status={a.status} />
                    {a.risk_score !== null && (
                      <Badge
                        tone={a.risk_score >= 0.75 ? 'bad' : a.risk_score >= 0.5 ? 'warn' : 'good'}
                      >
                        Risk: {Math.round(a.risk_score * 100)}%
                      </Badge>
                    )}
                  </div>

                  <div className="mt-2 grid gap-2 sm:grid-cols-2 text-xs text-muted">
                    <div>
                      <span className="text-muted block text-[10px] uppercase tracking-wider font-semibold">
                        Action & Target
                      </span>
                      <span className="font-mono text-ink">{a.action}</span>
                      {a.run_id && (
                        <span className="ml-2">
                          · Run:{' '}
                          <button
                            type="button"
                            onClick={() => navigate('runs', a.run_id!)}
                            className="font-mono text-[var(--accent)] underline hover:text-ink"
                          >
                            {a.run_id.slice(0, 8)}
                          </button>
                        </span>
                      )}
                    </div>

                    <div>
                      <span className="text-muted block text-[10px] uppercase tracking-wider font-semibold">
                        Requested By
                      </span>
                      <span className="text-ink font-medium">
                        {a.requested_by} ({a.requested_role})
                      </span>
                      <span className="text-muted ml-2">· {fmtTime(a.created_at)}</span>
                    </div>
                  </div>

                  {a.status !== 'pending' && (
                    <div className="mt-3 rounded-lg bg-surface-2/60 p-2.5 text-xs border border-line">
                      <span className="font-semibold text-ink">Decision Record: </span>
                      <span className="capitalize font-medium">{a.status}</span> by{' '}
                      <strong>{a.reviewer}</strong> ({a.reviewer_role}) at {fmtTime(a.decided_at)}
                      {a.note && <span className="block mt-1 italic text-ink-2">&quot;{a.note}&quot;</span>}
                    </div>
                  )}
                </div>

                {/* Action controls for pending items */}
                {isPending && (
                  <div className="flex flex-col gap-2 shrink-0 sm:items-end">
                    {isSameActor && (
                      <span className="text-[11px] text-amber-600 dark:text-amber-400">
                        Self-approval prohibited (switch role in Settings)
                      </span>
                    )}
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        type="text"
                        value={notes[a.id] ?? ''}
                        onChange={(e) => setNotes({ ...notes, [a.id]: e.target.value })}
                        placeholder="Reviewer decision rationale…"
                        aria-label="Reviewer Note"
                        className="h-8 w-56 rounded-lg border border-line bg-surface px-2.5 text-xs text-ink outline-none focus:border-[var(--accent)]"
                      />
                      <Button
                        size="sm"
                        variant="danger"
                        busy={busy === a.id + 'reject'}
                        disabled={isSameActor}
                        onClick={() => void decide(a, 'reject')}
                      >
                        <X className="size-3.5" /> Reject
                      </Button>
                      <Button
                        size="sm"
                        variant="primary"
                        busy={busy === a.id + 'approve'}
                        disabled={isSameActor}
                        onClick={() => void decide(a, 'approve')}
                      >
                        <Check className="size-3.5" /> Approve
                      </Button>
                    </div>
                  </div>
                )}
              </div>

              {errors[a.id] && (
                <div className="mt-3">
                  <ErrorBox>{errors[a.id]}</ErrorBox>
                </div>
              )}

              <div className="mt-4 border-t border-line/60 pt-3">
                <JSONInspector
                  title={`Evidence Payload (${Object.keys(a.payload).length} keys)`}
                  value={a.payload}
                  maxHeight={240}
                  defaultExpandDepth={1}
                />
              </div>
            </Card>
          )
        })}
      </div>
    </div>
  )
}

import { Check, ClipboardCheck, X } from 'lucide-react'
import { useState } from 'react'

import { Badge, Button, Card, Disclosure, Empty, ErrorBox, JsonView, PageHeader, Spinner, StatusBadge, Tabs } from '../components/ui'
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

  async function decide(a: Approval, decision: 'approve' | 'reject') {
    setBusy(a.id + decision)
    try {
      const r = await send<EngineResponse>('POST', `/api/approvals/${a.id}/decision`, { decision, note: notes[a.id] || null })
      if (!r.success) setErrors((e) => ({ ...e, [a.id]: `${r.error?.code}: ${r.error?.message}` }))
      else { setErrors((e) => ({ ...e, [a.id]: '' })); await list.reload() }
    } catch (e) {
      setErrors((x) => ({ ...x, [a.id]: (e as Error).message }))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div>
      <PageHeader title="Human approvals" description={<>Sensitive actions proposed by pipelines wait here. Deciding requires the <b>approval:decide</b> permission (reviewer/admin); requesters cannot approve their own requests and AI actors can never decide. You are <b>{identity.actor}</b> ({identity.role}).</>}
        actions={<Tabs value={filter} onChange={setFilter} options={[{ id: 'pending', label: 'Pending' }, { id: 'all', label: 'All' }]} />} />
      {list.loading && !list.data && <Spinner />}
      {list.error && <ErrorBox>{list.error}</ErrorBox>}
      {list.data?.length === 0 && (
        <Empty icon={<ClipboardCheck className="size-6" />} title={filter === 'pending' ? 'Nothing waiting for review' : 'No approval requests yet'}>
          Run the Finance or Healthcare pipeline to generate review requests.
        </Empty>
      )}
      <div className="space-y-3">
        {list.data?.map((a) => (
          <Card key={a.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-ink">{a.title} <StatusBadge status={a.status} /></p>
                <p className="mt-1 text-xs text-muted">
                  action <span className="font-mono">{a.action}</span> · risk {a.risk_score ?? '—'} · requested by {a.requested_by} ({a.requested_role}) · {fmtTime(a.created_at)}
                  {a.run_id && <> · <button className="underline" onClick={() => navigate('runs', a.run_id!)}>run</button></>}
                </p>
                {a.status !== 'pending' && <p className="mt-1 text-xs text-ink-2">{a.status} by <b>{a.reviewer}</b> ({a.reviewer_role}) · {fmtTime(a.decided_at)}{a.note ? ` — “${a.note}”` : ''}</p>}
              </div>
              {a.status === 'pending' && (
                <div className="flex flex-wrap items-center gap-2">
                  <input value={notes[a.id] ?? ''} onChange={(e) => setNotes({ ...notes, [a.id]: e.target.value })} placeholder="Reviewer note"
                    aria-label="Reviewer note" className="w-48 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs outline-none focus:border-[var(--accent)]" />
                  <Button size="sm" busy={busy === a.id + 'reject'} onClick={() => void decide(a, 'reject')}><X className="size-3.5" aria-hidden />Reject</Button>
                  <Button size="sm" variant="primary" busy={busy === a.id + 'approve'} onClick={() => void decide(a, 'approve')}><Check className="size-3.5" aria-hidden />Approve</Button>
                </div>
              )}
            </div>
            {errors[a.id] && <div className="mt-3"><ErrorBox>{errors[a.id]}</ErrorBox></div>}
            <div className="mt-3"><Disclosure summary={<span className="text-xs text-ink-2">Evidence payload <Badge>{Object.keys(a.payload).length} fields</Badge></span>}><JsonView value={a.payload} maxHeight={260} /></Disclosure></div>
          </Card>
        ))}
      </div>
    </div>
  )
}

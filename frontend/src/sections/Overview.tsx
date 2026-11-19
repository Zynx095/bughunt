import { ArrowRight, Link2, ShieldCheck, ShieldX } from 'lucide-react'

import { DomainBadgeIcon } from '../components/domainIcon'
import { Badge, Button, Card, Empty, ErrorBox, PageHeader, Spinner, Stat, StatusBadge } from '../components/ui'
import { cx } from '../lib/cx'
import { useApp } from '../context'
import { fmtMs, fmtTime, short } from '../lib/format'
import { useApi } from '../lib/hooks'
import type { Overview } from '../lib/types'

const ENGINE_TITLES: Record<string, string> = {
  security: 'Security', ai: 'AI', ml: 'Machine learning', crypto: 'Cryptography', data: 'Data', decision: 'Decision',
}

export function OverviewPage() {
  const { active, domains, setActiveDomain, navigate } = useApp()
  const { data, error, loading } = useApi<Overview>('/api/overview')

  return (
    <div>
      <PageHeader title="Overview" description="Live state of the framework: engine health, persisted activity and the tamper-evident audit chain. Every number here is read from the database."
        actions={<Button variant="primary" onClick={() => navigate('workspace')}>Open workspace <ArrowRight className="size-4" aria-hidden /></Button>} />
      {error && <ErrorBox>{error}</ErrorBox>}
      {loading && !data && <Spinner />}
      {data && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
            <Stat label="Engine executions" value={data.counts.executions} hint={`${data.counts.failed_executions} failed`} />
            <Stat label="Pipeline runs" value={data.counts.pipeline_runs} />
            <Stat label="Pending approvals" value={data.counts.pending_approvals} tone={data.counts.pending_approvals ? 'warn' : 'neutral'} />
            <Stat label="Security events" value={data.counts.security_events} tone={data.counts.security_events ? 'warn' : 'neutral'} />
            <Stat label="Documents / datasets" value={`${data.counts.documents} / ${data.counts.datasets}`} />
            <Stat label="Audit chain" value={data.audit_chain.valid ? 'intact' : 'BROKEN'} tone={data.audit_chain.valid ? 'good' : 'bad'}
              hint={`${data.audit_chain.checked} events verified`} />
          </div>

          <div className="grid gap-5 xl:grid-cols-3">
            <Card title="Engine health" subtitle={`API v${data.health.version} · database ${data.health.database}`} className="xl:col-span-2">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(data.health.engines).map(([name, h]) => (
                  <div key={name} className="rounded-lg border border-line p-3">
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-medium">{ENGINE_TITLES[name] ?? name}</p>
                      <StatusBadge status={h.status} />
                    </div>
                    <dl className="mt-2 space-y-0.5 text-xs text-ink-2">
                      {Object.entries(h).filter(([k]) => !['status', 'warning'].includes(k)).map(([k, v]) => (
                        <div key={k} className="flex justify-between gap-2"><dt className="text-muted">{k.replace(/_/g, ' ')}</dt><dd className="truncate font-medium">{String(v ?? '—')}</dd></div>
                      ))}
                    </dl>
                    {h.warning && <p className="mt-2 text-[11px] leading-snug text-warn-ink">{h.warning}</p>}
                  </div>
                ))}
              </div>
            </Card>

            <Card title="Audit chain" subtitle="SHA-256 hash chain over every audit event">
              <div className="flex items-start gap-3">
                {data.audit_chain.valid ? <ShieldCheck className="size-8 text-good-ink" aria-hidden /> : <ShieldX className="size-8 text-critical-ink" aria-hidden />}
                <div className="min-w-0 text-sm">
                  <p className="font-medium">{data.audit_chain.valid ? 'All events verify' : `Chain broken at event #${data.audit_chain.broken_at_id}`}</p>
                  <p className="mt-1 text-xs text-muted">{data.audit_chain.checked} events checked. Editing or deleting any past event breaks every later hash.</p>
                  {data.audit_chain.head && <p className="mt-2 flex items-center gap-1 font-mono text-[11px] text-ink-2"><Link2 className="size-3" aria-hidden />head {short(data.audit_chain.head, 20)}</p>}
                </div>
              </div>
              <div className="mt-4 space-y-1.5">
                {data.recent_audit.slice(0, 6).map((e) => (
                  <div key={e.id} className="flex items-center justify-between gap-2 text-xs">
                    <span className="min-w-0 truncate"><Badge tone={e.category === 'security' ? 'warn' : 'neutral'}>{e.category}</Badge> <span className="text-ink-2">{e.action}</span></span>
                    <span className="shrink-0 text-muted">{fmtTime(e.ts)}</span>
                  </div>
                ))}
              </div>
              <div className="mt-3"><Button size="sm" variant="ghost" onClick={() => navigate('audit')}>View audit log <ArrowRight className="size-3.5" aria-hidden /></Button></div>
            </Card>
          </div>

          <Card title="Domain adapters" subtitle="One framework, nine adapters. Each adapter selects its engines, UI sections and pipeline. Click to activate.">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {domains.map((d) => (
                <button key={d.id} onClick={async () => { await setActiveDomain(d.id); navigate('workspace') }}
                  className={cx('flex items-start gap-3 rounded-lg border p-3 text-left transition hover:bg-surface-2',
                    d.id === active?.id ? 'border-[var(--accent)] ring-1 ring-[var(--accent)]' : 'border-line')}>
                  <DomainBadgeIcon name={d.icon} color={d.color} />
                  <span className="min-w-0">
                    <span className="flex items-center gap-2 text-sm font-medium text-ink">{d.name}{d.id === active?.id && <Badge tone="accent">active</Badge>}</span>
                    <span className="mt-0.5 block text-xs text-ink-2">{d.scenario}</span>
                    <span className="mt-1.5 flex flex-wrap gap-1">{d.engines.map((e) => <Badge key={e}>{e}</Badge>)}</span>
                  </span>
                </button>
              ))}
            </div>
          </Card>

          <Card title="Recent pipeline runs" actions={<Button size="sm" variant="ghost" onClick={() => navigate('runs')}>All runs <ArrowRight className="size-3.5" aria-hidden /></Button>}>
            {data.recent_runs.length === 0 ? (
              <Empty title="No runs yet">Open the workspace and run the active domain's pipeline on its sample data.</Empty>
            ) : (
              <div className="divide-y divide-line">
                {data.recent_runs.map((r) => (
                  <button key={r.id} onClick={() => navigate('runs', r.id)} className="flex w-full items-center gap-3 py-2 text-left hover:bg-surface-2">
                    <StatusBadge status={r.status} />
                    <span className="w-36 shrink-0 truncate text-xs font-medium">{domains.find((d) => d.id === r.domain)?.name ?? r.domain}</span>
                    <span className="min-w-0 flex-1 truncate text-xs text-ink-2">{r.headline ?? r.error}</span>
                    <span className="tabular shrink-0 text-xs text-muted">{fmtMs(r.duration_ms)}</span>
                    <span className="hidden shrink-0 text-xs text-muted sm:inline">{fmtTime(r.created_at)}</span>
                  </button>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  )
}

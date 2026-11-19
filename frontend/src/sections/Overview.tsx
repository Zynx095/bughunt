import {
  ArrowRight,
  Cpu,
  Database,
  Link2,
  RotateCcw,
  ShieldCheck,
  ShieldX,
} from 'lucide-react'
import { useState } from 'react'

import { DomainBadgeIcon } from '../components/domainIcon'
import { EngineStatusCard } from '../components/EngineStatusCard'
import { Badge, Button, Card, Empty, ErrorBox, Spinner, Stat, StatusBadge } from '../components/ui'
import { useApp } from '../context'
import { cx } from '../lib/cx'
import { fmtMs, fmtTime, short } from '../lib/format'
import { useApi } from '../lib/hooks'
import type { Overview } from '../lib/types'

const ENGINE_TITLES: Record<string, string> = {
  security: 'Security & Policy',
  ai: 'AI & Inference',
  ml: 'Machine Learning',
  crypto: 'Cryptography & Integrity',
  data: 'Data & ETL',
  decision: 'Decision & Rules',
}

export function OverviewPage() {
  const { active, domains, setActiveDomain, navigate } = useApp()
  const { data, error, loading, reload } = useApi<Overview>('/api/overview')
  const [reverifying, setReverifying] = useState(false)

  const handleReverify = async () => {
    setReverifying(true)
    try {
      await reload()
    } finally {
      setReverifying(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Executive Command Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex size-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-[10px] font-bold uppercase tracking-widest text-muted">
              Operational Intelligence Command
            </span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-ink sm:text-3xl mt-0.5">
            Platform Overview
          </h1>
          <p className="mt-1 text-sm text-ink-2 max-w-2xl">
            Live telemetry of the OMNIFORGE framework: six engines, nine domain adapters, and the cryptographic audit chain.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <Button size="sm" variant="ghost" onClick={handleReverify} busy={reverifying}>
            <RotateCcw className="size-3.5" /> Refresh Telemetry
          </Button>
          <Button variant="primary" onClick={() => navigate('workspace')}>
            <span>Open {active?.name ?? 'Workspace'}</span>
            <ArrowRight className="size-4" aria-hidden />
          </Button>
        </div>
      </div>

      {error && <ErrorBox>{error}</ErrorBox>}
      {loading && !data && <div className="py-12"><Spinner label="Gathering platform telemetry" /></div>}

      {data && (
        <div className="space-y-6">
          {/* Top Status Bar: Engine Health, DB, Audit */}
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="flex items-center gap-3 rounded-xl border border-line bg-surface p-3.5">
              <div className="rounded-lg bg-emerald-500/10 p-2.5 text-emerald-600 dark:text-emerald-400">
                <Cpu className="size-5" />
              </div>
              <div className="min-w-0">
                <span className="text-[10px] font-bold uppercase tracking-wider text-muted">
                  Intelligence Mesh
                </span>
                <p className="text-sm font-semibold text-ink flex items-center gap-1.5">
                  <span>6 of 6 Engines Ready</span>
                  <StatusBadge status={data.health.status} />
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3 rounded-xl border border-line bg-surface p-3.5">
              <div className="rounded-lg bg-blue-500/10 p-2.5 text-blue-600 dark:text-blue-400">
                <Database className="size-5" />
              </div>
              <div className="min-w-0">
                <span className="text-[10px] font-bold uppercase tracking-wider text-muted">
                  Database & Store
                </span>
                <p className="text-sm font-semibold text-ink flex items-center gap-1.5">
                  <span>SQLite Verified</span>
                  <StatusBadge status={data.health.database} />
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3 rounded-xl border border-line bg-surface p-3.5">
              <div className="rounded-lg bg-purple-500/10 p-2.5 text-purple-600 dark:text-purple-400">
                {data.audit_chain.valid ? (
                  <ShieldCheck className="size-5 text-good-ink" />
                ) : (
                  <ShieldX className="size-5 text-critical-ink" />
                )}
              </div>
              <div className="min-w-0">
                <span className="text-[10px] font-bold uppercase tracking-wider text-muted">
                  Cryptographic Chain
                </span>
                <p className="text-sm font-semibold text-ink">
                  {data.audit_chain.valid ? 'SHA-256 Chain Intact' : 'INTEGRITY ALERT'}
                </p>
              </div>
            </div>
          </div>

          {/* Operational Metrics Grid */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
            <Stat
              label="Engine Calls"
              value={data.counts.executions}
              hint={`${data.counts.failed_executions} failed/blocked`}
            />
            <Stat label="Pipeline Runs" value={data.counts.pipeline_runs} />
            <Stat
              label="Pending Approvals"
              value={data.counts.pending_approvals}
              tone={data.counts.pending_approvals ? 'warn' : 'neutral'}
              hint={data.counts.pending_approvals ? 'Action required' : 'Queue clear'}
            />
            <Stat
              label="Security Events"
              value={data.counts.security_events}
              tone={data.counts.security_events ? 'warn' : 'neutral'}
            />
            <Stat
              label="Evidence & Datasets"
              value={`${data.counts.documents} / ${data.counts.datasets}`}
            />
            <Stat
              label="Verified Audit Events"
              value={data.audit_chain.checked}
              tone={data.audit_chain.valid ? 'good' : 'bad'}
              hint={data.audit_chain.head ? `Head: ${short(data.audit_chain.head, 8)}` : undefined}
            />
          </div>

          {/* Intelligence Engine Status Grid */}
          <div>
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-bold uppercase tracking-wider text-ink">
                  Intelligence Engine Fleet
                </h3>
                <p className="text-xs text-muted">
                  Uniform envelope execution with deterministic role-based access policy
                </p>
              </div>
              <Button size="sm" variant="ghost" onClick={() => navigate('engines')}>
                Open Engine Lab <ArrowRight className="size-3" />
              </Button>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {Object.entries(data.health.engines).map(([name, h]) => (
                <EngineStatusCard
                  key={name}
                  name={name}
                  title={ENGINE_TITLES[name] ?? name}
                  status={h.status}
                  warning={h.warning}
                  details={h}
                  onTest={() => navigate('engines')}
                />
              ))}
            </div>
          </div>

          {/* Domain Adapters Fleet */}
          <div>
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-bold uppercase tracking-wider text-ink">
                  Domain Adapters Fleet (9 Configured)
                </h3>
                <p className="text-xs text-muted">
                  Adaptive problem-specific workflows running atop the shared engine foundation
                </p>
              </div>
              <span className="font-mono text-xs text-muted">
                Active: <strong className="text-ink">{active?.name}</strong>
              </span>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {domains.map((d) => {
                const isActive = d.id === active?.id
                return (
                  <button
                    key={d.id}
                    type="button"
                    onClick={async () => {
                      await setActiveDomain(d.id)
                      navigate('workspace')
                    }}
                    className={cx(
                      'flex items-start gap-3.5 rounded-xl border p-4 text-left transition-all duration-150',
                      isActive
                        ? 'border-[var(--accent)] bg-[var(--accent)]/[0.04] ring-1 ring-[var(--accent)] shadow-sm'
                        : 'border-line bg-surface hover:border-line/80 hover:bg-surface-2/60'
                    )}
                  >
                    <DomainBadgeIcon name={d.icon} color={d.color} size="md" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-1">
                        <span className="truncate text-sm font-bold text-ink">{d.name}</span>
                        {isActive && <Badge tone="accent">Active</Badge>}
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs text-ink-2">{d.scenario}</p>
                      <div className="mt-2.5 flex flex-wrap gap-1">
                        {d.engines.map((e) => (
                          <span
                            key={e}
                            className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-muted border border-line/60"
                          >
                            {e}
                          </span>
                        ))}
                      </div>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Split Section: Cryptographic Chain & Recent Runs */}
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
            {/* Audit Chain & Tamper Evidence */}
            <Card
              title="Cryptographic Audit Integrity"
              subtitle="SHA-256 hash chaining prevents and detects tampering across all historical events"
              actions={
                <Button size="sm" variant="ghost" onClick={() => navigate('audit')}>
                  Full Audit Log <ArrowRight className="size-3" />
                </Button>
              }
            >
              <div className="flex items-start gap-3 rounded-lg bg-surface-2/60 p-3.5 border border-line">
                {data.audit_chain.valid ? (
                  <ShieldCheck className="size-7 text-good-ink shrink-0" />
                ) : (
                  <ShieldX className="size-7 text-critical-ink shrink-0" />
                )}
                <div className="min-w-0 text-xs">
                  <p className="font-semibold text-ink text-sm">
                    {data.audit_chain.valid
                      ? 'Tamper-Evident Hash Chain Verified'
                      : `Chain broken at event #${data.audit_chain.broken_at_id}`}
                  </p>
                  <p className="mt-0.5 text-muted">
                    {data.audit_chain.checked} total events verified against cryptographic root.
                  </p>
                  {data.audit_chain.head && (
                    <p className="mt-1.5 flex items-center gap-1 font-mono text-[11px] text-ink-2">
                      <Link2 className="size-3 text-muted" /> Head:{' '}
                      <span className="font-semibold">{short(data.audit_chain.head, 24)}</span>
                    </p>
                  )}
                </div>
              </div>

              <div className="mt-4 space-y-2">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-muted block">
                  Recent Audit Events
                </span>
                {data.recent_audit.slice(0, 5).map((e) => (
                  <div
                    key={e.id}
                    className="flex items-center justify-between gap-2 text-xs py-1 border-b border-line/40 last:border-0"
                  >
                    <div className="flex items-center gap-2 min-w-0 truncate">
                      <Badge tone={e.category === 'security' ? 'warn' : 'neutral'}>
                        {e.category}
                      </Badge>
                      <span className="font-medium text-ink truncate">{e.action}</span>
                    </div>
                    <span className="shrink-0 font-mono text-[11px] text-muted">
                      {fmtTime(e.ts)}
                    </span>
                  </div>
                ))}
              </div>
            </Card>

            {/* Recent Pipeline Runs */}
            <Card
              title="Recent Pipeline Runs"
              subtitle="Persisted pipeline results across all domain adapters"
              actions={
                <Button size="sm" variant="ghost" onClick={() => navigate('runs')}>
                  View All Runs <ArrowRight className="size-3" />
                </Button>
              }
              pad={false}
            >
              {data.recent_runs.length === 0 ? (
                <div className="p-6">
                  <Empty title="No pipeline runs recorded">
                    Open the workspace and execute the active domain pipeline to see historical runs here.
                  </Empty>
                </div>
              ) : (
                <div className="divide-y divide-line">
                  {data.recent_runs.map((r) => (
                    <div
                      key={r.id}
                      onClick={() => navigate('runs', r.id)}
                      className="flex cursor-pointer items-center justify-between gap-3 p-3.5 text-xs hover:bg-surface-2 transition"
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <StatusBadge status={r.status} />
                        <div className="min-w-0">
                          <p className="truncate font-semibold text-ink">
                            {r.headline ?? r.error ?? 'Pipeline run'}
                          </p>
                          <p className="font-mono text-[11px] text-muted">
                            Domain: <strong className="text-ink-2">{r.domain}</strong> · ID: {short(r.id, 8)} · by {r.actor}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-3 shrink-0 text-muted">
                        <span className="tabular font-mono">{fmtMs(r.duration_ms)}</span>
                        <span>{fmtTime(r.created_at)}</span>
                        <ArrowRight className="size-3 text-muted" />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}

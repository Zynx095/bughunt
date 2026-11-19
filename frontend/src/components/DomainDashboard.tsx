import { ArrowRight, Cpu, Play } from 'lucide-react'

import { DOMAIN_METADATA } from '../lib/domainConfig'
import { fmtMs, fmtTime } from '../lib/format'
import type { DomainInfo, RunRecord } from '../lib/types'
import { DomainBadgeIcon } from './domainIcon'
import { Badge, Button, Card, Stat, StatusBadge } from './ui'

interface DomainDashboardProps {
  domain: DomainInfo
  recentRuns?: RunRecord[]
  onLaunchWorkspace: () => void
  onViewRun: (runId: string) => void
}

export function DomainDashboard({
  domain,
  recentRuns = [],
  onLaunchWorkspace,
  onViewRun,
}: DomainDashboardProps) {
  const meta = DOMAIN_METADATA[domain.id]
  const completedCount = recentRuns.filter((r) => r.status === 'completed').length
  const failedCount = recentRuns.filter((r) => r.status === 'failed').length

  return (
    <div className="space-y-4">
      {/* Domain Header Card */}
      <div className="rounded-xl border border-line bg-surface p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3.5">
            <DomainBadgeIcon name={domain.icon} color={domain.color} size="lg" />
            <div className="min-w-0">
              <span className="text-[10px] font-bold uppercase tracking-wider text-muted">
                {meta?.category ?? 'Domain Adapter'}
              </span>
              <h2 className="text-xl font-bold tracking-tight text-ink">{domain.name}</h2>
              <p className="mt-1 max-w-2xl text-sm text-ink-2">{domain.tagline}</p>
            </div>
          </div>
          <Button variant="primary" onClick={onLaunchWorkspace}>
            <Play className="size-4" aria-hidden /> Launch Pipeline
          </Button>
        </div>

        {/* Engine dependencies badges */}
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line/60 pt-3 text-xs">
          <span className="text-muted font-medium flex items-center gap-1">
            <Cpu className="size-3.5" /> Engines:
          </span>
          {domain.engines.map((e) => (
            <Badge key={e} tone="neutral">
              {e}
            </Badge>
          ))}
          <span className="text-muted ml-auto font-mono text-[11px]">
            {domain.steps.length} sequential pipeline steps
          </span>
        </div>
      </div>

      {/* Operational stats for this domain */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Total Recorded Runs" value={recentRuns.length} />
        <Stat
          label="Pass Rate"
          value={recentRuns.length ? `${Math.round((completedCount / recentRuns.length) * 100)}%` : '—'}
          tone={failedCount ? 'warn' : 'good'}
        />
        <Stat
          label="Avg Pipeline Latency"
          value={
            recentRuns.length
              ? fmtMs(Math.round(recentRuns.reduce((acc, r) => acc + r.duration_ms, 0) / recentRuns.length))
              : '—'
          }
        />
        <Stat label="Configured Engines" value={domain.engines.length} />
      </div>

      {/* Recent runs list */}
      {recentRuns.length > 0 && (
        <Card title="Recent Domain Runs" pad={false}>
          <div className="divide-y divide-line">
            {recentRuns.slice(0, 5).map((run) => (
              <div
                key={run.id}
                onClick={() => onViewRun(run.id)}
                className="flex cursor-pointer items-center justify-between gap-3 p-3 text-xs hover:bg-surface-2 transition"
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <StatusBadge status={run.status} />
                  <span className="font-mono text-muted">{run.id}</span>
                  <span className="truncate font-medium text-ink max-w-sm">
                    {run.headline ?? run.error ?? 'Pipeline execution'}
                  </span>
                </div>
                <div className="flex items-center gap-3 shrink-0 text-muted">
                  <span className="tabular font-mono">{fmtMs(run.duration_ms)}</span>
                  <span>{fmtTime(run.created_at)}</span>
                  <ArrowRight className="size-3" />
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

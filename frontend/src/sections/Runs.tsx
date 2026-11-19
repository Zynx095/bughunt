import { ArrowLeft, Clock, Filter, Layers, Play, Search, User } from 'lucide-react'
import { useMemo, useState } from 'react'

import { JSONInspector } from '../components/JSONInspector'
import { StepList, StepOutputs } from '../components/presentation'
import { ResultsRenderer } from '../components/ResultsRenderer'
import { Badge, Button, Card, Disclosure, Empty, ErrorBox, PageHeader, Spinner, StatusBadge } from '../components/ui'
import { useApp } from '../context'
import { cx } from '../lib/cx'
import { fmtMs, fmtTime } from '../lib/format'
import { useApi } from '../lib/hooks'
import type { RunRecord } from '../lib/types'

export function RunsPage() {
  const { param, navigate, domains, active } = useApp()
  const runs = useApi<RunRecord[]>('/api/runs?limit=100')
  const detail = useApi<RunRecord>(param ? `/api/runs/${param}` : null)
  const [filterDomain, setFilterDomain] = useState<string>('all')
  const [filterStatus, setFilterStatus] = useState<string>('all')

  const domainName = (id: string) => domains.find((d) => d.id === id)?.name ?? id

  const filteredRuns = useMemo(() => {
    if (!runs.data) return []
    return runs.data.filter((r) => {
      const matchDom = filterDomain === 'all' || r.domain === filterDomain
      const matchStat = filterStatus === 'all' || r.status === filterStatus
      return matchDom && matchStat
    })
  }, [runs.data, filterDomain, filterStatus])

  if (param) {
    const run = detail.data
    const domain = domains.find((d) => d.id === run?.domain)
    return (
      <div className="space-y-5">
        <Button size="sm" variant="ghost" onClick={() => navigate('runs')}>
          <ArrowLeft className="size-4" aria-hidden /> Back to Execution History
        </Button>

        {detail.loading && <div className="py-12"><Spinner label="Loading Run Details" /></div>}
        {detail.error && <ErrorBox>{detail.error}</ErrorBox>}

        {run && (
          <>
            <PageHeader
              title={domainName(run.domain)}
              description={
                <>
                  Execution <code className="font-mono text-ink">{run.id}</code> ·{' '}
                  {fmtTime(run.created_at)} · {fmtMs(run.duration_ms)} · Executed by{' '}
                  <strong className="text-ink">{run.actor}</strong> ({run.role})
                </>
              }
              actions={<StatusBadge status={run.status} />}
            />

            <div className="grid gap-5 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
              {/* Left: Step progress list */}
              <Card title="Pipeline Execution Status">
                {domain && <StepList steps={domain.steps} run={run} />}
              </Card>

              {/* Right: Results renderer */}
              <div className="min-w-0 space-y-4">
                {run.error && <ErrorBox>{run.error}</ErrorBox>}
                {run.presentation && (
                  <ResultsRenderer
                    presentation={run.presentation}
                    runId={run.id}
                    domainId={run.domain}
                  />
                )}
                <Disclosure summary={<span className="text-xs font-semibold text-ink">Inspect Step-by-Step Engine Envelopes</span>}>
                  <StepOutputs run={run} />
                </Disclosure>
                {run.input && (
                  <Disclosure summary={<span className="text-xs font-semibold text-ink">View Input Payload Provided</span>}>
                    <JSONInspector title="Run Input" value={run.input} />
                  </Disclosure>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Runs & Execution History"
        description="Persistent repository of all pipeline executions across every domain. Each record preserves input parameters, execution telemetry, step latencies, warnings, and structured outputs."
      />

      <Card
        title="Execution Records"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={filterDomain}
              onChange={(e) => setFilterDomain(e.target.value)}
              aria-label="Filter Domain"
              className="h-8 rounded-md border border-line bg-surface px-2 text-xs text-ink outline-none"
            >
              <option value="all">All Domains</option>
              {domains.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>

            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              aria-label="Filter Status"
              className="h-8 rounded-md border border-line bg-surface px-2 text-xs text-ink outline-none"
            >
              <option value="all">All Statuses</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
              <option value="running">Running</option>
            </select>
          </div>
        }
        pad={false}
      >
        {runs.loading && !runs.data && <div className="p-8"><Spinner /></div>}
        {runs.error && <div className="p-4"><ErrorBox>{runs.error}</ErrorBox></div>}
        {filteredRuns.length === 0 && (
          <div className="p-8">
            <Empty title="No pipeline runs found">
              Execute a scenario pipeline from the Workspace to generate run records.
            </Empty>
          </div>
        )}

        {filteredRuns.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-2/60 border-b border-line text-xs text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Domain</th>
                  <th className="px-4 py-2 font-medium">Verdict / Outcome</th>
                  <th className="px-4 py-2 font-medium">Pipeline Stages</th>
                  <th className="px-4 py-2 text-right font-medium">Latency</th>
                  <th className="px-4 py-2 font-medium">Timestamp</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/60">
                {filteredRuns.map((r) => (
                  <tr
                    key={r.id}
                    onClick={() => navigate('runs', r.id)}
                    className={cx(
                      'cursor-pointer hover:bg-surface-2 transition-colors',
                      r.domain === active?.id && 'bg-[var(--accent)]/[0.03]'
                    )}
                  >
                    <td className="px-4 py-2.5">
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-xs font-semibold text-ink">
                      {domainName(r.domain)}
                    </td>
                    <td className="max-w-md px-4 py-2.5 text-xs text-ink-2 truncate">
                      {r.headline ?? r.error ?? 'Completed successfully'}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="flex gap-1" aria-label="Step statuses">
                        {r.steps.map((s) => (
                          <span
                            key={s.id}
                            title={`${s.title}: ${s.status} (${fmtMs(s.execution_time_ms)})`}
                            className={cx(
                              'h-2.5 w-3.5 rounded-sm transition-all',
                              s.status === 'completed'
                                ? 'bg-emerald-500'
                                : s.status === 'failed'
                                  ? 'bg-rose-500'
                                  : 'bg-line'
                            )}
                          />
                        ))}
                      </span>
                    </td>
                    <td className="tabular whitespace-nowrap px-4 py-2.5 text-right font-mono text-xs text-muted">
                      {fmtMs(r.duration_ms)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-xs text-muted">
                      {fmtTime(r.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

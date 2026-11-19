import { ArrowLeft } from 'lucide-react'

import { PresentationView, StepList, StepOutputs } from '../components/presentation'
import { Button, Card, Disclosure, Empty, ErrorBox, JsonView, PageHeader, Spinner, StatusBadge } from '../components/ui'
import { cx } from '../lib/cx'
import { useApp } from '../context'
import { fmtMs, fmtTime } from '../lib/format'
import { useApi } from '../lib/hooks'
import type { RunRecord } from '../lib/types'

export function RunsPage() {
  const { param, navigate, domains, active } = useApp()
  const runs = useApi<RunRecord[]>('/api/runs?limit=100')
  const detail = useApi<RunRecord>(param ? `/api/runs/${param}` : null)
  const domainName = (id: string) => domains.find((d) => d.id === id)?.name ?? id

  if (param) {
    const run = detail.data
    const domain = domains.find((d) => d.id === run?.domain)
    return (
      <div className="space-y-5">
        <Button size="sm" variant="ghost" onClick={() => navigate('runs')}><ArrowLeft className="size-4" aria-hidden />All runs</Button>
        {detail.loading && <Spinner />}
        {detail.error && <ErrorBox>{detail.error}</ErrorBox>}
        {run && (
          <>
            <PageHeader title={domainName(run.domain)} description={<>Run <span className="font-mono">{run.id}</span> · {fmtTime(run.created_at)} · {fmtMs(run.duration_ms)} · by {run.actor} ({run.role})</>}
              actions={<StatusBadge status={run.status} />} />
            <div className="grid gap-5 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
              <Card title="Execution status">{domain && <StepList steps={domain.steps} run={run} />}</Card>
              <div className="min-w-0 space-y-4">
                {run.error && <ErrorBox>{run.error}</ErrorBox>}
                {run.presentation && <PresentationView p={run.presentation} />}
                <Disclosure summary={<span className="text-sm font-medium">Step outputs</span>}><StepOutputs run={run} /></Disclosure>
                <Disclosure summary={<span className="text-sm font-medium">Input used</span>}><JsonView value={run.input} /></Disclosure>
              </div>
            </div>
          </>
        )}
      </div>
    )
  }

  return (
    <div>
      <PageHeader title="Runs & results" description="Every pipeline execution is persisted with its per-step status, timings, warnings and results." />
      <Card pad={false}>
        {runs.loading && !runs.data && <div className="p-4"><Spinner /></div>}
        {runs.error && <div className="p-4"><ErrorBox>{runs.error}</ErrorBox></div>}
        {runs.data?.length === 0 && <div className="p-4"><Empty title="No runs yet">Run a pipeline from the workspace.</Empty></div>}
        {runs.data && runs.data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead><tr className="border-b border-line text-xs text-muted">
                <th className="px-4 py-2 font-medium">Status</th><th className="px-4 py-2 font-medium">Domain</th>
                <th className="px-4 py-2 font-medium">Result</th><th className="px-4 py-2 font-medium">Steps</th>
                <th className="px-4 py-2 text-right font-medium">Duration</th><th className="px-4 py-2 font-medium">When</th>
              </tr></thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.id} onClick={() => navigate('runs', r.id)} className={cx('cursor-pointer border-b border-line/70 hover:bg-surface-2', r.domain === active?.id && 'bg-[var(--accent)]/[0.03]')}>
                    <td className="px-4 py-2"><StatusBadge status={r.status} /></td>
                    <td className="whitespace-nowrap px-4 py-2 text-xs font-medium">{domainName(r.domain)}</td>
                    <td className="max-w-xl px-4 py-2 text-xs text-ink-2"><span className="line-clamp-2">{r.headline ?? r.error}</span></td>
                    <td className="px-4 py-2">
                      <span className="flex gap-0.5" aria-label="step statuses">
                        {r.steps.map((s) => <span key={s.id} title={`${s.title}: ${s.status}`} className={cx('h-2 w-3 rounded-sm',
                          s.status === 'completed' ? 'bg-good' : s.status === 'failed' ? 'bg-critical' : 'bg-line')} />)}
                      </span>
                    </td>
                    <td className="tabular whitespace-nowrap px-4 py-2 text-right text-xs text-muted">{fmtMs(r.duration_ms)}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-xs text-muted">{fmtTime(r.created_at)}</td>
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

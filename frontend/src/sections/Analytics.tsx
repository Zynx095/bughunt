import { ChartCard } from '../components/charts'
import { DataTable } from '../components/table'
import { Button, Card, Empty, ErrorBox, PageHeader, Spinner, Stat } from '../components/ui'
import { useApp } from '../context'
import { useApi } from '../lib/hooks'
import type { Analytics } from '../lib/types'

export function AnalyticsPage() {
  const { domains } = useApp()
  const { data, error, loading, reload } = useApi<Analytics>('/api/analytics')
  const name = (id: string) => domains.find((d) => d.id === id)?.name ?? id

  return (
    <div>
      <PageHeader title="Analytics" description="Measured from the executions table: every engine call is recorded with its latency and outcome. Nothing here is simulated."
        actions={<Button size="sm" onClick={() => void reload()}>Refresh</Button>} />
      {loading && !data && <Spinner />}
      {error && <ErrorBox>{error}</ErrorBox>}
      {data && data.counts.executions === 0 && <Empty title="No executions recorded yet">Run a pipeline or call an engine from the Engine lab.</Empty>}
      {data && data.counts.executions > 0 && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Engine executions" value={data.counts.executions} />
            <Stat label="Success rate" value={`${(((data.counts.executions - data.counts.failed_executions) / data.counts.executions) * 100).toFixed(1)}%`}
              tone={data.counts.failed_executions ? 'warn' : 'good'} hint={`${data.counts.failed_executions} failed or denied`} />
            <Stat label="Pipeline runs" value={data.counts.pipeline_runs} />
            <Stat label="Security events" value={data.counts.security_events} tone={data.counts.security_events ? 'warn' : 'neutral'} />
          </div>
          <div className="grid gap-5 xl:grid-cols-2">
            <ChartCard spec={{ type: 'bar', title: 'Executions by engine', x: 'engine', series: [{ key: 'count', label: 'Executions' }],
              data: [...data.per_engine].sort((a, b) => b.count - a.count) }} />
            <ChartCard spec={{ type: 'bar', title: 'Mean latency by engine (ms)', x: 'engine', series: [{ key: 'avg_ms', label: 'Mean ms' }],
              data: [...data.per_engine].sort((a, b) => b.avg_ms - a.avg_ms) }} />
          </div>
          <ChartCard spec={{ type: 'line', title: `Latency of the last ${data.recent.length} executions (ms)`, x: 'n', series: [{ key: 'ms', label: 'Latency ms' }],
            data: data.recent.map((r, i) => ({ n: i + 1, ms: r.ms, op: `${r.engine}.${r.operation}` })) }} />
          <div className="grid gap-5 xl:grid-cols-2">
            <Card title="Busiest operations">
              <DataTable columns={[{ key: 'op', label: 'Operation' }, { key: 'count', label: 'Calls' }, { key: 'avg_ms', label: 'Mean ms' }]}
                rows={data.per_operation.map((o) => ({ ...o, op: `${o.engine}.${o.operation}` }))} />
            </Card>
            <Card title="Pipeline runs by domain">
              <DataTable columns={[{ key: 'domain', label: 'Domain' }, { key: 'status', label: 'Status' }, { key: 'count', label: 'Runs' }, { key: 'avg_ms', label: 'Mean ms' }]}
                rows={data.runs.map((r) => ({ ...r, domain: name(r.domain) }))} />
              {data.errors.length > 0 && (
                <div className="mt-4">
                  <p className="mb-1 text-xs font-medium text-muted">Failures by error code</p>
                  <DataTable columns={[{ key: 'code', label: 'Code' }, { key: 'count', label: 'Count' }]} rows={data.errors} />
                </div>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}

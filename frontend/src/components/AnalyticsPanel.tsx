import { RefreshCw } from 'lucide-react'

import type { Analytics } from '../lib/types'
import { ChartCard } from './charts'
import { ExecutionTrendsChart } from './specializedCharts'
import { DataTable } from './table'
import { Button, Card, Stat } from './ui'

interface AnalyticsPanelProps {
  analytics: Analytics
  onRefresh?: () => void
  domainNameMap?: (domainId: string) => string
}

export function AnalyticsPanel({
  analytics,
  onRefresh,
  domainNameMap = (id) => id,
}: AnalyticsPanelProps) {
  const successRate = analytics.counts.executions
    ? (((analytics.counts.executions - analytics.counts.failed_executions) / analytics.counts.executions) * 100).toFixed(1)
    : '100'

  return (
    <div className="space-y-5">
      {onRefresh && (
        <div className="flex justify-end">
          <Button size="sm" variant="ghost" onClick={onRefresh}>
            <RefreshCw className="size-3.5" /> Refresh Analytics
          </Button>
        </div>
      )}
      {/* Metrics Row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat
          label="Total Engine Executions"
          value={analytics.counts.executions}
          hint={`${analytics.counts.failed_executions} failed/rejected`}
        />
        <Stat
          label="Execution Success Rate"
          value={`${successRate}%`}
          tone={analytics.counts.failed_executions ? 'warn' : 'good'}
        />
        <Stat label="Total Pipeline Runs" value={analytics.counts.pipeline_runs} />
        <Stat
          label="Security Events"
          value={analytics.counts.security_events}
          tone={analytics.counts.security_events ? 'warn' : 'neutral'}
        />
      </div>

      {/* Primary Engine Charts */}
      <div className="grid gap-5 xl:grid-cols-2">
        <ChartCard
          spec={{
            type: 'bar',
            title: 'Calls by Engine',
            x: 'engine',
            series: [{ key: 'count', label: 'Executions' }],
            data: [...analytics.per_engine].sort((a, b) => b.count - a.count),
          }}
        />
        <ChartCard
          spec={{
            type: 'bar',
            title: 'Mean Engine Latency (ms)',
            x: 'engine',
            series: [{ key: 'avg_ms', label: 'Mean ms' }],
            data: [...analytics.per_engine].sort((a, b) => b.avg_ms - a.avg_ms),
          }}
        />
      </div>

      {/* Latency History */}
      {analytics.recent.length > 0 && (
        <ExecutionTrendsChart
          data={analytics.recent.map((r, i) => ({
            n: i + 1,
            ms: r.ms,
            operation: r.operation,
            engine: r.engine,
          }))}
          title={`Latency History (Last ${analytics.recent.length} Calls)`}
        />
      )}

      {/* Detailed Tables */}
      <div className="grid gap-5 xl:grid-cols-2">
        <Card title="Top Engine Operations" subtitle="Ranked by invocation count">
          <DataTable
            columns={[
              { key: 'op', label: 'Operation' },
              { key: 'count', label: 'Calls' },
              { key: 'avg_ms', label: 'Mean ms' },
            ]}
            rows={analytics.per_operation.map((o) => ({
              ...o,
              op: `${o.engine}.${o.operation}`,
            }))}
          />
        </Card>

        <Card title="Pipeline Runs by Domain" subtitle="Historical volume and duration">
          <DataTable
            columns={[
              { key: 'domain', label: 'Domain' },
              { key: 'status', label: 'Status' },
              { key: 'count', label: 'Runs' },
              { key: 'avg_ms', label: 'Mean ms' },
            ]}
            rows={analytics.runs.map((r) => ({
              ...r,
              domain: domainNameMap(r.domain),
            }))}
          />
          {analytics.errors.length > 0 && (
            <div className="mt-4 border-t border-line/60 pt-3">
              <p className="mb-2 text-xs font-semibold text-muted">Error Code Frequency</p>
              <DataTable
                columns={[
                  { key: 'code', label: 'Error Code' },
                  { key: 'count', label: 'Count' },
                ]}
                rows={analytics.errors}
              />
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

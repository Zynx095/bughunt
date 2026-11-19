import { BarChart3, RefreshCw } from 'lucide-react'

import { AnalyticsPanel } from '../components/AnalyticsPanel'
import { Button, Empty, ErrorBox, PageHeader, Spinner } from '../components/ui'
import { useApp } from '../context'
import { useApi } from '../lib/hooks'
import type { Analytics } from '../lib/types'

export function AnalyticsPage() {
  const { domains } = useApp()
  const { data, error, loading, reload } = useApi<Analytics>('/api/analytics')
  const name = (id: string) => domains.find((d) => d.id === id)?.name ?? id

  return (
    <div className="space-y-5">
      <PageHeader
        title="Operational Analytics"
        description="Measured execution metrics from the persistent SQLite store: execution volume, latency distribution, pass rates, and failure codes. Every data point reflects actual engine invocations."
        actions={
          <Button size="sm" onClick={() => void reload()}>
            <RefreshCw className="size-3.5" /> Refresh Telemetry
          </Button>
        }
      />

      {loading && !data && <div className="py-12"><Spinner label="Calculating Execution Statistics" /></div>}
      {error && <ErrorBox>{error}</ErrorBox>}

      {data && data.counts.executions === 0 && (
        <Empty title="No executions recorded yet">
          Run a domain pipeline or execute an operation in the Engine Lab to generate execution analytics.
        </Empty>
      )}

      {data && data.counts.executions > 0 && (
        <AnalyticsPanel analytics={data} onRefresh={() => void reload()} domainNameMap={name} />
      )}
    </div>
  )
}

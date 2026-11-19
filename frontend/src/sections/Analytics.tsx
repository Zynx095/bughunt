import { RefreshCw } from 'lucide-react'
import { useState } from 'react'

import { AnalyticsPanel } from '../components/AnalyticsPanel'
import { Button, Empty, ErrorBox, PageHeader, Spinner, Tabs } from '../components/ui'
import { useApp } from '../context'
import { CrowdAnalyticsPage } from '../crowdguard/pages/CrowdAnalytics'
import { useApi } from '../lib/hooks'
import type { Analytics } from '../lib/types'

/** One analytics destination: crowd-safety outcomes (scenario evaluation) and platform telemetry. */
export function AnalyticsPage() {
  const [tab, setTab] = useState<'crowd' | 'platform'>('crowd')
  return (
    <div className="space-y-4">
      <Tabs value={tab} onChange={setTab} options={[{ id: 'crowd', label: 'Crowd safety' }, { id: 'platform', label: 'Platform telemetry' }]} />
      {tab === 'crowd' ? <CrowdAnalyticsPage /> : <PlatformTelemetry />}
    </div>
  )
}

function PlatformTelemetry() {
  const { domains } = useApp()
  const { data, error, loading, reload } = useApi<Analytics>('/api/analytics')
  const name = (id: string) => domains.find((d) => d.id === id)?.name ?? id
  return (
    <div className="space-y-5">
      <PageHeader title="Platform telemetry"
        description="Measured from the SQLite store: execution volume, latency, pass rates and failure codes. Every point is a real engine invocation."
        actions={<Button size="sm" onClick={() => void reload()}><RefreshCw className="size-3.5" /> Refresh</Button>} />
      {loading && !data && <div className="py-12"><Spinner label="Calculating execution statistics" /></div>}
      {error && <ErrorBox>{error}</ErrorBox>}
      {data && data.counts.executions === 0 && (
        <Empty title="No executions recorded yet">Run a domain pipeline or an Engine Lab operation to generate telemetry.</Empty>
      )}
      {data && data.counts.executions > 0 && <AnalyticsPanel analytics={data} onRefresh={() => void reload()} domainNameMap={name} />}
    </div>
  )
}

import { useEffect, useState } from 'react'

import { DynamicWorkspace } from '../components/DynamicWorkspace'
import { ErrorBox, Spinner } from '../components/ui'
import { useApp } from '../context'
import { get, send } from '../lib/api'
import { useApi } from '../lib/hooks'
import type { DomainInfo, RunRecord } from '../lib/types'

export function WorkspacePage() {
  const { active, domains, setActiveDomain, identity, navigate } = useApp()
  const { data: detail, error } = useApi<DomainInfo>(active ? `/api/domains/${active.id}` : null)
  const [initialRun, setInitialRun] = useState<RunRecord | null>(null)

  // Fetch the most recent persisted run for this domain (real stored data)
  useEffect(() => {
    if (!active) return
    let cancelled = false
    get<RunRecord[]>(`/api/runs?domain=${active.id}&limit=1`)
      .then((list) => (list[0] ? get<RunRecord>(`/api/runs/${list[0].id}`) : null))
      .then((latest) => {
        if (!cancelled && latest) {
          setInitialRun(latest)
        }
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [active])

  if (!active) return null
  if (error) return <div className="p-4"><ErrorBox>{error}</ErrorBox></div>
  if (!detail) return <div className="p-8"><Spinner label="Initializing Domain Workspace" /></div>

  const handleExecute = async (input: unknown): Promise<RunRecord> => {
    return await send<RunRecord>('POST', `/api/domains/${detail.id}/run`, { input })
  }

  return (
    <DynamicWorkspace
      key={detail.id}
      domain={detail}
      allDomains={domains}
      onSelectDomain={setActiveDomain}
      identityRole={identity.role}
      onExecutePipeline={handleExecute}
      onNavigate={(sec, param) => navigate(sec as any, param)}
      initialRun={initialRun}
    />
  )
}

import { useState } from 'react'

import { Tabs } from '../components/ui'
import { AuditVerificationPage } from '../crowdguard/pages/AuditVerification'
import { AuditPage } from './Audit'

/** Audit & Verification: capability/incident verification and the hash-chained audit log in one place. */
export function GovernanceAuditPage() {
  const [tab, setTab] = useState<'verify' | 'log'>('verify')
  return (
    <div className="space-y-4">
      <Tabs value={tab} onChange={setTab} options={[{ id: 'verify', label: 'Verification' }, { id: 'log', label: 'Audit log & executions' }]} />
      {tab === 'verify' ? <AuditVerificationPage /> : <AuditPage />}
    </div>
  )
}

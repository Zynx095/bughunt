import { Radio } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { DomainBadgeIcon } from '../components/domainIcon'
import { DataTable } from '../components/table'
import { Badge, Button, Card, ErrorBox, PageHeader, Spinner, WarnBox } from '../components/ui'
import { cx } from '../lib/cx'
import { useApp } from '../context'
import { callEngine } from '../lib/api'
import { useApi } from '../lib/hooks'
import type { EngineResponse, Role, SettingsView } from '../lib/types'

const ROLES: { id: Role; text: string }[] = [
  { id: 'viewer', text: 'Read-only compute' },
  { id: 'analyst', text: 'Run pipelines, upload, sign manifests' },
  { id: 'reviewer', text: 'Analyst + decide approvals, decrypt' },
  { id: 'admin', text: 'Everything' },
]

interface ProviderStatus { name: string; model: string | null; configured: boolean; verified: boolean; last_error: string | null }

export function SettingsPage() {
  const { domains, active, setActiveDomain, identity, setIdentity } = useApp()
  const settings = useApi<SettingsView>('/api/settings', [active?.id])
  type ProvResult = { active: string; preference: string; providers: ProviderStatus[] }
  const [prov, setProv] = useState<EngineResponse<ProvResult> | null>(null)
  const [ping, setPing] = useState<EngineResponse | null>(null)
  const [pinging, setPinging] = useState(false)
  const [policy, setPolicy] = useState<EngineResponse<{ roles: Record<string, string[]> }> | null>(null)
  const [actor, setActor] = useState(identity.actor)

  const loadProviders = useCallback(() => callEngine<ProvResult>('ai', 'providers', {}).then(setProv).catch(() => undefined), [])
  useEffect(() => {
    void loadProviders()
    void callEngine<{ roles: Record<string, string[]> }>('security', 'policy', {}).then(setPolicy).catch(() => undefined)
  }, [loadProviders])

  const cfg = settings.data?.config ?? {}

  return (
    <div className="space-y-5">
      <PageHeader title="Settings" description="Domain selection drives which engines, sections and pipeline are active. Credentials are read by the backend from environment variables and are never sent to the browser." />

      <Card title="Active domain" subtitle="Switching changes the workspace pipeline and the visible sections">
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {domains.map((d) => (
            <button key={d.id} onClick={() => void setActiveDomain(d.id)}
              className={cx('flex items-center gap-3 rounded-lg border p-2.5 text-left text-sm transition hover:bg-surface-2',
                d.id === active?.id ? 'border-[var(--accent)] ring-1 ring-[var(--accent)]' : 'border-line')}>
              <DomainBadgeIcon name={d.icon} color={d.color} size="sm" />
              <span className="min-w-0 flex-1 truncate">{d.name}</span>
              {d.id === active?.id && <Badge tone="accent">active</Badge>}
            </button>
          ))}
        </div>
        {settings.data && <p className="mt-3 text-xs text-muted">Visible sections: {settings.data.sections.join(' · ')}</p>}
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card title="Identity (simulated)" subtitle="Sent as request headers; the backend enforces the policy for the declared role">
          <WarnBox>There is no authentication in the foundation build. Put a real identity provider (OIDC/JWT) in front of the API before any deployment.</WarnBox>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {ROLES.map((r) => (
              <button key={r.id} onClick={() => setIdentity({ role: r.id, actor: actor || `demo-${r.id}` })}
                className={cx('rounded-lg border p-2.5 text-left transition hover:bg-surface-2', identity.role === r.id ? 'border-[var(--accent)] ring-1 ring-[var(--accent)]' : 'border-line')}>
                <p className="text-sm font-medium capitalize">{r.id}</p>
                <p className="text-xs text-muted">{r.text}</p>
              </button>
            ))}
          </div>
          <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (/^[A-Za-z0-9_.@-]{1,64}$/.test(actor)) setIdentity({ ...identity, actor }) }}>
            <input value={actor} onChange={(e) => setActor(e.target.value)} aria-label="Actor name"
              className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-[var(--accent)]" />
            <Button type="submit">Set actor name</Button>
          </form>
          <p className="mt-2 text-xs text-muted">Tip: approve requests as a different actor than the one who ran the pipeline — self-approval is blocked.</p>
        </Card>

        <Card title="AI providers" subtitle={`Preference: ${prov?.result.preference ?? '…'} · active: ${prov?.result.active ?? '…'}`}
          actions={<Button size="sm" busy={pinging} disabled={prov?.result.active === 'local-fallback'} onClick={async () => { setPinging(true); try { setPing(await callEngine('ai', 'ping', {})) } finally { setPinging(false); void loadProviders() } }}>
            <Radio className="size-3.5" aria-hidden />Test live call</Button>}>
          {!prov && <Spinner />}
          {prov && (
            <div className="space-y-2">
              {prov.result.providers.map((p) => (
                <div key={p.name} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line px-3 py-2 text-sm">
                  <span className="font-medium">{p.name}<span className="ml-2 font-mono text-xs text-muted">{p.model ?? 'no model set'}</span></span>
                  <span className="flex gap-1.5">
                    <Badge tone={p.configured ? 'good' : 'neutral'}>{p.configured ? 'configured' : 'not configured'}</Badge>
                    {p.configured && <Badge tone={p.verified ? 'good' : 'warn'}>{p.verified ? 'verified by a live call' : 'not yet verified'}</Badge>}
                  </span>
                  {p.last_error && <p className="w-full text-xs text-critical-ink">{p.last_error}</p>}
                </div>
              ))}
              {prov.result.active === 'local-fallback' && (
                <p className="text-xs text-ink-2">No LLM key found. AI steps use deterministic local methods (extractive summaries, templates, rule-based rewriting) and are labelled “local fallback”. Set <span className="font-mono">GEMINI_API_KEY</span> (or <span className="font-mono">OPENAI_API_KEY</span> + <span className="font-mono">OPENAI_MODEL</span>) in <span className="font-mono">.env</span> and restart the backend.</p>
              )}
              {ping && (ping.success
                ? <p className="text-xs text-good-ink">Live call OK: {String((ping.result as Record<string, unknown>).provider)} replied “{String((ping.result as Record<string, unknown>).reply)}” in {String((ping.result as Record<string, unknown>).latency_ms)} ms</p>
                : <ErrorBox>{ping.error?.message}</ErrorBox>)}
            </div>
          )}
        </Card>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card title="Access policy" subtitle="Deterministic RBAC evaluated before every operation; AI-originated actors are capped at read">
          {policy ? (
            <DataTable columns={[{ key: 'role', label: 'Role' }, { key: 'perms', label: 'Permissions' }]}
              rows={Object.entries(policy.result.roles).map(([role, perms]) => ({ role, perms: perms.join(', ') }))} />
          ) : <Spinner />}
        </Card>
        <Card title="Runtime configuration" subtitle="Non-secret values only">
          {settings.loading && <Spinner />}
          <DataTable columns={[{ key: 'k', label: 'Setting' }, { key: 'v', label: 'Value' }]}
            rows={Object.entries(cfg).map(([k, v]) => ({ k: k.replace(/_/g, ' '), v: v === null ? '—' : String(v) }))} />
        </Card>
      </div>
    </div>
  )
}

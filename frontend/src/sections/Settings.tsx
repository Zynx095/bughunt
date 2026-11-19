import {
  Moon,
  Radio,
  Sun,
  Tv,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTheme } from '../lib/theme'

import { DomainBadgeIcon } from '../components/domainIcon'
import { DataTable } from '../components/table'
import { Badge, Button, Card, ErrorBox, PageHeader, Spinner, WarnBox } from '../components/ui'
import { useApp } from '../context'
import { callEngine } from '../lib/api'
import { cx } from '../lib/cx'
import { fmtMs } from '../lib/format'
import { useApi } from '../lib/hooks'
import type { EngineResponse, Role, SettingsView } from '../lib/types'

const ROLES: { id: Role; title: string; text: string }[] = [
  { id: 'viewer', title: 'Viewer', text: 'Read-only telemetry and dashboard inspection' },
  { id: 'analyst', title: 'Analyst', text: 'Run pipelines, ingest data, sign manifests' },
  { id: 'reviewer', title: 'Reviewer', text: 'Analyst rights + decide approval holds & decrypt PHI' },
  { id: 'admin', title: 'Administrator', text: 'Complete administrative & configuration access' },
]

interface ProviderStatus {
  name: string
  model: string | null
  configured: boolean
  verified: boolean
  last_error: string | null
}

export function SettingsPage() {
  const { domains, active, setActiveDomain, identity, setIdentity } = useApp()
  const { preference: theme, setPreference: setTheme, resolved } = useTheme()
  const settings = useApi<SettingsView>('/api/settings', [active?.id])

  type ProvResult = { active: string; preference: string; providers: ProviderStatus[] }
  const [prov, setProv] = useState<EngineResponse<ProvResult> | null>(null)
  const [ping, setPing] = useState<EngineResponse | null>(null)
  const [pinging, setPinging] = useState(false)
  const [policy, setPolicy] = useState<EngineResponse<{ roles: Record<string, string[]> }> | null>(null)
  const [actor, setActor] = useState(identity.actor)

  const loadProviders = useCallback(
    () => callEngine<ProvResult>('ai', 'providers', {}).then(setProv).catch(() => undefined),
    []
  )

  useEffect(() => {
    void loadProviders()
    void callEngine<{ roles: Record<string, string[]> }>('security', 'policy', {})
      .then(setPolicy)
      .catch(() => undefined)
  }, [loadProviders])

  const cfg = settings.data?.config ?? {}

  return (
    <div className="space-y-6">
      <PageHeader
        title="Platform Settings & Governance"
        description="Configure runtime domain adapters, simulated RBAC identities, appearance modes, and AI engine telemetry. Secrets and credentials remain secured on the backend and are never sent to the client."
      />

      {/* Theme & Appearance */}
      <Card title="Appearance" subtitle={`Saved in this browser. Currently showing the ${resolved} theme; switches animate unless reduced motion is requested.`}>
        <div className="grid gap-3 sm:grid-cols-3 max-w-xl">
          <button
            type="button"
            onClick={() => setTheme('dark')}
            className={cx(
              'flex items-center gap-3 rounded-xl border p-3 text-left transition',
              theme === 'dark'
                ? 'border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)] font-semibold'
                : 'border-line bg-surface hover:bg-surface-2'
            )}
          >
            <Moon className="size-5 text-[var(--accent)]" />
            <div>
              <p className="text-xs font-semibold text-ink">Dark Mode</p>
              <p className="text-[11px] text-muted">Charcoal-navy for control rooms</p>
            </div>
          </button>

          <button
            type="button"
            onClick={() => setTheme('light')}
            className={cx(
              'flex items-center gap-3 rounded-xl border p-3 text-left transition',
              theme === 'light'
                ? 'border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)] font-semibold'
                : 'border-line bg-surface hover:bg-surface-2'
            )}
          >
            <Sun className="size-5 text-warn" />
            <div>
              <p className="text-xs font-semibold text-ink">Light Mode</p>
              <p className="text-[11px] text-muted">Ivory neutrals, crisp ink</p>
            </div>
          </button>

          <button
            type="button"
            onClick={() => setTheme('system')}
            className={cx(
              'flex items-center gap-3 rounded-xl border p-3 text-left transition',
              theme === 'system'
                ? 'border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)] font-semibold'
                : 'border-line bg-surface hover:bg-surface-2'
            )}
          >
            <Tv className="size-5 text-muted" />
            <div>
              <p className="text-xs font-semibold text-ink">System</p>
              <p className="text-[11px] text-muted">Follow OS preferences</p>
            </div>
          </button>
        </div>
      </Card>

      {/* Active Domain Selector */}
      <Card
        title="Active Domain Adapter"
        subtitle="Selects the pipeline, input schema and sample data used by the Domain Workspace and Run History"
      >
        <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
          {domains.map((d) => {
            const isActive = d.id === active?.id
            return (
              <button
                key={d.id}
                type="button"
                onClick={() => void setActiveDomain(d.id)}
                className={cx(
                  'flex items-center gap-3 rounded-xl border p-3 text-left text-xs transition',
                  isActive
                    ? 'border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)] font-semibold text-ink'
                    : 'border-line bg-surface hover:bg-surface-2 text-ink-2'
                )}
              >
                <DomainBadgeIcon name={d.icon} color={d.color} size="sm" />
                <span className="min-w-0 flex-1 truncate font-medium">{d.name}</span>
                {isActive && <Badge tone="accent">Active</Badge>}
              </button>
            )
          })}
        </div>
        {settings.data && (
          <p className="mt-3 text-xs text-muted">
            Enabled Navigation Sections:{' '}
            <span className="font-mono text-ink-2">{settings.data.sections.join(' · ')}</span>
          </p>
        )}
      </Card>

      {/* Identity & Simulated RBAC */}
      <div className="grid gap-6 xl:grid-cols-2">
        <Card
          title="Simulated Identity (RBAC Policy)"
          subtitle="Declared via headers in the foundation build; the FastAPI backend strictly enforces permissions"
        >
          <WarnBox>
            Authentication is simulated for rapid prototyping. Real enterprise deployments should place an
            OIDC / OAuth2 token exchange gateway in front of the API.
          </WarnBox>

          <div className="mt-4 grid gap-2.5 sm:grid-cols-2">
            {ROLES.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => setIdentity({ role: r.id, actor: actor || `demo-${r.id}` })}
                className={cx(
                  'rounded-xl border p-3 text-left transition',
                  identity.role === r.id
                    ? 'border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)]'
                    : 'border-line bg-surface hover:bg-surface-2'
                )}
              >
                <p className="text-xs font-semibold text-ink">{r.title}</p>
                <p className="text-[11px] text-muted mt-0.5 leading-snug">{r.text}</p>
              </button>
            ))}
          </div>

          <form
            className="mt-4 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (/^[A-Za-z0-9_.@-]{1,64}$/.test(actor)) {
                setIdentity({ ...identity, actor })
              }
            }}
          >
            <input
              type="text"
              value={actor}
              onChange={(e) => setActor(e.target.value)}
              aria-label="Actor Identity"
              placeholder="Actor name (e.g. analyst-1)"
              className="h-9 min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 text-xs text-ink outline-none focus:border-[var(--accent)]"
            />
            <Button type="submit">Update Actor</Button>
          </form>
          <p className="mt-2 text-[11px] text-muted">
            Tip: To test approval queues, switch actors after submitting a transaction—the policy engine blocks self-approval.
          </p>
        </Card>

        {/* AI Engine & Providers */}
        <Card
          title="AI Inference Providers"
          subtitle={`Active Provider: ${prov?.result.active ?? '…'} · User Preference: ${prov?.result.preference ?? '…'}`}
          actions={
            <Button
              size="sm"
              busy={pinging}
              disabled={prov?.result.active === 'local-fallback'}
              onClick={async () => {
                setPinging(true)
                try {
                  setPing(await callEngine('ai', 'ping', {}))
                } finally {
                  setPinging(false)
                  void loadProviders()
                }
              }}
            >
              <Radio className="size-3.5" aria-hidden /> Test Live LLM Call
            </Button>
          }
        >
          {!prov && <Spinner label="Probing AI Provider Mesh" />}
          {prov && (
            <div className="space-y-3">
              <div className="space-y-2">
                {prov.result.providers.map((p) => (
                  <div
                    key={p.name}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-surface p-3 text-xs"
                  >
                    <div>
                      <span className="font-semibold text-ink">{p.name}</span>
                      <span className="ml-2 font-mono text-[11px] text-muted">
                        {p.model ?? 'no model set'}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Badge tone={p.configured ? 'good' : 'neutral'}>
                        {p.configured ? 'Configured' : 'Not Configured'}
                      </Badge>
                      {p.configured && (
                        <Badge tone={p.verified ? 'good' : 'warn'}>
                          {p.verified ? 'Verified' : 'Pending Verification'}
                        </Badge>
                      )}
                    </div>
                    {p.last_error && (
                      <p className="w-full text-xs text-critical-ink mt-1">{p.last_error}</p>
                    )}
                  </div>
                ))}
              </div>

              {prov.result.active === 'local-fallback' && (
                <div className="rounded-lg bg-surface-2 p-3 text-xs text-ink-2 border border-line">
                  <p className="font-semibold text-ink mb-1">Local Deterministic Fallback Active</p>
                  No external LLM credentials were detected in the backend environment. All pipeline AI steps
                  automatically execute via deterministic local algorithms (frequency-based extractive summarization,
                  pattern-based rule generation, template explanations) marked as &quot;local fallback&quot;. To activate live
                  generative inference, set <code className="font-mono text-ink">GEMINI_API_KEY</code> in <code className="font-mono text-ink">.env</code>.
                </div>
              )}

              {ping && (
                <div className="mt-2">
                  {ping.success ? (
                    <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-700 dark:text-emerald-400">
                      Live Call Succeeded: {String((ping.result as Record<string, unknown>).provider)} responded in{' '}
                      {fmtMs(Number((ping.result as Record<string, unknown>).latency_ms))}: &quot;
                      {String((ping.result as Record<string, unknown>).reply)}&quot;
                    </div>
                  ) : (
                    <ErrorBox>{ping.error?.message}</ErrorBox>
                  )}
                </div>
              )}
            </div>
          )}
        </Card>
      </div>

      {/* Security Policies & Runtime Config */}
      <div className="grid gap-6 xl:grid-cols-2">
        <Card
          title="Access Control Matrix (RBAC)"
          subtitle="Deterministic permissions evaluated before every engine execution"
        >
          {policy ? (
            <DataTable
              columns={[
                { key: 'role', label: 'Role' },
                { key: 'perms', label: 'Granted Permissions' },
              ]}
              rows={Object.entries(policy.result.roles).map(([r, perms]) => ({
                role: r,
                perms: perms.join(', '),
              }))}
            />
          ) : (
            <Spinner />
          )}
        </Card>

        <Card
          title="Runtime Environment Configuration"
          subtitle="Non-secret platform parameters"
        >
          {settings.loading && <Spinner />}
          <DataTable
            columns={[
              { key: 'k', label: 'Parameter' },
              { key: 'v', label: 'Configured Value' },
            ]}
            rows={Object.entries(cfg).map(([k, v]) => ({
              k: k.replace(/_/g, ' '),
              v: v === null ? '—' : String(v),
            }))}
          />
        </Card>
      </div>
    </div>
  )
}

import { Braces, Play, RotateCcw, Target } from 'lucide-react'
import { useEffect, useState } from 'react'

import { DomainBadgeIcon } from '../components/domainIcon'
import { PresentationView, StepList, StepOutputs } from '../components/presentation'
import { Badge, Button, Card, Disclosure, ErrorBox, Spinner, StatusBadge } from '../components/ui'
import { useApp } from '../context'
import { ApiError, get, send } from '../lib/api'
import { fmtMs, fmtTime } from '../lib/format'
import { useApi } from '../lib/hooks'
import type { DomainInfo, RunRecord } from '../lib/types'

export function WorkspacePage() {
  const { active, domains, setActiveDomain, identity, navigate } = useApp()
  const { data: detail, error } = useApi<DomainInfo>(active ? `/api/domains/${active.id}` : null)
  const [edited, setText] = useState<string | null>(null)
  const [parseError, setParseError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [run, setRun] = useState<RunRecord | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [isLatest, setIsLatest] = useState(false)

  // Show the most recent persisted run for this domain (real stored data, not a placeholder).
  useEffect(() => {
    if (!active) return
    let cancelled = false
    get<RunRecord[]>(`/api/runs?domain=${active.id}&limit=1`)
      .then((list) => (list[0] ? get<RunRecord>(`/api/runs/${list[0].id}`) : null))
      .then((latest) => { if (!cancelled && latest) { setRun((cur) => cur ?? latest); setIsLatest(true) } })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [active])

  const sample = detail?.sample_input
  const text = edited ?? (sample ? JSON.stringify(sample, null, 2) : '')

  if (!active) return null
  const d = detail ?? active

  async function execute() {
    let input: unknown
    try {
      input = JSON.parse(text)
      setParseError(null)
    } catch (e) {
      setParseError(`Input is not valid JSON: ${(e as Error).message}`)
      return
    }
    setRunning(true)
    setRunError(null)
    try {
      setRun(await send<RunRecord>('POST', `/api/domains/${d.id}/run`, { input }))
      setIsLatest(false)
    } catch (e) {
      setRun(null)
      setRunError(e instanceof ApiError && e.status === 403 ? `${e.message} — switch role in Settings.` : (e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <DomainBadgeIcon name={d.icon} color={d.color} size="lg" />
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wide text-muted">{d.name}</p>
            <h1 className="text-xl font-semibold tracking-tight text-ink">{d.scenario}</h1>
            <p className="mt-1 max-w-3xl text-sm text-ink-2">{d.tagline}</p>
          </div>
        </div>
        <label className="flex items-center gap-2 text-xs text-muted">
          Domain
          <select value={d.id} onChange={(e) => void setActiveDomain(e.target.value)}
            className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink">
            {domains.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        </label>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <div className="space-y-4">
          <Card title="Pipeline" subtitle={`${d.steps.length} steps · engines: ${d.engines.join(', ')}`}>
            <StepList steps={d.steps} run={run} running={running} />
          </Card>
          <Card title="How it works">
            <p className="text-sm leading-relaxed text-ink-2">{d.description}</p>
            {d.impact && <p className="mt-3 flex items-start gap-2 text-sm text-ink"><Target className="mt-0.5 size-4 shrink-0 text-[var(--accent)]" aria-hidden />{d.impact}</p>}
          </Card>
        </div>

        <div className="min-w-0 space-y-4">
          <Card title="Scenario input" subtitle="Pre-filled with the bundled synthetic sample. Edit the JSON to try your own data; it is validated server-side."
            actions={
              <>
                <Button size="sm" variant="ghost" onClick={() => { try { setText(JSON.stringify(JSON.parse(text), null, 2)); setParseError(null) } catch (e) { setParseError((e as Error).message) } }}>
                  <Braces className="size-3.5" aria-hidden />Format
                </Button>
                <Button size="sm" variant="ghost" disabled={!sample} onClick={() => setText(null)}>
                  <RotateCcw className="size-3.5" aria-hidden />Reset sample
                </Button>
                <Button variant="primary" busy={running} disabled={!text} onClick={() => void execute()}>
                  <Play className="size-4" aria-hidden />Run pipeline
                </Button>
              </>
            }>
            {error && <ErrorBox>{error}</ErrorBox>}
            {!detail && !error && <Spinner label="Loading sample" />}
            {detail && (
              <Disclosure summary={<span className="text-xs text-ink-2">Input JSON <span className="text-muted">({(text.length / 1024).toFixed(1)} KB) · running as <b>{identity.role}</b></span></span>}>
                <textarea value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} aria-label="Scenario input JSON"
                  className="h-80 w-full resize-y rounded-lg border border-line bg-surface-2 p-3 font-mono text-[11.5px] leading-relaxed text-ink outline-none focus:border-[var(--accent)]" />
              </Disclosure>
            )}
            {parseError && <div className="mt-3"><ErrorBox>{parseError}</ErrorBox></div>}
            {runError && <div className="mt-3"><ErrorBox>{runError}</ErrorBox></div>}
          </Card>

          {running && <Card><Spinner label="Running pipeline through the engine registry" /></Card>}
          {run && !running && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                <StatusBadge status={run.status} />
                {isLatest && <span className="font-medium text-ink-2">Previous run from {fmtTime(run.created_at)} —</span>}
                <span>run <span className="font-mono">{run.id}</span></span>
                <span>· {fmtMs(run.duration_ms)}</span>
                <span>· as {run.actor} ({run.role})</span>
                <Button size="sm" variant="ghost" onClick={() => navigate('runs', run.id)}>Open in runs</Button>
                {run.steps.some((s) => s.metadata?.fallback) && <Badge tone="neutral">some steps used the local (non-LLM) fallback</Badge>}
              </div>
              {run.status === 'failed' && <ErrorBox>{run.error}</ErrorBox>}
              {run.presentation && <PresentationView p={run.presentation} />}
              <Disclosure summary={<span className="text-sm font-medium">Step-by-step engine outputs <span className="font-normal text-muted">(raw envelopes)</span></span>}>
                <StepOutputs run={run} />
              </Disclosure>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

import {
  Braces,
  BrainCircuit,
  Cpu,
  Play,
  RotateCcw,
  Target,
} from 'lucide-react'
import { useMemo, useState } from 'react'

import { getDomainMeta } from '../lib/domainConfig'
import type { DomainInfo, RunRecord } from '../lib/types'
import { DomainBadgeIcon } from './domainIcon'
import { ExecutionPanel } from './ExecutionPanel'
import { JSONInspector } from './JSONInspector'
import { StepList } from './presentation'
import { Badge, Button, Card, Disclosure, ErrorBox, Tabs } from './ui'

interface DynamicWorkspaceProps {
  domain: DomainInfo
  allDomains: DomainInfo[]
  onSelectDomain: (domainId: string) => Promise<void>
  identityRole: string
  onExecutePipeline: (input: unknown) => Promise<RunRecord>
  onNavigate: (section: string, param?: string) => void
  initialRun?: RunRecord | null
}

export function DynamicWorkspace({
  domain,
  allDomains,
  onSelectDomain,
  identityRole,
  onExecutePipeline,
  onNavigate,
  initialRun = null,
}: DynamicWorkspaceProps) {
  const [activeTab, setActiveTab] = useState<'console' | 'studio' | 'insights' | 'anatomy'>('console')
  const [text, setText] = useState<string>(
    domain.sample_input ? JSON.stringify(domain.sample_input, null, 2) : ''
  )
  const [parseError, setParseError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [run, setRun] = useState<RunRecord | null>(initialRun)
  const [runError, setRunError] = useState<string | null>(null)
  const [isLatest, setIsLatest] = useState(Boolean(initialRun))

  // Text initializes with domain sample input on mount (keyed by domain.id in caller)

  const meta = useMemo(() => getDomainMeta(domain.id, domain.name, domain.color), [domain])

  const formatJson = () => {
    try {
      setText(JSON.stringify(JSON.parse(text), null, 2))
      setParseError(null)
    } catch (e) {
      setParseError((e as Error).message)
    }
  }

  const resetSample = () => {
    if (domain.sample_input) {
      setText(JSON.stringify(domain.sample_input, null, 2))
      setParseError(null)
    }
  }

  const handleRun = async () => {
    let parsedInput: unknown
    try {
      parsedInput = JSON.parse(text)
      setParseError(null)
    } catch (e) {
      setParseError(`Input is not valid JSON: ${(e as Error).message}`)
      return
    }

    setRunning(true)
    setRunError(null)
    try {
      const result = await onExecutePipeline(parsedInput)
      setRun(result)
      setIsLatest(false)
      setActiveTab('console')
    } catch (e) {
      setRun(null)
      const msg = (e as Error).message
      setRunError(msg.includes('403') ? `${msg} — switch role in Settings.` : msg)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="space-y-5">
      {/* Top Domain Operational Header */}
      <div className="rounded-xl border border-line bg-surface p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-4">
            <DomainBadgeIcon name={domain.icon} color={domain.color} size="lg" />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-muted">
                  {meta.category} Domain Adapter
                </span>
                <span className="font-mono text-[10px] text-muted">ID: {domain.id}</span>
              </div>
              <h1 className="text-xl font-bold tracking-tight text-ink sm:text-2xl">
                {domain.scenario}
              </h1>
              <p className="mt-1 max-w-3xl text-sm text-ink-2">{domain.tagline}</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <label className="flex items-center gap-2 text-xs font-medium text-muted">
              <span>Switch:</span>
              <select
                value={domain.id}
                onChange={(e) => void onSelectDomain(e.target.value)}
                className="h-8 rounded-lg border border-line bg-surface px-2.5 text-xs font-medium text-ink outline-none focus:border-[var(--accent)]"
              >
                {allDomains.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        {/* Impact Bar */}
        {domain.impact && (
          <div className="mt-4 flex items-center gap-2 rounded-lg bg-[var(--accent)]/[0.07] border border-[var(--accent)]/20 px-3 py-2 text-xs text-ink">
            <Target className="size-4 shrink-0 text-[var(--accent)]" aria-hidden />
            <span className="font-medium text-muted">Operational Objective:</span>
            <span className="font-semibold text-ink">{domain.impact}</span>
          </div>
        )}

        {/* Tab Navigation */}
        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-line/60 pt-3">
          <Tabs
            value={activeTab}
            onChange={setActiveTab}
            options={[
              { id: 'console', label: 'Execution & Verdict' },
              { id: 'studio', label: 'Input Scenario Studio' },
              { id: 'insights', label: 'Domain Intelligence' },
              { id: 'anatomy', label: 'Pipeline Architecture' },
            ]}
          />

          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              busy={running}
              disabled={!text}
              onClick={() => void handleRun()}
            >
              <Play className="size-3.5" aria-hidden /> Run {domain.name} Pipeline
            </Button>
          </div>
        </div>
      </div>

      {/* Main Tab Panels */}
      {activeTab === 'console' && (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
          {/* Left: Pipeline step overview & quick actions */}
          <div className="space-y-4">
            <Card
              title="Execution Pipeline"
              subtitle={`${domain.steps.length} sequential steps · engines: ${domain.engines.join(', ')}`}
            >
              <StepList steps={domain.steps} run={run} running={running} />
            </Card>

            <Card title="How It Operates">
              <p className="text-xs leading-relaxed text-ink-2">{domain.description}</p>
              <div className="mt-3 border-t border-line/60 pt-3 space-y-1.5 text-xs">
                <span className="font-medium text-ink">Active Engines:</span>
                <div className="flex flex-wrap gap-1">
                  {domain.engines.map((e) => (
                    <Badge key={e} tone="neutral">
                      {e}
                    </Badge>
                  ))}
                </div>
              </div>
            </Card>
          </div>

          {/* Right: Results renderer & execution panel */}
          <div className="min-w-0">
            <ExecutionPanel
              domain={domain}
              run={run}
              running={running}
              isLatest={isLatest}
              runError={runError}
              onExecute={handleRun}
              onNavigateToRuns={(runId) => onNavigate('runs', runId)}
            />
            {!run && !running && (
              <div className="rounded-xl border border-dashed border-line p-10 text-center">
                <BrainCircuit className="mx-auto size-10 text-muted" />
                <h3 className="mt-3 text-sm font-semibold text-ink">No execution in session</h3>
                <p className="mt-1 text-xs text-muted max-w-sm mx-auto">
                  Click &quot;Run Pipeline&quot; above to process the scenario input through the{' '}
                  {domain.name} engine sequence.
                </p>
                <div className="mt-4">
                  <Button variant="primary" onClick={() => void handleRun()}>
                    <Play className="size-3.5" /> Execute Pipeline Now
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {activeTab === 'studio' && (
        <div className="space-y-4">
          <Card
            title="Scenario Input Studio"
            subtitle="Validated server-side against the domain's declared Pydantic schema before execution"
            actions={
              <div className="flex items-center gap-2">
                <Button size="sm" variant="ghost" onClick={formatJson}>
                  <Braces className="size-3" /> Format JSON
                </Button>
                <Button size="sm" variant="ghost" onClick={resetSample}>
                  <RotateCcw className="size-3" /> Reset Sample
                </Button>
                <Button variant="primary" busy={running} onClick={() => void handleRun()}>
                  <Play className="size-3.5" /> Run Scenario
                </Button>
              </div>
            }
          >
            {parseError && <div className="mb-3"><ErrorBox>{parseError}</ErrorBox></div>}
            <div className="rounded-lg border border-line bg-surface-2 overflow-hidden">
              <div className="flex items-center justify-between border-b border-line px-3 py-2 text-xs text-muted">
                <span className="font-mono">input.json</span>
                <span>{(text.length / 1024).toFixed(1)} KB · running as role: <strong className="text-ink">{identityRole}</strong></span>
              </div>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                spellCheck={false}
                aria-label="Scenario Input JSON"
                rows={16}
                className="w-full resize-y bg-transparent p-3 font-mono text-xs leading-relaxed text-ink outline-none"
              />
            </div>

            {domain.input_schema && (
              <div className="mt-4">
                <Disclosure summary={<span className="text-xs font-semibold text-ink">View Input Schema (Pydantic / JSON Schema)</span>}>
                  <JSONInspector title="Declared Schema" value={domain.input_schema} defaultExpandDepth={2} />
                </Disclosure>
              </div>
            )}
          </Card>
        </div>
      )}

      {activeTab === 'insights' && (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {meta.engineRoles.map((er) => (
              <div key={er.engine} className="rounded-xl border border-line bg-surface p-4">
                <div className="flex items-center gap-2">
                  <Cpu className="size-4 text-[var(--accent)]" />
                  <h4 className="text-xs font-bold uppercase tracking-wider text-ink">
                    {er.engine} engine
                  </h4>
                </div>
                <p className="mt-2 text-xs text-ink-2 leading-relaxed">{er.role}</p>
              </div>
            ))}
          </div>

          <Card title="Domain Telemetry & Capabilities" subtitle="Engine orchestration characteristics">
            <div className="space-y-2 text-xs">
              <div className="flex justify-between py-1 border-b border-line/60">
                <span className="text-muted">Primary Engine</span>
                <span className="font-mono font-medium text-ink">{meta.primaryEngine}</span>
              </div>
              <div className="flex justify-between py-1 border-b border-line/60">
                <span className="text-muted">Pipeline Length</span>
                <span className="font-mono font-medium text-ink">{domain.steps.length} steps</span>
              </div>
              <div className="flex justify-between py-1 border-b border-line/60">
                <span className="text-muted">Access Policy Permission</span>
                <span className="font-mono font-medium text-ink">pipeline:run</span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-muted">Available Telemetry Metrics</span>
                <span className="font-medium text-ink">{meta.keyMetrics.join(' · ')}</span>
              </div>
            </div>
          </Card>
        </div>
      )}

      {activeTab === 'anatomy' && (
        <Card title="Pipeline Execution Anatomy" subtitle="Step-by-step engine calls and rationale">
          <div className="space-y-3">
            {domain.steps.map((s, idx) => (
              <div
                key={s.id}
                className="flex items-start gap-3 rounded-lg border border-line p-3.5 bg-surface-2/40"
              >
                <div className="flex size-6 shrink-0 items-center justify-center rounded-full bg-[var(--accent)]/10 text-xs font-bold text-[var(--accent)]">
                  {idx + 1}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h4 className="text-sm font-semibold text-ink">
                      {s.title}
                      {s.optional && (
                        <span className="ml-2 font-mono text-[10px] text-muted font-normal">
                          (optional)
                        </span>
                      )}
                    </h4>
                    <span className="font-mono text-xs text-[var(--accent)]">
                      {s.engine}.{s.operation}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-ink-2">{s.why}</p>
                  <div className="mt-2 flex items-center gap-2 text-[11px] text-muted">
                    {s.foreach && <Badge tone="info">Invoked per item</Badge>}
                    <span className="font-mono text-[10px]">ID: {s.id}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

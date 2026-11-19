import { Clock, Cpu, ExternalLink, User } from 'lucide-react'
import { useState } from 'react'

import { fmtMs, fmtTime } from '../lib/format'
import type { DomainInfo, RunRecord } from '../lib/types'
import { JSONInspector } from './JSONInspector'
import { StepList, StepOutputs } from './presentation'
import { ResultsRenderer } from './ResultsRenderer'
import { Badge, Card, Disclosure, ErrorBox, Spinner, StatusBadge, Tabs } from './ui'

interface ExecutionPanelProps {
  domain: DomainInfo
  run: RunRecord | null
  running: boolean
  isLatest?: boolean
  runError: string | null
  onExecute?: () => void
  onNavigateToRuns: (runId: string) => void
}

export function ExecutionPanel({
  domain,
  run,
  running,
  isLatest = false,
  runError,
  onExecute: _onExecute,
  onNavigateToRuns,
}: ExecutionPanelProps) {
  const [activeTab, setActiveTab] = useState<'verdict' | 'steps' | 'raw'>('verdict')

  return (
    <div className="space-y-4">
      {/* Execution status banner when running or completed */}
      {running && (
        <div className="flex items-center gap-3 rounded-xl border border-[var(--accent)]/40 bg-[var(--accent)]/[0.05] p-4 text-sm">
          <Spinner label={`Executing ${domain.name} pipeline through engine registry`} />
        </div>
      )}

      {runError && <ErrorBox>{runError}</ErrorBox>}

      {run && !running && (
        <div className="space-y-4">
          {/* Metadata Bar */}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface p-3 text-xs shadow-sm">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={run.status} />
              {isLatest && (
                <span className="font-semibold text-ink-2">
                  Persisted Run ({fmtTime(run.created_at)})
                </span>
              )}
              <span className="font-mono text-muted">ID: {run.id}</span>
              <span className="text-muted">·</span>
              <span className="tabular font-medium text-ink flex items-center gap-1">
                <Clock className="size-3 text-muted" /> {fmtMs(run.duration_ms)}
              </span>
              <span className="text-muted">·</span>
              <span className="text-ink-2 flex items-center gap-1">
                <User className="size-3 text-muted" /> {run.actor} ({run.role})
              </span>
            </div>

            <div className="flex items-center gap-2">
              {run.steps.some((s) => s.metadata?.fallback) && (
                <Badge tone="neutral" title="Deterministic local engine fallback used">
                  <Cpu className="size-3" aria-hidden /> local fallback
                </Badge>
              )}
              <button
                type="button"
                onClick={() => onNavigateToRuns(run.id)}
                className="inline-flex items-center gap-1 font-medium text-[var(--accent)] hover:underline"
              >
                <span>Full run history</span>
                <ExternalLink className="size-3" aria-hidden />
              </button>
            </div>
          </div>

          {/* Navigation Tabs for Execution Output */}
          <div className="flex items-center justify-between border-b border-line pb-2">
            <Tabs
              value={activeTab}
              onChange={setActiveTab}
              options={[
                { id: 'verdict', label: 'Structured Verdict' },
                { id: 'steps', label: `Pipeline Steps (${run.steps.length})` },
                { id: 'raw', label: 'Engine Envelopes' },
              ]}
            />
          </div>

          {/* Tab Content */}
          {activeTab === 'verdict' && (
            <>
              {run.presentation ? (
                <ResultsRenderer
                  presentation={run.presentation}
                  runId={run.id}
                  domainId={run.domain}
                />
              ) : (
                <Card>
                  <p className="text-sm text-muted">No visual presentation payload for this execution.</p>
                </Card>
              )}
            </>
          )}

          {activeTab === 'steps' && (
            <Card title="Step-by-Step Telemetry" subtitle="Declared pipeline stages mapped to genuine execution responses">
              <StepList steps={domain.steps} run={run} running={running} />
            </Card>
          )}

          {activeTab === 'raw' && (
            <div className="space-y-4">
              <Disclosure defaultOpen summary={<span className="text-sm font-semibold">Step-by-step engine envelopes</span>}>
                <StepOutputs run={run} />
              </Disclosure>
              {run.input && (
                <Disclosure summary={<span className="text-sm font-semibold">Exact Input Payload</span>}>
                  <JSONInspector title="Input Payload" value={run.input} />
                </Disclosure>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

import { Check, Download, Sparkles } from 'lucide-react'
import { useState } from 'react'

import { fmtValue } from '../lib/format'
import type { Presentation } from '../lib/types'
import { ChartCard } from './charts'
import { EvidenceViewer } from './EvidenceViewer'
import { NarrativeCard } from './presentation'
import { DataTable } from './table'
import { Card, Stat } from './ui'

interface ResultsRendererProps {
  presentation: Presentation
  runId?: string
  domainId?: string
  className?: string
}

export function ResultsRenderer({
  presentation,
  runId,
  domainId,
  className = '',
}: ResultsRendererProps) {
  const [exported, setExported] = useState(false)

  const downloadJson = () => {
    const blob = new Blob([JSON.stringify(presentation, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `omniforge-results-${domainId ?? 'run'}-${runId ?? Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
    setExported(true)
    setTimeout(() => setExported(false), 2000)
  }

  return (
    <div className={`space-y-4 ${className}`}>
      {/* Primary Result Headline Banner */}
      <div className="relative overflow-hidden rounded-xl border border-[var(--accent)]/40 bg-[var(--accent)]/[0.06] p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <span className="inline-flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-[var(--accent)]">
              <Sparkles className="size-3" aria-hidden /> Operational Intelligence Verdict
            </span>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-ink sm:text-xl">
              {presentation.headline}
            </h2>
          </div>
          <button
            type="button"
            onClick={downloadJson}
            className="flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-xs font-medium text-ink hover:bg-surface-2 transition shadow-sm shrink-0"
            title="Download structured results as JSON"
          >
            {exported ? (
              <>
                <Check className="size-3.5 text-good-ink" />
                <span className="text-good-ink">Saved</span>
              </>
            ) : (
              <>
                <Download className="size-3.5 text-muted" />
                <span>Export Verdict</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Primary Metrics Grid */}
      {presentation.metrics.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
          {presentation.metrics.map((m) => (
            <Stat
              key={m.label}
              label={m.label}
              value={fmtValue(m.value)}
              hint={m.hint ?? undefined}
              tone={m.tone}
            />
          ))}
        </div>
      )}

      {/* AI / Local Fallback Narrative */}
      {presentation.narrative && <NarrativeCard narrative={presentation.narrative} />}

      {/* Visualizations (Charts) */}
      {presentation.charts.length > 0 && (
        <div className={`grid gap-4 ${presentation.charts.length > 1 ? 'xl:grid-cols-2' : ''}`}>
          {presentation.charts.map((c) => (
            <ChartCard key={c.title} spec={c} />
          ))}
        </div>
      )}

      {/* Data Tables */}
      {presentation.tables
        .filter((t) => t.rows.length > 0)
        .map((t) => (
          <Card
            key={t.title}
            title={t.title}
            subtitle={`${t.rows.length} record${t.rows.length === 1 ? '' : 's'}`}
          >
            <div className="max-h-[28rem] overflow-auto">
              <DataTable columns={t.columns} rows={t.rows} />
            </div>
          </Card>
        ))}

      {/* Cryptographic Artifacts / Merkle Trees / Manifests */}
      {presentation.artifacts && Object.keys(presentation.artifacts).length > 0 && (
        <EvidenceViewer
          artifacts={presentation.artifacts}
          merkleRoot={typeof presentation.artifacts.merkle_root === 'string' ? presentation.artifacts.merkle_root : undefined}
          signatureHex={typeof presentation.artifacts.signature_hex === 'string' ? presentation.artifacts.signature_hex : undefined}
          publicKeyHex={typeof presentation.artifacts.public_key_hex === 'string' ? presentation.artifacts.public_key_hex : undefined}
        />
      )}

      {/* Notes & Audit Remarks */}
      {presentation.notes.length > 0 && (
        <div className="rounded-xl border border-line bg-surface-2/60 p-4">
          <p className="text-xs font-semibold text-ink-2 mb-2">Audit & Advisory Notes:</p>
          <ul className="space-y-1.5 text-xs text-muted">
            {presentation.notes.map((n, idx) => (
              <li key={idx} className="flex items-start gap-2">
                <span className="text-[var(--accent)] font-bold">•</span>
                <span>{n}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

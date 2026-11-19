import { AlertTriangle, ArrowRight, Cpu, Database, KeyRound, Lock, ShieldCheck, Sparkles, Users } from 'lucide-react'

import { cx } from '../lib/cx'
import { StatusBadge } from './ui'

interface EngineStatusCardProps {
  name: string
  title: string
  status: string
  warning?: string
  details?: Record<string, unknown>
  operationsCount?: number
  onTest?: () => void
}

const ENGINE_ICONS: Record<string, typeof Cpu> = {
  security: ShieldCheck,
  ai: Sparkles,
  ml: Cpu,
  crypto: KeyRound,
  data: Database,
  decision: Lock,
  crowd: Users,
}

export function EngineStatusCard({
  name,
  title,
  status,
  warning,
  details = {},
  operationsCount,
  onTest,
}: EngineStatusCardProps) {
  const Icon = ENGINE_ICONS[name] ?? Cpu
  const isOk = status === 'ok'

  return (
    <div className={cx(
      'rounded-xl border p-4 transition-all duration-200 bg-surface',
      isOk ? 'border-line hover:border-line/80' : 'border-amber-500/40 bg-amber-500/[0.02]'
    )}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="rounded-lg bg-surface-2 p-2 text-ink">
            <Icon className="size-5" aria-hidden />
          </div>
          <div>
            <h4 className="text-sm font-semibold text-ink">{title}</h4>
            <p className="font-mono text-[11px] text-muted">{name}</p>
          </div>
        </div>
        <StatusBadge status={status} />
      </div>

      {/* Engine metrics */}
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        {operationsCount !== undefined && (
          <div className="rounded-md bg-surface-2/60 px-2.5 py-1.5">
            <span className="block text-[10px] uppercase tracking-wider text-muted">Operations</span>
            <span className="font-mono font-medium text-ink">{operationsCount} available</span>
          </div>
        )}
        {Object.entries(details)
          .filter(([k]) => !['status', 'warning'].includes(k))
          .slice(0, operationsCount !== undefined ? 3 : 4)
          .map(([k, v]) => (
            <div key={k} className="rounded-md bg-surface-2/60 px-2.5 py-1.5">
              <span className="block text-[10px] uppercase tracking-wider text-muted truncate">
                {k.replace(/_/g, ' ')}
              </span>
              <span className="font-mono font-medium text-ink truncate block" title={String(v)}>
                {String(v ?? '—')}
              </span>
            </div>
          ))}
      </div>

      {warning && (
        <div className="mt-3 flex items-start gap-1.5 rounded-md border border-amber-500/30 bg-amber-500/10 p-2 text-[11px] text-amber-700 dark:text-amber-400">
          <AlertTriangle className="size-3.5 shrink-0 mt-0.5" aria-hidden />
          <p className="leading-snug">{warning}</p>
        </div>
      )}

      {onTest && (
        <div className="mt-3 pt-2.5 border-t border-line/60 flex justify-end">
          <button
            type="button"
            onClick={onTest}
            className="inline-flex items-center gap-1 text-xs font-medium text-[var(--accent)] hover:underline"
          >
            <span>Test in Lab</span>
            <ArrowRight className="size-3" aria-hidden />
          </button>
        </div>
      )}
    </div>
  )
}

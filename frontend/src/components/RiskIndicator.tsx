import { AlertOctagon, AlertTriangle, ShieldCheck } from 'lucide-react'

import { cx } from '../lib/cx'

export interface RiskFactor {
  name: string
  points?: number
  value?: number
  max?: number
  weight?: number
}

interface RiskIndicatorProps {
  score: number
  max?: number
  band?: 'critical' | 'high' | 'medium' | 'low' | string
  label?: string
  factors?: RiskFactor[]
  size?: 'sm' | 'md' | 'lg'
  showBar?: boolean
}

const BAND_CONFIG: Record<
  string,
  { label: string; color: string; bg: string; text: string; border: string; icon: typeof AlertTriangle }
> = {
  critical: {
    label: 'Critical Risk',
    color: '#ef4444',
    bg: 'bg-rose-500/10 dark:bg-rose-500/15',
    text: 'text-rose-700 dark:text-rose-400',
    border: 'border-rose-500/30',
    icon: AlertOctagon,
  },
  high: {
    label: 'High Risk',
    color: '#f97316',
    bg: 'bg-orange-500/10 dark:bg-orange-500/15',
    text: 'text-orange-700 dark:text-orange-400',
    border: 'border-orange-500/30',
    icon: AlertTriangle,
  },
  medium: {
    label: 'Moderate Risk',
    color: '#f59e0b',
    bg: 'bg-amber-500/10 dark:bg-amber-500/15',
    text: 'text-amber-700 dark:text-amber-400',
    border: 'border-amber-500/30',
    icon: AlertTriangle,
  },
  low: {
    label: 'Low Risk',
    color: '#10b981',
    bg: 'bg-emerald-500/10 dark:bg-emerald-500/15',
    text: 'text-emerald-700 dark:text-emerald-400',
    border: 'border-emerald-500/30',
    icon: ShieldCheck,
  },
}

function resolveBand(score: number, max: number): string {
  const pct = (score / max) * 100
  if (pct >= 75) return 'critical'
  if (pct >= 50) return 'high'
  if (pct >= 25) return 'medium'
  return 'low'
}

export function RiskIndicator({
  score,
  max = 100,
  band,
  label = 'Assessed Risk',
  factors = [],
  size = 'md',
  showBar = true,
}: RiskIndicatorProps) {
  const bandKey = band ? band.toLowerCase() : resolveBand(score, max)
  const cfg = BAND_CONFIG[bandKey] ?? BAND_CONFIG.medium
  const Icon = cfg.icon
  const pct = Math.min(100, Math.max(0, (score / max) * 100))

  return (
    <div className={cx('rounded-xl border', size === 'sm' ? 'p-2 text-xs' : 'p-3.5', cfg.border, cfg.bg)}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <Icon className={cx('size-5', cfg.text)} aria-hidden />
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-muted">{label}</p>
            <p className={cx('font-medium leading-none mt-0.5', cfg.text)}>{cfg.label}</p>
          </div>
        </div>
        <div className="text-right">
          <span className="tabular font-mono text-2xl font-bold tracking-tight text-ink">
            {Math.round(score)}
          </span>
          <span className="font-mono text-xs text-muted">/{max}</span>
        </div>
      </div>

      {showBar && (
        <div className="mt-3">
          <div className="h-2 w-full overflow-hidden rounded-full bg-line/80">
            <div
              className="h-full rounded-full transition-all duration-500 ease-out"
              style={{
                width: `${pct}%`,
                backgroundColor: cfg.color,
              }}
            />
          </div>
          <div className="mt-1 flex justify-between text-[10px] font-mono text-muted">
            <span>0</span>
            <span>25</span>
            <span>50</span>
            <span>75</span>
            <span>{max}</span>
          </div>
        </div>
      )}

      {factors.length > 0 && (
        <div className="mt-3 border-t border-line/60 pt-2.5">
          <p className="text-[11px] font-medium text-ink-2 mb-1.5">Contributing Signals:</p>
          <div className="space-y-1">
            {factors.map((f, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <span className="text-muted truncate max-w-[70%]">{f.name}</span>
                <span className="tabular font-mono font-medium text-ink">
                  {f.points !== undefined ? `+${f.points} pts` : f.value}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

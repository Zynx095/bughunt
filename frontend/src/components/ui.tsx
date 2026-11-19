import { AlertTriangle, CheckCircle2, ChevronDown, CircleSlash, Info, Loader2, XCircle } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { cx } from '../lib/cx'

export function Card({ title, subtitle, actions, children, className, pad = true }: {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
  pad?: boolean
}) {
  return (
    <section className={cx('rounded-xl border border-line bg-surface', className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0">
            {title && <h3 className="text-sm font-semibold text-ink">{title}</h3>}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={pad ? 'p-4' : ''}>{children}</div>
    </section>
  )
}

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

export function Button({ children, onClick, variant = 'secondary', disabled, busy, type = 'button', title, size = 'md' }: {
  children: ReactNode
  onClick?: () => void
  variant?: ButtonVariant
  disabled?: boolean
  busy?: boolean
  type?: 'button' | 'submit'
  title?: string
  size?: 'sm' | 'md'
}) {
  const styles: Record<ButtonVariant, string> = {
    primary: 'bg-[var(--accent)] text-white hover:brightness-110 border-transparent',
    secondary: 'bg-surface text-ink border-line hover:bg-surface-2',
    ghost: 'bg-transparent text-ink-2 border-transparent hover:bg-surface-2',
    danger: 'bg-critical text-white border-transparent hover:brightness-110',
  }
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled || busy}
      className={cx(
        'inline-flex items-center justify-center gap-1.5 rounded-lg border font-medium transition disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3.5 py-2 text-sm',
        styles[variant],
      )}
    >
      {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
}

type Tone = 'neutral' | 'good' | 'warn' | 'bad' | 'info' | 'accent'

const toneClass: Record<Tone, string> = {
  neutral: 'bg-surface-2 text-ink-2 border-line',
  good: 'bg-good/10 text-good-ink border-good/30',
  warn: 'bg-warn/15 text-warn-ink border-warn/40',
  bad: 'bg-critical/10 text-critical-ink border-critical/30',
  info: 'bg-[#2a78d6]/10 text-[#1c5cab] dark:text-[#86b6ef] border-[#2a78d6]/30',
  accent: 'bg-[var(--accent)]/10 text-ink border-[var(--accent)]/30',
}

export function Badge({ children, tone = 'neutral', title }: { children: ReactNode; tone?: Tone; title?: string }) {
  return (
    <span title={title} className={cx('inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px] font-medium', toneClass[tone])}>
      {children}
    </span>
  )
}

const BAND_TONE: Record<string, Tone> = { critical: 'bad', high: 'bad', medium: 'warn', low: 'good' }

/** Status is never colour alone: every band badge carries an icon and its label. */
export function BandBadge({ band }: { band: string | null | undefined }) {
  if (!band) return <span className="text-muted">—</span>
  const tone = BAND_TONE[band] ?? 'neutral'
  const Icon = tone === 'bad' ? XCircle : tone === 'warn' ? AlertTriangle : CheckCircle2
  return (
    <Badge tone={tone}>
      <Icon className="size-3" aria-hidden />
      {band}
    </Badge>
  )
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, [Tone, typeof CheckCircle2]> = {
    ok: ['good', CheckCircle2], completed: ['good', CheckCircle2], approved: ['good', CheckCircle2], valid: ['good', CheckCircle2],
    running: ['info', Loader2], pending: ['warn', AlertTriangle], degraded: ['warn', AlertTriangle],
    skipped: ['neutral', CircleSlash], failed: ['bad', XCircle], rejected: ['bad', XCircle], error: ['bad', XCircle],
  }
  const [tone, Icon] = map[status] ?? ['neutral', Info]
  return (
    <Badge tone={tone}>
      <Icon className={cx('size-3', status === 'running' && 'animate-spin')} aria-hidden />
      {status}
    </Badge>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-muted" role="status">
      <Loader2 className="size-4 animate-spin" aria-hidden /> {label}…
    </div>
  )
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-critical/30 bg-critical/10 px-3 py-2 text-sm text-critical-ink" role="alert">
      <XCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 break-words">{children}</div>
    </div>
  )
}

export function WarnBox({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-sm text-warn-ink">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 break-words">{children}</div>
    </div>
  )
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-line px-6 py-10 text-center">
      {icon && <div className="text-muted">{icon}</div>}
      <p className="text-sm font-medium text-ink">{title}</p>
      {children && <div className="max-w-md text-xs text-muted">{children}</div>}
    </div>
  )
}

export function Stat({ label, value, hint, tone = 'neutral' }: { label: string; value: ReactNode; hint?: ReactNode; tone?: 'neutral' | 'good' | 'warn' | 'bad' }) {
  const bar: Record<string, string> = { neutral: 'bg-line', good: 'bg-good', warn: 'bg-warn', bad: 'bg-critical' }
  const Icon = tone === 'good' ? CheckCircle2 : tone === 'warn' ? AlertTriangle : tone === 'bad' ? XCircle : null
  return (
    <div className="relative overflow-hidden rounded-xl border border-line bg-surface px-4 py-3">
      <span className={cx('absolute inset-y-0 left-0 w-1', bar[tone])} aria-hidden />
      <p className="flex items-center gap-1 text-xs font-medium text-muted">
        {Icon && <Icon className={cx('size-3.5', tone === 'good' ? 'text-good-ink' : tone === 'warn' ? 'text-warn-ink' : 'text-critical-ink')} aria-label={tone} />}
        {label}
      </p>
      <p className={cx('tabular mt-1 font-semibold text-ink', typeof value === 'string' && value.length > 14 ? 'line-clamp-2 break-words text-sm leading-snug' : 'truncate text-xl')}
        title={typeof value === 'string' ? value : undefined}>{value}</p>
      {hint && <p className="mt-0.5 truncate text-xs text-muted" title={typeof hint === 'string' ? hint : undefined}>{hint}</p>}
    </div>
  )
}

export function JsonView({ value, maxHeight = 360 }: { value: unknown; maxHeight?: number }) {
  return (
    <pre className="overflow-auto rounded-lg border border-line bg-surface-2 p-3 font-mono text-[11.5px] leading-relaxed text-ink-2" style={{ maxHeight }}>
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

export function Disclosure({ summary, children, defaultOpen = false }: { summary: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="rounded-lg border border-line">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm text-ink hover:bg-surface-2">
        <span className="min-w-0 flex-1">{summary}</span>
        <ChevronDown className={cx('size-4 shrink-0 text-muted transition', open && 'rotate-180')} aria-hidden />
      </button>
      {open && <div className="border-t border-line p-3">{children}</div>}
    </div>
  )
}

export function PageHeader({ title, description, actions, icon }: { title: string; description?: ReactNode; actions?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
      <div className="flex min-w-0 items-start gap-3">
        {icon}
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
          {description && <p className="mt-1 max-w-3xl text-sm text-ink-2">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Tabs<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: { id: T; label: string }[] }) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-surface-2 p-0.5" role="tablist">
      {options.map((o) => (
        <button key={o.id} role="tab" aria-selected={value === o.id} onClick={() => onChange(o.id)}
          className={cx('rounded-md px-3 py-1 text-xs font-medium transition', value === o.id ? 'bg-surface text-ink shadow-sm' : 'text-muted hover:text-ink')}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

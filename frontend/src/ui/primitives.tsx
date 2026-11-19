import { ChevronRight } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { cx } from '../lib/cx'

type Variant = 'primary' | 'plain' | 'quiet' | 'danger'

export function Button({ children, onClick, variant = 'plain', disabled, busy, title, type = 'button', className }: {
  children: ReactNode; onClick?: () => void; variant?: Variant; disabled?: boolean; busy?: boolean; title?: string; type?: 'button' | 'submit'; className?: string
}) {
  const look: Record<Variant, string> = {
    primary: 'bg-accent text-accent-ink hover:brightness-110 border-transparent',
    plain: 'bg-raised text-ink border-line hover:border-line-strong',
    quiet: 'bg-transparent text-ink-2 border-transparent hover:text-ink hover:bg-raised',
    danger: 'bg-transparent text-critical border-[color-mix(in_srgb,var(--color-critical)_40%,transparent)] hover:bg-[color-mix(in_srgb,var(--color-critical)_10%,transparent)]',
  }
  return (
    <button type={type} title={title} onClick={onClick} disabled={disabled || busy}
      className={cx('inline-flex h-8 items-center justify-center gap-1.5 rounded-[5px] border px-3 text-[13px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45',
        look[variant], className)}>
      {busy && <span className="size-3 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden />}
      {children}
    </button>
  )
}

/** A flush panel region with a quiet header; optionally collapsible. Not a floating card. */
export function Section({ title, aside, children, collapsible, defaultOpen = true, className }: {
  title: ReactNode; aside?: ReactNode; children: ReactNode; collapsible?: boolean; defaultOpen?: boolean; className?: string
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className={cx('border-b border-line', className)}>
      <header className="flex min-h-10 items-center justify-between gap-2 px-4 pt-3 pb-1.5">
        {collapsible ? (
          <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
            className="flex items-center gap-1 text-[13px] font-semibold text-ink">
            <ChevronRight className={cx('size-3.5 text-muted transition-transform', open && 'rotate-90')} aria-hidden />{title}
          </button>
        ) : <h2 className="text-[13px] font-semibold text-ink">{title}</h2>}
        {aside && <div className="flex items-center gap-1.5 text-[12px] text-muted">{aside}</div>}
      </header>
      {(!collapsible || open) && <div className="px-4 pb-3.5">{children}</div>}
    </section>
  )
}

export function Toggle({ checked, onChange, label, swatch }: { checked: boolean; onChange: (v: boolean) => void; label: string; swatch?: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 py-1 text-[13px] text-ink-2 hover:text-ink">
      <input type="checkbox" className="peer sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className={cx('relative h-[14px] w-[24px] rounded-full border transition-colors peer-focus-visible:outline-2 peer-focus-visible:outline-accent',
        checked ? 'border-accent bg-accent' : 'border-line-strong bg-raised')} aria-hidden>
        <span className={cx('absolute top-[1px] size-[10px] rounded-full transition-all', checked ? 'left-[11px] bg-accent-ink' : 'left-[1px] bg-muted')} />
      </span>
      {swatch}
      <span>{label}</span>
    </label>
  )
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block text-[12.5px] text-ink-2">
      <span className="mb-1 block">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[12px] text-muted">{hint}</span>}
    </label>
  )
}

export const inputCls = 'h-8 w-full rounded-[5px] border border-line bg-raised px-2 text-[13px] text-ink outline-none focus:border-accent'

/** Status word with its colour, never colour alone. */
export function StatusText({ colour, children, title }: { colour: string; children: ReactNode; title?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap" title={title}>
      <span className="inline-block size-2 rounded-full" style={{ background: colour }} aria-hidden />
      <span>{children}</span>
    </span>
  )
}

export function Note({ children, tone = 'muted' }: { children: ReactNode; tone?: 'muted' | 'warn' | 'bad' }) {
  const c = tone === 'bad' ? 'text-critical' : tone === 'warn' ? 'text-elevated' : 'text-muted'
  return <p className={cx('text-[12.5px] leading-snug', c)}>{children}</p>
}

export function KV({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[13px]">
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="text-right text-ink tabular">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

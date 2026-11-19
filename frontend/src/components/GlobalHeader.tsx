import { Bell, Check, ChevronDown, Menu, Monitor, Moon, Sun, User, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import type { Identity } from '../lib/api'
import { cx } from '../lib/cx'
import { useTheme, type ThemePreference } from '../lib/theme'
import type { DomainInfo, Health, Role, SectionId } from '../lib/types'
import { DomainBadgeIcon } from './domainIcon'
import { StatusBadge } from './ui'

interface GlobalHeaderProps {
  activeDomain: DomainInfo | null
  domains: DomainInfo[]
  onSelectDomain: (id: string) => Promise<void>
  group: string
  sectionLabel: string
  showDomainSwitcher: boolean
  identity: Identity
  onSelectRole: (role: Role) => void
  pendingApprovalsCount: number
  onNavigate: (section: SectionId) => void
  onOpenMobileMenu: () => void
  health: Health | null
}

const ROLES: Role[] = ['viewer', 'analyst', 'reviewer', 'admin']
const THEMES: { id: ThemePreference; label: string; icon: typeof Sun }[] = [
  { id: 'light', label: 'Light', icon: Sun },
  { id: 'dark', label: 'Dark', icon: Moon },
  { id: 'system', label: 'System', icon: Monitor },
]

/** Close a popover on outside click or Escape. */
function useDismiss(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return undefined
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) close() }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open, close])
  return ref
}

export function GlobalHeader({ activeDomain, domains, onSelectDomain, group, sectionLabel, showDomainSwitcher, identity, onSelectRole,
  pendingApprovalsCount, onNavigate, onOpenMobileMenu, health }: GlobalHeaderProps) {
  const { preference, setPreference } = useTheme()
  const [engineOpen, setEngineOpen] = useState(false)
  const [roleOpen, setRoleOpen] = useState(false)
  const [domainOpen, setDomainOpen] = useState(false)
  const roleRef = useDismiss(roleOpen, () => setRoleOpen(false))
  const domainRef = useDismiss(domainOpen, () => setDomainOpen(false))
  const engineCount = health?.engines ? Object.keys(health.engines).length : 0
  const degraded = health ? health.status !== 'ok' : false

  return (
    <header className="sticky top-0 z-20 flex h-14 w-full items-center justify-between gap-3 border-b border-line bg-page/85 px-4 backdrop-blur-md lg:px-6">
      <div className="flex min-w-0 items-center gap-2.5">
        <button type="button" onClick={onOpenMobileMenu} className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-ink lg:hidden" aria-label="Open navigation">
          <Menu className="size-5" />
        </button>
        <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-[13px]">
          <span className="hidden text-muted sm:inline">{group}</span>
          <span className="hidden text-line sm:inline">/</span>
          <span className="truncate font-medium text-ink">{sectionLabel}</span>
        </nav>
        {showDomainSwitcher && activeDomain && (
          <div className="relative ml-1" ref={domainRef}>
            <button type="button" onClick={() => setDomainOpen(!domainOpen)} aria-expanded={domainOpen}
              className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink-2 hover:text-ink">
              <span className="inline-block size-2 rounded-full" style={{ background: activeDomain.color }} aria-hidden />
              <span className="max-w-[180px] truncate">{activeDomain.name}</span>
              <ChevronDown className="size-3 text-muted" />
            </button>
            {domainOpen && (
              <div className="absolute left-0 top-9 z-50 w-72 rounded-lg border border-line bg-surface p-1.5 shadow-xl">
                <p className="px-2 py-1 text-[10.5px] font-semibold uppercase tracking-wider text-muted">Domain adapter</p>
                <div className="max-h-80 overflow-y-auto">
                  {domains.map((d) => (
                    <button key={d.id} type="button" onClick={async () => { await onSelectDomain(d.id); setDomainOpen(false) }}
                      className={cx('flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-xs', d.id === activeDomain.id ? 'bg-surface-2 font-medium text-ink' : 'text-ink-2 hover:bg-surface-2')}>
                      <DomainBadgeIcon name={d.icon} color={d.color} size="sm" />
                      <span className="flex-1 truncate">{d.name}</span>
                      {d.id === activeDomain.id && <Check className="size-3.5 text-[var(--accent)]" />}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="flex items-center gap-1.5 sm:gap-2">
        <button type="button" onClick={() => setEngineOpen(true)} title="Engine health"
          className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink-2 hover:text-ink">
          <span className={cx('size-1.5 rounded-full', degraded ? 'bg-warn' : 'bg-good')} aria-hidden />
          <span className="tabular">{engineCount} engines</span>
          <span className="sr-only">{degraded ? 'degraded' : 'healthy'}</span>
        </button>

        <button type="button" onClick={() => onNavigate('approvals')} title={`${pendingApprovalsCount} pending approvals`}
          className="relative rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-ink" aria-label={`${pendingApprovalsCount} pending approvals`}>
          <Bell className="size-4" />
          {pendingApprovalsCount > 0 && <span className="absolute right-1 top-1 size-1.5 rounded-full bg-warn" aria-hidden />}
        </button>

        <div className="hidden items-center rounded-md border border-line bg-surface-2 p-0.5 sm:flex" role="radiogroup" aria-label="Theme">
          {THEMES.map((t) => (
            <button key={t.id} type="button" role="radio" aria-checked={preference === t.id} title={`${t.label} theme`} onClick={() => setPreference(t.id)}
              className={cx('rounded px-1.5 py-1 transition-colors', preference === t.id ? 'bg-surface text-ink shadow-sm' : 'text-muted hover:text-ink')}>
              <t.icon className="size-3.5" aria-hidden />
              <span className="sr-only">{t.label}</span>
            </button>
          ))}
        </div>

        <div className="relative" ref={roleRef}>
          <button type="button" onClick={() => setRoleOpen(!roleOpen)} aria-expanded={roleOpen}
            className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1 text-xs hover:bg-surface-2">
            <User className="size-3 text-muted" aria-hidden />
            <span className="max-w-[90px] truncate font-medium text-ink">{identity.actor}</span>
            <span className="font-mono text-[10px] uppercase text-muted">{identity.role}</span>
            <ChevronDown className="size-3 text-muted" />
          </button>
          {roleOpen && (
            <div className="absolute right-0 top-9 z-50 w-52 rounded-lg border border-line bg-surface p-1.5 shadow-xl">
              <p className="px-2 py-1 text-[10.5px] font-semibold uppercase tracking-wider text-muted">Simulated role</p>
              {ROLES.map((r) => (
                <button key={r} type="button" onClick={() => { onSelectRole(r); setRoleOpen(false) }}
                  className={cx('flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-xs capitalize', identity.role === r ? 'bg-surface-2 font-medium text-ink' : 'text-ink-2 hover:bg-surface-2')}>
                  {r}{identity.role === r && <Check className="size-3 text-[var(--accent)]" />}
                </button>
              ))}
              <div className="mt-1 flex gap-1 border-t border-line px-1 pt-1.5 sm:hidden">
                {THEMES.map((t) => (
                  <button key={t.id} type="button" onClick={() => setPreference(t.id)} className={cx('flex-1 rounded px-1 py-1 text-[11px]', preference === t.id ? 'bg-surface-2 text-ink' : 'text-muted')}>{t.label}</button>
                ))}
              </div>
              <p className="mt-1 border-t border-line px-2 pt-1.5 text-[10.5px] text-muted">Declared via headers; the backend enforces the policy.</p>
            </div>
          )}
        </div>
      </div>

      {engineOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => setEngineOpen(false)} role="dialog" aria-modal="true" aria-label="Engine health">
          <div className="w-full max-w-md rounded-xl border border-line bg-surface p-4 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-line pb-2.5">
              <h3 className="text-sm font-semibold text-ink">Engine registry · {health?.status ?? 'unknown'}</h3>
              <button type="button" onClick={() => setEngineOpen(false)} className="text-muted hover:text-ink" aria-label="Close"><X className="size-4" /></button>
            </div>
            <ul className="mt-3 space-y-1.5">
              {health?.engines ? Object.entries(health.engines).map(([name, h]) => (
                <li key={name} className="flex items-start justify-between gap-3 rounded-md border border-line px-3 py-2 text-xs">
                  <div className="min-w-0">
                    <p className="font-medium capitalize text-ink">{name}</p>
                    {h.warning && <p className="mt-0.5 text-[11px] text-warn-ink">{h.warning}</p>}
                  </div>
                  <StatusBadge status={h.status} />
                </li>
              )) : <li className="py-4 text-center text-xs text-muted">Loading…</li>}
            </ul>
            <div className="mt-3 flex justify-end">
              <button type="button" onClick={() => { setEngineOpen(false); onNavigate('engines') }}
                className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:brightness-110">Open Engine Lab</button>
            </div>
          </div>
        </div>
      )}
    </header>
  )
}

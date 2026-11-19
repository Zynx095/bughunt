import {
  Bell,
  Check,
  ChevronDown,
  Cpu,
  Menu,
  Moon,
  Sun,
  User,
  X,
} from 'lucide-react'
import { useState } from 'react'

import type { Identity } from '../lib/api'
import { cx } from '../lib/cx'
import type { DomainInfo, Health, Role, SectionId } from '../lib/types'
import { DomainBadgeIcon } from './domainIcon'
import { StatusBadge } from './ui'

interface GlobalHeaderProps {
  activeDomain: DomainInfo | null
  domains: DomainInfo[]
  onSelectDomain: (id: string) => Promise<void>
  section?: SectionId
  sectionLabel: string
  identity: Identity
  onSelectRole: (role: Role) => void
  theme: 'system' | 'dark' | 'light'
  onSelectTheme: (theme: 'system' | 'dark' | 'light') => void
  pendingApprovalsCount: number
  onNavigate: (section: SectionId) => void
  onOpenMobileMenu: () => void
  health: Health | null
}

const ROLES: Role[] = ['viewer', 'analyst', 'reviewer', 'admin']

export function GlobalHeader({
  activeDomain,
  domains,
  onSelectDomain,
  sectionLabel,
  identity,
  onSelectRole,
  theme,
  onSelectTheme,
  pendingApprovalsCount,
  onNavigate,
  onOpenMobileMenu,
  health,
}: GlobalHeaderProps) {
  const [engineModalOpen, setEngineModalOpen] = useState(false)
  const [roleMenuOpen, setRoleMenuOpen] = useState(false)
  const [domainMenuOpen, setDomainMenuOpen] = useState(false)

  const isDegraded = health?.status !== 'ok'

  return (
    <header className="sticky top-0 z-20 flex h-14 w-full items-center justify-between border-b border-line bg-page/90 px-4 backdrop-blur lg:px-6">
      {/* Left: Mobile Toggle & Breadcrumbs */}
      <div className="flex items-center gap-3 min-w-0">
        <button
          type="button"
          onClick={onOpenMobileMenu}
          className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-ink lg:hidden"
          aria-label="Open navigation menu"
        >
          <Menu className="size-5" />
        </button>

        {/* Global Breadcrumbs */}
        <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-xs text-muted">
          <span className="font-bold tracking-wider text-ink">OMNIFORGE</span>
          <span>/</span>
          {activeDomain && (
            <>
              <button
                type="button"
                onClick={() => setDomainMenuOpen(!domainMenuOpen)}
                className="flex items-center gap-1 font-medium text-ink-2 hover:text-ink"
              >
                <span
                  className="size-2 rounded-full inline-block"
                  style={{ backgroundColor: activeDomain.color }}
                />
                <span className="truncate max-w-[120px] sm:max-w-none">{activeDomain.name}</span>
                <ChevronDown className="size-3 text-muted" />
              </button>
              <span>/</span>
            </>
          )}
          <span className="font-semibold text-ink truncate">{sectionLabel}</span>
        </nav>
      </div>

      {/* Domain Switcher Dropdown Modal/Popover */}
      {domainMenuOpen && (
        <div className="absolute left-16 top-12 z-50 w-72 rounded-xl border border-line bg-surface p-2 shadow-2xl">
          <div className="px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-muted">
            Select Active Domain Adapter
          </div>
          <div className="max-h-80 space-y-1 overflow-y-auto">
            {domains.map((d) => (
              <button
                key={d.id}
                type="button"
                onClick={async () => {
                  await onSelectDomain(d.id)
                  setDomainMenuOpen(false)
                }}
                className={cx(
                  'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-xs transition',
                  d.id === activeDomain?.id
                    ? 'bg-[var(--accent)]/10 text-ink font-semibold'
                    : 'text-ink-2 hover:bg-surface-2'
                )}
              >
                <DomainBadgeIcon name={d.icon} color={d.color} size="sm" />
                <span className="truncate flex-1">{d.name}</span>
                {d.id === activeDomain?.id && <Check className="size-3.5 text-[var(--accent)]" />}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Right Controls: Engine Health, Approvals Bell, Role Switcher, Theme */}
      <div className="flex items-center gap-2 sm:gap-3">
        {/* Engine Mesh Indicator Button */}
        <button
          type="button"
          onClick={() => setEngineModalOpen(true)}
          className="flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1 text-xs text-ink hover:bg-surface-2 transition"
          title="Inspect Engine Health"
        >
          <span
            className={cx(
              'size-2 rounded-full',
              isDegraded ? 'bg-amber-500 animate-pulse' : 'bg-emerald-500'
            )}
          />
          <Cpu className="size-3.5 text-muted hidden sm:inline" />
          <span className="font-medium hidden sm:inline">6 Engines</span>
          <span className="text-[10px] text-muted">({health?.status ?? 'ok'})</span>
        </button>

        {/* Pending Approvals Bell */}
        <button
          type="button"
          onClick={() => onNavigate('approvals')}
          className="relative rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-ink transition"
          title={`${pendingApprovalsCount} Pending Approvals`}
        >
          <Bell className="size-4" />
          {pendingApprovalsCount > 0 && (
            <span className="absolute right-1 top-1 flex size-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
              <span className="relative inline-flex size-2 rounded-full bg-amber-500" />
            </span>
          )}
        </button>

        {/* Theme Quick Toggle */}
        <button
          type="button"
          onClick={() => onSelectTheme(theme === 'dark' ? 'light' : 'dark')}
          className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-ink transition"
          title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Mode`}
        >
          {theme === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </button>

        {/* Actor & Role Quick Selector */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setRoleMenuOpen(!roleMenuOpen)}
            className="flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1 text-xs hover:bg-surface-2 transition"
          >
            <User className="size-3 text-muted" />
            <span className="font-medium text-ink truncate max-w-[80px] sm:max-w-none">
              {identity.actor}
            </span>
            <span className="rounded bg-surface-2 px-1 py-0.2 font-mono text-[10px] text-muted uppercase">
              {identity.role}
            </span>
            <ChevronDown className="size-3 text-muted" />
          </button>

          {roleMenuOpen && (
            <div className="absolute right-0 top-10 z-50 w-52 rounded-xl border border-line bg-surface p-2 shadow-2xl">
              <div className="px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-muted">
                Switch Simulated Role
              </div>
              <div className="space-y-0.5">
                {ROLES.map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => {
                      onSelectRole(r)
                      setRoleMenuOpen(false)
                    }}
                    className={cx(
                      'flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-xs capitalize transition',
                      identity.role === r
                        ? 'bg-[var(--accent)]/10 text-[var(--accent)] font-semibold'
                        : 'text-ink-2 hover:bg-surface-2'
                    )}
                  >
                    <span>{r}</span>
                    {identity.role === r && <Check className="size-3 text-[var(--accent)]" />}
                  </button>
                ))}
              </div>
              <div className="mt-2 border-t border-line/60 pt-2 px-2 text-[10px] text-muted">
                Simulated headers for RBAC policy enforcement
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Engine Status Modal */}
      {engineModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
          onClick={() => setEngineModalOpen(false)}
        >
          <div
            className="w-full max-w-lg rounded-2xl border border-line bg-surface p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-line pb-3">
              <div className="flex items-center gap-2">
                <Cpu className="size-5 text-[var(--accent)]" />
                <h3 className="text-base font-bold text-ink">Intelligence Engine Mesh</h3>
              </div>
              <button
                type="button"
                onClick={() => setEngineModalOpen(false)}
                className="text-muted hover:text-ink"
              >
                <X className="size-4" />
              </button>
            </div>

            <div className="mt-4 space-y-2.5">
              {health?.engines ? (
                Object.entries(health.engines).map(([name, h]) => (
                  <div
                    key={name}
                    className="flex items-center justify-between rounded-xl border border-line bg-surface-2/60 p-3 text-xs"
                  >
                    <div>
                      <span className="font-semibold text-ink capitalize">{name} Engine</span>
                      {h.warning && (
                        <p className="mt-0.5 text-[11px] text-amber-600 dark:text-amber-400">
                          {h.warning}
                        </p>
                      )}
                    </div>
                    <StatusBadge status={h.status} />
                  </div>
                ))
              ) : (
                <div className="py-4 text-center text-xs text-muted">Telemetry loading…</div>
              )}
            </div>

            <div className="mt-5 flex justify-end">
              <button
                type="button"
                onClick={() => {
                  setEngineModalOpen(false)
                  onNavigate('engines')
                }}
                className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110"
              >
                Launch Engine Lab
              </button>
            </div>
          </div>
        </div>
      )}
    </header>
  )
}

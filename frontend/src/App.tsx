import {
  Activity,
  BarChart3,
  ClipboardCheck,
  Cpu,
  DatabaseZap,
  FlaskConical,
  History,
  LayoutDashboard,
  ScrollText,
  Settings as SettingsIcon,
  UserRound,
  X,
  type LucideIcon,
} from 'lucide-react'
import React, { Suspense, useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react'

import { DomainBadgeIcon } from './components/domainIcon'
import { GlobalHeader } from './components/GlobalHeader'
import { ErrorBox, Spinner } from './components/ui'
import { AppContext, type AppState, type ThemePreference } from './context'
import { get, loadIdentity, saveIdentity, send, setApiIdentity, type Identity } from './lib/api'
import { cx } from './lib/cx'
import type { Approval, DomainInfo, Health, Role, SectionId, SettingsView } from './lib/types'

// Route-level code-splitting: each section is loaded lazily on demand
const OverviewPage = React.lazy(() => import('./sections/Overview').then((m) => ({ default: m.OverviewPage })))
const WorkspacePage = React.lazy(() => import('./sections/Workspace').then((m) => ({ default: m.WorkspacePage })))
const IngestionPage = React.lazy(() => import('./sections/Ingestion').then((m) => ({ default: m.IngestionPage })))
const RunsPage = React.lazy(() => import('./sections/Runs').then((m) => ({ default: m.RunsPage })))
const ApprovalsPage = React.lazy(() => import('./sections/Approvals').then((m) => ({ default: m.ApprovalsPage })))
const AnalyticsPage = React.lazy(() => import('./sections/Analytics').then((m) => ({ default: m.AnalyticsPage })))
const EngineLab = React.lazy(() => import('./sections/EngineLab').then((m) => ({ default: m.EngineLab })))
const AuditPage = React.lazy(() => import('./sections/Audit').then((m) => ({ default: m.AuditPage })))
const SettingsPage = React.lazy(() => import('./sections/Settings').then((m) => ({ default: m.SettingsPage })))

interface NavCategory {
  title: string
  items: { id: SectionId; label: string; icon: LucideIcon }[]
}

const NAV_GROUPS: NavCategory[] = [
  {
    title: 'Platform Command',
    items: [{ id: 'overview', label: 'Platform Overview', icon: LayoutDashboard }],
  },
  {
    title: 'Domain Intelligence',
    items: [
      { id: 'workspace', label: 'Domain Workspace', icon: FlaskConical },
      { id: 'ingestion', label: 'Data & Evidence Vault', icon: DatabaseZap },
      { id: 'runs', label: 'Runs & Execution History', icon: History },
    ],
  },
  {
    title: 'Governance & Security',
    items: [
      { id: 'approvals', label: 'Human Approvals', icon: ClipboardCheck },
      { id: 'audit', label: 'Cryptographic Audit Log', icon: ScrollText },
    ],
  },
  {
    title: 'Engineering Console',
    items: [
      { id: 'analytics', label: 'Telemetry & Analytics', icon: BarChart3 },
      { id: 'engines', label: 'Engine Lab Console', icon: Cpu },
      { id: 'settings', label: 'Settings & Runtime', icon: SettingsIcon },
    ],
  },
]

const ALL_NAV_ITEMS = NAV_GROUPS.flatMap((g) => g.items)

function parseHash(): { section: SectionId; param: string | null } {
  const [, section, param] = window.location.hash.split('/')
  const valid = ALL_NAV_ITEMS.some((n) => n.id === section)
  return { section: valid ? (section as SectionId) : 'overview', param: param ?? null }
}

const THEME_KEY = 'omniforge.theme'

function getInitialTheme(): ThemePreference {
  try {
    const saved = localStorage.getItem(THEME_KEY)
    if (saved === 'dark' || saved === 'light' || saved === 'system') return saved
  } catch {
    /* ignore */
  }
  return 'system'
}

function applyTheme(theme: ThemePreference) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.classList.remove('dark', 'light')
  if (theme === 'dark') {
    root.classList.add('dark')
  } else if (theme === 'light') {
    root.classList.add('light')
  }
}

export default function App() {
  const [route, setRoute] = useState(parseHash)
  const [domains, setDomains] = useState<DomainInfo[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [identity, setIdentityState] = useState<Identity>(loadIdentity)
  const [theme, setThemeState] = useState<ThemePreference>(getInitialTheme)
  const [health, setHealth] = useState<Health | null>(null)
  const [pendingCount, setPendingCount] = useState<number>(0)
  const [bootError, setBootError] = useState<string | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)

  // Initialize theme
  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  const setTheme = useCallback((nextTheme: ThemePreference) => {
    try {
      localStorage.setItem(THEME_KEY, nextTheme)
    } catch {
      /* ignore */
    }
    setThemeState(nextTheme)
    applyTheme(nextTheme)
  }, [])

  useEffect(() => {
    const onHash = () => setRoute(parseHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const refreshHealth = useCallback(async () => {
    try {
      const [h, apps] = await Promise.all([
        get<Health>('/api/health'),
        get<Approval[]>('/api/approvals?status=pending').catch(() => []),
      ])
      setHealth(h)
      setPendingCount(apps.length)
    } catch {
      /* ignore */
    }
  }, [])

  // Initial boot load
  useEffect(() => {
    Promise.all([
      get<DomainInfo[]>('/api/domains'),
      get<SettingsView>('/api/settings'),
      get<Health>('/api/health').catch(() => null),
      get<Approval[]>('/api/approvals?status=pending').catch(() => []),
    ])
      .then(([d, s, h, apps]) => {
        setDomains(d)
        setActiveId(s.active_domain)
        if (h) setHealth(h)
        if (apps) setPendingCount(apps.length)
      })
      .catch((e: Error) => setBootError(e.message))
  }, [])

  const navigate = useCallback((section: SectionId, param?: string) => {
    window.location.hash = `/${section}${param ? `/${param}` : ''}`
    setMenuOpen(false)
  }, [])

  const setActiveDomain = useCallback(async (id: string) => {
    const s = await send<SettingsView>('PUT', '/api/settings', { active_domain: id })
    setActiveId(s.active_domain)
  }, [])

  const setIdentity = useCallback((i: Identity) => {
    setApiIdentity(i)
    saveIdentity(i)
    setIdentityState(i)
  }, [])

  const setRole = useCallback(
    (role: Role) => {
      setIdentity({ ...identity, role })
    },
    [identity, setIdentity]
  )

  const active = domains.find((d) => d.id === activeId) ?? null
  const visibleItemIds = useMemo(() => {
    if (!active) return new Set(ALL_NAV_ITEMS.map((n) => n.id))
    return new Set(active.sections)
  }, [active])

  const section = active && !active.sections.includes(route.section) ? 'overview' : route.section
  const currentNav = ALL_NAV_ITEMS.find((n) => n.id === section)

  const state: AppState = {
    domains,
    active,
    setActiveDomain,
    identity,
    setIdentity,
    navigate,
    param: route.param,
    theme,
    setTheme,
    health,
    pendingApprovalsCount: pendingCount,
    refreshHealth,
  }

  const accent = { '--accent': active?.color ?? '#3b82f6' } as CSSProperties

  if (bootError) {
    return (
      <div className="mx-auto max-w-xl p-10">
        <ErrorBox>
          <p className="font-semibold text-base">Cannot reach the OMNIFORGE Backend API</p>
          <p className="mt-1 text-sm">{bootError}</p>
          <p className="mt-3 text-xs bg-surface-2 p-2 rounded border border-line font-mono">
            Start backend: cd backend &amp;&amp; python -m uvicorn app.main:app --port 8000
          </p>
        </ErrorBox>
      </div>
    )
  }

  if (!active) {
    return (
      <div className="flex h-screen items-center justify-center p-10">
        <Spinner label="Booting OMNIFORGE Engine Mesh & Domain Adapters" />
      </div>
    )
  }

  return (
    <AppContext.Provider value={state}>
      <div className="flex min-h-screen bg-page text-ink" style={accent}>
        {/* Sidebar */}
        <aside
          className={cx(
            'fixed inset-y-0 left-0 z-40 flex w-64 flex-col bg-sidebar text-sidebar-ink transition-transform duration-200 lg:translate-x-0 border-r border-line/40',
            menuOpen ? 'translate-x-0' : '-translate-x-full'
          )}
        >
          {/* Brand Logo Header */}
          <div className="flex items-center gap-2.5 px-5 pb-4 pt-5 border-b border-line/20">
            <img src="/favicon.svg" alt="OMNIFORGE" className="size-8" />
            <div className="min-w-0">
              <p className="text-sm font-bold tracking-wider text-sidebar-ink">OMNIFORGE</p>
              <p className="text-[10px] text-sidebar-muted uppercase tracking-widest font-mono">
                Adaptive AI Framework
              </p>
            </div>
            <button
              type="button"
              className="ml-auto rounded p-1 text-sidebar-muted hover:text-sidebar-ink lg:hidden"
              onClick={() => setMenuOpen(false)}
              aria-label="Close menu"
            >
              <X className="size-5" />
            </button>
          </div>

          {/* Active Domain Quick Card */}
          <div className="p-3">
            <button
              type="button"
              onClick={() => navigate('settings')}
              className="flex w-full items-center gap-2.5 rounded-xl bg-sidebar-2 px-3 py-2.5 text-left transition hover:brightness-110 border border-white/5"
            >
              <DomainBadgeIcon name={active.icon} color={active.color} size="sm" />
              <span className="min-w-0 flex-1">
                <span className="block text-[9px] uppercase tracking-wider text-sidebar-muted font-bold">
                  Active Adapter
                </span>
                <span className="block truncate text-xs font-semibold text-sidebar-ink">
                  {active.name}
                </span>
              </span>
            </button>
          </div>

          {/* Grouped Navigation */}
          <nav className="flex-1 space-y-4 overflow-y-auto px-3 py-2" aria-label="Main Navigation">
            {NAV_GROUPS.map((group) => {
              const visibleInGroup = group.items.filter((item) => visibleItemIds.has(item.id))
              if (visibleInGroup.length === 0) return null
              return (
                <div key={group.title} className="space-y-1">
                  <span className="px-3 text-[10px] font-bold uppercase tracking-widest text-sidebar-muted/80 block">
                    {group.title}
                  </span>
                  {visibleInGroup.map((n) => {
                    const isCurrent = section === n.id
                    return (
                      <button
                        key={n.id}
                        type="button"
                        onClick={() => navigate(n.id)}
                        aria-current={isCurrent ? 'page' : undefined}
                        className={cx(
                          'flex w-full items-center justify-between gap-2.5 rounded-lg px-3 py-2 text-xs font-medium transition',
                          isCurrent
                            ? 'bg-sidebar-2 text-white font-semibold shadow-sm'
                            : 'text-sidebar-muted hover:bg-sidebar-2/60 hover:text-sidebar-ink'
                        )}
                      >
                        <div className="flex items-center gap-2.5 truncate">
                          <n.icon
                            className="size-4 shrink-0"
                            style={isCurrent ? { color: active.color } : undefined}
                            aria-hidden
                          />
                          <span className="truncate">{n.label}</span>
                        </div>
                        {n.id === 'approvals' && pendingCount > 0 && (
                          <span className="rounded-full bg-amber-500/20 px-1.5 py-0.2 text-[10px] font-bold text-amber-300">
                            {pendingCount}
                          </span>
                        )}
                      </button>
                    )
                  })}
                </div>
              )
            })}
          </nav>

          {/* User Simulation Footer */}
          <div className="border-t border-white/10 p-4 text-[11px] text-sidebar-muted bg-sidebar/50">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-sidebar-ink font-semibold">
                <UserRound className="size-3.5 text-sidebar-muted" />
                <span className="truncate max-w-[100px]">{identity.actor}</span>
              </span>
              <span className="rounded bg-sidebar-2 px-1.5 py-0.5 text-[10px] uppercase font-mono text-[var(--accent)] font-bold">
                {identity.role}
              </span>
            </div>
            <p className="mt-1 flex items-center gap-1 text-[10px] text-sidebar-muted">
              <Activity className="size-3 text-sidebar-muted" /> Simulated Identity Headers
            </p>
          </div>
        </aside>

        {/* Mobile Backdrop */}
        {menuOpen && (
          <div
            className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm lg:hidden"
            onClick={() => setMenuOpen(false)}
            aria-hidden
          />
        )}

        {/* Main Content Area */}
        <div className="flex min-w-0 flex-1 flex-col lg:pl-64">
          <GlobalHeader
            activeDomain={active}
            domains={domains}
            onSelectDomain={setActiveDomain}
            section={section}
            sectionLabel={currentNav?.label ?? 'Workspace'}
            identity={identity}
            onSelectRole={setRole}
            theme={theme}
            onSelectTheme={setTheme}
            pendingApprovalsCount={pendingCount}
            onNavigate={navigate}
            onOpenMobileMenu={() => setMenuOpen(true)}
            health={health}
          />

          <main className="mx-auto w-full max-w-[1440px] flex-1 px-4 py-6 sm:px-6 lg:px-8">
            <Suspense
              fallback={
                <div className="flex h-64 items-center justify-center">
                  <Spinner label={`Loading ${currentNav?.label ?? 'Interface'}`} />
                </div>
              }
            >
              {section === 'overview' && <OverviewPage />}
              {section === 'workspace' && <WorkspacePage key={active.id} />}
              {section === 'ingestion' && <IngestionPage />}
              {section === 'runs' && <RunsPage />}
              {section === 'approvals' && <ApprovalsPage />}
              {section === 'analytics' && <AnalyticsPage />}
              {section === 'engines' && <EngineLab />}
              {section === 'audit' && <AuditPage />}
              {section === 'settings' && <SettingsPage />}
            </Suspense>
          </main>
        </div>
      </div>
    </AppContext.Provider>
  )
}

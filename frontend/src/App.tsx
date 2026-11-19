import {
  BarChart3, Camera, ClipboardCheck, Cpu, DatabaseZap, FlaskConical, Flame, History, LayoutDashboard, Layers, Navigation,
  Radio, Settings as SettingsIcon, ShieldCheck, Siren, TrendingUp, X, type LucideIcon,
} from 'lucide-react'
import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react'

import { GlobalHeader } from './components/GlobalHeader'
import { ErrorBox, Spinner } from './components/ui'
import { AppContext, type AppState } from './context'
import { CrowdGuardProvider } from './crowdguard/state'
import { get, loadIdentity, saveIdentity, send, setApiIdentity, type Identity } from './lib/api'
import { cx } from './lib/cx'
import type { Approval, DomainInfo, Health, Role, SectionId, SettingsView } from './lib/types'

// Route-level code splitting: every screen is loaded on demand.
const lazy = (load: () => Promise<Record<string, unknown>>, name: string) =>
  React.lazy(async () => ({ default: (await load())[name] as React.ComponentType }))

const SCREENS: Record<SectionId, React.LazyExoticComponent<React.ComponentType>> = {
  'cg-command': lazy(() => import('./crowdguard/pages/CommandCentre'), 'CommandCentrePage'),
  'cg-live': lazy(() => import('./crowdguard/pages/LiveMonitoring'), 'LiveMonitoringPage'),
  'cg-heatmap': lazy(() => import('./crowdguard/pages/VirtualHeatmap'), 'VirtualHeatmapPage'),
  'cg-zones': lazy(() => import('./crowdguard/pages/ZoneIntelligence'), 'ZoneIntelligencePage'),
  'cg-forecast': lazy(() => import('./crowdguard/pages/Forecasting'), 'ForecastingPage'),
  'cg-routes': lazy(() => import('./crowdguard/pages/MovementPlanner'), 'MovementPlannerPage'),
  'cg-incidents': lazy(() => import('./crowdguard/pages/Incidents'), 'IncidentsPage'),
  overview: lazy(() => import('./sections/Overview'), 'OverviewPage'),
  workspace: lazy(() => import('./sections/Workspace'), 'WorkspacePage'),
  ingestion: lazy(() => import('./sections/Ingestion'), 'IngestionPage'),
  runs: lazy(() => import('./sections/Runs'), 'RunsPage'),
  analytics: lazy(() => import('./sections/Analytics'), 'AnalyticsPage'),
  approvals: lazy(() => import('./sections/Approvals'), 'ApprovalsPage'),
  audit: lazy(() => import('./sections/Governance'), 'GovernanceAuditPage'),
  engines: lazy(() => import('./sections/EngineLab'), 'EngineLab'),
  settings: lazy(() => import('./sections/Settings'), 'SettingsPage'),
}

interface NavItem { id: SectionId; label: string; icon: LucideIcon }
interface NavGroup { title: string; items: NavItem[] }

const NAV_GROUPS: NavGroup[] = [
  {
    title: 'CROWDGUARD',
    items: [
      { id: 'cg-command', label: 'Command Centre', icon: Radio },
      { id: 'cg-live', label: 'Live Monitoring', icon: Camera },
      { id: 'cg-heatmap', label: 'Virtual Heatmap', icon: Flame },
      { id: 'cg-zones', label: 'Zone Intelligence', icon: Layers },
      { id: 'cg-forecast', label: 'Crowd Forecasting', icon: TrendingUp },
      { id: 'cg-routes', label: 'Movement Planner', icon: Navigation },
      { id: 'cg-incidents', label: 'Incident Management', icon: Siren },
    ],
  },
  {
    title: 'OMNIFORGE',
    items: [
      { id: 'overview', label: 'Overview', icon: LayoutDashboard },
      { id: 'workspace', label: 'Domain Workspace', icon: FlaskConical },
      { id: 'ingestion', label: 'Data & Evidence', icon: DatabaseZap },
      { id: 'runs', label: 'Run History', icon: History },
      { id: 'analytics', label: 'Analytics', icon: BarChart3 },
    ],
  },
  {
    title: 'Governance',
    items: [
      { id: 'approvals', label: 'Approvals', icon: ClipboardCheck },
      { id: 'audit', label: 'Audit & Verification', icon: ShieldCheck },
    ],
  },
  {
    title: 'Engineering',
    items: [
      { id: 'engines', label: 'Engine Lab', icon: Cpu },
      { id: 'settings', label: 'Settings', icon: SettingsIcon },
    ],
  },
]

const ALL_ITEMS = NAV_GROUPS.flatMap((g) => g.items.map((i) => ({ ...i, group: g.title })))
// Screens that read the shared deterministic crowd simulation.
const CROWD_SCREENS = new Set<SectionId>(['cg-command', 'cg-zones', 'cg-forecast', 'cg-routes', 'cg-incidents', 'cg-live', 'analytics'])

function parseHash(): { section: SectionId; param: string | null } {
  const [, section, param] = window.location.hash.split('/')
  const valid = ALL_ITEMS.some((n) => n.id === section)
  return { section: valid ? (section as SectionId) : 'cg-command', param: param ?? null }
}

export default function App() {
  const [route, setRoute] = useState(parseHash)
  const [domains, setDomains] = useState<DomainInfo[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [identity, setIdentityState] = useState<Identity>(loadIdentity)
  const [health, setHealth] = useState<Health | null>(null)
  const [pendingCount, setPendingCount] = useState(0)
  const [bootError, setBootError] = useState<string | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => {
    const onHash = () => setRoute(parseHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const refreshHealth = useCallback(async () => {
    try {
      const [h, apps] = await Promise.all([get<Health>('/api/health'), get<Approval[]>('/api/approvals?status=pending').catch(() => [])])
      setHealth(h)
      setPendingCount(apps.length)
    } catch {
      /* the header shows the last known state */
    }
  }, [])

  useEffect(() => {
    Promise.all([get<DomainInfo[]>('/api/domains'), get<SettingsView>('/api/settings'), get<Health>('/api/health').catch(() => null),
      get<Approval[]>('/api/approvals?status=pending').catch(() => [])])
      .then(([d, s, h, apps]) => {
        setDomains(d)
        setActiveId(s.active_domain)
        if (h) setHealth(h)
        setPendingCount(apps.length)
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
  const setRole = useCallback((role: Role) => setIdentity({ ...identity, role }), [identity, setIdentity])

  const active = domains.find((d) => d.id === activeId) ?? null
  const section = route.section
  const current = ALL_ITEMS.find((n) => n.id === section)
  const state = useMemo<AppState>(() => ({
    domains, active, setActiveDomain, identity, setIdentity, navigate, param: route.param, health,
    pendingApprovalsCount: pendingCount, refreshHealth,
  }), [domains, active, setActiveDomain, identity, setIdentity, navigate, route.param, health, pendingCount, refreshHealth])

  if (bootError) {
    return (
      <div className="mx-auto max-w-xl p-10">
        <ErrorBox>
          <p className="text-base font-semibold">Cannot reach the CROWDGUARD / OMNIFORGE API</p>
          <p className="mt-1 text-sm">{bootError}</p>
          <p className="mt-3 rounded border border-line bg-surface-2 p-2 font-mono text-xs">cd backend &amp;&amp; python -m uvicorn app.main:app --port 8000</p>
        </ErrorBox>
      </div>
    )
  }
  if (!active) {
    return <div className="flex h-screen items-center justify-center"><Spinner label="Connecting to the engine registry" /></div>
  }

  const Screen = SCREENS[section]
  return (
    <AppContext.Provider value={state}>
      <div className="flex min-h-screen bg-page text-ink">
        <aside className={cx('fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-line bg-sidebar text-sidebar-ink transition-transform duration-200 lg:translate-x-0',
          menuOpen ? 'translate-x-0' : '-translate-x-full')}>
          <div className="flex h-14 items-center gap-2.5 border-b border-line px-4">
            <img src="/favicon.svg" alt="" className="size-7" />
            <div className="min-w-0 leading-tight">
              <p className="text-[13px] font-semibold tracking-wide">CROWDGUARD</p>
              <p className="text-[10.5px] text-sidebar-muted">on OMNIFORGE</p>
            </div>
            <button type="button" className="ml-auto rounded p-1 text-sidebar-muted hover:text-sidebar-ink lg:hidden" onClick={() => setMenuOpen(false)} aria-label="Close menu">
              <X className="size-4" />
            </button>
          </div>
          <nav className="flex-1 space-y-5 overflow-y-auto px-2.5 py-4" aria-label="Main navigation">
            {NAV_GROUPS.map((group) => (
              <div key={group.title}>
                <p className="mb-1 px-2.5 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-sidebar-muted">{group.title}</p>
                <ul className="space-y-px">
                  {group.items.map((n) => {
                    const on = section === n.id
                    return (
                      <li key={n.id}>
                        <button type="button" onClick={() => navigate(n.id)} aria-current={on ? 'page' : undefined}
                          className={cx('group flex w-full items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13px] transition-colors',
                            on ? 'bg-sidebar-2 font-medium text-sidebar-ink' : 'text-sidebar-muted hover:bg-sidebar-2/60 hover:text-sidebar-ink')}>
                          <n.icon className={cx('size-4 shrink-0', on ? 'text-[var(--accent)]' : 'opacity-80')} aria-hidden />
                          <span className="truncate">{n.label}</span>
                          {n.id === 'approvals' && pendingCount > 0 && (
                            <span className="ml-auto rounded-full bg-warn/20 px-1.5 text-[10px] font-semibold text-warn-ink">{pendingCount}</span>
                          )}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </div>
            ))}
          </nav>
          <p className="border-t border-line px-4 py-3 text-[10.5px] leading-snug text-sidebar-muted">
            Advisory system. Identity is simulated (no authentication).
          </p>
        </aside>
        {menuOpen && <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={() => setMenuOpen(false)} aria-hidden />}

        <div className="flex min-w-0 flex-1 flex-col lg:pl-60">
          <GlobalHeader activeDomain={active} domains={domains} onSelectDomain={setActiveDomain} group={current?.group ?? ''}
            sectionLabel={current?.label ?? ''} showDomainSwitcher={['workspace', 'runs', 'ingestion'].includes(section)}
            identity={identity} onSelectRole={setRole} pendingApprovalsCount={pendingCount} onNavigate={navigate}
            onOpenMobileMenu={() => setMenuOpen(true)} health={health} />
          <CrowdGuardProvider active={CROWD_SCREENS.has(section)}>
            <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-5 sm:px-6 lg:px-8">
              <Suspense fallback={<div className="flex h-64 items-center justify-center"><Spinner label={`Loading ${current?.label ?? ''}`} /></div>}>
                {section === 'workspace' ? <Screen key={active.id} /> : <Screen />}
              </Suspense>
            </main>
          </CrowdGuardProvider>
        </div>
      </div>
    </AppContext.Provider>
  )
}

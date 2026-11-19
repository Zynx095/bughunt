import {
  Activity, BarChart3, ClipboardCheck, Cpu, DatabaseZap, FlaskConical, History, LayoutDashboard, Menu, ScrollText,
  Settings as SettingsIcon, UserRound, X, type LucideIcon,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react'

import { DomainBadgeIcon } from './components/domainIcon'
import { ErrorBox, Spinner } from './components/ui'
import { cx } from './lib/cx'
import { AppContext, type AppState, type ThemePreference } from './context'
import { get, loadIdentity, saveIdentity, send, setApiIdentity, type Identity } from './lib/api'
import type { DomainInfo, Health, SectionId, SettingsView } from './lib/types'
import { AnalyticsPage } from './sections/Analytics'
import { ApprovalsPage } from './sections/Approvals'
import { AuditPage } from './sections/Audit'
import { EngineLab } from './sections/EngineLab'
import { IngestionPage } from './sections/Ingestion'
import { OverviewPage } from './sections/Overview'
import { RunsPage } from './sections/Runs'
import { SettingsPage } from './sections/Settings'
import { WorkspacePage } from './sections/Workspace'

const NAV: { id: SectionId; label: string; icon: LucideIcon }[] = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'workspace', label: 'Workspace', icon: FlaskConical },
  { id: 'ingestion', label: 'Data & documents', icon: DatabaseZap },
  { id: 'runs', label: 'Runs & results', icon: History },
  { id: 'approvals', label: 'Approvals', icon: ClipboardCheck },
  { id: 'analytics', label: 'Analytics', icon: BarChart3 },
  { id: 'engines', label: 'Engine lab', icon: Cpu },
  { id: 'audit', label: 'Audit log', icon: ScrollText },
  { id: 'settings', label: 'Settings', icon: SettingsIcon },
]

function parseHash(): { section: SectionId; param: string | null } {
  const [, section, param] = window.location.hash.split('/')
  const valid = NAV.some((n) => n.id === section)
  return { section: valid ? (section as SectionId) : 'overview', param: param ?? null }
}

export default function App() {
  const [route, setRoute] = useState(parseHash)
  const [domains, setDomains] = useState<DomainInfo[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [identity, setIdentityState] = useState<Identity>(loadIdentity)
  const [bootError, setBootError] = useState<string | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [theme, setTheme] = useState<ThemePreference>('system')
  const [health, setHealth] = useState<Health | null>(null)
  const [pendingApprovalsCount] = useState<number>(0)

  const refreshHealth = useCallback(async () => {
    try {
      const h = await get<Health>('/api/health')
      setHealth(h)
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    refreshHealth()
  }, [refreshHealth])

  useEffect(() => {
    const onHash = () => setRoute(parseHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    Promise.all([get<DomainInfo[]>('/api/domains'), get<SettingsView>('/api/settings')])
      .then(([d, s]) => { setDomains(d); setActiveId(s.active_domain) })
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

  const active = domains.find((d) => d.id === activeId) ?? null
  const visible = useMemo(() => NAV.filter((n) => !active || active.sections.includes(n.id)), [active])
  const section = active && !active.sections.includes(route.section) ? 'overview' : route.section

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
    pendingApprovalsCount,
    refreshHealth,
  }
  const accent = { '--accent': active?.color ?? '#2a78d6' } as CSSProperties

  if (bootError) {
    return (
      <div className="mx-auto max-w-xl p-10">
        <ErrorBox>
          <p className="font-medium">Cannot reach the OMNIFORGE API.</p>
          <p className="mt-1">{bootError}</p>
          <p className="mt-2 text-xs">Start the backend: <code className="font-mono">cd backend && uvicorn app.main:app --port 8000</code></p>
        </ErrorBox>
      </div>
    )
  }
  if (!active) return <div className="p-10"><Spinner label="Starting OMNIFORGE" /></div>

  return (
    <AppContext.Provider value={state}>
      <div className="flex min-h-screen" style={accent}>
        <aside className={cx('fixed inset-y-0 left-0 z-30 flex w-64 flex-col bg-sidebar text-sidebar-ink transition-transform lg:translate-x-0',
          menuOpen ? 'translate-x-0' : '-translate-x-full')}>
          <div className="flex items-center gap-2.5 px-5 pb-4 pt-5">
            <img src="/favicon.svg" alt="" className="size-8" />
            <div>
              <p className="text-sm font-semibold tracking-wide">OMNIFORGE</p>
              <p className="text-[11px] text-sidebar-muted">Adaptive intelligence framework</p>
            </div>
            <button className="ml-auto lg:hidden" onClick={() => setMenuOpen(false)} aria-label="Close menu"><X className="size-5" /></button>
          </div>
          <button onClick={() => navigate('settings')} className="mx-3 mb-3 flex items-center gap-2.5 rounded-lg bg-sidebar-2 px-3 py-2.5 text-left hover:brightness-125">
            <DomainBadgeIcon name={active.icon} color={active.color} size="sm" />
            <span className="min-w-0">
              <span className="block text-[10px] uppercase tracking-wide text-sidebar-muted">Active domain</span>
              <span className="block truncate text-xs font-medium">{active.name}</span>
            </span>
          </button>
          <nav className="flex-1 space-y-0.5 overflow-y-auto px-3" aria-label="Sections">
            {visible.map((n) => (
              <button key={n.id} onClick={() => navigate(n.id)} aria-current={section === n.id ? 'page' : undefined}
                className={cx('flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition',
                  section === n.id ? 'bg-sidebar-2 font-medium text-white' : 'text-sidebar-muted hover:bg-sidebar-2/60 hover:text-sidebar-ink')}>
                <n.icon className="size-4" aria-hidden style={section === n.id ? { color: active.color } : undefined} />
                {n.label}
              </button>
            ))}
          </nav>
          <div className="border-t border-white/10 px-5 py-3 text-[11px] text-sidebar-muted">
            <p className="flex items-center gap-1.5"><UserRound className="size-3.5" aria-hidden />{identity.actor} · <span className="font-medium text-sidebar-ink">{identity.role}</span></p>
            <p className="mt-0.5 flex items-center gap-1.5"><Activity className="size-3.5" aria-hidden />Identity is simulated (no auth)</p>
          </div>
        </aside>
        {menuOpen && <div className="fixed inset-0 z-20 bg-black/40 lg:hidden" onClick={() => setMenuOpen(false)} aria-hidden />}

        <div className="flex min-w-0 flex-1 flex-col lg:pl-64">
          <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-line bg-page/90 px-4 py-2.5 backdrop-blur lg:hidden">
            <button onClick={() => setMenuOpen(true)} aria-label="Open menu"><Menu className="size-5" /></button>
            <span className="text-sm font-semibold">OMNIFORGE</span>
          </header>
          <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6 lg:px-8">
            {section === 'overview' && <OverviewPage />}
            {section === 'workspace' && <WorkspacePage key={active.id} />}
            {section === 'ingestion' && <IngestionPage />}
            {section === 'runs' && <RunsPage />}
            {section === 'approvals' && <ApprovalsPage />}
            {section === 'analytics' && <AnalyticsPage />}
            {section === 'engines' && <EngineLab />}
            {section === 'audit' && <AuditPage />}
            {section === 'settings' && <SettingsPage />}
          </main>
        </div>
      </div>
    </AppContext.Provider>
  )
}

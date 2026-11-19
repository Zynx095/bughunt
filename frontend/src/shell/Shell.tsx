import { Monitor, Moon, Sun, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import { cx } from '../lib/cx'
import { fmtClock } from '../lib/format'
import { useTheme, type ThemePreference } from '../lib/theme'
import { useLive } from '../live/context'
import { SEVERITY_VAR } from '../map/palette'
import { monitorWords, SCREENS, type ScreenId } from './screens'

export function BrandMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 22 22" aria-hidden>
      <defs>
        <linearGradient id="mark-grad" x1="5" y1="16" x2="17" y2="6" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--color-accent)" />
          <stop offset="1" stopColor="var(--color-accent-2)" />
        </linearGradient>
      </defs>
      <rect x="1.75" y="1.75" width="18.5" height="18.5" rx="3.5" fill="none" stroke="currentColor" strokeWidth="1.5" opacity="0.55" />
      <path d="M6 15.5 L10 10.5 L16.5 6.5" fill="none" stroke="url(#mark-grad)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="6" cy="15.5" r="2" fill="currentColor" />
    </svg>
  )
}

const THEMES: { id: ThemePreference; label: string; icon: typeof Sun }[] = [
  { id: 'light', label: 'Light', icon: Sun }, { id: 'dark', label: 'Dark', icon: Moon }, { id: 'system', label: 'Match system', icon: Monitor },
]

export function ThemeSwitch() {
  const { preference, setPreference } = useTheme()
  return (
    <div className="flex items-center rounded-[6px] border border-line p-0.5" role="radiogroup" aria-label="Theme">
      {THEMES.map((t) => (
        <button key={t.id} type="button" role="radio" aria-checked={preference === t.id} title={t.label} onClick={() => setPreference(t.id)}
          className={cx('rounded-[4px] p-1 transition-colors', preference === t.id ? 'bg-raised text-ink shadow-[0_0_0_1px_var(--color-line)]' : 'text-muted hover:text-ink')}>
          <t.icon className="size-3.5" aria-hidden /><span className="sr-only">{t.label}</span>
        </button>
      ))}
    </div>
  )
}

export function TopBar({ screen, onNavigate }: { screen: ScreenId; onNavigate: (s: ScreenId) => void }) {
  const { status, snapshot, connection } = useLive()
  const src = snapshot?.source ?? status?.source
  const st = snapshot?.status ?? status?.status
  const m = monitorWords(st, src?.kind)
  return (
    <header className="flex h-12 shrink-0 items-center gap-6 border-b border-line bg-panel px-4">
      <div className="flex items-center gap-2 text-ink">
        <BrandMark />
        <span className="font-display text-[17px] font-semibold tracking-[0.06em]">CROWDGUARD</span>
      </div>
      <nav aria-label="Screens" className="flex h-full items-stretch gap-1 overflow-x-auto">
        {SCREENS.map((s) => (
          <button key={s.id} type="button" onClick={() => onNavigate(s.id)} aria-current={screen === s.id ? 'page' : undefined}
            className={cx('relative whitespace-nowrap px-2.5 text-[13.5px] transition-colors',
              screen === s.id ? 'font-semibold text-ink' : 'text-ink-2 hover:text-ink')}>
            {s.label}
            {screen === s.id && <span className="absolute inset-x-2.5 bottom-0 h-[2px] rounded-full bg-accent" aria-hidden />}
          </button>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-4 text-[13px]">
        <span className="hidden items-center gap-2 lg:flex">
          <span className="inline-block size-2 rounded-full" style={{ background: m.colour }} aria-hidden />
          <span className="font-medium text-ink">{m.word}</span>
          {src && <span className="max-w-[220px] truncate text-ink-2" title={src.label}>{src.label}</span>}
        </span>
        <span className={cx('hidden md:inline', connection === 'open' ? 'text-muted' : 'text-elevated')}>
          {connection === 'open' ? 'Connected' : connection === 'connecting' ? 'Connecting' : 'Reconnecting'}
        </span>
        <ThemeSwitch />
      </div>
    </header>
  )
}

export function StatusBar() {
  const { snapshot, status, connection, lastMessageAt } = useLive()
  const s = snapshot?.stats ?? status?.stats
  const src = snapshot?.source ?? status?.source
  const st = snapshot?.status ?? status?.status
  const health = !st || st === 'idle' ? 'No source' : st === 'running' ? (snapshot?.detection_failed ? 'Detection failing' : 'Healthy')
    : st === 'stale' || st === 'disconnected' ? 'No frames' : st
  const [now, setNow] = useState(0)
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])
  const stale = connection === 'open' && st === 'running' && now > 0 && now - lastMessageAt > 3000
  const cells: [string, string][] = [
    ['Processing', s?.fps ? `${s.fps.toFixed(1)} fps` : '—'],
    ['Detected', snapshot ? String(snapshot.stats.detections) : '—'],
    ['Tracked', snapshot ? String(snapshot.tracks.filter((t) => !t.predicted).length) : '—'],
    ['Frame', snapshot?.frame.index != null ? String(snapshot.frame.index) : '—'],
    ['Captured', fmtClock(snapshot?.frame.captured_at, true)],
    ['Latency', s?.e2e_ms != null ? `${Math.round(s.e2e_ms)} ms` : '—'],
    ['Skipped', s ? String(s.skipped) : '—'],
  ]
  return (
    <footer className="flex h-8 shrink-0 items-center gap-0 overflow-x-auto border-t border-line bg-panel text-[12.5px]" aria-label="Processing status">
      {cells.map(([k, v]) => (
        <span key={k} className="flex h-full items-center gap-1.5 whitespace-nowrap border-r border-line px-3">
          <span className="text-muted">{k}</span><span className="text-ink tabular">{v}</span>
        </span>
      ))}
      <span className="flex h-full items-center gap-1.5 whitespace-nowrap px-3">
        <span className="text-muted">Camera</span>
        <span className={cx('tabular', health === 'Healthy' ? 'text-normal' : health === 'No source' ? 'text-ink-2' : 'text-critical')}>{stale ? 'No updates' : health}</span>
        {src && src.kind !== 'live_camera' && <span className="text-muted">({src.kind === 'synthetic' ? 'simulated' : 'recorded'})</span>}
      </span>
    </footer>
  )
}

export function Toasts() {
  const { toasts, dismissToast } = useLive()
  if (!toasts.length) return null
  return (
    <div className="pointer-events-none fixed right-4 top-14 z-50 flex w-[340px] flex-col gap-2" aria-live="polite">
      {toasts.map((a) => (
        <div key={a.id} className="pointer-events-auto rounded-[6px] border border-line bg-raised px-3 py-2.5 text-[13px] shadow-lg"
          style={{ borderLeft: `3px solid ${SEVERITY_VAR[a.severity]}` }}>
          <div className="flex items-start justify-between gap-2">
            <p className="font-semibold text-ink">{a.observation}</p>
            <button type="button" onClick={() => dismissToast(a.id)} className="text-muted hover:text-ink" aria-label="Dismiss"><X className="size-3.5" /></button>
          </div>
          <p className="mt-0.5 text-ink-2">{a.action}</p>
        </div>
      ))}
    </div>
  )
}

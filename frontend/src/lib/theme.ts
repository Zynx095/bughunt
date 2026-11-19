import { createContext, useContext } from 'react'

/** Central theme model. The provider (ThemeProvider.tsx) owns the state; everything else reads tokens. */
export type ThemePreference = 'system' | 'dark' | 'light'
export type ResolvedTheme = 'dark' | 'light'

const KEY = 'omniforge.theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'

export function loadThemePreference(): ThemePreference {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'dark' || v === 'light' || v === 'system') return v
  } catch {
    /* storage unavailable */
  }
  return 'system'
}

export function saveThemePreference(t: ThemePreference): void {
  try {
    localStorage.setItem(KEY, t)
  } catch {
    /* non-fatal */
  }
}

export function systemTheme(): ResolvedTheme {
  return typeof window !== 'undefined' && window.matchMedia(DARK_QUERY).matches ? 'dark' : 'light'
}

export function resolveTheme(t: ThemePreference): ResolvedTheme {
  return t === 'system' ? systemTheme() : t
}

let transitionTimer: number | undefined

/** Apply a resolved theme to <html>. With `animate`, colours ease for ~300 ms (skipped for reduced motion). */
export function applyResolvedTheme(theme: ResolvedTheme, animate: boolean): void {
  const root = document.documentElement
  const current = root.classList.contains('dark') ? 'dark' : root.classList.contains('light') ? 'light' : null
  if (current === theme) return
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (animate && !reduce) {
    root.classList.add('theme-transition')
    window.clearTimeout(transitionTimer)
    transitionTimer = window.setTimeout(() => root.classList.remove('theme-transition'), 320)
  }
  root.classList.toggle('dark', theme === 'dark')
  root.classList.toggle('light', theme === 'light')
  root.dataset.theme = theme
}

export function watchSystemTheme(onChange: (t: ResolvedTheme) => void): () => void {
  const mq = window.matchMedia(DARK_QUERY)
  const handler = () => onChange(mq.matches ? 'dark' : 'light')
  mq.addEventListener('change', handler)
  return () => mq.removeEventListener('change', handler)
}

export interface ThemeState {
  preference: ThemePreference
  resolved: ResolvedTheme
  setPreference: (t: ThemePreference) => void
}

export const ThemeContext = createContext<ThemeState | null>(null)

export function useTheme(): ThemeState {
  const v = useContext(ThemeContext)
  if (!v) throw new Error('useTheme outside ThemeProvider')
  return v
}

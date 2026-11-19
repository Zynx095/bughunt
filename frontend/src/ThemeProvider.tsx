import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import {
  applyResolvedTheme, loadThemePreference, resolveTheme, saveThemePreference, ThemeContext, watchSystemTheme,
  type ResolvedTheme, type ThemePreference,
} from './lib/theme'

/** Owns the light / dark / system preference, persists it, follows the OS in "system" mode and
 *  animates switches (the initial theme is applied before React mounts, see index.html). */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPref] = useState<ThemePreference>(loadThemePreference)
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolveTheme(loadThemePreference()))

  useEffect(() => {
    applyResolvedTheme(resolved, true)
  }, [resolved])

  useEffect(() => {
    if (preference !== 'system') return undefined
    return watchSystemTheme(setResolved)
  }, [preference])

  const setPreference = useCallback((t: ThemePreference) => {
    saveThemePreference(t)
    setPref(t)
    setResolved(resolveTheme(t))
  }, [])

  const value = useMemo(() => ({ preference, resolved, setPreference }), [preference, resolved, setPreference])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

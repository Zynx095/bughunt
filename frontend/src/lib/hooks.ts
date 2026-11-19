import { useCallback, useEffect, useState } from 'react'

import { get } from './api'

/** Fetch JSON on mount (and whenever `path` or `deps` change) with explicit loading/error state. */
export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState<boolean>(Boolean(path))

  const reload = useCallback(async () => {
    if (!path) return
    setLoading(true)
    try {
      setData(await get<T>(path))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps])

  useEffect(() => {
    void reload()
  }, [reload])

  return { data, error, loading, reload, setData }
}

function resolveIsDark(): boolean {
  if (typeof document === 'undefined') return false
  if (document.documentElement.classList.contains('dark')) return true
  if (document.documentElement.classList.contains('light')) return false
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

/** Track whether dark mode is currently active (via explicit class or OS preference). */
export function useDarkMode(): boolean {
  const [dark, setDark] = useState(resolveIsDark)

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setDark(resolveIsDark())
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })

    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => setDark(resolveIsDark())
    mq.addEventListener('change', onChange)

    return () => {
      observer.disconnect()
      mq.removeEventListener('change', onChange)
    }
  }, [])

  return dark
}

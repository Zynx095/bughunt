import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { live, liveSocketUrl } from './client'
import { DEFAULT_LAYERS, LiveContext, type Connection, type Layers, type LiveState } from './context'
import type { Alert, FrameMessage, SiteGeometry, Snapshot, StatusMessage } from './types'

const LAYERS_KEY = 'crowdguard.layers'

function loadLayers(): Layers {
  try {
    const raw = localStorage.getItem(LAYERS_KEY)
    if (raw) return { ...DEFAULT_LAYERS, ...(JSON.parse(raw) as Partial<Layers>) }
  } catch {
    /* defaults */
  }
  return DEFAULT_LAYERS
}

/** One WebSocket to the live monitor for the whole app. Reconnects with back-off; on reconnect the
 *  server immediately sends its newest snapshot, so the map never shows anything older than that. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const [connection, setConnection] = useState<Connection>('connecting')
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [status, setStatus] = useState<StatusMessage | null>(null)
  const [frame, setFrame] = useState<FrameMessage | null>(null)
  const [site, setSite] = useState<SiteGeometry | null>(null)
  const [wantFrames, setWantFrames] = useState(false)
  const [layers, setLayersState] = useState<Layers>(loadLayers)
  const [toasts, setToasts] = useState<Alert[]>([])
  const [lastMessageAt, setLastMessageAt] = useState(0)
  const pending = useRef<Snapshot | null>(null)

  const refreshSite = useCallback(async () => {
    setSite(await live.site())
  }, [])

  useEffect(() => {
    const id = window.setTimeout(() => { void refreshSite().catch(() => undefined) }, 0)
    return () => window.clearTimeout(id)
  }, [refreshSite])

  useEffect(() => {
    let ws: WebSocket | null = null
    let closed = false
    let backoff = 500
    let timer: number | undefined
    let raf = 0

    const flush = () => {
      raf = 0
      if (pending.current) {
        setSnapshot(pending.current)
        pending.current = null
      }
    }

    const connect = () => {
      ws = new WebSocket(liveSocketUrl(wantFrames))
      ws.onopen = () => {
        backoff = 500
        setConnection('open')
      }
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data as string) as Snapshot | StatusMessage | FrameMessage
        setLastMessageAt(Date.now())
        if (msg.type === 'snapshot') {
          // Coalesce to one React update per animation frame.
          pending.current = msg
          if (!raf) raf = requestAnimationFrame(flush)
          if (msg.new_alerts.length) {
            const fresh = msg.new_alerts.filter((a) => a.severity !== 'info' || a.kind === 'camera_reconnected')
            if (fresh.length) setToasts((t) => [...fresh, ...t].slice(0, 4))
          }
        } else if (msg.type === 'status') {
          setStatus(msg)
          if (msg.status === 'idle') setSnapshot(null)
        } else if (msg.type === 'frame') {
          setFrame(msg)
        }
      }
      ws.onclose = () => {
        if (closed) return
        setConnection('reconnecting')
        timer = window.setTimeout(connect, backoff)
        backoff = Math.min(5000, backoff * 2)
      }
      ws.onerror = () => ws?.close()
    }
    connect()
    return () => {
      closed = true
      window.clearTimeout(timer)
      if (raf) cancelAnimationFrame(raf)
      ws?.close()
    }
  }, [wantFrames])

  // The site geometry can change from another tab or a calibration that rescales it.
  const siteKey = snapshot ? `${snapshot.site.width_m}x${snapshot.site.height_m}x${snapshot.grid.rows}x${snapshot.grid.cols}` : ''
  useEffect(() => {
    if (!siteKey || !site) return
    if (`${site.width_m}x${site.height_m}x${site.rows}x${site.cols}` === siteKey) return
    const id = window.setTimeout(() => { void refreshSite().catch(() => undefined) }, 0)
    return () => window.clearTimeout(id)
  }, [siteKey, site, refreshSite])

  const setLayers = useCallback((l: Layers) => {
    setLayersState(l)
    try {
      localStorage.setItem(LAYERS_KEY, JSON.stringify(l))
    } catch {
      /* non-fatal */
    }
  }, [])
  const dismissToast = useCallback((id: string) => setToasts((t) => t.filter((a) => a.id !== id)), [])

  useEffect(() => {
    if (!toasts.length) return undefined
    const id = window.setTimeout(() => setToasts((t) => t.slice(0, -1)), 8000)
    return () => window.clearTimeout(id)
  }, [toasts])

  const value = useMemo<LiveState>(() => ({
    connection, snapshot, status, frame, site, refreshSite, setWantFrames, layers, setLayers, toasts, dismissToast, lastMessageAt,
  }), [connection, snapshot, status, frame, site, refreshSite, layers, setLayers, toasts, dismissToast, lastMessageAt])
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>
}

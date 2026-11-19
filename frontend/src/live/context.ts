import { createContext, useContext } from 'react'

import type { Alert, FrameMessage, SiteGeometry, Snapshot, StatusMessage } from './types'

export type Connection = 'connecting' | 'open' | 'reconnecting'

export interface Layers {
  heat: boolean
  free: boolean
  people: boolean
  vectors: boolean
  route: boolean
  zones: boolean
}

export interface LiveState {
  connection: Connection
  snapshot: Snapshot | null
  status: StatusMessage | null
  frame: FrameMessage | null
  site: SiteGeometry | null
  refreshSite: () => Promise<void>
  setWantFrames: (on: boolean) => void
  layers: Layers
  setLayers: (l: Layers) => void
  toasts: Alert[]
  dismissToast: (id: string) => void
  lastMessageAt: number
}

export const LiveContext = createContext<LiveState | null>(null)

export function useLive(): LiveState {
  const v = useContext(LiveContext)
  if (!v) throw new Error('useLive outside LiveProvider')
  return v
}

export const DEFAULT_LAYERS: Layers = { heat: true, free: true, people: true, vectors: true, route: true, zones: true }

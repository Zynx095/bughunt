import { createContext, useContext } from 'react'

import type { Frame, Simulation, Venue } from './types'

export interface ScenarioOptions {
  intervention: boolean
  exit_blockage: boolean
  feed_outage: boolean
}

export interface CrowdState {
  venue: Venue | null
  sim: Simulation | null
  frame: Frame | null
  tick: number
  setTick: (t: number) => void
  playing: boolean
  setPlaying: (p: boolean) => void
  speedMs: number
  setSpeedMs: (ms: number) => void
  options: ScenarioOptions
  setOptions: (o: ScenarioOptions) => void
  loading: boolean
  error: string | null
  load: () => void
  warnings: string[]
}

export const CrowdCtx = createContext<CrowdState | null>(null)

export function useCrowd(): CrowdState {
  const v = useContext(CrowdCtx)
  if (!v) throw new Error('useCrowd outside CrowdGuardProvider')
  return v
}

export const BAND_COLOR: Record<string, string> = {
  normal: '#10b981', elevated: '#f59e0b', high: '#f97316', critical: '#ef4444', unknown: '#71717a',
}

export const BAND_LABEL: Record<string, string> = {
  normal: 'Normal', elevated: 'Elevated', high: 'High', critical: 'Critical', unknown: 'Unknown',
}

export const SEVERITY_TONE: Record<string, 'bad' | 'warn' | 'neutral' | 'info'> = {
  critical: 'bad', high: 'bad', medium: 'warn', low: 'info', info: 'neutral',
}

export function fmtInt(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : Math.round(v).toLocaleString()
}

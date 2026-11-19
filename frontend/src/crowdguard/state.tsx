import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { cgResult } from './api'
import { CrowdCtx, type CrowdState, type ScenarioOptions } from './store'
import type { Simulation, Venue } from './types'

const DEFAULT_OPTIONS: ScenarioOptions = { intervention: true, exit_blockage: true, feed_outage: true }
const START_TICK = 38

/** Holds the venue and the deterministic simulation timeline shared by every CROWDGUARD screen. Loads lazily. */
export function CrowdGuardProvider({ children, active }: { children: ReactNode; active: boolean }) {
  const [venue, setVenue] = useState<Venue | null>(null)
  const [sim, setSim] = useState<Simulation | null>(null)
  const [tick, setTickState] = useState(START_TICK)
  const [playing, setPlaying] = useState(false)
  const [speedMs, setSpeedMs] = useState(900)
  const [options, setOptionsState] = useState<ScenarioOptions>(DEFAULT_OPTIONS)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const requested = useRef<string | null>(null)

  const fetchAll = useCallback(async (opts: ScenarioOptions) => {
    setLoading(true)
    setError(null)
    try {
      const [v, s] = await Promise.all([
        venue ? Promise.resolve({ result: venue }) : cgResult<Venue>('/venue'),
        cgResult<Simulation>('/simulation', { ...opts, detector_glitch: true }),
      ])
      setVenue(v.result)
      setSim(s.result)
      setWarnings(s.env.warnings)
      setTickState((t) => Math.min(t, s.result.frames.length - 1))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [venue])

  const load = useCallback(() => {
    requested.current = JSON.stringify(options)
    void fetchAll(options)
  }, [fetchAll, options])

  useEffect(() => {
    if (active && requested.current !== JSON.stringify(options)) load()
  }, [active, options, load])

  const setOptions = useCallback((o: ScenarioOptions) => {
    setPlaying(false)
    setOptionsState(o)
  }, [])

  const setTick = useCallback((t: number) => {
    setTickState(() => Math.max(0, Math.min(t, (sim?.frames.length ?? 1) - 1)))
  }, [sim])

  useEffect(() => {
    if (!playing || !sim) return
    const id = window.setInterval(() => {
      setTickState((t) => {
        if (t >= sim.frames.length - 1) {
          setPlaying(false)
          return t
        }
        return t + 1
      })
    }, speedMs)
    return () => window.clearInterval(id)
  }, [playing, sim, speedMs])

  const frame = sim ? sim.frames[Math.min(tick, sim.frames.length - 1)] : null
  const value = useMemo<CrowdState>(() => ({
    venue, sim, frame, tick, setTick, playing, setPlaying, speedMs, setSpeedMs, options, setOptions, loading, error, load, warnings,
  }), [venue, sim, frame, tick, setTick, playing, speedMs, options, setOptions, loading, error, load, warnings])
  return <CrowdCtx.Provider value={value}>{children}</CrowdCtx.Provider>
}

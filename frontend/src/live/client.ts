import { get, send, upload } from '../lib/api'
import type { EngineResponse } from '../lib/types'
import type { CameraInfo, Recording, SiteConfig, SiteGeometry, SourceSpec, StatusMessage } from './types'

/** The one client for live-monitoring endpoints. Engine-backed calls return the OMNIFORGE envelope;
 *  `unwrap` turns a failed envelope into an Error carrying the backend's message. */
async function unwrap<T>(p: Promise<EngineResponse<T>>): Promise<T> {
  const env = await p
  if (!env.success) throw new Error(env.error?.message ?? 'Request failed')
  return env.result
}

const base = '/api/crowdguard/live'

export const live = {
  status: () => unwrap(get<EngineResponse<StatusMessage & { detector: Record<string, unknown>; device: string }>>(`${base}/status`)),
  cameras: () => unwrap(get<EngineResponse<{ cameras: CameraInfo[] }>>(`${base}/cameras`)).then((r) => r.cameras),
  start: (source: SourceSpec, max_fps = 12) => unwrap(send<EngineResponse<StatusMessage>>('POST', `${base}/start`, { source, max_fps })),
  stop: () => unwrap(send<EngineResponse<StatusMessage>>('POST', `${base}/stop`)),
  site: () => unwrap(get<EngineResponse<SiteGeometry>>(`${base}/site`)),
  saveSite: (site: SiteConfig) => unwrap(send<EngineResponse<SiteGeometry>>('PUT', `${base}/site`, site)),
  calibrate: (body: { image_points: [number, number][]; width_m?: number; height_m?: number; confirmed: boolean }) =>
    unwrap(send<EngineResponse<Record<string, unknown>>>('POST', `${base}/calibration`, body)),
  origin: (body: { mode: 'auto' } | { mode: 'zone'; zone_id: string } | { mode: 'point'; x: number; y: number }) =>
    unwrap(send<EngineResponse<unknown>>('POST', `${base}/origin`, body)),
  portal: (portal_id: string, available: boolean) => unwrap(send<EngineResponse<SiteGeometry>>('POST', `${base}/portals`, { portal_id, available })),
  alerts: (limit = 150) => unwrap(get<EngineResponse<{ active: unknown[]; history: unknown[]; suppressed_duplicates: number }>>(`${base}/alerts?limit=${limit}`)),
  recordings: () => get<Recording[]>(`${base}/recordings`),
  uploadRecording: (file: File) => upload<{ id: string; filename: string }>(`${base}/recordings`, file),
  sampleRecording: () => send<{ id: string; filename: string; provenance: { label: string } }>('POST', `${base}/recordings/sample`),
}

export function liveSocketUrl(frames: boolean): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}${base}/ws${frames ? '?frames=1' : ''}`
}

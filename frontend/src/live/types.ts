/* Contract of the real-time monitoring API (/api/crowdguard/live/*). Mirrors backend/app/crowdguard/live_monitor.py. */

export type Pt = [number, number]
export type SourceKind = 'live_camera' | 'recorded_video' | 'synthetic'
export type MonitorStatus = 'idle' | 'starting' | 'running' | 'disconnected' | 'ended' | 'error' | 'stale'
export type Band = 'normal' | 'elevated' | 'high' | 'critical' | 'unknown' | 'restricted'
export type Severity = 'info' | 'low' | 'medium' | 'high' | 'critical'

export interface SourceInfo {
  kind: SourceKind
  live: boolean
  label: string
  width: number
  height: number
  native_fps: number | null
}

export interface LiveStats {
  fps: number
  capture_fps: number
  proc_ms: number | null
  e2e_ms: number | null
  processed: number
  captured: number
  skipped: number
  detections: number
  tracks: number
  started_at: number | null
  reconnects: number
}

export interface CalibrationInfo {
  image_points: Pt[]
  frame_size: [number, number]
  confirmed: boolean
  metric: boolean
  source: string
  visible_fraction: number
}

export interface Track {
  id: number
  box: [number, number, number, number]
  conf: number
  foot_px: Pt
  ground: Pt
  vel: Pt
  speed: number
  heading: number
  last_seen: number
  seen_ago_s: number
  predicted: boolean
  uncertainty_m: number
  in_view: boolean
}

export interface ZoneState {
  id: string
  name: string
  restricted: boolean
  capacity: number
  area_m2: number
  population: number | null
  occupancy_pct: number | null
  band: Band
  density: number | null
  density_index: number | null
  mean_speed: number | null
  visible_fraction: number
  note: string | null
}

export interface RouteRec {
  available: boolean
  reason?: string
  origin?: string
  exit_id?: string
  exit_name?: string
  exit_kind?: string
  points?: Pt[]
  length_m?: number
  walk_s?: number
  cost?: number
  held_s?: number
  pending_switch?: number
  naive?: { exit_id: string; exit_name: string; points: Pt[]; length_m: number; congested_points: Pt[]; unknown_cells: number } | null
  rejected_exits?: { id: string; name: string; reason: string }[]
  reasons?: string[]
  advisory?: string
}

export interface Alert {
  id: string
  key: string
  kind: string
  severity: Severity
  raised_at: number
  updated_at: number
  location: Record<string, string | number | null>
  observation: string
  action: string
  metrics: Record<string, unknown>
  status: 'active' | 'cleared' | 'event'
  escalated_at?: number
  cleared_at?: number
}

export interface Snapshot {
  type: 'snapshot'
  seq: number
  server_time: number
  frame: { index: number | null; captured_at: number | null; width: number; height: number }
  source: SourceInfo | null
  status: MonitorStatus
  error: { code: string; message: string } | null
  stats: LiveStats
  detector: string
  detection_failed: boolean
  tracker: string
  calibration: CalibrationInfo | null
  site: { id: string; width_m: number; height_m: number }
  tracks: Track[]
  grid: { rows: number; cols: number; cell_m: number; state: string; unit: string; values: number[]; free_m2: number[] }
  space: {
    available_m2: number; occupied_m2: number; congested_m2: number; blocked_m2: number; unknown_m2: number
    free_space_m2: number; observed_walkable_m2: number; observed_fraction: number; peak: number | null; people_in_view: number | null
  }
  zones: ZoneState[]
  zone_history: Record<string, number[]>
  route: RouteRec
  alerts: Alert[]
  new_alerts: Alert[]
}

export interface StatusMessage {
  type: 'status'
  status: MonitorStatus
  error: { code: string; message: string } | null
  source: SourceInfo | null
  source_key: string | null
  stats: LiveStats
  seq: number
  origin: { mode: 'auto' | 'zone' | 'point'; zone_id?: string; x?: number; y?: number }
  calibration: CalibrationInfo | null
  subscribers: number
  max_fps: number
}

export interface FrameMessage {
  type: 'frame'
  index: number
  captured_at: number
  width: number
  height: number
  image: string
}

export interface Portal {
  id: string
  name: string
  kind: 'entrance' | 'exit' | 'emergency_exit'
  a: Pt
  b: Pt
  available: boolean
}

export interface SiteZone {
  id: string
  name: string
  polygon: Pt[]
  capacity: number | null
  restricted: boolean
}

export interface Obstacle {
  id: string
  name: string
  polygon: Pt[]
}

export interface SiteConfig {
  id: string
  name: string
  width_m: number
  height_m: number
  cell_m: number
  walkable: Pt[] | null
  obstacles: Obstacle[]
  zones: SiteZone[]
  portals: Portal[]
  occupied_density: number
  congested_density: number
  kde_sigma_m: number
}

export interface SiteGeometry extends SiteConfig {
  rows: number
  cols: number
  blocked: string
  portal_capacity_ppm: Record<string, number>
  zone_area_m2: Record<string, number>
}

export interface CameraInfo {
  index: number
  backend?: string
  status: 'available' | 'no_frames' | 'in_use_by_crowdguard'
  width?: number
  height?: number
  label: string
  detail?: string
}

export interface Recording {
  id: string
  filename: string
  size: number
  created_at: string
}

export type SourceSpec =
  | { kind: 'webcam'; index: number }
  | { kind: 'stream'; url: string }
  | { kind: 'file'; document_id: string }
  | { kind: 'synthetic'; scenario: string }

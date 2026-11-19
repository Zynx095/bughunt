/* Types mirroring the CROWDGUARD backend (`crowd` engine). Every value shown in the UI comes from these payloads. */

export type Band = 'normal' | 'elevated' | 'high' | 'critical' | 'unknown'
export type FeedStatus = 'ok' | 'stale' | 'missing' | 'detector_error'
export type Severity = 'info' | 'low' | 'medium' | 'high' | 'critical'

export interface VenueZone {
  id: string
  name: string
  kind: string
  polygon: [number, number][]
  area_m2: number
  safe_capacity: number
  camera_id: string | null
  centroid: [number, number]
  service_rate_ppm?: number | null
}

export interface VenueNode {
  id: string
  name: string
  kind: 'zone' | 'gate' | 'exit' | 'junction'
  pos: [number, number]
  entrance?: boolean
  exit?: boolean
  emergency_exit?: boolean
}

export interface VenueEdge {
  id: string
  a: string
  b: string
  length_m: number
  width_m: number
  kind: string
  capacity_ppm: number
}

export interface CameraLayoutZone {
  id: string
  name: string
  polygon: [number, number][]
  area_m2: number
  safe_capacity: number
  venue_zone?: string
  coverage?: number
}

export interface CameraLayout {
  description: string
  meters_per_pixel: number | null
  zones: CameraLayoutZone[]
}

export interface Venue {
  id: string
  name: string
  synthetic: boolean
  canvas: { width: number; height: number; units: string }
  start_clock: string
  tick_seconds: number
  thresholds: Record<string, number>
  zones: VenueZone[]
  nodes: VenueNode[]
  edges: VenueEdge[]
  camera_layouts: Record<string, CameraLayout>
  graph: { nodes: number; edges: number; library: string }
}

export interface Reading {
  zone_id: string
  t: number
  source: string
  value_kind: 'synthetic' | 'measured'
  feed_status: FeedStatus
  observed_count: number | null
  estimate: number | null
  lower: number | null
  upper: number | null
  safe_capacity: number
  area_m2: number
  occupancy_pct: number | null
  upper_pct: number | null
  density_ppm2: number | null
  level_of_service: string | null
  band: Band
  confidence: number
  data_quality: 'good' | 'fair' | 'poor' | 'unavailable'
  method: string
  carried_forward: boolean
  age_s: number | null
  recall_assumed: number | null
  spare_capacity: number | null
  notes: string[]
  synthetic_truth?: number
  coverage?: number
}

export interface ZoneForecast {
  available: boolean
  method: string
  reason?: string
  history_points?: number
  horizon: number
  forecast: number[]
  lower: number[]
  upper: number[]
  current: number
  current_pct: number
  predicted_end: number
  predicted_end_pct: number
  peak: number
  peak_pct: number
  peak_in_min: number
  delta_vs_current: number
  minutes_to_capacity: number | null
  minutes_to_possible_breach: number | null
  p_exceed_at_horizon: number
}

export interface ZoneFlow {
  mean_speed?: number | null
  unit?: string
  stationary_fraction?: number | null
  inflow_ppm?: number
  outflow_ppm?: number
  net_ppm?: number
  vector?: [number, number]
  magnitude?: number
  direction?: string | null
}

export interface EdgeFlow {
  id: string
  from: string
  to: string
  flow_ppm: number
  capacity_ppm: number
  utilisation: number
  throughput_utilisation: number
}

export interface Alert {
  id: string
  rule: string
  severity: Severity
  type: string
  entity: 'zone' | 'exit' | 'edge'
  target: string
  target_name: string
  message: string
  rule_description: string
  confidence: number | null
  facts: Record<string, unknown>
}

export interface RouteCheck {
  name: string
  passed: boolean
  detail: string
}

export interface RouteOption {
  id: string
  path: string[]
  names: string[]
  destination: string
  destination_name: string
  edges: string[]
  length_m: number
  est_travel_s: number
  bottleneck_edge: string | null
  bottleneck_capacity_ppm: number | null
  time_to_move_group_min: number | null
  max_zone_pct_on_path: number | null
  unverified_zones: string[]
  checks: RouteCheck[]
  safety_score: number
  destination_spare: number | null
  score_note?: string
}

export interface RoutePlan {
  source: string
  source_name?: string
  purpose: 'relieve' | 'egress'
  group_size: number
  recommended: RouteOption | null
  alternatives?: RouteOption[]
  alternatives_count?: number
  shortest_path: { path: string[]; names: string[]; length_m: number; safe: boolean; checks: RouteCheck[]; destination?: string }
  allocation: { destination: string; destination_name: string; people: number; route_id: string; via: string[] }[]
  unallocated: number
  rejected_destinations: { id: string; name: string; reason: string }[]
  explanation: string[]
  advisory?: string
  blocked_edges?: string[]
  blocked_nodes?: string[]
}

export interface Recommendation {
  id: string
  priority: number
  severity: Severity
  action_type: string
  target: string
  target_name: string
  title: string
  detail: string
  rationale: string[]
  confidence: number | null
  requires_human_decision: boolean
  permitted: boolean
  guard: string
  route?: RoutePlan
  group_size?: number
}

export interface Summary {
  estimated_attendance: number
  attendance_lower: number
  attendance_upper: number
  zones_total: number
  zones_without_live_data: number
  zones_without_live_data_ids: string[]
  zones_high_or_critical: number
  alerts_critical: number
  alerts_high: number
  alerts_total: number
  exits_total: number
  exits_available: number
  coverage_note: string | null
}

export interface StoryEvent {
  tick: number
  kind: 'info' | 'hazard' | 'action'
  text: string
}

export interface Frame {
  tick: number
  clock: string
  t: number
  readings: Record<string, Reading>
  forecasts: Record<string, ZoneForecast>
  flows: Record<string, ZoneFlow>
  edge_flows: EdgeFlow[]
  exit_status: Record<string, 'open' | 'blocked'>
  alerts: Alert[]
  recommendations: Recommendation[]
  summary: Summary
  arrivals_ppm: Record<string, number>
  intervention_active: boolean
  events: StoryEvent[]
  incidents: { id: string; title: string; status: string }[]
}

export interface SimIncident {
  id: string
  title: string
  zone: string
  severity: Severity
  events: { tick: number; clock: string; status: string; actor: string; note: string }[]
}

export interface Simulation {
  scenario: Record<string, unknown> & { label: string; ticks: number; start_clock: string; intervention: boolean }
  frames: Frame[]
  incidents: SimIncident[]
  events: StoryEvent[]
  counterfactual: { label: string; main_stage: number[]; peak: number; peak_pct: number }
  evaluation: {
    estimation_error_vs_synthetic_truth: Record<string, { mae: number; bias: number; mape_pct: number }>
    main_stage_forecast_backtest: { available: boolean; horizon: number; origins: number; mae: number; baseline_mae: number; beats_baseline: boolean; mae_pct_of_capacity: number }
    main_stage_peak: { tick: number; clock: string; estimate: number; pct: number }
    milestones: Record<string, { tick: number; clock: string } | null>
    note: string
  }
}

export interface Envelope<T> {
  success: boolean
  engine: string
  result: T
  confidence: number | null
  execution_time_ms: number
  warnings: string[]
  metadata: Record<string, unknown>
  error: { code: string; message: string; details?: unknown } | null
}

export interface Incident {
  id: string
  title: string
  zone_id: string | null
  severity: Severity
  status: string
  source: string
  alert_id: string | null
  evidence: Record<string, unknown>
  evidence_hash: string
  events: { seq: number; ts: string; status: string; action: string; actor: string; role: string; note: string; prev_hash: string; hash: string }[]
  sealed_root: string | null
  created_by: string
  created_at: string
  updated_at: string
}

export type Role = 'viewer' | 'analyst' | 'reviewer' | 'admin'

export interface EngineError {
  code: string
  message: string
  details?: unknown
}

/** The universal engine response envelope (mirrors backend EngineResponse). */
export interface EngineResponse<T = Record<string, unknown>> {
  success: boolean
  engine: string
  result: T
  confidence: number | null
  execution_time_ms: number
  warnings: string[]
  metadata: Record<string, unknown>
  error: EngineError | null
}

export interface OperationInfo {
  name: string
  description: string
  access: 'read' | 'write' | 'sensitive'
  permission: string
  input_schema: JsonSchema
}

export interface EngineInfo {
  name: string
  title: string
  description: string
  health: Record<string, unknown> & { status: string; warning?: string }
  operations: OperationInfo[]
}

export interface JsonSchema {
  type?: string | string[]
  properties?: Record<string, JsonSchema>
  required?: string[]
  default?: unknown
  examples?: unknown[]
  enum?: unknown[]
  items?: JsonSchema
  anyOf?: JsonSchema[]
  $ref?: string
  $defs?: Record<string, JsonSchema>
  description?: string
  title?: string
}

export type SectionId =
  | 'overview' | 'workspace' | 'virtual-heatmap' | 'ingestion' | 'runs' | 'analytics' | 'approvals' | 'engines' | 'audit' | 'settings'

export interface StepInfo {
  id: string
  title: string
  engine: string
  operation: string
  why: string
  foreach: boolean
  optional: boolean
}

export interface DomainInfo {
  id: string
  name: string
  tagline: string
  description: string
  icon: string
  color: string
  scenario: string
  impact: string
  engines: string[]
  sections: SectionId[]
  steps: StepInfo[]
  input_schema: JsonSchema
  sample_input?: Record<string, unknown>
}

export interface Metric {
  label: string
  value: string | number | null
  tone: 'neutral' | 'good' | 'warn' | 'bad'
  hint?: string | null
}

export interface ChartSpec {
  type: 'bar' | 'line' | 'scatter'
  title: string
  data: Record<string, unknown>[]
  x: string
  series: { key: string; label: string }[]
  color_by?: string
  color_key?: string
  layout?: 'vertical'
  y_max?: number
  reference_lines?: { y: number; label: string }[]
}

export interface TableSpec {
  title: string
  columns: { key: string; label: string }[]
  rows: Record<string, unknown>[]
}

export interface Narrative {
  text: string
  source: string
  model?: string | null
  fallback: boolean
}

export interface Presentation {
  headline: string
  metrics: Metric[]
  charts: ChartSpec[]
  tables: TableSpec[]
  narrative: Narrative | null
  notes: string[]
  artifacts?: Record<string, unknown>
}

export interface RunStep {
  id: string
  title: string
  engine: string
  operation: string
  why?: string
  status: 'running' | 'completed' | 'failed' | 'skipped'
  warnings: string[]
  items: number
  execution_time_ms: number
  error?: string
  confidence?: number | null
  metadata?: Record<string, unknown>
  result?: unknown
}

export interface RunRecord {
  id: string
  domain: string
  status: 'running' | 'completed' | 'failed'
  actor: string
  role: string
  input?: Record<string, unknown>
  steps: RunStep[]
  presentation: Presentation | null
  error: string | null
  duration_ms: number
  created_at: string
  finished_at: string | null
  headline?: string | null
}

export interface AuditEvent {
  id: number
  ts: string
  category: string
  action: string
  actor: string
  role: string
  severity: string
  detail: Record<string, unknown>
  prev_hash: string
  hash: string
}

export interface Approval {
  id: string
  title: string
  action: string
  payload: Record<string, unknown>
  risk_score: number | null
  status: 'pending' | 'approved' | 'rejected'
  requested_by: string
  requested_role: string
  reviewer: string | null
  reviewer_role: string | null
  note: string | null
  run_id: string | null
  created_at: string
  decided_at: string | null
}

export interface DocumentRecord {
  id: string
  filename: string
  content_type: string
  kind: 'pdf' | 'image' | 'csv' | 'json' | 'txt'
  size: number
  sha256: string
  uploaded_by: string
  created_at: string
}

export interface DatasetRecord {
  id: string
  name: string
  source: string
  document_id: string | null
  columns: { column: string; type: string; missing: number; unique: number }[]
  row_count: number
  created_at: string
}

export interface Counts {
  executions: number
  failed_executions: number
  pipeline_runs: number
  documents: number
  datasets: number
  keys: number
  audit_events: number
  pending_approvals: number
  security_events: number
}

export interface ChainStatus {
  valid: boolean
  checked: number
  head?: string
  broken_at_id?: number
  reason?: string
}

export interface Health {
  status: string
  version: string
  database: string
  engines: Record<string, Record<string, unknown> & { status: string; warning?: string }>
}

export interface Overview {
  counts: Counts
  health: Health
  active_domain: string
  recent_runs: RunRecord[]
  recent_audit: AuditEvent[]
  audit_chain: ChainStatus
}

export interface Analytics {
  counts: Counts
  per_engine: { engine: string; count: number; success: number; avg_ms: number; max_ms: number }[]
  per_operation: { engine: string; operation: string; count: number; avg_ms: number }[]
  errors: { code: string; count: number }[]
  runs: { domain: string; status: string; count: number; avg_ms: number }[]
  recent: { id: number; engine: string; operation: string; ms: number; success: boolean; at: string }[]
}

export interface SettingsView {
  active_domain: string
  sections: SectionId[]
  all_sections: SectionId[]
  config: Record<string, unknown>
}

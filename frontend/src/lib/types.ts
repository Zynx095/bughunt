/** Shared platform types used by the CROWDGUARD client. */
export type Role = 'viewer' | 'analyst' | 'reviewer' | 'admin'

export interface EngineError {
  code: string
  message: string
  details?: unknown
}

/** The OMNIFORGE response envelope every engine-backed route returns. */
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

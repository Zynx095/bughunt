import type { EngineResponse, Role } from './types'

/**
 * Thin API client. Identity is *declared* through headers (simulated in the
 * foundation build); the backend enforces the policy for whatever role is sent.
 * No credentials or API keys ever live in the frontend.
 */
export interface Identity {
  role: Role
  actor: string
}

const IDENTITY_KEY = 'omniforge.identity'

export function loadIdentity(): Identity {
  try {
    const raw = localStorage.getItem(IDENTITY_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Identity
      if (parsed.role && parsed.actor) return parsed
    }
  } catch {
    /* storage unavailable: fall through to default */
  }
  return { role: 'analyst', actor: 'demo-analyst' }
}

export function saveIdentity(identity: Identity): void {
  try {
    localStorage.setItem(IDENTITY_KEY, JSON.stringify(identity))
  } catch {
    /* non-fatal */
  }
}

let identity: Identity = loadIdentity()
export const setApiIdentity = (next: Identity) => {
  identity = next
}

export class ApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, message: string, body: unknown) {
    super(message)
    this.status = status
    this.body = body
  }
}

function headers(extra?: Record<string, string>): Record<string, string> {
  return { 'X-Omniforge-Role': identity.role, 'X-Omniforge-Actor': identity.actor, ...extra }
}

async function parse<T>(res: Response): Promise<T> {
  const text = await res.text()
  let body: unknown = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = text
  }
  if (!res.ok) {
    // Engine envelopes carry their own error; return them so callers can render warnings + error together.
    if (body && typeof body === 'object' && 'success' in body && 'engine' in body) return body as T
    const detail = body && typeof body === 'object' && 'detail' in body ? (body as { detail: unknown }).detail : text
    throw new ApiError(res.status, typeof detail === 'string' ? detail : JSON.stringify(detail), body)
  }
  return body as T
}

export async function get<T>(path: string): Promise<T> {
  return parse<T>(await fetch(path, { headers: headers() }))
}

export async function send<T>(method: 'POST' | 'PUT', path: string, body?: unknown): Promise<T> {
  return parse<T>(await fetch(path, {
    method,
    headers: headers({ 'Content-Type': 'application/json' }),
    body: body === undefined ? undefined : JSON.stringify(body),
  }))
}

export async function upload<T>(path: string, file: File): Promise<T> {
  const form = new FormData()
  form.append('file', file)
  return parse<T>(await fetch(path, { method: 'POST', headers: headers(), body: form }))
}

export function callEngine<T = Record<string, unknown>>(engine: string, op: string, payload: unknown) {
  return send<EngineResponse<T>>('POST', `/api/engines/${engine}/${op}`, payload)
}

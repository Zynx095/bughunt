import { get, send } from '../lib/api'
import type { Envelope } from './types'

/** Calls a CROWDGUARD route and returns its engine envelope. Throws only on transport/HTTP errors without an envelope. */
export function cg<T>(path: string, body?: unknown): Promise<Envelope<T>> {
  return body === undefined ? get<Envelope<T>>(`/api/crowdguard${path}`) : send<Envelope<T>>('POST', `/api/crowdguard${path}`, body)
}

/** Unwrap an envelope or throw its error message. */
export async function cgResult<T>(path: string, body?: unknown): Promise<{ result: T; env: Envelope<T> }> {
  const env = await cg<T>(path, body)
  if (!env.success) throw new Error(env.error ? `${env.error.code}: ${env.error.message}` : 'Request failed')
  return { result: env.result, env }
}

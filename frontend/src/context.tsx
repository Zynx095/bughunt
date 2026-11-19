import { createContext, useContext } from 'react'

import type { Identity } from './lib/api'
import type { DomainInfo, SectionId } from './lib/types'

export interface AppState {
  domains: DomainInfo[]
  active: DomainInfo | null
  setActiveDomain: (id: string) => Promise<void>
  identity: Identity
  setIdentity: (i: Identity) => void
  navigate: (section: SectionId, param?: string) => void
  param: string | null
}

export const AppContext = createContext<AppState | null>(null)

export function useApp(): AppState {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp outside AppContext')
  return ctx
}

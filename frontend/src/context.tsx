import { createContext, useContext } from 'react'

import type { Identity } from './lib/api'
import type { DomainInfo, Health, SectionId } from './lib/types'

export type ThemePreference = 'system' | 'dark' | 'light'

export interface AppState {
  domains: DomainInfo[]
  active: DomainInfo | null
  setActiveDomain: (id: string) => Promise<void>
  identity: Identity
  setIdentity: (i: Identity) => void
  navigate: (section: SectionId, param?: string) => void
  param: string | null
  theme: ThemePreference
  setTheme: (theme: ThemePreference) => void
  health: Health | null
  pendingApprovalsCount: number
  refreshHealth: () => Promise<void>
}

export const AppContext = createContext<AppState | null>(null)

export function useApp(): AppState {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp outside AppContext')
  return ctx
}

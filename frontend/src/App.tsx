import React, { Suspense, useCallback, useEffect, useState } from 'react'

import { LiveProvider } from './live/LiveProvider'
import { StatusBar, Toasts, TopBar } from './shell/Shell'
import { SCREENS, type ScreenId } from './shell/screens'

const lazy = (load: () => Promise<Record<string, unknown>>, name: string) =>
  React.lazy(async () => ({ default: (await load())[name] as React.ComponentType }))

const VIEWS: Record<ScreenId, React.LazyExoticComponent<React.ComponentType>> = {
  command: lazy(() => import('./screens/CommandCentre'), 'CommandCentre'),
  camera: lazy(() => import('./screens/LiveCamera'), 'LiveCamera'),
  venue: lazy(() => import('./screens/VenueMap'), 'VenueMapScreen'),
  incidents: lazy(() => import('./screens/Incidents'), 'Incidents'),
  settings: lazy(() => import('./screens/Settings'), 'Settings'),
}

function screenFromHash(): ScreenId {
  const id = window.location.hash.replace(/^#\/?/, '').split('/')[0]
  return SCREENS.some((s) => s.id === id) ? (id as ScreenId) : 'command'
}

export default function App() {
  const [screen, setScreen] = useState<ScreenId>(screenFromHash)
  useEffect(() => {
    const on = () => setScreen(screenFromHash())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  const navigate = useCallback((s: ScreenId) => {
    window.location.hash = `/${s}`
  }, [])
  const View = VIEWS[screen]
  return (
    <LiveProvider>
      <div className="flex h-full flex-col bg-base text-ink">
        <TopBar screen={screen} onNavigate={navigate} />
        <main className="min-h-0 flex-1">
          <Suspense fallback={<div className="p-6 text-[13px] text-muted">Loading…</div>}>
            <View />
          </Suspense>
        </main>
        <StatusBar />
        <Toasts />
      </div>
    </LiveProvider>
  )
}

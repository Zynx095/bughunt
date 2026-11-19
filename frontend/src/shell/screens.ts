export type ScreenId = 'command' | 'camera' | 'venue' | 'incidents' | 'settings'

export const SCREENS: { id: ScreenId; label: string }[] = [
  { id: 'command', label: 'Command centre' },
  { id: 'camera', label: 'Live camera' },
  { id: 'venue', label: 'Venue map' },
  { id: 'incidents', label: 'Incidents' },
  { id: 'settings', label: 'Settings' },
]

/** What the system is doing right now, in words. */
export function monitorWords(status: string | undefined, kind: string | undefined): { word: string; colour: string } {
  if (!status || status === 'idle') return { word: 'Not monitoring', colour: 'var(--color-unknown)' }
  if (status === 'error') return { word: 'Source error', colour: 'var(--color-critical)' }
  if (status === 'disconnected' || status === 'stale') return { word: 'Feed lost', colour: 'var(--color-critical)' }
  if (status === 'ended') return { word: 'Recording ended', colour: 'var(--color-unknown)' }
  if (status === 'starting') return { word: 'Starting', colour: 'var(--color-elevated)' }
  if (kind === 'live_camera') return { word: 'Live', colour: 'var(--color-normal)' }
  if (kind === 'recorded_video') return { word: 'Recording playback', colour: 'var(--color-accent-2)' }
  return { word: 'Simulation', colour: 'var(--color-accent-2)' }
}


/** Map colours come from the CSS tokens so both themes stay in one place (index.css). */
export interface MapTokens {
  ground: string
  grid: string
  obstacle: string
  free: string
  line: string
  lineStrong: string
  ink: string
  ink2: string
  muted: string
  accent: string
  accent2: string
  normal: string
  elevated: string
  high: string
  critical: string
  unknown: string
}

export function readTokens(): MapTokens {
  const cs = getComputedStyle(document.documentElement)
  const v = (n: string) => cs.getPropertyValue(n).trim()
  return {
    ground: v('--color-map-ground'), grid: v('--color-map-grid'), obstacle: v('--color-map-obstacle'), free: v('--color-map-free'),
    line: v('--color-line'), lineStrong: v('--color-line-strong'), ink: v('--color-ink'), ink2: v('--color-ink-2'), muted: v('--color-muted'),
    accent: v('--color-accent'), accent2: v('--color-accent-2'), normal: v('--color-normal'), elevated: v('--color-elevated'),
    high: v('--color-high'), critical: v('--color-critical'), unknown: v('--color-unknown'),
  }
}

export function rgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

/** Zone status → colour token name. One meaning everywhere in the app. */
export const BAND_VAR: Record<string, string> = {
  normal: 'var(--color-normal)', elevated: 'var(--color-elevated)', high: 'var(--color-high)', critical: 'var(--color-critical)',
  unknown: 'var(--color-unknown)', restricted: 'var(--color-map-obstacle)',
}

export const BAND_TEXT: Record<string, string> = {
  normal: 'Normal', elevated: 'Elevated', high: 'High', critical: 'Critical', unknown: 'Unknown', restricted: 'Restricted',
}

export const SEVERITY_VAR: Record<string, string> = {
  critical: 'var(--color-critical)', high: 'var(--color-high)', medium: 'var(--color-elevated)', low: 'var(--color-ink-2)', info: 'var(--color-muted)',
}

/** Warm ramp for crowd density (0 = none, 1 = congestion threshold). Returns rgba components. */
export function heat(t: number, tk: MapTokens): [number, number, number, number] {
  if (t <= 0.04) return [0, 0, 0, 0]
  const stops: [number, string, number][] = [[0.04, tk.elevated, 0.0], [0.3, tk.elevated, 0.32], [0.65, tk.high, 0.5], [1.0, tk.critical, 0.62]]
  const x = Math.min(1, t)
  for (let i = 1; i < stops.length; i++) {
    const [t1, c1, a1] = stops[i]
    const [t0, c0, a0] = stops[i - 1]
    if (x <= t1) {
      const f = (x - t0) / (t1 - t0)
      const p = rgb(c0)
      const q = rgb(c1)
      return [p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f, p[2] + (q[2] - p[2]) * f, a0 + (a1 - a0) * f]
    }
  }
  const c = rgb(tk.critical)
  return [c[0], c[1], c[2], 0.62]
}

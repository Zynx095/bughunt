import { useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent, type ReactNode } from 'react'

import { useTheme } from '../lib/theme'
import type { Layers } from '../live/context'
import type { Pt, SiteGeometry, Snapshot } from '../live/types'
import { BAND_VAR, heat, readTokens, rgb } from './palette'

export type Selection = { kind: 'zone'; id: string } | { kind: 'track'; id: number } | null

interface Props {
  site: SiteGeometry
  snapshot: Snapshot | null
  layers: Layers
  selection?: Selection
  onSelect?: (s: Selection) => void
  pickPoint?: boolean
  onPickPoint?: (p: Pt) => void
  /** Editor hooks (Venue Map): pointer positions in metres, plus extra SVG content in metre coordinates. */
  onPointer?: (kind: 'down' | 'move' | 'up', p: Pt, e: RPointerEvent) => void
  overlay?: (scale: number) => ReactNode
  compact?: boolean
}

const CELL_PX = 8 // canvas pixels per grid cell for the state layer (enough for hatching)

/** The top-down map: canvas layers for cell states and the density heatmap, SVG for geometry, people,
 *  movement and the route. Everything drawn comes from the latest backend snapshot. */
export function SiteMap({ site, snapshot, layers, selection, onSelect, pickPoint, onPickPoint, onPointer, overlay, compact }: Props) {
  const { resolved } = useTheme()
  const wrap = useRef<HTMLDivElement>(null)
  const cellCanvas = useRef<HTMLCanvasElement>(null)
  const heatCanvas = useRef<HTMLCanvasElement>(null)
  const [box, setBox] = useState({ w: 0, h: 0 })
  const [hover, setHover] = useState<Pt | null>(null)
  const W = site.width_m
  const H = site.height_m

  useEffect(() => {
    const el = wrap.current
    if (!el) return undefined
    const ro = new ResizeObserver(([e]) => {
      const cw = e.contentRect.width
      const ch = e.contentRect.height
      const s = Math.min(cw / W, ch / H)
      setBox({ w: Math.floor(W * s), h: Math.floor(H * s) })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [W, H])
  const scale = box.w / W || 1 // CSS pixels per metre
  const grid = snapshot && snapshot.grid.rows === site.rows && snapshot.grid.cols === site.cols ? snapshot.grid : null

  // ---- cell-state layer (available / occupied / congested / blocked / unknown)
  useEffect(() => {
    const cv = cellCanvas.current
    if (!cv) return
    const tk = readTokens()
    const { rows, cols } = site
    cv.width = cols * CELL_PX
    cv.height = rows * CELL_PX
    const ctx = cv.getContext('2d')
    if (!ctx) return
    const img = ctx.createImageData(cv.width, cv.height)
    const crit = rgb(tk.critical)
    const obst = rgb(tk.obstacle)
    const unk = rgb(tk.unknown)
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const i = r * cols + c
        const st = grid ? grid.state[i] : site.blocked[i] === '1' ? 'B' : 'U'
        let col: [number, number, number] | null = null
        let a = 0
        let hatch = false
        if (st === 'B') { col = obst; a = 0.5 }
        else if (st === 'U') { col = unk; a = 0.22; hatch = true }
        else if (st === 'C') { col = crit; a = 0.2 }
        if (!col) continue
        for (let y = 0; y < CELL_PX; y++) {
          for (let x = 0; x < CELL_PX; x++) {
            const px = c * CELL_PX + x
            const py = r * CELL_PX + y
            let alpha = a
            if (hatch) alpha = (px + py) % 6 < 2 ? 0.55 : 0.12
            const o = (py * cv.width + px) * 4
            img.data[o] = col[0]
            img.data[o + 1] = col[1]
            img.data[o + 2] = col[2]
            img.data[o + 3] = Math.round(alpha * 255)
          }
        }
      }
    }
    ctx.putImageData(img, 0, 0)
  }, [grid, site, resolved])

  // ---- density heatmap (Gaussian KDE from the backend, smoothly upsampled)
  useEffect(() => {
    const cv = heatCanvas.current
    if (!cv || !box.w) return
    const ctx = cv.getContext('2d')
    if (!ctx) return
    cv.width = box.w
    cv.height = box.h
    ctx.clearRect(0, 0, box.w, box.h)
    if (!grid || (!layers.heat && !layers.free)) return
    const tk = readTokens()
    const free = rgb(tk.free)
    const area = site.cell_m * site.cell_m
    const small = document.createElement('canvas')
    small.width = grid.cols
    small.height = grid.rows
    const sctx = small.getContext('2d')
    if (!sctx) return
    const img = sctx.createImageData(grid.cols, grid.rows)
    const metric = grid.unit.startsWith('persons')
    for (let i = 0; i < grid.values.length; i++) {
      if (grid.state[i] === 'B' || grid.state[i] === 'U') continue
      const t = metric ? grid.values[i] / site.congested_density : grid.values[i]
      let [r, g, b, a] = layers.heat ? heat(t, tk) : [0, 0, 0, 0]
      if (a < 0.05 && layers.free && grid.state[i] === 'A') {
        // Open, observed floor: a light teal wash whose strength follows the usable free area.
        ;[r, g, b] = free
        a = 0.035 + 0.1 * Math.min(1, (grid.free_m2[i] ?? area) / area)
      }
      img.data[i * 4] = r
      img.data[i * 4 + 1] = g
      img.data[i * 4 + 2] = b
      img.data[i * 4 + 3] = Math.round(a * 255)
    }
    sctx.putImageData(img, 0, 0)
    ctx.imageSmoothingEnabled = true
    ctx.imageSmoothingQuality = 'high'
    ctx.drawImage(small, 0, 0, box.w, box.h)
  }, [grid, layers.heat, layers.free, box, site.congested_density, site.cell_m, resolved])

  const toMeters = (e: { clientX: number; clientY: number }, el: Element): Pt => {
    const r = el.getBoundingClientRect()
    return [((e.clientX - r.left) / r.width) * W, ((e.clientY - r.top) / r.height) * H]
  }

  const zoneState = useMemo(() => Object.fromEntries((snapshot?.zones ?? []).map((z) => [z.id, z])), [snapshot])
  const route = layers.route ? snapshot?.route : undefined
  const routeKey = route?.available ? `${route.exit_id}:${route.points?.length}:${route.points?.[0]?.join(',')}` : ''
  const fs = (px: number) => px / scale // font sizes in metres for a given pixel size
  const major = W <= 14 ? 1 : 5
  const hoverCell = hover && grid ? Math.min(grid.rows - 1, Math.floor(hover[1] / site.cell_m)) * grid.cols + Math.min(grid.cols - 1, Math.floor(hover[0] / site.cell_m)) : -1
  const STATE_WORD: Record<string, string> = { A: 'open floor', O: 'occupied', C: 'congested', B: 'blocked', U: 'not observed' }

  return (
    <div ref={wrap} className="relative flex h-full w-full items-center justify-center" style={{ minHeight: compact ? 180 : 320 }}>
      {box.w > 0 && (
        <div className="relative shadow-[0_0_0_1px_var(--color-line)]" style={{ width: box.w, height: box.h, background: 'var(--color-map-ground)' }}>
          <canvas ref={cellCanvas} className="pixelated absolute inset-0 h-full w-full" aria-hidden />
          <canvas ref={heatCanvas} className="absolute inset-0 h-full w-full" aria-hidden />
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className={`absolute inset-0 h-full w-full ${pickPoint ? 'cursor-crosshair' : ''}`}
            role="img" aria-label="Top-down map of the monitored area"
            onPointerMove={(e) => { const p = toMeters(e, e.currentTarget); setHover(p); onPointer?.('move', p, e) }}
            onPointerLeave={() => setHover(null)}
            onPointerDown={(e) => onPointer?.('down', toMeters(e, e.currentTarget), e)}
            onPointerUp={(e) => onPointer?.('up', toMeters(e, e.currentTarget), e)}
            onClick={(e) => {
              if (pickPoint && onPickPoint) onPickPoint(toMeters(e, e.currentTarget))
              else if (e.target === e.currentTarget) onSelect?.(null)
            }}>
            <defs>
              <pattern id="obstacle-hatch" width={0.4} height={0.4} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <rect width={0.4} height={0.4} fill="var(--color-map-obstacle)" opacity={0.55} />
                <line x1={0} y1={0} x2={0} y2={0.4} stroke="var(--color-map-ground)" strokeWidth={0.12} opacity={0.6} />
              </pattern>
              <linearGradient id="route-grad" gradientUnits="userSpaceOnUse"
                x1={route?.points?.[0]?.[0] ?? 0} y1={route?.points?.[0]?.[1] ?? 0}
                x2={route?.points?.at(-1)?.[0] ?? W} y2={route?.points?.at(-1)?.[1] ?? H}>
                <stop offset="0" stopColor="var(--color-accent)" />
                <stop offset="1" stopColor="var(--color-accent-2)" />
              </linearGradient>
              <marker id="arrow" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                <path d="M0 0 L10 5 L0 10 z" fill="var(--color-ink-2)" />
              </marker>
            </defs>

            {/* Metric grid (major lines) */}
            {Array.from({ length: Math.floor(W / major) + 1 }, (_, i) => (
              <line key={`gx${i}`} x1={i * major} y1={0} x2={i * major} y2={H} stroke="var(--color-map-grid)" strokeWidth={1} vectorEffect="non-scaling-stroke" pointerEvents="none" />
            ))}
            {Array.from({ length: Math.floor(H / major) + 1 }, (_, i) => (
              <line key={`gy${i}`} x1={0} y1={i * major} x2={W} y2={i * major} stroke="var(--color-map-grid)" strokeWidth={1} vectorEffect="non-scaling-stroke" pointerEvents="none" />
            ))}

            {site.walkable && (
              <polygon points={site.walkable.map((p) => p.join(',')).join(' ')} fill="none" stroke="var(--color-line-strong)"
                strokeWidth={1.5} strokeDasharray="6 4" vectorEffect="non-scaling-stroke" pointerEvents="none" />
            )}
            {site.obstacles.map((o) => (
              <polygon key={o.id} points={o.polygon.map((p) => p.join(',')).join(' ')} fill="url(#obstacle-hatch)" stroke="var(--color-map-obstacle)"
                strokeWidth={1} vectorEffect="non-scaling-stroke"><title>{o.name}</title></polygon>
            ))}

            {layers.zones && site.zones.map((z) => {
              const zs = zoneState[z.id]
              const band = z.restricted ? 'restricted' : zs?.band ?? 'unknown'
              const sel = selection?.kind === 'zone' && selection.id === z.id
              const xs = z.polygon.map((p) => p[0])
              const ys = z.polygon.map((p) => p[1])
              return (
                <g key={z.id} onClick={(e) => { e.stopPropagation(); onSelect?.({ kind: 'zone', id: z.id }) }} className="cursor-pointer">
                  <polygon points={z.polygon.map((p) => p.join(',')).join(' ')} fill={sel ? 'color-mix(in srgb, var(--color-accent) 7%, transparent)' : 'transparent'}
                    stroke={BAND_VAR[band]} strokeWidth={sel ? 2.5 : 1.5} vectorEffect="non-scaling-stroke"
                    strokeDasharray={band === 'unknown' ? '3 3' : undefined} />
                  {!compact && (
                    <text x={Math.min(...xs) + fs(8)} y={Math.min(...ys) + fs(18)} fontSize={fs(12.5)} fill="var(--color-ink)" className="font-display" fontWeight={600}
                      stroke="var(--color-map-ground)" strokeWidth={fs(3)} paintOrder="stroke">
                      {z.name}
                      <tspan fill={BAND_VAR[band]} fontWeight={500}>
                        {'  '}{z.restricted ? 'restricted' : zs?.population == null ? 'unknown' : `${Math.round(zs.population)} / ${zs.capacity}`}
                      </tspan>
                    </text>
                  )}
                </g>
              )
            })}

            {site.portals.map((p) => {
              const usable = p.available && !snapshot?.route.rejected_exits?.some((r) => r.id === p.id)
              const colour = p.kind === 'entrance' ? 'var(--color-ink-2)' : usable ? 'var(--color-accent)' : 'var(--color-critical)'
              const mx = (p.a[0] + p.b[0]) / 2
              const my = (p.a[1] + p.b[1]) / 2
              return (
                <g key={p.id}>
                  <title>{`${p.name} (${p.kind.replace('_', ' ')}) ${usable ? 'open' : 'unavailable'}`}</title>
                  <line x1={p.a[0]} y1={p.a[1]} x2={p.b[0]} y2={p.b[1]} stroke={colour} strokeWidth={6} strokeLinecap="round" vectorEffect="non-scaling-stroke"
                    strokeDasharray={usable ? undefined : '4 4'} />
                  {!compact && (
                    <text x={mx} y={my} dx={mx > W - 2 ? -fs(6) : fs(6)} dy={my < 2 ? fs(16) : my > H - 2 ? -fs(8) : fs(4)} fontSize={fs(11.5)}
                      textAnchor={mx > W - 2 ? 'end' : 'start'} fill={colour} fontWeight={600} stroke="var(--color-map-ground)" strokeWidth={fs(3)} paintOrder="stroke">
                      {p.kind === 'emergency_exit' ? `${p.name} (emergency)` : p.name}{usable ? '' : ' unavailable'}
                    </text>
                  )}
                </g>
              )
            })}

            {route?.available && route.naive && route.naive.exit_id !== route.exit_id && (
              <polyline points={route.naive.points.map((p) => p.join(',')).join(' ')} fill="none" stroke="var(--color-ink-2)" strokeWidth={1.5}
                strokeDasharray="2 5" vectorEffect="non-scaling-stroke" opacity={0.8} pointerEvents="none" />
            )}
            {route?.available && route.naive?.congested_points.map((p, i) => (
              <rect key={i} x={p[0] - site.cell_m / 2} y={p[1] - site.cell_m / 2} width={site.cell_m} height={site.cell_m} fill="none"
                stroke="var(--color-critical)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" pointerEvents="none" />
            ))}
            {route?.available && route.points && (
              <g key={routeKey} pointerEvents="none">
                <polyline points={route.points.map((p) => p.join(',')).join(' ')} fill="none" stroke="var(--color-map-ground)" strokeWidth={7}
                  strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" opacity={0.85} />
                <polyline points={route.points.map((p) => p.join(',')).join(' ')} fill="none" stroke="url(#route-grad)" strokeWidth={3.5}
                  strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" className="route-in" />
                <circle cx={route.points[0][0]} cy={route.points[0][1]} r={fs(5)} fill="var(--color-accent)" stroke="var(--color-map-ground)" strokeWidth={fs(2)} />
                <circle cx={route.points.at(-1)![0]} cy={route.points.at(-1)![1]} r={fs(8)} fill="none" stroke="var(--color-accent-2)" strokeWidth={fs(2.5)} />
              </g>
            )}

            {layers.people && snapshot?.tracks.filter((t) => t.in_view).map((t) => {
              const sel = selection?.kind === 'track' && selection.id === t.id
              const r = Math.max(0.12, fs(2.6))
              return (
                <g key={t.id} onClick={(e) => { e.stopPropagation(); onSelect?.({ kind: 'track', id: t.id }) }} className="cursor-pointer">
                  {sel && <circle cx={t.ground[0]} cy={t.ground[1]} r={t.uncertainty_m} fill="color-mix(in srgb, var(--color-accent) 12%, transparent)"
                    stroke="var(--color-accent)" strokeWidth={1} strokeDasharray="3 2" vectorEffect="non-scaling-stroke" />}
                  {layers.vectors && t.speed > 0.15 && !t.predicted && (
                    <line x1={t.ground[0]} y1={t.ground[1]} x2={t.ground[0] + t.vel[0] * 1.5} y2={t.ground[1] + t.vel[1] * 1.5}
                      stroke="var(--color-ink-2)" strokeWidth={1.25} vectorEffect="non-scaling-stroke" markerEnd="url(#arrow)" />
                  )}
                  <circle cx={t.ground[0]} cy={t.ground[1]} r={r} fill={t.predicted ? 'var(--color-map-ground)' : 'var(--color-ink)'}
                    stroke={t.predicted ? 'var(--color-ink-2)' : 'var(--color-map-ground)'} strokeWidth={1.25} vectorEffect="non-scaling-stroke"
                    strokeDasharray={t.predicted ? '2 1.5' : undefined}>
                    <title>{`Person ${t.id}${t.predicted ? ` (estimated, last seen ${t.seen_ago_s.toFixed(1)} s ago)` : ''}`}</title>
                  </circle>
                  {sel && (
                    <text x={t.ground[0] + r * 1.6} y={t.ground[1] - r * 1.4} fontSize={fs(12)} fill="var(--color-ink)" fontWeight={600}
                      stroke="var(--color-map-ground)" strokeWidth={fs(3)} paintOrder="stroke">#{t.id}</text>
                  )}
                </g>
              )
            })}
            {overlay?.(scale)}
          </svg>

          {!compact && (
            <>
              <div className="pointer-events-none absolute bottom-2 left-2 rounded bg-[var(--color-raised)]/90 px-2 py-1 text-[12px] text-ink-2 shadow-[0_0_0_1px_var(--color-line)]">
                {hover ? (
                  <span className="tabular">
                    {hover[0].toFixed(1)} m, {hover[1].toFixed(1)} m
                    {hoverCell >= 0 && grid && <> — {STATE_WORD[grid.state[hoverCell]]}{grid.state[hoverCell] !== 'B' && grid.state[hoverCell] !== 'U'
                      ? `, ${grid.unit.startsWith('persons') ? `${grid.values[hoverCell].toFixed(2)} p/m²` : `density index ${grid.values[hoverCell].toFixed(2)}`}` : ''}</>}
                  </span>
                ) : <span>{pickPoint ? 'Click where the route should start' : 'Point at the map for position and density'}</span>}
              </div>
              <ScaleBar scale={scale} metric={!!snapshot?.calibration?.metric} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

function ScaleBar({ scale, metric }: { scale: number; metric: boolean }) {
  const target = 90 / scale
  const steps = [0.5, 1, 2, 5, 10, 20, 50, 100]
  const m = steps.find((s) => s >= target) ?? 100
  return (
    <div className="pointer-events-none absolute bottom-2 right-2 rounded bg-[var(--color-raised)]/90 px-2 py-1 text-[12px] text-ink-2 shadow-[0_0_0_1px_var(--color-line)]">
      <div className="h-1.5 border-x border-b border-ink-2" style={{ width: m * scale }} aria-hidden />
      <div className="mt-0.5 tabular">{m} m{metric ? '' : ' (assumed scale)'}</div>
    </div>
  )
}

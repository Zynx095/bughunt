import { useMemo } from 'react'

import { BAND_COLOR, BAND_LABEL, fmtInt } from './store'
import type { EdgeFlow, Reading, RouteOption, Venue } from './types'

const BAND_MARK: Record<string, string> = { normal: '●', elevated: '▲', high: '▲', critical: '✖', unknown: '?' }

interface Props {
  venue: Venue
  readings?: Record<string, Reading> | null
  edgeFlows?: EdgeFlow[]
  exitStatus?: Record<string, 'open' | 'blocked'>
  route?: RouteOption | null
  altRoutes?: RouteOption[]
  selected?: string | null
  onSelect?: (id: string) => void
  blockedEdges?: Set<string>
  blockedNodes?: Set<string>
  onToggleEdge?: (id: string) => void
  onToggleNode?: (id: string) => void
  showFlows?: boolean
  compact?: boolean
  label?: string
}

function utilColour(u: number): string {
  if (u >= 0.9) return '#ef4444'
  if (u >= 0.7) return '#f59e0b'
  return '#38bdf8'
}

/** Schematic venue map: zone polygons by risk band (with text labels, never colour alone), corridor flows,
 *  exits and the recommended route. Everything drawn comes from backend readings. */
export function VenueMap({ venue, readings, edgeFlows = [], exitStatus = {}, route, altRoutes = [], selected, onSelect,
  blockedEdges, blockedNodes, onToggleEdge, onToggleNode, showFlows = true, compact = false, label }: Props) {
  const pos = useMemo(() => Object.fromEntries(venue.nodes.map((n) => [n.id, n.pos])), [venue])
  const W = venue.canvas?.width ?? 1000
  const H = venue.canvas?.height ?? 640
  const routePts = (r: RouteOption) => r.path.map((n) => pos[n]).filter(Boolean).map((p) => p.join(',')).join(' ')

  return (
    <div className="relative w-full overflow-hidden rounded-xl border border-line bg-surface">
      {label && <div className="border-b border-line px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted">{label}</div>}
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img"
        aria-label="Venue map showing zones, occupancy, flows, exits and routes">
        <defs>
          <pattern id="cg-hatch" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="10" height="10" fill="#71717a" opacity="0.12" />
            <line x1="0" y1="0" x2="0" y2="10" stroke="#71717a" strokeWidth="3" opacity="0.45" />
          </pattern>
          <pattern id="cg-grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="var(--color-line)" strokeWidth="1" />
          </pattern>
          {['#38bdf8', '#f59e0b', '#ef4444'].map((c) => (
            <marker key={c} id={`cg-arrow-${c.slice(1)}`} viewBox="0 0 10 10" refX="7" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill={c} />
            </marker>
          ))}
        </defs>
        <rect width={W} height={H} fill="url(#cg-grid)" opacity="0.6" />

        {/* Corridors */}
        {venue.edges.map((e) => {
          const a = pos[e.a]
          const b = pos[e.b]
          if (!a || !b) return null
          const blocked = blockedEdges?.has(e.id)
          const mx = (a[0] + b[0]) / 2
          const my = (a[1] + b[1]) / 2
          return (
            <g key={e.id} onClick={onToggleEdge ? () => onToggleEdge(e.id) : undefined} className={onToggleEdge ? 'cursor-pointer' : undefined}>
              <title>{`${e.id}: ${e.length_m} m × ${e.width_m} m, capacity ≈ ${Math.round(e.capacity_ppm)} people/min${blocked ? ' — BLOCKED (planner)' : ''}`}</title>
              <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="var(--color-ink-2)" strokeOpacity={0.16} strokeWidth={Math.max(4, e.width_m * 2.2)} strokeLinecap="round" />
              {onToggleEdge && <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="transparent" strokeWidth={18} />}
              {blocked && (
                <>
                  <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="#ef4444" strokeWidth={3} strokeDasharray="6 5" />
                  <text x={mx} y={my + 5} textAnchor="middle" fontSize="16" fontWeight="700" fill="#ef4444">✖</text>
                </>
              )}
            </g>
          )
        })}

        {/* Zone areas */}
        {venue.zones.map((z) => {
          const r = readings?.[z.id]
          const band = r?.band ?? 'unknown'
          const live = r && r.feed_status === 'ok'
          const colour = BAND_COLOR[band] ?? BAND_COLOR.unknown
          const pts = z.polygon.map((p) => p.join(',')).join(' ')
          const isSel = selected === z.id
          return (
            <g key={z.id} onClick={onSelect ? () => onSelect(z.id) : undefined} className={onSelect ? 'cursor-pointer' : undefined}>
              <title>{`${z.name}: ${r?.estimate != null ? `${fmtInt(r.estimate)} (${fmtInt(r.lower)}–${fmtInt(r.upper)}) of ${fmtInt(z.safe_capacity)}` : 'no data'} · ${BAND_LABEL[band]} · feed ${r?.feed_status ?? 'none'}`}</title>
              <polygon points={pts} fill={colour} fillOpacity={band === 'critical' ? 0.34 : 0.22} stroke={colour} strokeWidth={isSel ? 4 : 2}
                className={band === 'critical' ? 'cg-pulse' : undefined} />
              {!live && <polygon points={pts} fill="url(#cg-hatch)" />}
              {isSel && <polygon points={pts} fill="none" stroke="var(--color-ink)" strokeWidth={1.5} strokeDasharray="4 4" />}
            </g>
          )
        })}

        {/* Flows */}
        {showFlows && edgeFlows.filter((f) => f.flow_ppm >= 8).map((f) => {
          const a = pos[f.from]
          const b = pos[f.to]
          if (!a || !b) return null
          const dx = b[0] - a[0]
          const dy = b[1] - a[1]
          const len = Math.hypot(dx, dy) || 1
          const nx = -dy / len * 7
          const ny = dx / len * 7
          const s = 0.3
          const e = 0.7
          const c = utilColour(f.utilisation)
          return (
            <g key={`${f.id}-${f.from}`}>
              <title>{`${f.from} → ${f.to}: ${Math.round(f.flow_ppm)} people/min (${Math.round(f.utilisation * 100)}% of corridor capacity)`}</title>
              <line x1={a[0] + dx * s + nx} y1={a[1] + dy * s + ny} x2={a[0] + dx * e + nx} y2={a[1] + dy * e + ny}
                stroke={c} strokeWidth={1.5 + 5 * Math.min(1, f.flow_ppm / 300)} strokeLinecap="round" strokeDasharray="7 5"
                className="cg-flow" markerEnd={`url(#cg-arrow-${c.slice(1)})`} />
            </g>
          )
        })}

        {/* Alternative and recommended routes */}
        {altRoutes.map((r) => (
          <polyline key={r.id} points={routePts(r)} fill="none" stroke="var(--color-ink-2)" strokeOpacity={0.55} strokeWidth={3} strokeDasharray="3 6" strokeLinejoin="round" />
        ))}
        {route && (
          <g>
            <polyline points={routePts(route)} fill="none" stroke="#0ea5e9" strokeOpacity={0.25} strokeWidth={14} strokeLinejoin="round" strokeLinecap="round" />
            <polyline points={routePts(route)} fill="none" stroke="#0ea5e9" strokeWidth={5} strokeDasharray="12 7" strokeLinejoin="round" strokeLinecap="round" className="cg-flow" />
            {pos[route.path[0]] && <circle cx={pos[route.path[0]][0]} cy={pos[route.path[0]][1]} r={6} fill="#0ea5e9" stroke="white" strokeWidth={2} />}
            {pos[route.destination] && (
              <g>
                <circle cx={pos[route.destination][0]} cy={pos[route.destination][1]} r={11} fill="white" stroke="#0ea5e9" strokeWidth={4} />
                <text x={pos[route.destination][0]} y={pos[route.destination][1] + 4} textAnchor="middle" fontSize="11" fontWeight="800" fill="#0369a1">{route.id}</text>
              </g>
            )}
          </g>
        )}

        {/* Zone labels (on top, with halo) */}
        {venue.zones.map((z) => {
          const r = readings?.[z.id]
          const band = r?.band ?? 'unknown'
          const live = r && r.feed_status === 'ok'
          const colour = BAND_COLOR[band] ?? BAND_COLOR.unknown
          const [cx, cy] = z.centroid
          const small = z.area_m2 < 900 || compact
          return (
            <g key={z.id} pointerEvents="none" stroke="var(--color-surface)" strokeWidth={3} paintOrder="stroke" strokeLinejoin="round">
              <text x={cx} y={cy - (small ? 14 : 26)} textAnchor="middle" fontSize={small ? 11 : 13} fontWeight="600" fill="var(--color-ink)">{z.name}</text>
              {r?.estimate != null ? (
                <>
                  <text x={cx} y={cy + (small ? 4 : 2)} textAnchor="middle" fontSize={small ? 17 : 24} fontWeight="700" fill="var(--color-ink)" className="tabular">
                    {r.occupancy_pct?.toFixed(0)}%
                  </text>
                  <text x={cx} y={cy + (small ? 18 : 22)} textAnchor="middle" fontSize={small ? 9.5 : 11} fill="var(--color-ink-2)" className="tabular">
                    {fmtInt(r.estimate)} / {fmtInt(z.safe_capacity)}
                  </text>
                </>
              ) : (
                <text x={cx} y={cy + 4} textAnchor="middle" fontSize={small ? 11 : 13} fontWeight="700" fill="var(--color-ink-2)">NO DATA</text>
              )}
              <text x={cx} y={cy + (small ? 31 : 40)} textAnchor="middle" fontSize={small ? 9 : 10.5} fontWeight="700" fill={colour} letterSpacing="0.06em">
                {BAND_MARK[band]} {live ? BAND_LABEL[band].toUpperCase() : r?.carried_forward ? `STALE FEED · ${Math.round(r.age_s ?? 0)} s` : r?.feed_status === 'detector_error' ? 'DETECTION FAILED' : 'NO LIVE FEED'}
              </text>
            </g>
          )
        })}

        {/* Junctions, gates, exits */}
        {venue.nodes.filter((n) => n.kind !== 'zone').map((n) => {
          const [x, y] = n.pos
          if (n.kind === 'junction') {
            return <g key={n.id}><title>{n.name}</title><circle cx={x} cy={y} r={7} fill="var(--color-surface)" stroke="var(--color-ink-2)" strokeWidth={2} /></g>
          }
          const blocked = exitStatus[n.id] === 'blocked' || blockedNodes?.has(n.id)
          const emergency = !!n.emergency_exit
          const fill = blocked ? '#ef4444' : emergency ? '#16a34a' : '#475569'
          const text = emergency ? n.name.replace('Emergency Exit ', '') : n.name
          const w = Math.max(54, text.length * 6.6 + 18)
          const vertical = x < 40 || x > W - 40
          const bx = vertical ? (x < 40 ? 4 : W - w - 4) : x - w / 2
          const by = vertical ? y - 30 : y < 40 ? y - 12 : y - 12
          return (
            <g key={n.id} onClick={onToggleNode ? () => onToggleNode(n.id) : undefined} className={onToggleNode ? 'cursor-pointer' : undefined}>
              <title>{`${n.name}${emergency ? ' (emergency exit — can never be closed by a software recommendation)' : ''}: ${blocked ? 'BLOCKED' : 'open'}`}</title>
              <rect x={bx} y={by} width={w} height={vertical ? 60 : 24} rx={6} fill={fill} stroke="white" strokeWidth={1.5} />
              {vertical ? (
                <>
                  <text x={bx + w / 2} y={by + 18} textAnchor="middle" fontSize="10" fontWeight="800" fill="white">{emergency ? 'EMERGENCY' : 'EXIT'}</text>
                  <text x={bx + w / 2} y={by + 33} textAnchor="middle" fontSize="11" fontWeight="700" fill="white">{text}</text>
                  <text x={bx + w / 2} y={by + 49} textAnchor="middle" fontSize="10" fontWeight="800" fill="white">{blocked ? '✖ BLOCKED' : '✔ OPEN'}</text>
                </>
              ) : (
                <text x={bx + w / 2} y={by + 16} textAnchor="middle" fontSize="11" fontWeight="700" fill="white">{blocked ? `✖ ${text} BLOCKED` : `${text}`}</text>
              )}
            </g>
          )
        })}
      </svg>
      {!compact && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-3 py-2 text-[11px] text-ink-2">
          {(['normal', 'elevated', 'high', 'critical'] as const).map((b) => (
            <span key={b} className="flex items-center gap-1"><span className="inline-block size-2.5 rounded-sm" style={{ background: BAND_COLOR[b] }} aria-hidden />{BAND_MARK[b]} {BAND_LABEL[b]}</span>
          ))}
          <span className="flex items-center gap-1"><span className="inline-block size-2.5 rounded-sm" style={{ background: 'repeating-linear-gradient(45deg,#71717a55 0 3px,transparent 3px 6px)' }} aria-hidden />No live feed (unknown ≠ empty)</span>
          {showFlows && <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-4" style={{ background: '#38bdf8' }} aria-hidden />Flow (amber ≥70%, red ≥90% of corridor capacity)</span>}
          <span className="flex items-center gap-1"><span className="inline-block h-1 w-4 rounded" style={{ background: '#0ea5e9' }} aria-hidden />Recommended route</span>
          <span className="flex items-center gap-1"><span className="inline-block size-2.5 rounded-sm bg-[#16a34a]" aria-hidden />Emergency exit</span>
        </div>
      )}
    </div>
  )
}

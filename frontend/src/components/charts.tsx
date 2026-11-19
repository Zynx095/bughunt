import { Table2 } from 'lucide-react'
import { useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from 'recharts'

import { fmtValue } from '../lib/format'
import { useDarkMode } from '../lib/hooks'
import type { ChartSpec } from '../lib/types'
import { DataTable } from './table'
import { Card, Tabs } from './ui'

/* Validated categorical palette (fixed order, never cycled) + chart chrome, light and dark steps. */
const PALETTE = {
  light: {
    series: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'],
    grid: '#e1e0d9', axis: '#c3c2b7', muted: '#898781', surface: '#ffffff', ink: '#0b0b0b', ink2: '#52514e',
  },
  dark: {
    series: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#0ca30c', '#9085e9', '#e66767'],
    grid: '#2c2c2a', axis: '#383835', muted: '#898781', surface: '#1a1a19', ink: '#f0efec', ink2: '#c3c2b7',
  },
}
/* Status colours are reserved for states and always paired with a label. */
const STATUS = { low: '#0ca30c', medium: '#fab219', high: '#ec835a', critical: '#d03b3b' } as const

/** Forecast-style series names get fixed roles so meaning is stable across charts. */
function seriesStyle(key: string, index: number, series: string[]) {
  if (key === 'upper' || key === 'lower') return { stroke: series[1], dash: '3 3', width: 1, opacity: 0.55, dot: false }
  if (key === 'forecast') return { stroke: series[1], dash: '6 3', width: 2, opacity: 1, dot: false }
  if (key === 'anomaly' || key === 'flagged') return { stroke: 'transparent', dash: undefined, width: 0, opacity: 1, dot: true }
  return { stroke: series[index % series.length], dash: undefined, width: 2, opacity: 1, dot: false }
}

function useChartTheme() {
  return useDarkMode() ? PALETTE.dark : PALETTE.light
}

function TooltipBox({ active, payload, label, xKey }: { active?: boolean; payload?: { name?: string; value?: unknown; color?: string; payload?: Record<string, unknown> }[]; label?: unknown; xKey: string }) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload ?? {}
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 font-medium text-ink">{fmtValue(label ?? row[xKey])}</p>
      {payload.filter((p) => p.value !== null && p.value !== undefined).map((p, i) => (
        <p key={i} className="flex items-center gap-2 text-ink-2">
          <span className="inline-block size-2 rounded-full" style={{ background: p.color }} aria-hidden />
          <span>{p.name}</span>
          <span className="tabular ml-auto pl-3 font-medium text-ink">{fmtValue(p.value)}</span>
        </p>
      ))}
      {typeof row.band === 'string' && <p className="mt-1 text-muted">band: {row.band}</p>}
    </div>
  )
}

export function ChartCard({ spec }: { spec: ChartSpec }) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const columns = [{ key: spec.x, label: spec.x }, ...spec.series.filter((s) => s.label).map((s) => ({ key: s.key, label: s.label })),
    ...(spec.color_by ? [{ key: spec.color_by, label: spec.color_by }] : []), ...(spec.color_key ? [{ key: spec.color_key, label: spec.color_key }] : [])]
  return (
    <Card title={spec.title} actions={<Tabs value={view} onChange={setView} options={[{ id: 'chart', label: 'Chart' }, { id: 'table', label: 'Table' }]} />}>
      {view === 'chart' ? (
        <>
          <Chart spec={spec} />
          {spec.color_by && <BandLegend bands={[...new Set(spec.data.map((d) => String(d[spec.color_by as string])))]} />}
        </>
      ) : (
        <div className="max-h-80 overflow-auto"><DataTable columns={columns} rows={spec.data} /></div>
      )}
      {view === 'chart' && <p className="mt-2 flex items-center gap-1 text-[11px] text-muted"><Table2 className="size-3" aria-hidden /> Values are available in the Table view.</p>}
    </Card>
  )
}

export function Chart({ spec, height = 280 }: { spec: ChartSpec; height?: number }) {
  const t = useChartTheme()
  const axisProps = { stroke: t.axis, tickLine: false, tick: { fill: t.muted, fontSize: 11 } }
  const grid = <CartesianGrid stroke={t.grid} vertical={false} />
  const multi = spec.series.length > 1
  const refLines = (spec.reference_lines ?? []).map((r) => (
    <ReferenceLine key={r.label} y={r.y} stroke={t.muted} strokeDasharray="4 4"
      label={{ value: r.label, position: 'insideTopRight', fill: t.ink2, fontSize: 11 }} />
  ))

  if (spec.type === 'line') {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={spec.data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          {grid}
          <XAxis dataKey={spec.x} {...axisProps} minTickGap={28} />
          <YAxis {...axisProps} width={48} />
          <Tooltip content={<TooltipBox xKey={spec.x} />} cursor={{ stroke: t.axis }} />
          {multi && <Legend iconType="plainline" itemSorter={null} wrapperStyle={{ fontSize: 12 }} />}
          {refLines}
          {spec.series.map((s, i) => {
            const st = seriesStyle(s.key, i, t.series)
            const dotColor = t.series[7]
            return (
              <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={st.dot ? dotColor : st.stroke}
                strokeWidth={st.width} strokeDasharray={st.dash} strokeOpacity={st.opacity} connectNulls={false}
                isAnimationActive={false} legendType={st.dot ? 'circle' : 'plainline'}
                dot={st.dot ? { r: 5, fill: dotColor, stroke: t.surface, strokeWidth: 2 } : false}
                activeDot={st.dot ? { r: 6 } : { r: 4, stroke: t.surface, strokeWidth: 2 }} />
            )
          })}
        </LineChart>
      </ResponsiveContainer>
    )
  }

  if (spec.type === 'scatter') {
    const key = spec.color_key ?? ''
    const groups = key ? [...new Set(spec.data.map((d) => String(d[key])))].sort() : ['all']
    return (
      <ResponsiveContainer width="100%" height={height}>
        <ScatterChart margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={t.grid} />
          <XAxis type="number" dataKey="x" name="PC1" {...axisProps} />
          <YAxis type="number" dataKey="y" name="PC2" {...axisProps} width={40} />
          <Tooltip content={<TooltipBox xKey="x" />} cursor={{ strokeDasharray: '3 3' }} />
          {groups.length > 1 && <Legend itemSorter={null} wrapperStyle={{ fontSize: 12 }} />}
          {groups.map((g, i) => (
            <Scatter key={g} name={g} data={key ? spec.data.filter((d) => String(d[key]) === g) : spec.data}
              fill={t.series[i]} stroke={t.surface} strokeWidth={2} isAnimationActive={false} />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    )
  }

  // bar
  const vertical = spec.layout === 'vertical'
  const bandKey = spec.color_by
  return (
    <ResponsiveContainer width="100%" height={vertical ? Math.max(180, spec.data.length * 30 + 30) : height}>
      <BarChart data={spec.data} layout={vertical ? 'vertical' : 'horizontal'} margin={{ top: 8, right: 16, bottom: 0, left: vertical ? 24 : 0 }} barCategoryGap="25%">
        <CartesianGrid stroke={t.grid} horizontal={!vertical} vertical={vertical} />
        {vertical ? (
          <>
            <XAxis type="number" {...axisProps} domain={[0, spec.y_max ?? 'auto']} />
            <YAxis type="category" dataKey={spec.x} {...axisProps} width={150} interval={0} />
          </>
        ) : (
          <>
            <XAxis dataKey={spec.x} {...axisProps} interval={spec.data.length > 14 ? 'preserveStartEnd' : 0} />
            <YAxis {...axisProps} width={44} domain={[0, spec.y_max ?? 'auto']} />
          </>
        )}
        <Tooltip content={<TooltipBox xKey={spec.x} />} cursor={{ fill: t.grid, opacity: 0.4 }} />
        {multi && <Legend itemSorter={null} wrapperStyle={{ fontSize: 12 }} />}
        {refLines}
        {spec.series.map((s, i) => (
          <Bar key={s.key} dataKey={s.key} name={s.label} fill={t.series[i]} maxBarSize={24} isAnimationActive={false}
            radius={vertical ? [0, 4, 4, 0] : [4, 4, 0, 0]} stroke={t.surface} strokeWidth={bandKey ? 0 : 1}>
            {bandKey && spec.data.map((d, j) => <Cell key={j} fill={STATUS[d[bandKey] as keyof typeof STATUS] ?? t.series[0]} />)}
          </Bar>
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Legend for status-coloured bars: colour + label, never colour alone. */
export function BandLegend({ bands }: { bands: string[] }) {
  return (
    <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-ink-2">
      {bands.map((b) => (
        <span key={b} className="flex items-center gap-1">
          <span className="inline-block size-2.5 rounded-sm" style={{ background: STATUS[b as keyof typeof STATUS] }} aria-hidden />{b}
        </span>
      ))}
    </div>
  )
}

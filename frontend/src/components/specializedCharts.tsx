import { useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { fmtMs, fmtValue } from '../lib/format'
import { useDarkMode } from '../lib/hooks'
import { DataTable } from './table'
import { Card, Tabs } from './ui'

const PALETTE = {
  light: {
    series: ['#2563eb', '#ea580c', '#059669', '#d97706', '#db2777', '#16a34a', '#7c3aed', '#dc2626'],
    grid: '#e5e7eb',
    axis: '#9ca3af',
    surface: '#ffffff',
    ink: '#111827',
  },
  dark: {
    series: ['#3b82f6', '#f97316', '#10b981', '#f59e0b', '#ec4899', '#22c55e', '#8b5cf6', '#ef4444'],
    grid: '#27272a',
    axis: '#71717a',
    surface: '#111114',
    ink: '#f4f4f6',
  },
}

const BAND_COLORS: Record<string, string> = {
  low: '#10b981',
  medium: '#f59e0b',
  high: '#f97316',
  critical: '#ef4444',
}

/** 1. Risk Distribution Chart */
export function RiskDistributionChart({
  data,
  title = 'Risk Distribution',
}: {
  data: { range: string; count: number; band: 'low' | 'medium' | 'high' | 'critical' }[]
  title?: string
}) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const isDark = useDarkMode()
  const theme = isDark ? PALETTE.dark : PALETTE.light

  return (
    <Card
      title={title}
      actions={
        <Tabs
          value={view}
          onChange={setView}
          options={[
            { id: 'chart', label: 'Chart' },
            { id: 'table', label: 'Table' },
          ]}
        />
      }
    >
      {view === 'chart' ? (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={data} margin={{ top: 10, right: 10, bottom: 0, left: -10 }}>
            <CartesianGrid stroke={theme.grid} vertical={false} />
            <XAxis dataKey="range" stroke={theme.axis} tick={{ fill: theme.axis, fontSize: 11 }} />
            <YAxis stroke={theme.axis} tick={{ fill: theme.axis, fontSize: 11 }} allowDecimals={false} />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const item = payload[0].payload as { range: string; count: number; band: string }
                return (
                  <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-md">
                    <p className="font-semibold text-ink">{item.range}</p>
                    <p className="text-ink-2 mt-0.5">
                      Count: <span className="font-mono font-medium">{item.count}</span>
                    </p>
                    <p className="text-muted text-[10px] capitalize">Band: {item.band}</p>
                  </div>
                )
              }}
            />
            <Bar dataKey="count" radius={[4, 4, 0, 0]}>
              {data.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={BAND_COLORS[entry.band] ?? theme.series[0]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <DataTable
          columns={[
            { key: 'range', label: 'Score Range' },
            { key: 'count', label: 'Frequency' },
            { key: 'band', label: 'Risk Band' },
          ]}
          rows={data}
        />
      )}
    </Card>
  )
}

/** 2. Time-Series Analysis Chart with anomaly bounds */
export function TimeSeriesAnalysisChart({
  data,
  xKey = 'timestamp',
  valueKey = 'value',
  forecastKey,
  upperKey,
  lowerKey,
  title = 'Time-Series Telemetry',
}: {
  data: Record<string, unknown>[]
  xKey?: string
  valueKey?: string
  forecastKey?: string
  upperKey?: string
  lowerKey?: string
  title?: string
}) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const isDark = useDarkMode()
  const theme = isDark ? PALETTE.dark : PALETTE.light

  return (
    <Card
      title={title}
      actions={
        <Tabs
          value={view}
          onChange={setView}
          options={[
            { id: 'chart', label: 'Chart' },
            { id: 'table', label: 'Table' },
          ]}
        />
      }
    >
      {view === 'chart' ? (
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={data} margin={{ top: 10, right: 10, bottom: 0, left: -10 }}>
            <CartesianGrid stroke={theme.grid} vertical={false} />
            <XAxis dataKey={xKey} stroke={theme.axis} tick={{ fill: theme.axis, fontSize: 11 }} />
            <YAxis stroke={theme.axis} tick={{ fill: theme.axis, fontSize: 11 }} />
            <Tooltip
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null
                return (
                  <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-md">
                    <p className="font-semibold text-ink">{fmtValue(label)}</p>
                    {payload.map((p, i) => (
                      <p key={i} className="flex items-center gap-2 text-ink-2">
                        <span className="size-2 rounded-full" style={{ backgroundColor: p.color }} />
                        <span>{p.name}:</span>
                        <span className="font-mono font-medium">{fmtValue(p.value)}</span>
                      </p>
                    ))}
                  </div>
                )
              }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line
              type="monotone"
              dataKey={valueKey}
              name="Observed"
              stroke={theme.series[0]}
              strokeWidth={2}
              dot={{ r: 2 }}
              activeDot={{ r: 5 }}
            />
            {forecastKey && (
              <Line
                type="monotone"
                dataKey={forecastKey}
                name="Forecast"
                stroke={theme.series[1]}
                strokeWidth={2}
                strokeDasharray="4 4"
                dot={false}
              />
            )}
            {upperKey && (
              <Line
                type="monotone"
                dataKey={upperKey}
                name="Upper Bound"
                stroke={theme.series[3]}
                strokeWidth={1}
                strokeDasharray="2 2"
                dot={false}
              />
            )}
            {lowerKey && (
              <Line
                type="monotone"
                dataKey={lowerKey}
                name="Lower Bound"
                stroke={theme.series[3]}
                strokeWidth={1}
                strokeDasharray="2 2"
                dot={false}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <DataTable
          columns={[
            { key: xKey, label: 'Timestamp' },
            { key: valueKey, label: 'Observed' },
            ...(forecastKey ? [{ key: forecastKey, label: 'Forecast' }] : []),
          ]}
          rows={data}
        />
      )}
    </Card>
  )
}

/** 3. Classification Matrix / Confusion Heatmap */
export function ClassificationMatrixChart({
  data,
  title = 'Classification Distribution',
}: {
  data: { label: string; predicted: string; count: number }[]
  title?: string
}) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const isDark = useDarkMode()
  const theme = isDark ? PALETTE.dark : PALETTE.light

  return (
    <Card
      title={title}
      actions={
        <Tabs
          value={view}
          onChange={setView}
          options={[
            { id: 'chart', label: 'Chart' },
            { id: 'table', label: 'Table' },
          ]}
        />
      }
    >
      {view === 'chart' ? (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={data} layout="vertical" margin={{ top: 10, right: 10, bottom: 0, left: 30 }}>
            <CartesianGrid stroke={theme.grid} horizontal={false} />
            <XAxis type="number" stroke={theme.axis} tick={{ fill: theme.axis, fontSize: 11 }} />
            <YAxis
              type="category"
              dataKey="label"
              stroke={theme.axis}
              tick={{ fill: theme.axis, fontSize: 11 }}
              width={80}
            />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const item = payload[0].payload as { label: string; predicted: string; count: number }
                return (
                  <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-md">
                    <p className="font-semibold text-ink">Class: {item.label}</p>
                    <p className="text-ink-2">
                      Predicted as {item.predicted}:{' '}
                      <span className="font-mono font-medium">{item.count}</span>
                    </p>
                  </div>
                )
              }}
            />
            <Bar dataKey="count" fill={theme.series[2]} radius={[0, 4, 4, 0]} maxBarSize={20} />
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <DataTable
          columns={[
            { key: 'label', label: 'Ground Truth' },
            { key: 'predicted', label: 'Predicted' },
            { key: 'count', label: 'Sample Count' },
          ]}
          rows={data}
        />
      )}
    </Card>
  )
}

/** 4. Execution Trends & Latency Chart */
export function ExecutionTrendsChart({
  data,
  title = 'Execution Latency Trends',
}: {
  data: { n: number; ms: number; operation?: string; engine?: string }[]
  title?: string
}) {
  const isDark = useDarkMode()
  const theme = isDark ? PALETTE.dark : PALETTE.light

  return (
    <Card title={title}>
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={data} margin={{ top: 10, right: 10, bottom: 0, left: -10 }}>
          <defs>
            <linearGradient id="latencyGlow" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={theme.series[0]} stopOpacity={0.4} />
              <stop offset="95%" stopColor={theme.series[0]} stopOpacity={0.0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={theme.grid} vertical={false} />
          <XAxis dataKey="n" stroke={theme.axis} tick={{ fill: theme.axis, fontSize: 11 }} />
          <YAxis stroke={theme.axis} tick={{ fill: theme.axis, fontSize: 11 }} />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const item = payload[0].payload as { n: number; ms: number; operation?: string; engine?: string }
              return (
                <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-md">
                  <p className="font-semibold text-ink">Call #{item.n}</p>
                  {item.operation && (
                    <p className="font-mono text-[11px] text-muted">
                      {item.engine ? `${item.engine}.` : ''}
                      {item.operation}
                    </p>
                  )}
                  <p className="mt-1 font-mono font-medium text-ink">
                    Latency: <span className="text-[var(--accent)]">{fmtMs(item.ms)}</span>
                  </p>
                </div>
              )
            }}
          />
          <Area
            type="monotone"
            dataKey="ms"
            stroke={theme.series[0]}
            strokeWidth={2}
            fillOpacity={1}
            fill="url(#latencyGlow)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </Card>
  )
}

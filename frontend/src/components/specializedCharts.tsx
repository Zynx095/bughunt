import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { fmtMs } from '../lib/format'
import { useDarkMode } from '../lib/hooks'
import { Card } from './ui'

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


/** 1. Risk Distribution Chart */
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

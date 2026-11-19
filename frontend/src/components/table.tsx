import { useMemo, useState } from 'react'

import { fmtValue } from '../lib/format'
import { BandBadge } from './ui'
import { cx } from '../lib/cx'

const BAND_COLUMNS = new Set(['band', 'severity', 'risk_band', 'max_severity'])
const MONO_COLUMNS = new Set(['sha256', 'hash', 'value', 'txn_id', 'id', 'digest'])

export function DataTable({ columns, rows, maxRows = 200 }: {
  columns: { key: string; label: string }[]
  rows: Record<string, unknown>[]
  maxRows?: number
}) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null)
  const sorted = useMemo(() => {
    if (!sort) return rows
    return [...rows].sort((a, b) => {
      const x = a[sort.key], y = b[sort.key]
      if (typeof x === 'number' && typeof y === 'number') return (x - y) * sort.dir
      return String(x ?? '').localeCompare(String(y ?? '')) * sort.dir
    })
  }, [rows, sort])

  if (!rows.length) return <p className="py-4 text-center text-xs text-muted">No rows.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-xs">
        <thead>
          <tr className="border-b border-line">
            {columns.map((c) => (
              <th key={c.key} scope="col" className="whitespace-nowrap px-2 py-2 font-medium text-muted">
                <button type="button" className="hover:text-ink" onClick={() => setSort((s) => ({ key: c.key, dir: s?.key === c.key && s.dir === 1 ? -1 : 1 }))}>
                  {c.label}{sort?.key === c.key ? (sort.dir === 1 ? ' ↑' : ' ↓') : ''}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.slice(0, maxRows).map((r, i) => (
            <tr key={i} className="border-b border-line/70 last:border-0 hover:bg-surface-2/60">
              {columns.map((c) => {
                const v = r[c.key]
                const long = typeof v === 'string' && v.length > 60
                return (
                  <td key={c.key} className={cx('px-2 py-1.5 align-top text-ink-2', typeof v === 'number' && 'tabular text-right',
                    MONO_COLUMNS.has(c.key) && 'font-mono text-[11px]', long ? 'min-w-64 max-w-md' : 'whitespace-nowrap')}>
                    {BAND_COLUMNS.has(c.key) && typeof v === 'string' ? <BandBadge band={v} /> : (
                      <span className={long ? 'line-clamp-3' : undefined} title={long ? (v as string) : undefined}>{fmtValue(v)}</span>
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > maxRows && <p className="pt-2 text-xs text-muted">Showing {maxRows} of {rows.length} rows.</p>}
    </div>
  )
}

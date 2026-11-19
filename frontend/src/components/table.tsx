import { ArrowDown, ArrowUp, ArrowUpDown, Download, Search } from 'lucide-react'
import { useMemo, useState } from 'react'

import { cx } from '../lib/cx'
import { fmtValue } from '../lib/format'
import { BandBadge } from './ui'

const BAND_COLUMNS = new Set(['band', 'severity', 'risk_band', 'max_severity'])
const MONO_COLUMNS = new Set(['sha256', 'hash', 'value', 'txn_id', 'id', 'digest', 'code'])

export interface TableColumn {
  key: string
  label: string
}

export function DataTable({
  columns,
  rows,
  maxRows = 200,
  enableFilter = true,
  enableExport = true,
}: {
  columns: TableColumn[]
  rows: Record<string, unknown>[]
  maxRows?: number
  enableFilter?: boolean
  enableExport?: boolean
}) {
  const [filter, setFilter] = useState('')
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null)
  const [page, setPage] = useState(0)
  const pageSize = 50

  const filtered = useMemo(() => {
    if (!filter.trim()) return rows
    const q = filter.toLowerCase().trim()
    return rows.filter((r) =>
      columns.some((c) => {
        const v = r[c.key]
        return v !== null && v !== undefined && String(v).toLowerCase().includes(q)
      })
    )
  }, [rows, filter, columns])

  const sorted = useMemo(() => {
    const list = filtered.slice(0, maxRows)
    if (!sort) return list
    return [...list].sort((a, b) => {
      const x = a[sort.key]
      const y = b[sort.key]
      if (typeof x === 'number' && typeof y === 'number') return (x - y) * sort.dir
      return String(x ?? '').localeCompare(String(y ?? '')) * sort.dir
    })
  }, [filtered, sort, maxRows])

  const paginated = useMemo(() => {
    const start = page * pageSize
    return sorted.slice(start, start + pageSize)
  }, [sorted, page, pageSize])

  const exportCsv = () => {
    const headers = columns.map((c) => `"${c.label.replace(/"/g, '""')}"`).join(',')
    const lines = sorted.map((r) =>
      columns
        .map((c) => {
          const v = r[c.key]
          if (v === null || v === undefined) return '""'
          const s = typeof v === 'object' ? JSON.stringify(v) : String(v)
          return `"${s.replace(/"/g, '""')}"`
        })
        .join(',')
    )
    const blob = new Blob([headers + '\n' + lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `omniforge-table-${Date.now()}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (!rows.length) return <p className="py-4 text-center text-xs text-muted">No rows to display.</p>

  const totalPages = Math.ceil(sorted.length / pageSize)

  return (
    <div className="space-y-2">
      {(enableFilter || (enableExport && sorted.length > 0)) && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          {enableFilter ? (
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 size-3 -translate-y-1/2 text-muted" aria-hidden />
              <input
                type="text"
                placeholder="Search table…"
                value={filter}
                onChange={(e) => {
                  setFilter(e.target.value)
                  setPage(0)
                }}
                className="h-7 w-48 rounded-md border border-line bg-surface px-2.5 pl-7 text-xs text-ink outline-none focus:border-[var(--accent)]"
              />
            </div>
          ) : <div />}

          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] text-muted">
              {sorted.length} {sorted.length === 1 ? 'row' : 'rows'}
            </span>
            {enableExport && (
              <button
                type="button"
                onClick={exportCsv}
                className="flex items-center gap-1 rounded border border-line px-2 py-1 text-[11px] font-medium text-ink-2 hover:bg-surface-2 transition"
                title="Download as CSV"
              >
                <Download className="size-3" />
                <span>CSV</span>
              </button>
            )}
          </div>
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full border-collapse text-left text-xs">
          <thead className="bg-surface-2/60">
            <tr className="border-b border-line">
              {columns.map((c) => {
                const isSorted = sort?.key === c.key
                return (
                  <th key={c.key} scope="col" className="whitespace-nowrap px-3 py-2 font-medium text-muted">
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 hover:text-ink font-semibold"
                      onClick={() =>
                        setSort((s) => ({
                          key: c.key,
                          dir: s?.key === c.key && s.dir === 1 ? -1 : 1,
                        }))
                      }
                    >
                      <span>{c.label}</span>
                      {isSorted ? (
                        sort.dir === 1 ? (
                          <ArrowUp className="size-3 text-[var(--accent)]" />
                        ) : (
                          <ArrowDown className="size-3 text-[var(--accent)]" />
                        )
                      ) : (
                        <ArrowUpDown className="size-2.5 opacity-40 hover:opacity-100" />
                      )}
                    </button>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-line/60 bg-surface">
            {paginated.map((r, i) => (
              <tr key={i} className="hover:bg-surface-2/60 transition-colors">
                {columns.map((c) => {
                  const v = r[c.key]
                  const long = typeof v === 'string' && v.length > 60
                  return (
                    <td
                      key={c.key}
                      className={cx(
                        'px-3 py-2 align-top text-ink-2',
                        typeof v === 'number' && 'tabular text-right',
                        MONO_COLUMNS.has(c.key) && 'font-mono text-[11px]',
                        long ? 'min-w-64 max-w-md' : 'whitespace-nowrap'
                      )}
                    >
                      {BAND_COLUMNS.has(c.key) && typeof v === 'string' ? (
                        <BandBadge band={v} />
                      ) : (
                        <span className={long ? 'line-clamp-2' : undefined} title={long ? String(v) : undefined}>
                          {fmtValue(v)}
                        </span>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
            {paginated.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-3 py-6 text-center text-xs text-muted">
                  No records match the filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-muted pt-1">
          <span>
            Page {page + 1} of {totalPages}
          </span>
          <div className="flex items-center gap-1">
            <button
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
              className="rounded border border-line px-2 py-0.5 text-xs disabled:opacity-40 hover:bg-surface-2"
            >
              Previous
            </button>
            <button
              disabled={page >= totalPages - 1}
              onClick={() => setPage((p) => p + 1)}
              className="rounded border border-line px-2 py-0.5 text-xs disabled:opacity-40 hover:bg-surface-2"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

import { Check, ChevronDown, ChevronRight, Copy, Search } from 'lucide-react'
import { useMemo, useState } from 'react'

import { cx } from '../lib/cx'

interface Props {
  value: unknown
  title?: string
  maxHeight?: number | string
  collapsedInitially?: boolean
  defaultExpandDepth?: number
}

function JsonNode({
  name,
  value,
  depth = 0,
  maxDepth = 2,
  filter = '',
}: {
  name?: string
  value: unknown
  depth?: number
  maxDepth?: number
  filter?: string
}) {
  const [collapsed, setCollapsed] = useState(depth >= maxDepth)

  if (value === null) {
    return (
      <div className="font-mono text-xs leading-5">
        {name && <span className="text-muted">{name}: </span>}
        <span className="font-semibold text-rose-500 dark:text-rose-400">null</span>
      </div>
    )
  }

  if (typeof value === 'boolean') {
    return (
      <div className="font-mono text-xs leading-5">
        {name && <span className="text-muted">{name}: </span>}
        <span className="font-semibold text-amber-600 dark:text-amber-400">{String(value)}</span>
      </div>
    )
  }

  if (typeof value === 'number') {
    return (
      <div className="font-mono text-xs leading-5">
        {name && <span className="text-muted">{name}: </span>}
        <span className="font-medium text-emerald-600 dark:text-emerald-400">{value}</span>
      </div>
    )
  }

  if (typeof value === 'string') {
    const isUrl = /^https?:\/\//.test(value)
    const isHash = /^[a-fA-F0-9]{32,64}$/.test(value)
    return (
      <div className="font-mono text-xs leading-5">
        {name && <span className="text-muted">{name}: </span>}
        <span
          className={cx(
            'break-all',
            isHash
              ? 'text-cyan-600 dark:text-cyan-400'
              : isUrl
                ? 'underline text-blue-600 dark:text-blue-400'
                : 'text-ink-2'
          )}
        >
          &quot;{value}&quot;
        </span>
      </div>
    )
  }

  const isArray = Array.isArray(value)
  const entries = isArray
    ? (value as unknown[]).map((v, i) => [String(i), v] as const)
    : Object.entries(value as Record<string, unknown>)

  const filteredEntries = filter
    ? entries.filter(([k, v]) =>
        k.toLowerCase().includes(filter.toLowerCase()) ||
        JSON.stringify(v).toLowerCase().includes(filter.toLowerCase())
      )
    : entries

  return (
    <div className="font-mono text-xs leading-5">
      <div
        className="flex cursor-pointer items-center gap-1 text-ink hover:text-[var(--accent)]"
        onClick={() => setCollapsed(!collapsed)}
      >
        {collapsed ? (
          <ChevronRight className="size-3 shrink-0 text-muted" aria-hidden />
        ) : (
          <ChevronDown className="size-3 shrink-0 text-muted" aria-hidden />
        )}
        {name && <span className="font-semibold text-ink">{name}: </span>}
        <span className="text-muted">
          {isArray ? `Array(${entries.length})` : `Object{${entries.length}}`}
        </span>
      </div>
      {!collapsed && (
        <div className="ml-3 border-l border-line/60 pl-2">
          {filteredEntries.map(([k, v]) => (
            <JsonNode
              key={k}
              name={isArray ? undefined : k}
              value={v}
              depth={depth + 1}
              maxDepth={maxDepth}
              filter={filter}
            />
          ))}
          {filteredEntries.length === 0 && filter && (
            <div className="text-[11px] italic text-muted">No matches</div>
          )}
        </div>
      )}
    </div>
  )
}

export function JSONInspector({
  value,
  title,
  maxHeight = 360,
  defaultExpandDepth = 2,
}: Props) {
  const [filter, setFilter] = useState('')
  const [copied, setCopied] = useState(false)
  const [rawView, setRawView] = useState(false)

  const jsonString = useMemo(() => {
    try {
      return JSON.stringify(value, null, 2)
    } catch {
      return String(value)
    }
  }, [value])

  const copy = async () => {
    await navigator.clipboard.writeText(jsonString)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface-2">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-surface px-3 py-2 text-xs">
        <div className="flex items-center gap-2">
          {title && <span className="font-semibold text-ink">{title}</span>}
          <span className="font-mono text-[11px] text-muted">
            {(jsonString.length / 1024).toFixed(1)} KB
          </span>
        </div>
        <div className="flex items-center gap-2">
          {!rawView && (
            <div className="relative">
              <Search className="absolute left-2 top-1/2 size-3 -translate-y-1/2 text-muted" aria-hidden />
              <input
                type="text"
                placeholder="Filter keys/values…"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="h-6 w-32 rounded border border-line bg-surface-2 pl-6 pr-2 font-mono text-[11px] text-ink outline-none focus:w-44 focus:border-[var(--accent)] transition-all"
              />
            </div>
          )}
          <button
            type="button"
            onClick={() => setRawView(!rawView)}
            className="rounded border border-line px-2 py-0.5 text-[11px] font-medium text-ink-2 hover:bg-surface-2"
          >
            {rawView ? 'Tree' : 'Raw'}
          </button>
          <button
            type="button"
            onClick={() => void copy()}
            className="flex items-center gap-1 rounded border border-line px-2 py-0.5 text-[11px] font-medium text-ink-2 hover:bg-surface-2"
            title="Copy JSON"
          >
            {copied ? (
              <>
                <Check className="size-3 text-good-ink" />
                <span className="text-good-ink">Copied</span>
              </>
            ) : (
              <>
                <Copy className="size-3" />
                <span>Copy</span>
              </>
            )}
          </button>
        </div>
      </div>
      <div className="overflow-auto p-3" style={{ maxHeight }}>
        {rawView ? (
          <pre className="font-mono text-[11.5px] leading-relaxed text-ink-2 whitespace-pre-wrap break-all">
            {jsonString}
          </pre>
        ) : (
          <JsonNode value={value} maxDepth={defaultExpandDepth} filter={filter} />
        )}
      </div>
    </div>
  )
}

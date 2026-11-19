import { FileUp, ShieldCheck } from 'lucide-react'
import { useRef, useState } from 'react'

import { DataTable } from '../components/table'
import { Badge, Button, Card, Empty, ErrorBox, JsonView, PageHeader, Spinner, WarnBox } from '../components/ui'
import { callEngine, upload } from '../lib/api'
import { fmtBytes, fmtTime, short } from '../lib/format'
import { useApi } from '../lib/hooks'
import type { DatasetRecord, DocumentRecord, EngineResponse } from '../lib/types'

type Action = { label: string; engine: string; op: string; payload: (d: DocumentRecord) => Record<string, unknown> }

const ACTIONS: Record<DocumentRecord['kind'], Action[]> = {
  csv: [{ label: 'Ingest as dataset', engine: 'data', op: 'ingest', payload: (d) => ({ name: d.filename, document_id: d.id }) }],
  json: [{ label: 'Ingest as dataset', engine: 'data', op: 'ingest', payload: (d) => ({ name: d.filename, document_id: d.id }) }],
  pdf: [{ label: 'Extract text', engine: 'data', op: 'document_text', payload: (d) => ({ document_id: d.id }) },
    { label: 'Index for Q&A', engine: 'ai', op: 'rag_index', payload: (d) => ({ collection: 'uploads', document_ids: [d.id] }) }],
  txt: [{ label: 'Extract text', engine: 'data', op: 'document_text', payload: (d) => ({ document_id: d.id }) },
    { label: 'Index for Q&A', engine: 'ai', op: 'rag_index', payload: (d) => ({ collection: 'uploads', document_ids: [d.id] }) }],
  image: [{ label: 'Image features', engine: 'data', op: 'image_features', payload: (d) => ({ document_id: d.id }) }],
}

export function IngestionPage() {
  const docs = useApi<DocumentRecord[]>('/api/documents')
  const datasets = useApi<DatasetRecord[]>('/api/datasets')
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [result, setResult] = useState<{ title: string; resp: EngineResponse } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [question, setQuestion] = useState('')

  async function onUpload(files: FileList | null) {
    if (!files?.length) return
    setUploading(true)
    setUploadError(null)
    try {
      for (const f of Array.from(files)) await upload<DocumentRecord>('/api/documents', f)
      await docs.reload()
    } catch (e) {
      setUploadError((e as Error).message)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function act(title: string, engine: string, op: string, payload: Record<string, unknown>, key: string) {
    setBusy(key)
    try {
      const resp = await callEngine(engine, op, payload)
      setResult({ title, resp })
      if (op === 'ingest') await datasets.reload()
    } catch (e) {
      setResult({ title, resp: { success: false, engine, result: {}, confidence: null, execution_time_ms: 0, warnings: [], metadata: {}, error: { code: 'REQUEST_FAILED', message: (e as Error).message } } })
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader title="Data & documents" description="Upload CSV, JSON, PDF, text or images. File type is detected from content (not the client's claim), the SHA-256 is recorded at upload, and integrity can be re-verified at any time." />

      <Card title="Upload" subtitle="PDF · PNG/JPEG/WEBP · CSV · JSON · TXT/MD/LOG — max size set by OMNIFORGE_MAX_UPLOAD_MB">
        <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-line px-6 py-8 text-center hover:bg-surface-2"
          onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); void onUpload(e.dataTransfer.files) }}>
          <FileUp className="size-6 text-muted" aria-hidden />
          <span className="text-sm font-medium text-ink">{uploading ? 'Uploading…' : 'Drop files here or click to choose'}</span>
          <span className="text-xs text-muted">Uploads require the analyst role or higher</span>
          <input ref={fileRef} type="file" multiple className="sr-only" onChange={(e) => void onUpload(e.target.files)}
            accept=".pdf,.png,.jpg,.jpeg,.webp,.csv,.json,.txt,.md,.log" />
        </label>
        {uploadError && <div className="mt-3"><ErrorBox>{uploadError}</ErrorBox></div>}
      </Card>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card title="Documents" subtitle={docs.data ? `${docs.data.length} stored` : undefined} pad={false}>
          {docs.loading && !docs.data && <div className="p-4"><Spinner /></div>}
          {docs.error && <div className="p-4"><ErrorBox>{docs.error}</ErrorBox></div>}
          {docs.data?.length === 0 && <div className="p-4"><Empty title="No documents yet">Upload a file to get started.</Empty></div>}
          <ul className="divide-y divide-line">
            {docs.data?.map((d) => (
              <li key={d.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink">{d.filename} <Badge>{d.kind}</Badge></p>
                    <p className="mt-0.5 font-mono text-[11px] text-muted" title={d.sha256}>sha256 {short(d.sha256, 24)} · {fmtBytes(d.size)} · {d.uploaded_by} · {fmtTime(d.created_at)}</p>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {ACTIONS[d.kind].map((a) => (
                      <Button key={a.label} size="sm" busy={busy === d.id + a.op} onClick={() => void act(`${a.label}: ${d.filename}`, a.engine, a.op, a.payload(d), d.id + a.op)}>{a.label}</Button>
                    ))}
                    <Button size="sm" variant="ghost" busy={busy === d.id + 'verify'} onClick={() => void act(`Integrity: ${d.filename}`, 'crypto', 'verify_document', { document_id: d.id }, d.id + 'verify')}>
                      <ShieldCheck className="size-3.5" aria-hidden />Verify
                    </Button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </Card>

        <div className="space-y-5">
          <Card title="Ask the uploaded documents" subtitle="Retrieval over the 'uploads' collection (index PDFs/TXT first)">
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (question.trim().length >= 3) void act(`Q&A: ${question}`, 'ai', 'rag_query', { collection: 'uploads', question }, 'rag') }}>
              <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask a question…" aria-label="Question"
                className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-[var(--accent)]" />
              <Button type="submit" variant="primary" busy={busy === 'rag'} disabled={question.trim().length < 3}>Ask</Button>
            </form>
          </Card>

          <Card title="Result" subtitle={result?.title}>
            {!result && <Empty title="Run an action">Results of ingestion, extraction, Q&A and integrity checks appear here with their full engine envelope.</Empty>}
            {result && <EnvelopeSummary resp={result.resp} />}
          </Card>
        </div>
      </div>

      <Card title="Datasets" subtitle="Stored tables usable by any engine via dataset_id">
        {datasets.data?.length === 0 && <Empty title="No datasets">Ingest an uploaded CSV or JSON file.</Empty>}
        {datasets.data && datasets.data.length > 0 && (
          <DataTable columns={[{ key: 'name', label: 'Name' }, { key: 'id', label: 'dataset_id' }, { key: 'row_count', label: 'Rows' }, { key: 'cols', label: 'Columns' }, { key: 'created', label: 'Created' }]}
            rows={datasets.data.map((d) => ({ ...d, cols: d.columns.map((c) => `${c.column}:${c.type}`).join(', '), created: fmtTime(d.created_at) }))} />
        )}
      </Card>
    </div>
  )
}

export function EnvelopeSummary({ resp }: { resp: EngineResponse }) {
  const r = resp.result as Record<string, unknown>
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge tone={resp.success ? 'good' : 'bad'}>{resp.success ? 'success' : resp.error?.code}</Badge>
        <span className="text-muted">{resp.engine}.{String(resp.metadata.operation ?? '')} · {resp.execution_time_ms} ms</span>
        {resp.confidence !== null && <Badge>confidence {resp.confidence}</Badge>}
        {typeof resp.metadata.provider === 'string' && <Badge tone={resp.metadata.fallback ? 'neutral' : 'info'}>{resp.metadata.provider}</Badge>}
      </div>
      {resp.error && <ErrorBox>{resp.error.message}</ErrorBox>}
      {resp.warnings.map((w) => <WarnBox key={w}>{w}</WarnBox>)}
      {typeof r.intact === 'boolean' && (
        <p className={r.intact ? 'text-sm font-medium text-good-ink' : 'text-sm font-medium text-critical-ink'}>
          {r.intact ? '✓ File matches the hash recorded at upload' : '✗ File has changed since upload'}
        </p>
      )}
      {typeof r.answer === 'string' && <p className="rounded-lg bg-surface-2 p-3 text-sm text-ink">{r.answer}</p>}
      <JsonView value={resp.result} maxHeight={320} />
    </div>
  )
}

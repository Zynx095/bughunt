import { FileText, FileUp, ShieldAlert, ShieldCheck, Sparkles } from 'lucide-react'
import { useRef, useState } from 'react'

import { JSONInspector } from '../components/JSONInspector'
import { DataTable } from '../components/table'
import { Badge, Button, Card, Empty, ErrorBox, PageHeader, Spinner, WarnBox } from '../components/ui'
import { callEngine, upload } from '../lib/api'
import { fmtBytes, fmtTime, short } from '../lib/format'
import { useApi } from '../lib/hooks'
import type { DatasetRecord, DocumentRecord, EngineResponse } from '../lib/types'

type Action = {
  label: string
  engine: string
  op: string
  payload: (d: DocumentRecord) => Record<string, unknown>
}

const ACTIONS: Record<DocumentRecord['kind'], Action[]> = {
  csv: [{ label: 'Ingest Dataset', engine: 'data', op: 'ingest', payload: (d) => ({ name: d.filename, document_id: d.id }) }],
  json: [{ label: 'Ingest Dataset', engine: 'data', op: 'ingest', payload: (d) => ({ name: d.filename, document_id: d.id }) }],
  pdf: [
    { label: 'Extract Text', engine: 'data', op: 'document_text', payload: (d) => ({ document_id: d.id }) },
    { label: 'Index for RAG', engine: 'ai', op: 'rag_index', payload: (d) => ({ collection: 'uploads', document_ids: [d.id] }) },
  ],
  txt: [
    { label: 'Extract Text', engine: 'data', op: 'document_text', payload: (d) => ({ document_id: d.id }) },
    { label: 'Index for RAG', engine: 'ai', op: 'rag_index', payload: (d) => ({ collection: 'uploads', document_ids: [d.id] }) },
  ],
  image: [{ label: 'Extract Features', engine: 'data', op: 'image_features', payload: (d) => ({ document_id: d.id }) }],
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

  const onUpload = async (files: FileList | null) => {
    if (!files?.length) return
    setUploading(true)
    setUploadError(null)
    try {
      for (const f of Array.from(files)) {
        await upload<DocumentRecord>('/api/documents', f)
      }
      await docs.reload()
    } catch (e) {
      setUploadError((e as Error).message)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const act = async (
    title: string,
    engine: string,
    op: string,
    payload: Record<string, unknown>,
    key: string
  ) => {
    setBusy(key)
    try {
      const resp = await callEngine(engine, op, payload)
      setResult({ title, resp })
      if (op === 'ingest') await datasets.reload()
    } catch (e) {
      setResult({
        title,
        resp: {
          success: false,
          engine,
          result: {},
          confidence: null,
          execution_time_ms: 0,
          warnings: [],
          metadata: {},
          error: { code: 'REQUEST_FAILED', message: (e as Error).message },
        },
      })
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data Ingestion & Evidence Vault"
        description="Ingest tabular datasets (CSV/JSON), extract text from unstructured documents (PDF/TXT), generate dense semantic RAG embeddings, and cryptographically verify byte integrity using SHA-256."
      />

      {/* Upload Zone */}
      <Card title="Upload Evidence & Datasets" subtitle="Content-type sniffed by magic bytes on backend · SHA-256 digest recorded on disk">
        <label
          className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-line px-6 py-8 text-center transition hover:border-[var(--accent)] hover:bg-surface-2"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            void onUpload(e.dataTransfer.files)
          }}
        >
          <div className="rounded-full bg-[var(--accent)]/10 p-3 text-[var(--accent)]">
            <FileUp className="size-6" aria-hidden />
          </div>
          <span className="text-sm font-semibold text-ink">
            {uploading ? 'Uploading and computing SHA-256…' : 'Drop documents here or click to browse'}
          </span>
          <span className="text-xs text-muted">
            Supported: PDF, PNG, JPEG, WEBP, CSV, JSON, TXT, MD, LOG (requires Analyst role or above)
          </span>
          <input
            ref={fileRef}
            type="file"
            multiple
            className="sr-only"
            onChange={(e) => void onUpload(e.target.files)}
            accept=".pdf,.png,.jpg,.jpeg,.webp,.csv,.json,.txt,.md,.log"
          />
        </label>
        {uploadError && <div className="mt-3"><ErrorBox>{uploadError}</ErrorBox></div>}
      </Card>

      {/* Split View: Documents Vault & RAG / Operation Result */}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        {/* Document Records */}
        <Card
          title="Uploaded Documents Vault"
          subtitle={docs.data ? `${docs.data.length} documents archived with cryptographic hashes` : undefined}
          pad={false}
        >
          {docs.loading && !docs.data && <div className="p-8"><Spinner label="Querying Vault" /></div>}
          {docs.error && <div className="p-4"><ErrorBox>{docs.error}</ErrorBox></div>}
          {docs.data?.length === 0 && (
            <div className="p-8">
              <Empty title="No documents stored yet">
                Upload files above to trigger content extraction, RAG indexing, or dataset conversion.
              </Empty>
            </div>
          )}

          <ul className="divide-y divide-line">
            {docs.data?.map((d) => (
              <li key={d.id} className="p-4 hover:bg-surface-2/40 transition">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <FileText className="size-4 text-muted shrink-0" />
                      <span className="truncate text-sm font-semibold text-ink">{d.filename}</span>
                      <Badge tone="neutral">{d.kind}</Badge>
                    </div>
                    <p className="mt-1 font-mono text-[11px] text-muted truncate" title={d.sha256}>
                      SHA-256: {short(d.sha256, 20)} · {fmtBytes(d.size)} · By {d.uploaded_by} ·{' '}
                      {fmtTime(d.created_at)}
                    </p>
                  </div>

                  <div className="flex flex-wrap gap-1.5 shrink-0">
                    {ACTIONS[d.kind]?.map((a) => (
                      <Button
                        key={a.label}
                        size="sm"
                        busy={busy === d.id + a.op}
                        onClick={() =>
                          void act(`${a.label}: ${d.filename}`, a.engine, a.op, a.payload(d), d.id + a.op)
                        }
                      >
                        {a.label}
                      </Button>
                    ))}
                    <Button
                      size="sm"
                      variant="ghost"
                      busy={busy === d.id + 'verify'}
                      onClick={() =>
                        void act(
                          `Integrity Verification: ${d.filename}`,
                          'crypto',
                          'verify_document',
                          { document_id: d.id },
                          d.id + 'verify'
                        )
                      }
                    >
                      <ShieldCheck className="size-3.5" aria-hidden /> Verify Integrity
                    </Button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </Card>

        {/* Right: RAG Q&A and Output Envelope */}
        <div className="space-y-5">
          {/* RAG Query Card */}
          <Card
            title="Semantic Document Q&A"
            subtitle="Dense retrieval query over indexed PDF/TXT documents in the 'uploads' collection"
          >
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                if (question.trim().length >= 3) {
                  void act(
                    `RAG Query: "${question}"`,
                    'ai',
                    'rag_query',
                    { collection: 'uploads', question },
                    'rag'
                  )
                }
              }}
            >
              <input
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ask a question about uploaded documents…"
                aria-label="Semantic Query"
                className="h-9 min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 text-xs text-ink outline-none focus:border-[var(--accent)]"
              />
              <Button
                type="submit"
                variant="primary"
                busy={busy === 'rag'}
                disabled={question.trim().length < 3}
              >
                <Sparkles className="size-3.5" /> Ask
              </Button>
            </form>
          </Card>

          {/* Operation Result */}
          <Card
            title={result ? result.title : 'Engine Result'}
            subtitle={result ? 'Universal response envelope' : 'Extraction & verification outputs appear here'}
          >
            {!result ? (
              <Empty title="No active operation result">
                Click an action on any document (e.g. Extract Text, Verify Integrity) or run a Q&A query to see the engine envelope.
              </Empty>
            ) : (
              <EnvelopeSummary resp={result.resp} />
            )}
          </Card>
        </div>
      </div>

      {/* Datasets Table */}
      <Card
        title="Stored Tabular Datasets"
        subtitle="Ingested tables with column statistics accessible to ML and Decision engines by dataset_id"
      >
        {datasets.data?.length === 0 && (
          <Empty title="No datasets configured">
            Upload a CSV or JSON file above and click &quot;Ingest Dataset&quot;.
          </Empty>
        )}
        {datasets.data && datasets.data.length > 0 && (
          <DataTable
            columns={[
              { key: 'name', label: 'Dataset Name' },
              { key: 'id', label: 'Dataset ID' },
              { key: 'row_count', label: 'Rows' },
              { key: 'cols', label: 'Schema Columns' },
              { key: 'created', label: 'Ingested At' },
            ]}
            rows={datasets.data.map((d) => ({
              ...d,
              cols: d.columns.map((c) => `${c.column} (${c.type})`).join(', '),
              created: fmtTime(d.created_at),
            }))}
          />
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
        <Badge tone={resp.success ? 'good' : 'bad'}>
          {resp.success ? 'Success' : resp.error?.code ?? 'Failed'}
        </Badge>
        <span className="font-mono text-muted">
          {resp.engine}.{String(resp.metadata.operation ?? '')} · {resp.execution_time_ms} ms
        </span>
        {resp.confidence !== null && (
          <Badge tone="neutral">Confidence: {resp.confidence}</Badge>
        )}
        {typeof resp.metadata.provider === 'string' && (
          <Badge tone={resp.metadata.fallback ? 'neutral' : 'info'}>
            Provider: {resp.metadata.provider}
          </Badge>
        )}
      </div>

      {resp.error && <ErrorBox>{resp.error.message}</ErrorBox>}
      {resp.warnings.map((w, idx) => (
        <WarnBox key={idx}>{w}</WarnBox>
      ))}

      {typeof r.intact === 'boolean' && (
        <div
          className={`flex items-center gap-2 rounded-lg p-3 text-xs font-semibold ${
            r.intact
              ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/30'
              : 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border border-rose-500/30'
          }`}
        >
          {r.intact ? <ShieldCheck className="size-5" /> : <ShieldAlert className="size-5" />}
          <span>
            {r.intact
              ? 'CRYPTOGRAPHIC MATCH: File content strictly matches the SHA-256 recorded at upload.'
              : 'TAMPER DETECTED: File content hash differs from the hash recorded at upload!'}
          </span>
        </div>
      )}

      {typeof r.answer === 'string' && (
        <div className="rounded-lg bg-surface-2 p-3 text-xs text-ink leading-relaxed border border-line">
          <p className="font-semibold text-ink mb-1 flex items-center gap-1.5">
            <Sparkles className="size-3.5 text-[var(--accent)]" /> Generated RAG Response:
          </p>
          <p className="whitespace-pre-line">{r.answer}</p>
        </div>
      )}

      <JSONInspector title="Result Payload" value={resp.result} defaultExpandDepth={2} />
    </div>
  )
}

import { AlertTriangle, Check, Copy, FileText, KeyRound, ShieldAlert, ShieldCheck } from 'lucide-react'
import { useState } from 'react'

import { short } from '../lib/format'
import { JSONInspector } from './JSONInspector'
import { Badge, Card } from './ui'

export interface EvidenceItem {
  id?: string | number
  name: string
  sha256: string
  bytes?: number
  proof_steps?: number
}

interface EvidenceViewerProps {
  caseId?: string
  merkleRoot?: string
  signatureHex?: string
  publicKeyHex?: string
  signatureValid?: boolean
  items?: EvidenceItem[]
  tamperTest?: {
    originalValid: boolean
    alteredValid: boolean
    detected: boolean
  }
  artifacts?: Record<string, unknown>
}

export function EvidenceViewer({
  caseId,
  merkleRoot,
  signatureHex,
  publicKeyHex,
  signatureValid = true,
  items = [],
  tamperTest,
  artifacts,
}: EvidenceViewerProps) {
  const [copiedKey, setCopiedKey] = useState<string | null>(null)

  const copy = async (text: string, key: string) => {
    await navigator.clipboard.writeText(text)
    setCopiedKey(key)
    setTimeout(() => setCopiedKey(null), 2000)
  }

  return (
    <div className="space-y-4">
      {/* Cryptographic seal status banner */}
      <div className="rounded-xl border border-line bg-surface p-4 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="rounded-lg bg-[var(--accent)]/10 p-2.5 text-[var(--accent)]">
              {signatureValid ? (
                <ShieldCheck className="size-6 text-good-ink" />
              ) : (
                <ShieldAlert className="size-6 text-critical-ink" />
              )}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold text-ink">
                  {caseId ? `Case Evidence Vault: ${caseId}` : 'Cryptographic Evidence Vault'}
                </h3>
                <Badge tone={signatureValid ? 'good' : 'bad'}>
                  {signatureValid ? 'Ed25519 Sealed' : 'Invalid Signature'}
                </Badge>
              </div>
              <p className="mt-1 text-xs text-muted max-w-xl">
                Tamper-evident chain of custody using SHA-256 Merkle tree leaves and Ed25519 asymmetric signature.
              </p>
            </div>
          </div>

          {merkleRoot && (
            <div className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-right">
              <span className="block text-[10px] font-semibold uppercase tracking-wider text-muted">
                Merkle Root (SHA-256)
              </span>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="font-mono text-xs font-semibold text-ink">
                  {short(merkleRoot, 20)}
                </span>
                <button
                  type="button"
                  onClick={() => void copy(merkleRoot, 'merkle')}
                  className="rounded p-1 text-muted hover:text-ink"
                  title="Copy full Merkle root"
                >
                  {copiedKey === 'merkle' ? <Check className="size-3 text-good-ink" /> : <Copy className="size-3" />}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Signature details */}
        {(signatureHex || publicKeyHex) && (
          <div className="mt-4 grid gap-3 border-t border-line/60 pt-3 sm:grid-cols-2 text-xs">
            {signatureHex && (
              <div className="flex items-center justify-between gap-2 rounded border border-line/60 bg-surface-2 px-2.5 py-1.5 font-mono">
                <span className="text-muted flex items-center gap-1"><KeyRound className="size-3" />Sig:</span>
                <span className="truncate text-ink-2">{short(signatureHex, 24)}</span>
                <button onClick={() => void copy(signatureHex, 'sig')} className="text-muted hover:text-ink">
                  {copiedKey === 'sig' ? <Check className="size-3 text-good-ink" /> : <Copy className="size-3" />}
                </button>
              </div>
            )}
            {publicKeyHex && (
              <div className="flex items-center justify-between gap-2 rounded border border-line/60 bg-surface-2 px-2.5 py-1.5 font-mono">
                <span className="text-muted flex items-center gap-1"><KeyRound className="size-3" />Pub:</span>
                <span className="truncate text-ink-2">{short(publicKeyHex, 24)}</span>
                <button onClick={() => void copy(publicKeyHex, 'pub')} className="text-muted hover:text-ink">
                  {copiedKey === 'pub' ? <Check className="size-3 text-good-ink" /> : <Copy className="size-3" />}
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Tamper check banner if present */}
      {tamperTest && (
        <div className="flex items-start gap-3 rounded-xl border border-line bg-surface p-4">
          <div className="rounded-lg bg-surface-2 p-2 text-muted">
            {tamperTest.detected ? (
              <ShieldCheck className="size-5 text-good-ink" />
            ) : (
              <AlertTriangle className="size-5 text-warn-ink" />
            )}
          </div>
          <div>
            <p className="text-xs font-semibold text-ink">
              Live Tamper Detection Verification:{' '}
              <span className={tamperTest.detected ? 'text-good-ink' : 'text-critical-ink'}>
                {tamperTest.detected ? 'PASS (Tampering Successfully Detected)' : 'FAIL'}
              </span>
            </p>
            <p className="mt-0.5 text-xs text-muted">
              Original item proof verified against signed root. Altered variant failed Merkle inclusion proof check.
            </p>
          </div>
        </div>
      )}

      {/* Evidence items table */}
      {items.length > 0 && (
        <Card title={`Sealed Evidence Items (${items.length})`} subtitle="Individual SHA-256 leaf hashes and Merkle audit paths" pad={false}>
          <div className="max-h-72 overflow-auto">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-surface border-b border-line text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Item Name</th>
                  <th className="px-3 py-2 font-medium">SHA-256 Digest</th>
                  {items.some((i) => i.proof_steps !== undefined) && (
                    <th className="px-3 py-2 font-medium">Proof Depth</th>
                  )}
                  {items.some((i) => i.bytes !== undefined) && (
                    <th className="px-3 py-2 text-right font-medium">Size</th>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-line/60">
                {items.map((item, idx) => (
                  <tr key={idx} className="hover:bg-surface-2/60">
                    <td className="px-3 py-2 font-medium text-ink flex items-center gap-1.5">
                      <FileText className="size-3.5 text-muted shrink-0" />
                      <span className="truncate max-w-xs">{item.name}</span>
                    </td>
                    <td className="px-3 py-2 font-mono text-[11px] text-ink-2">
                      <div className="flex items-center gap-1">
                        <span>{short(item.sha256, 20)}</span>
                        <button
                          type="button"
                          onClick={() => void copy(item.sha256, `item-${idx}`)}
                          className="text-muted hover:text-ink"
                          title="Copy digest"
                        >
                          {copiedKey === `item-${idx}` ? (
                            <Check className="size-3 text-good-ink" />
                          ) : (
                            <Copy className="size-3" />
                          )}
                        </button>
                      </div>
                    </td>
                    {items.some((i) => i.proof_steps !== undefined) && (
                      <td className="px-3 py-2 text-muted font-mono">
                        {item.proof_steps ?? 0} steps
                      </td>
                    )}
                    {items.some((i) => i.bytes !== undefined) && (
                      <td className="px-3 py-2 text-right text-muted tabular">
                        {item.bytes} B
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Raw artifacts inspector */}
      {artifacts && Object.keys(artifacts).length > 0 && (
        <JSONInspector title="Cryptographic Manifest & Artifacts" value={artifacts} defaultExpandDepth={1} />
      )}
    </div>
  )
}

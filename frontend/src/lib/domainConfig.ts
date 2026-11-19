import type { LucideIcon } from 'lucide-react'
import {
  BrainCircuit,
  Building2,
  FileSearch,
  GraduationCap,
  HeartPulse,
  Leaf,
  Scale,
  ShieldAlert,
  Siren,
  Sparkles,
} from 'lucide-react'

export interface DomainMeta {
  id: string
  name: string
  category: 'security' | 'intelligence' | 'operations' | 'social'
  icon: LucideIcon
  color: string
  tagline: string
  primaryEngine: string
  engineRoles: { engine: string; role: string }[]
  keyMetrics: string[]
  recommendedPresets?: { label: string; description: string; inputPatch: Record<string, unknown> }[]
  inspectionHighlights?: { label: string; keyPath: string; type: 'badge' | 'score' | 'hash' | 'status' }[]
}

export const DOMAIN_METADATA: Record<string, DomainMeta> = {
  cybersecurity: {
    id: 'cybersecurity',
    name: 'Cybersecurity & Online Safety',
    category: 'security',
    icon: ShieldAlert,
    color: '#e11d48',
    tagline: 'Inbound threat triage, prompt injection defense, credential redaction & security policy enforcement',
    primaryEngine: 'security',
    engineRoles: [
      { engine: 'security', role: 'Heuristic threat scanning & prompt-injection detection' },
      { engine: 'decision', role: 'Weighted multi-factor risk scoring & deterministic delivery policies' },
      { engine: 'ai', role: 'Plain-language analyst explanation with local fallback' },
    ],
    keyMetrics: ['Quarantined', 'Secrets redacted', 'Warned', 'Delivered', 'AI-injection attempts'],
    inspectionHighlights: [
      { label: 'Risk Score', keyPath: 'score', type: 'score' },
      { label: 'Action', keyPath: 'action', type: 'badge' },
      { label: 'Injection Verdict', keyPath: 'injection', type: 'status' },
    ],
  },
  forensics: {
    id: 'forensics',
    name: 'Digital Forensics',
    category: 'security',
    icon: FileSearch,
    color: '#0891b2',
    tagline: 'Cryptographic evidence sealing, Merkle tree inclusion proofs, Ed25519 signatures & tamper detection',
    primaryEngine: 'crypto',
    engineRoles: [
      { engine: 'crypto', role: 'SHA-256 evidence hashing, Merkle tree assembly & Ed25519 signing' },
      { engine: 'data', role: 'IOC & technical entity extraction from evidence artifacts' },
      { engine: 'decision', role: 'Chain of custody verification & tamper classification' },
    ],
    keyMetrics: ['Evidence items', 'Merkle root', 'Manifest signature', 'Tamper test'],
    inspectionHighlights: [
      { label: 'SHA-256 Digest', keyPath: 'sha256', type: 'hash' },
      { label: 'Proof Steps', keyPath: 'proof_steps', type: 'badge' },
    ],
  },
  finance: {
    id: 'finance',
    name: 'Finance & Fraud Prevention',
    category: 'operations',
    icon: Scale,
    color: '#059669',
    tagline: 'Real-time transaction anomaly detection, ML classification, multi-signal aggregation & human hold queue',
    primaryEngine: 'ml',
    engineRoles: [
      { engine: 'ml', role: 'Supervised fraud classification & contamination anomaly detection' },
      { engine: 'decision', role: 'Multi-signal Bayesian aggregation & approval hold generation' },
      { engine: 'data', role: 'Feature cleaning, missing value imputation & scaling' },
    ],
    keyMetrics: ['Transactions', 'Fraud alerts', 'Held for review', 'Auto-cleared'],
    inspectionHighlights: [
      { label: 'Fraud Probability', keyPath: 'prob', type: 'score' },
      { label: 'Hold Decision', keyPath: 'decision', type: 'status' },
    ],
  },
  healthcare: {
    id: 'healthcare',
    name: 'Healthcare & Well-being',
    category: 'operations',
    icon: HeartPulse,
    color: '#0284c7',
    tagline: 'Privacy-preserving remote vitals monitoring, NEWS2 early warning triage & AES-GCM encrypted PHI',
    primaryEngine: 'crypto',
    engineRoles: [
      { engine: 'crypto', role: 'HMAC-SHA256 patient pseudonymization & AES-256-GCM PHI encryption' },
      { engine: 'ml', role: 'Baseline vitals drift & patient-specific anomaly detection' },
      { engine: 'decision', role: 'NEWS2 clinical deterioration scoring & escalation holds' },
    ],
    keyMetrics: ['Triage score', 'Encrypted PHI', 'Urgent review', 'Stable'],
    inspectionHighlights: [
      { label: 'NEWS2 Band', keyPath: 'band', type: 'badge' },
      { label: 'Escalation', keyPath: 'escalation', type: 'status' },
    ],
  },
  education: {
    id: 'education',
    name: 'Education & Learning',
    category: 'intelligence',
    icon: GraduationCap,
    color: '#7c3aed',
    tagline: 'Curriculum document indexing, semantic vector retrieval & verifiable citation-backed Q&A',
    primaryEngine: 'ai',
    engineRoles: [
      { engine: 'data', role: 'Text extraction, lexical feature scoring & chunk segmentation' },
      { engine: 'ai', role: 'Dense semantic RAG indexing & citation-grounded question answering' },
      { engine: 'security', role: 'Curriculum query sanitization & prompt-injection defense' },
    ],
    keyMetrics: ['Chunks indexed', 'Citation confidence', 'Queries answered', 'Vocabulary richness'],
  },
  smart_city: {
    id: 'smart_city',
    name: 'Smart City & Mobility',
    category: 'operations',
    icon: Building2,
    color: '#d97706',
    tagline: 'Urban sensor telemetry, traffic congestion forecasting & infrastructure anomaly alerting',
    primaryEngine: 'ml',
    engineRoles: [
      { engine: 'data', role: 'Sensor telemetry ingestion, temporal grouping & normalization' },
      { engine: 'ml', role: 'Holt-Winters seasonal forecasting & sensor outlier detection' },
      { engine: 'decision', role: 'Dynamic corridor re-routing & dispatch recommendations' },
    ],
    keyMetrics: ['Active corridors', 'Congestion alerts', 'Forecast horizon', 'Model confidence'],
  },
  environment: {
    id: 'environment',
    name: 'Environment & Sustainability',
    category: 'operations',
    icon: Leaf,
    color: '#16a34a',
    tagline: 'Environmental sensor monitoring, air-quality index forecasting & hazardous emission spike alerts',
    primaryEngine: 'ml',
    engineRoles: [
      { engine: 'data', role: 'Multi-station environmental sensor parsing & feature synthesis' },
      { engine: 'ml', role: 'AQI timeseries trend projection & chemical anomaly detection' },
      { engine: 'decision', role: 'Public advisory thresholds & environmental compliance alerts' },
    ],
    keyMetrics: ['Monitored stations', 'Exceedance events', 'AQI forecast', 'Anomaly rate'],
  },
  public_safety: {
    id: 'public_safety',
    name: 'Public Safety & Emergency Dispatch',
    category: 'operations',
    icon: Siren,
    color: '#dc2626',
    tagline: 'Emergency incident intake, multi-class severity classification & prioritized dispatch routing',
    primaryEngine: 'ml',
    engineRoles: [
      { engine: 'ml', role: 'Emergency transcript text classification & category tagging' },
      { engine: 'decision', role: 'Priority queue scoring, triage escalation & unit allocation' },
      { engine: 'ai', role: 'Structured responder briefing notes & local fallback summaries' },
    ],
    keyMetrics: ['Active incidents', 'Immediate dispatch', 'Category distribution', 'Triage confidence'],
  },
  accessibility: {
    id: 'accessibility',
    name: 'Social Impact & Accessibility',
    category: 'social',
    icon: Sparkles,
    color: '#9333ea',
    tagline: 'Administrative text readability scoring, plain-language transformation & accessibility compliance',
    primaryEngine: 'ai',
    engineRoles: [
      { engine: 'data', role: 'Readability index calculation (Flesch-Kincaid, Gunning-Fog) & lexical metrics' },
      { engine: 'ai', role: 'Deterministic and LLM-assisted plain-language document simplification' },
      { engine: 'decision', role: 'Accessibility barrier scoring & plain-language verification' },
    ],
    keyMetrics: ['Grade level reduction', 'Simplified sentences', 'Readability gain', 'Tone preservation'],
  },
}

/** Get metadata for a domain ID, with graceful fallback for future unknown hackathon domains. */
export function getDomainMeta(id: string, name?: string, color?: string): DomainMeta {
  if (DOMAIN_METADATA[id]) return DOMAIN_METADATA[id]
  return {
    id,
    name: name || id.replace(/_/g, ' ').toUpperCase(),
    category: 'intelligence',
    icon: BrainCircuit,
    color: color || '#3b82f6',
    tagline: 'Dynamic domain adapter registered in OMNIFORGE framework',
    primaryEngine: 'decision',
    engineRoles: [{ engine: 'decision', role: 'Core pipeline orchestration & policy evaluation' }],
    keyMetrics: ['Executions', 'Status', 'Duration'],
  }
}

# OMNIFORGE Frontend Architecture

> **Superseded.** This document describes the earlier multi-domain OMNIFORGE frontend (sections, domain workspace). The frontend on
> `feature/crowdguard-realtime-ux` is the five-screen CROWDGUARD interface described in
> [`CROWDGUARD_ARCHITECTURE.md`](CROWDGUARD_ARCHITECTURE.md#6a-frontend) and
> [`CROWDGUARD_REALTIME_ARCHITECTURE.md`](CROWDGUARD_REALTIME_ARCHITECTURE.md). The backend engines and adapters it refers to are unchanged.

This document outlines the architectural principles, component hierarchies, routing patterns, design token systems, and extension points of the **PROJECT OMNIFORGE** frontend.

---

## 1. High-Level Architecture

OMNIFORGE is an operational intelligence and adaptive AI engineering framework built with:
- **Framework**: React 19 + TypeScript (strict mode)
- **Bundler**: Vite 8 with Rolldown chunking and route-level code splitting
- **Styling**: Tailwind CSS v4 (`@tailwindcss/vite`) with custom dark-first design tokens
- **Data Visualisation**: Recharts (with accessible dual-view data tables)
- **Icons**: Lucide React
- **Linter**: Oxlint (0 errors, 0 warnings)
- **Backend Communication**: FastAPI via Vite dev proxy `/api` (or direct origin in production)

### Core Architectural Principles
1. **Intelligence Infrastructure vs. Operational Experience**: The backend remains the strict source of truth for operations, validation, policy enforcement, and cryptographic hashes. The frontend visualizes, orchestrates, and inspects without synthesizing or faking data.
2. **Domain Adaptation without Application Rebuild**: Rather than building separate frontends for different domains, OMNIFORGE employs a configuration-driven architecture (`DynamicWorkspace` and `domainConfig.ts`).
3. **Enterprise Aesthetics**: Minimalist, high-density, dark-first operational interface inspired by Linear, Vercel, and Palantir. Restrained accent colors, hairline borders, monospace data points, and accessible status indicators.
4. **Zero-Friction Code Splitting**: Initial bundle size was reduced from ~780 KB down to **27.95 KB** (`index.js`, gzip: 8.46 KB) via dynamic imports and manual chunk separation (`vendor-react`, `vendor-charts`, `vendor-icons`).

---

## 2. Component Hierarchy

```
<App> (State: domains, activeDomain, identity, theme, health, pendingCount)
 ├── <aside> (Application Sidebar: Grouped Navigation, Domain Quick Card, Actor Footer)
 └── <div main-pane>
      ├── <GlobalHeader> (Breadcrumbs, Domain Switcher, Engine Health Mesh, Approvals Bell, Theme Toggle, Role Switcher)
      └── <main> (Suspense with Route Code-Splitting)
           ├── [section === 'overview']   -> <OverviewPage>
           │    ├── <Stat> (Executive KPI Grid)
           │    ├── <EngineStatusCard> (6-Engine Fleet Matrix)
           │    ├── <DomainBadgeIcon> (9 Domain Adapters Fleet)
           │    └── Cryptographic Audit & Recent Runs
           │
           ├── [section === 'workspace']  -> <WorkspacePage>
           │    └── <DynamicWorkspace>
           │         ├── Domain Operational Header
           │         ├── Tabs:
           │         │    ├── "console":   <ExecutionPanel> -> <ResultsRenderer>, <StepList>, <StepOutputs>
           │         │    ├── "studio":    Input JSON Editor & <JSONInspector> (Schema)
           │         │    ├── "insights":  Engine orchestration & telemetry metrics
           │         │    └── "anatomy":   Pipeline step dependency breakdown
           │
           ├── [section === 'ingestion']  -> <IngestionPage>
           │    ├── Drag-and-drop Evidence Uploader
           │    ├── Documents Vault & SHA-256 Verifier
           │    ├── Semantic RAG Q&A Console
           │    ├── <EnvelopeSummary> -> <JSONInspector>
           │    └── Tabular Datasets Table (<DataTable>)
           │
           ├── [section === 'runs']       -> <RunsPage>
           │    ├── Filterable Runs Ledger (<DataTable>)
           │    └── Single Run Inspector (<ResultsRenderer>, <StepList>, <StepOutputs>)
           │
           ├── [section === 'approvals']  -> <ApprovalsPage>
           │    └── Human Governance Queue (<StatusBadge>, <JSONInspector>, Reviewer Note & Decision Actions)
           │
           ├── [section === 'analytics']  -> <AnalyticsPage>
           │    └── <AnalyticsPanel> (<Stat>, <ChartCard>, <ExecutionTrendsChart>, <DataTable>)
           │
           ├── [section === 'engines']    -> <EngineLab>
           │    ├── Operations Explorer (Grouped by Engine with Access Badges)
           │    ├── Interactive Request Payload Editor & cURL Generator
           │    └── Response Inspector (<StatusBadge>, <JSONInspector>)
           │
           ├── [section === 'audit']      -> <AuditPage>
           │    ├── Cryptographic Hash Chain Verifier (<ShieldCheck>, Head Hash)
           │    ├── Audit Events Table with Search & Category Filter
           │    └── Engine Executions Log (<DataTable>)
           │
           └── [section === 'settings']   -> <SettingsPage>
                ├── Theme & Appearance Switcher (Dark, Light, System)
                ├── Domain Adapter Switcher
                ├── Simulated Identity & RBAC Matrix
                ├── AI Inference Provider Mesh & Live Test Call
                └── Access Control Policy & Runtime Configuration (<DataTable>)
```

---

## 3. Routing System

The frontend utilizes a hash-based router (`#/<section>/<param?>`), providing deterministic navigation without requiring server-side fallback rewrites:
- `#/overview`: Platform command & fleet telemetry.
- `#/workspace`: Active domain execution console and scenario studio.
- `#/ingestion`: Document vault, dataset converter, and semantic RAG console.
- `#/runs` or `#/runs/<run_id>`: Historical execution ledger and single-run verdict viewer.
- `#/approvals`: Pending human approvals queue.
- `#/analytics`: Latency distributions, throughput, and error codes.
- `#/engines`: Engineering console for direct operation invocations.
- `#/audit`: Tamper-evident append-only ledger and cryptographic chain verification.
- `#/settings`: Domain, theme, simulated identity, and AI provider configurations.

Routing updates via `window.location.hash`, with hashchange listeners in `App.tsx`. All routes are protected by domain section visibility rules (`active.sections`).

---

## 4. API Integration Layer

All backend communication is centralized in `src/lib/api.ts`:
- **Identity Simulation**: Every request attaches `X-Omniforge-Role` and `X-Omniforge-Actor` headers declared in frontend state. The backend enforces deterministic RBAC against these declared headers.
- **Envelope Parsing**: Backend responses are parsed uniformly. If an engine returns an error within an `EngineResponse` envelope, it is returned intact so that warnings and errors render together in the UI.
- **Core Functions**:
  - `get<T>(path: string): Promise<T>`
  - `send<T>(method: 'POST' | 'PUT', path: string, body?: unknown): Promise<T>`
  - `upload<T>(path: string, file: File): Promise<T>`
  - `callEngine<T>(engine: string, op: string, payload: unknown)`

---

## 5. Domain Configuration Architecture

The system supports domain-driven dynamic behavior via `src/lib/domainConfig.ts` and backend domain adapters (`/api/domains/{id}`):
```typescript
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
```
If a new domain is registered in the backend tomorrow, `getDomainMeta(id)` falls back gracefully with default intelligence categorization, color accents, and full UI compatibility without breaking.

---

## 6. How to Add a New Screen / Navigation Section

1. Define the section identifier in `src/lib/types.ts`:
   ```typescript
   export type SectionId =
     | 'overview' | 'workspace' | 'ingestion' | 'runs' | 'analytics'
     | 'approvals' | 'engines' | 'audit' | 'settings' | 'new_section'
   ```
2. Create the section component in `src/sections/NewSection.tsx`:
   ```tsx
   import { PageHeader } from '../components/ui'

   export function NewSectionPage() {
     return (
       <div className="space-y-5">
         <PageHeader title="New Capability" description="..." />
       </div>
     )
   }
   ```
3. Register the route with lazy loading in `src/App.tsx`:
   ```tsx
   const NewSectionPage = React.lazy(() => import('./sections/NewSection').then(m => ({ default: m.NewSectionPage })))
   ```
4. Add the navigation item to `NAV_GROUPS` in `src/App.tsx`.
5. Add the section to the active domain's `sections` array in the backend adapter if domain-specific, or platform-wide if universal.

---

## 7. How to Add a New Data Visualisation

1. Use or extend `src/components/specializedCharts.tsx` or `src/components/charts.tsx`.
2. Ensure every chart adheres to the **Dual-View Rule**:
   - Provide an accessible table view toggle using `<DataTable />`.
   - Never rely on color alone: pair status colors with text labels.
   - Respect dark/light mode via `useDarkMode()`.
3. Example implementation:
   ```tsx
   export function CustomHeatmapChart({ data, title }: { data: any[]; title?: string }) {
     const [view, setView] = useState<'chart' | 'table'>('chart')
     const isDark = useDarkMode()
     return (
       <Card title={title} actions={<Tabs value={view} onChange={setView} options={[{ id: 'chart', label: 'Chart' }, { id: 'table', label: 'Table' }]} />}>
         {view === 'chart' ? (
           <ResponsiveContainer width="100%" height={260}>
             {/* Recharts component */}
           </ResponsiveContainer>
         ) : (
           <DataTable columns={...} rows={data} />
         )}
       </Card>
     )
   }
   ```

---

## 8. Integrating New Backend Operations

1. In the backend, define the Pydantic input and register the operation with `@engine.operation(...)`.
2. In the frontend:
   - The operation will immediately appear in the **Engine Lab Explorer** under its parent engine, complete with access badge, description, and schema inspector.
   - To invoke it programmatically from a component:
     ```typescript
     import { callEngine } from '../lib/api'
     const resp = await callEngine('ml', 'my_new_op', { param: 123 })
     ```
   - All responses return the universal `EngineResponse<T>` contract.

---

## 9. Reusable Component Inventory

| Component | File | Purpose |
|---|---|---|
| `DynamicWorkspace` | `src/components/DynamicWorkspace.tsx` | Complete adaptive domain console with pipeline runner, input studio, insights, and anatomy. |
| `DomainDashboard` | `src/components/DomainDashboard.tsx` | Domain activity, pass rate, average latency, and recent executions widget. |
| `EngineStatusCard` | `src/components/EngineStatusCard.tsx` | Engine telemetry card with status indicator, latency, operations count, and Lab link. |
| `ExecutionPanel` | `src/components/ExecutionPanel.tsx` | 7-stage pipeline execution manager and verdict presenter. |
| `ResultsRenderer` | `src/components/ResultsRenderer.tsx` | Renders headline, metrics grid, charts, tables, narrative, artifacts, and JSON export. |
| `RiskIndicator` | `src/components/RiskIndicator.tsx` | Visual risk gauge (0-100), band badge, threshold bar, and contributing factor signals. |
| `EvidenceViewer` | `src/components/EvidenceViewer.tsx` | Merkle root inspector, SHA-256 leaf table, Ed25519 signature status, and tamper check indicator. |
| `AnalyticsPanel` | `src/components/AnalyticsPanel.tsx` | Operational telemetry panel with engine calls, latency trends, and error codes. |
| `DataTable` | `src/components/table.tsx` | Enhanced data table with sorting, column search, pagination, and CSV export. |
| `JSONInspector` | `src/components/JSONInspector.tsx` | Syntax-highlighted, searchable JSON tree with collapsible nodes and copy to clipboard. |
| `GlobalHeader` | `src/components/GlobalHeader.tsx` | Platform breadcrumbs, domain selector, engine mesh health popover, role switcher, and theme toggle. |

---

## 10. Known Limitations & Design Boundaries

1. **Simulated Authentication**: As part of the hackathon foundation, identity is declared in HTTP request headers (`X-Omniforge-Role`, `X-Omniforge-Actor`). Real production deployments must place an OIDC/OAuth2 proxy in front of the API.
2. **Recharts Container Rendering**: Responsive Recharts components require an explicit pixel height or percentage height inside a flex/grid container with `min-w-0` to avoid horizontal layout overflow.
3. **Local Fallback Transparency**: When no LLM API keys (`GEMINI_API_KEY`) are present, AI operations run via deterministic local fallbacks (extractive summarization, rule templates) and are clearly flagged with a "local fallback" badge.

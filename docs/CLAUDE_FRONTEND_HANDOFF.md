# OMNIFORGE Claude Code Frontend Handoff Guide

> **Directive for Claude Code / Future AI Agents:**
> When the official hackathon problem statement is announced, follow this guide to adapt and extend OMNIFORGE.
> **DO NOT** rebuild the frontend shell, rewrite the backend, discard existing routes, or replace working components with static mockups.

---

## 1. Quick Start Checklist for Claude Code

When starting on the official hackathon problem statement:
1. **Verify your Git branch**:
   Ensure you are working on `feature/omniforge-frontend` (or a sub-branch branched from it). Never overwrite `main`.
2. **Review existing architecture**:
   Read `docs/FRONTEND_ARCHITECTURE.md` before making architectural choices.
3. **Preserve the application foundation**:
   - The global application shell (`src/App.tsx`, `src/components/GlobalHeader.tsx`) is already fully built, responsive, accessible, and code-split.
   - All 9 existing domain adapters and 6 intelligence engines are functional and pass all tests.
   - All 9 navigation routes (`overview`, `workspace`, `ingestion`, `runs`, `approvals`, `analytics`, `engines`, `audit`, `settings`) must remain functional.
4. **Identify the problem domain**:
   - Match the announced problem statement to one of the 9 built-in domains (Cybersecurity, Forensics, Finance, Healthcare, Education, Smart City, Environment, Public Safety, Social Impact), **OR** register a 10th domain adapter.

---

## 2. Adaptation Strategy: Choose Your Path

### Scenario A: The Problem Matches an Existing Domain (e.g. Cybersecurity, Fraud, Healthcare)
1. **Keep the Backend Domain Adapter**: Use the existing adapter in `backend/app/domains/adapters/<domain>.py`.
2. **Customize Input & Sample Data**:
   - Modify or add a sample scenario JSON in `backend/sample_data/<domain>.json`.
   - Update the scenario description and target objectives in the adapter.
3. **Enhance Presentation**:
   - Update the `present(pc)` function in the backend domain adapter to compute domain-specific metrics, charts, or tables.
   - The frontend `ResultsRenderer` will automatically render these new metrics, charts, and tables without frontend code modifications.
4. **Add Domain-Specific Visuals (Optional)**:
   - In `src/lib/domainConfig.ts`, update `DOMAIN_METADATA[<domain>]` with custom inspection highlights, presets, or tags.
   - If specialized interactive widgets are needed, add them to `src/components/specializedCharts.tsx` and mount them in `DynamicWorkspace`.

### Scenario B: The Problem Requires a Brand New 10th Domain (e.g. Supply Chain, Agritech, Legal)
1. **Backend Step**: Create `backend/app/domains/adapters/<new_domain>.py` subclassing `DomainAdapter`. Define:
   - `input_model`: Pydantic schema for scenario inputs.
   - `steps`: Sequential engine operations to call (`security`, `ai`, `ml`, `crypto`, `data`, `decision`).
   - `present`: Function returning `headline`, `metrics`, `charts`, `tables`, `narrative`, and `artifacts`.
2. **Register in Backend**: Add the adapter to `backend/app/domains/registry.py`.
3. **Frontend Step (Automatic)**:
   - The frontend dynamically loads `/api/domains`. Your new domain will **instantly** appear in the Domain Switcher, Overview fleet cards, and Settings without changing any frontend files.
4. **Frontend Step (Polish)**:
   - Add a metadata entry to `DOMAIN_METADATA` in `src/lib/domainConfig.ts` with an icon, color accent, category, and key metrics.

---

## 3. Rules of Engagement for Claude Code

### Rule 1: Never Discard Existing Functionality
Do not delete existing components (`EngineLab`, `Audit`, `Approvals`, `Ingestion`, `Analytics`, `Overview`). The hackathon judges will evaluate the completeness, security, and governance of the entire platform.

### Rule 2: Preserve the Design System & Tokens
- Always use the semantic CSS variables defined in `src/index.css`:
  - `bg-page`, `bg-surface`, `bg-surface-2`
  - `text-ink`, `text-ink-2`, `text-muted`
  - `border-line`
  - `var(--accent)` for dynamic domain brand accents
  - `text-good-ink`, `text-warn-ink`, `text-critical-ink` for status
- Do not introduce arbitrary hardcoded hex codes for structural surfaces.
- Ensure light and dark themes both look sharp. Use `useDarkMode()` for Recharts SVG colors.

### Rule 3: Maintain the Dual-View Chart Rule
Every new Recharts visualization must offer an accessible table-view alternative using `<DataTable />`. Never convey status by color alone: pair every tone with an icon and text label (e.g., using `<BandBadge />` or `<StatusBadge />`).

### Rule 4: Genuine Telemetry Only
Never synthesize fake AI progress bars, simulated thinking animations, or fake latency numbers in the frontend. All execution states, duration numbers, and cryptographic digests must originate from genuine FastAPI backend responses.

### Rule 5: Keep the Bundle Trim & Fast
- Route components must remain dynamically imported via `React.lazy()` in `src/App.tsx`.
- Run `npm --prefix frontend run build` to verify that `index.js` remains small and that no bundle warnings are triggered.
- Run `npm --prefix frontend run lint` (`oxlint`) to ensure 0 errors and 0 warnings.

---

## 4. Key Reusable Components to Leverage

When building problem-specific screens, reuse these battle-tested components:

```tsx
// 1. Dynamic Interactive Workspace
import { DynamicWorkspace } from './components/DynamicWorkspace'

// 2. Structured Results Presenter (renders headlines, metrics, charts, tables, narratives)
import { ResultsRenderer } from './components/ResultsRenderer'

// 3. Searchable, Sortable, Paginated, Exportable Table
import { DataTable } from './components/table'

// 4. Interactive JSON Tree Inspector
import { JSONInspector } from './components/JSONInspector'

// 5. Visual Risk Meter with Contributing Factors
import { RiskIndicator } from './components/RiskIndicator'

// 6. Cryptographic Evidence & Merkle Proof Viewer
import { EvidenceViewer } from './components/EvidenceViewer'

// 7. Specialized Recharts Components (Risk, Time-series, Confusion Matrix, Latency)
import {
  RiskDistributionChart,
  TimeSeriesAnalysisChart,
  ClassificationMatrixChart,
  ExecutionTrendsChart
} from './components/specializedCharts'
```

---

## 5. Verification Commands Before Submission

Before committing your changes, always run:

```bash
# 1. Typecheck & production build (must exit with code 0)
npm --prefix frontend run build

# 2. Fast linting (must report 0 errors, 0 warnings)
npm --prefix frontend run lint

# 3. Backend test suite (all 78+ tests must pass)
python -m pytest backend/tests
```

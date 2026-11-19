# CROWDGUARD — Crowd Safety Monitoring at Public Events (on OMNIFORGE)

CROWDGUARD estimates how many people are in each zone of a venue, flags overcrowding and fast build-up early, forecasts capacity
breaches, and recommends safer crowd movement with an explanation for each route. Its Virtual Crowd Intelligence Engine (VCIE) turns
camera footage into a calibrated bird's-eye density heatmap, movement map and digital twin. It runs on the OMNIFORGE framework described
below: the six engines and nine original adapters are unchanged, and CROWDGUARD adds a seventh `crowd` engine, a tenth `crowd_safety`
adapter, and a CROWDGUARD section (Command Centre, Live Monitoring, Virtual Heatmap, Zone Intelligence, Forecasting, Movement Planner,
Incidents) in a redesigned shell with light, dark and system themes.

* Architecture: [`docs/CROWDGUARD_ARCHITECTURE.md`](docs/CROWDGUARD_ARCHITECTURE.md)
* Two-minute pitch: [`docs/CROWDGUARD_PITCH.md`](docs/CROWDGUARD_PITCH.md)
* Test results: [`docs/CROWDGUARD_TEST_RESULTS.md`](docs/CROWDGUARD_TEST_RESULTS.md)
* VCIE mathematics and operator guide: [`docs/VIRTUAL_HEATMAP_ARCHITECTURE.md`](docs/VIRTUAL_HEATMAP_ARCHITECTURE.md)

```bash
cd frontend && npm install && npm run build
cd ../backend && python -m pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000          # open http://127.0.0.1:8000  →  Command Centre
```

Video analysis needs `opencv-python`, plus `ultralytics` with a **local** YOLO weights file. The repository root ships `yolov8n.pt`
(Ultralytics, AGPL-3.0); `CROWDGUARD_YOLO_WEIGHTS` or `backend/models/` can point elsewhere. Nothing is downloaded at runtime. Without
weights it falls back to OpenCV HOG and says so. The simulation, alerts, forecasting and routing need neither.
The demo data is **synthetic** and labelled on every screen. CROWDGUARD does not certify event safety: organisers make every decision.

---

# OMNIFORGE — Universal Adaptive Intelligence Framework

OMNIFORGE is a reusable foundation for turning a problem statement into a working AI-powered prototype quickly.
It has **one** FastAPI backend with six engines (AI, ML, cryptography, security, data and decision) behind a common
contract, and **nine domain adapters**. Each adapter is a declarative pipeline over those engines, not a separate app. The React
frontend adapts to the active domain: its sections, pipeline, inputs and result views are driven by the backend.

> **Status:** foundation mode. All nine pipelines run end to end on bundled **synthetic** data. No LLM key was present
> while this was built, so every AI step was exercised through its **labelled local fallback**. The Gemini and
> OpenAI-compatible provider code paths have unit tests that use a fake provider; they have **not** been checked against a live API.

---

## 1. Quick start

Prerequisites: Python 3.11+ (built and tested on 3.12) and Node 20+ (built on Node 26).

```bash
# Backend (terminal 1)
cd backend
python -m pip install -r requirements.txt      # skip if the packages are already installed
python -m uvicorn app.main:app --reload --port 8000

# Frontend (terminal 2)
cd frontend
npm install
npm run dev                                     # http://localhost:5173 (proxies /api to :8000)
```

**Single-server demo mode:** run `npm run build` in `frontend/`, then start only the backend. FastAPI serves the built UI at
<http://127.0.0.1:8000>. Interactive API docs are at <http://127.0.0.1:8000/docs>.

**Optional configuration:** copy `.env.example` to `.env` (repository root or `backend/`).

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` (+ `GEMINI_MODEL`) | Enables Gemini. Check the current model id at ai.google.dev/gemini-api/docs/models; the default `gemini-3.5-flash` has not been verified in this environment. |
| `OPENAI_API_KEY` + `OPENAI_MODEL` (+ `OPENAI_BASE_URL`) | Any OpenAI-compatible server: OpenAI, Groq, OpenRouter, Ollama, LM Studio, vLLM… |
| `AI_PROVIDER` | `auto` (the first configured provider) \| `gemini` \| `openai` \| `local` |
| `OMNIFORGE_MASTER_KEY` | base64 of a 32-byte key-encryption key. Without it, a dev key file is generated in `backend/.data/`. |

After adding a key, restart the backend and use **Settings → Test live call** (`ai.ping`). This makes one real call and marks the provider *verified*.

**Tests**

```bash
cd backend && python -m pytest          # 78 tests
cd frontend && npm run build && npm run lint
```

---

## 2. Architecture

```mermaid
flowchart LR
  subgraph UI["React + Vite + Tailwind + Recharts"]
    OV[Overview] --- WS[Workspace] --- DI[Data & docs] --- RU[Runs] --- AP[Approvals] --- AN[Analytics] --- EL[Engine lab] --- AU[Audit] --- SE[Settings]
  end
  UI -- "/api (role headers)" --> API[FastAPI routes]
  API --> PR[Pipeline runner]
  API --> REG
  PR --> REG
  subgraph REG["Engine registry"]
    direction TB
    POL{{"Deterministic policy gate<br/>(RBAC + AI-actor cap, fail-closed)"}}
    POL --> SEC[Security] & AI[AI] & ML[ML] & CR[Crypto] & DA[Data] & DE[Decision]
  end
  AI -. "screens untrusted text via registry" .-> SEC
  AI -- "optional" --> LLM[(Gemini / OpenAI-compatible)]
  AI -- "fallback" --> LOC[Local deterministic methods]
  REG -- observer --> DB[(SQLite: executions, runs, hash-chained audit,<br/>documents, datasets, wrapped keys, approvals, RAG chunks)]
  DOM[Domain adapters x9<br/>steps + input model + sample + presenter] --> PR
```

**Layers (each depends only on the one below it):**

| Layer | Location | Responsibility |
|---|---|---|
| Presentation | `frontend/src` | Generic renderers for the backend `presentation` contract: metrics, charts, tables, narrative |
| API | `backend/app/api` | HTTP, identity context, upload sniffing. Delegates everything else. |
| Domain adapters | `backend/app/domains` | Declarative pipelines: `Step(engine, operation, build(ctx))` plus a presenter |
| Engines | `backend/app/engines/*` | Independently testable capabilities exposed as typed operations |
| Core | `backend/app/core` | `BaseEngine`, the `@operation` decorator, `EngineRegistry`, the response contract |
| Persistence | `backend/app/db` | The `Store` facade over SQLAlchemy/SQLite. Engines never touch sessions directly. |
| Composition root | `backend/app/services.py` | The only place where concrete classes are wired together (dependency injection) |

### Universal engine contract

Every operation, whether called from the API, a pipeline or another engine, returns the same envelope:

```json
{ "success": true, "engine": "crypto", "result": {}, "confidence": null,
  "execution_time_ms": 1.9, "warnings": [], "metadata": {"operation": "hash", "request_id": "…"}, "error": null }
```

`confidence` is `null` unless it can be computed meaningfully: classifier probabilities (labelled *uncalibrated*) or the
decision engine's agreement × coverage heuristic (labelled *heuristic*). `error` (`{code, message, details}`) is the
one addition to the base contract. HTTP status codes match the outcome: 403 policy, 404 unknown, 422 validation, 503 no provider.

Each operation declares a Pydantic input model, which handles validation and also produces the JSON schema the Engine lab uses. It also declares an access level
(`read` / `write` / `sensitive`) and a permission string. The registry runs the policy check **before** validation and execution.

### Engines

| Engine | Operations (non-read access shown) | Implementation |
|---|---|---|
| `security` | `threat_scan`, `prompt_injection`, `validate`, `authorize`, `policy`, `events` | Transparent regex + URL heuristics with noisy-OR scoring. Every finding names its rule. |
| `ai` | `summarize`, `explain`, `simplify`, `structured`, `generate`, `rag_index` (write), `rag_query`, `rag_collections`, `providers`, `ping` | Provider abstraction (Gemini SDK; OpenAI-compatible over HTTP). TF-IDF RAG. Local fallbacks: extractive summary, template explanation, rule-based plain language. |
| `ml` | `classify`, `regress`, `predict`, `cluster`, `anomaly`, `forecast`, `text_classify`, `evaluate`, `list_models` | scikit-learn. Metrics are always reported **next to a naive baseline**. The forecaster picks a model on a validation window and reports on a later, untouched test window. |
| `crypto` | `hash`, `hmac`, `generate_key` (write), `encrypt` (write), `decrypt` (sensitive), `sign` (sensitive), `verify`, `merkle_root`, `merkle_verify`, `verify_document`, `list_keys` | `cryptography` + `hashlib` only: AES-256-GCM, Ed25519, HMAC-SHA256, RFC 6962-style Merkle tree. Key material is envelope-encrypted under a KEK. |
| `data` | `ingest` (write), `profile`, `clean`, `normalise`, `extract_features`, `text_features`, `extract_entities`, `document_text`, `image_features`, `list_datasets` | pandas, pypdf, Pillow. Readability (Flesch), IOC/entity regexes, perceptual hashes, EXIF. |
| `decision` | `evaluate_rules`, `risk_score`, `aggregate`, `request_approval` (write), `decide_approval` (sensitive), `list_approvals` | A JSON rule DSL (no `eval`), explainable weighted scores with per-factor contributions, multi-signal aggregation, a human approval workflow. |

---

## 3. The nine domain adapters

Each adapter in `backend/app/domains/adapters/` defines an input model, sample data, ordered steps, the UI sections it shows and a presenter.

| Domain | Scenario | Pipeline (engine.operation) | Measurable output |
|---|---|---|---|
| Cybersecurity & Online Safety | Inbound message triage | security.threat_scan ×N → security.prompt_injection ×N → decision.risk_score → decision.evaluate_rules → ai.explain | A deliver / warn / quarantine / redact decision per message, with the rules that fired |
| Digital Forensics | Evidence sealing & chain of custody | crypto.hash ×N → crypto.merkle_root → crypto.generate_key → crypto.sign → crypto.verify → tamper test (crypto.merkle_verify) → data.extract_entities | A signed Merkle root; a demonstration that the original verifies and an altered copy fails; IOC table |
| Smart City & Mobility | Junction congestion early warning | data.profile → data.extract_features → ml.anomaly → ml.forecast (weekly season) → decision.evaluate_rules → ai.explain | Forecast peak vs capacity, anomalous hours, backtest MAE vs seasonal-naive |
| Healthcare & Well-being | Remote deterioration early warning | crypto HMAC pseudonym + AES-GCM on the identifier → NEWS2-inspired rules → personal-baseline anomaly → risk score → clinician approval request → ai.explain | Risk score with factor breakdown; the identifier is never shown or sent to an LLM |
| Education & Academia | Course assistant & learner support | ai.rag_index → ai.rag_query (cited) → ai.summarize ×N → ml.cluster | A cited answer; learner groups with profiles |
| Finance & Fraud Prevention | Transaction fraud screening | data.clean → ml.classify (holdout metrics) → ml.anomaly → fraud rules → decision.aggregate (with confidence) → approval per hold → ai.explain | Holds queued for human review; F1/AUC compared with the majority baseline |
| Public Safety & Emergency | Emergency call triage | ml.text_classify (CV metrics) → data.extract_entities ×N → life-threat rules (override the model) → priority score → ai.summarize | Dispatch queue ordered by priority; low-confidence calls routed to a human |
| Environment & Sustainability | Air-quality early warning | data.clean → ml.anomaly → spike filter + ml.forecast → AQI advisory rules → ai.explain (public audience) | Next-24 h PM2.5 band, gaps filled, faulty spikes removed, backtest MAE vs baseline |
| Social Impact & Accessibility | Plain-language public notices | data.text_features → ai.simplify (re-measured) → ai.summarize | Reading grade before and after (computed by formula, not claimed) |

Results from the bundled samples on this machine (no LLM, local fallbacks) are listed below. The data is synthetic, so these
numbers only show that the pipelines work. They are not evidence of real-world accuracy.

| Domain | Result |
|---|---|
| Cyber | 5/8 messages actioned |
| Forensics | Tamper detected |
| Smart city | Forecast peak 822 veh/h (91% of capacity). Backtest MAE 27 vs 29 for seasonal-naive. |
| Healthcare | Latest risk 74/100, approval queued |
| Finance | 4/24 held. Holdout macro-F1 0.86, ROC AUC 0.71. |
| Public safety | 5-fold CV macro-F1 0.57 on 60 examples |
| Environment | Backtest MAE 14.4 vs 13.9 for the baseline. The model does **not** beat the baseline here, and the UI shows that. |
| Accessibility | FK grade 18.2 → 9.2 (target 8 not met by the local rules) |

---

## 4. Security model

**What is enforced:**

- **Deterministic policy gate.** `security/policy.py` is checked by the registry before every operation. It fails closed if no authorizer is configured.
  Roles: `viewer` (read), `analyst` (+ write, run pipelines, sign), `reviewer` (+ decrypt, decide approvals), `admin`.
- **AI cannot authorise.** Actors of type `ai` are capped at `read` whatever their role, and explicitly denied `approval:decide`, `crypto:sign`
  and `crypto:decrypt`. LLM output is advisory text that no code path acts on.
- **Human approval.** `decide_approval` needs `approval:decide` and a human actor. Self-approval is blocked and logged.
  Approvals can only be decided once.
- **Prompt-injection defence.** Untrusted text is screened before it reaches a remote LLM. A `block` verdict falls back to local processing,
  or returns an error for LLM-only operations. Content is always wrapped in `<untrusted_input>` delimiters, which are stripped from the text first so they cannot be faked.
  RAG passages are also screened, so a document carrying indirect injection is **excluded** from the context.
- **Key management.** Secrets are AES-256-GCM-wrapped under a KEK with the label and type as AAD. Key material is never returned by any API.
  Swap `LocalKeyStore` for a KMS/HSM-backed `KeyManager` without touching the engine.
- **Tamper-evident audit.** Every audit event stores `prev_hash` and `hash = SHA256(prev_hash ‖ canonical_event)`. `GET /api/audit/verify`
  recomputes the chain and reports the first broken event. A test edits a row and confirms the break is detected.
- **Uploads.** The type is detected from magic bytes or by strict parsing, not taken from the client. Filenames are sanitised, size is capped, files are stored by SHA-256,
  and `crypto.verify_document` re-hashes a stored file to detect modification.
- **No secrets in the frontend.** Keys are read from the environment by the backend only. `/api/config` exposes non-secret fields.

**What is *not* provided (be explicit in demos):**

- **No authentication.** Identity (role and actor name) is *declared* through `X-Omniforge-Role` / `X-Omniforge-Actor` headers, so the
  policy can be demonstrated. Put OIDC/JWT in front of the API before exposing it anywhere.
- The audit chain is tamper-*evident*, not tamper-*proof*. Someone with database access can rewrite the whole chain. Anchor the head hash
  externally (for example by signing or publishing it periodically) for stronger guarantees.
- Threat and injection detection are heuristics. They reduce risk but cannot catch novel or obfuscated attacks.

---

## 5. API reference

Full interactive schema: `/docs` (OpenAPI). All routes are under `/api`.

| Method & path | Purpose |
|---|---|
| `GET /health` | Status of the database and every engine (including provider and KEK warnings) |
| `GET /config`, `GET /whoami` | Non-secret configuration; the declared identity |
| `GET /engines`, `GET /engines/{name}` | Engines, operations, access levels and input JSON schemas |
| `POST /engines/{name}/{operation}` | Execute one operation (body = input model). Returns the envelope. |
| `GET /domains`, `GET /domains/{id}` | Adapters (the detail includes `sample_input`) |
| `POST /domains/{id}/run` | Run the pipeline, `{"input": {...}}`. Omit `input` to use the sample. |
| `GET /runs`, `GET /runs/{id}` | Persisted runs with per-step status, timings, results and presentation |
| `GET /settings`, `PUT /settings` | Active domain (which controls the visible sections) |
| `POST /documents` (multipart), `GET /documents` | Upload and list (SHA-256 recorded) |
| `GET /datasets`, `GET /datasets/{id}` | Stored tables (reference them as `dataset_id` in ML/data operations) |
| `GET /approvals`, `POST /approvals/{id}/decision` | Human approval queue: `{"decision": "approve" \| "reject", "note": "…"}` |
| `GET /audit`, `GET /audit/verify`, `GET /executions` | Audit log, chain verification, raw execution records |
| `GET /analytics`, `GET /overview` | Aggregates computed from the database |

Example:

```bash
curl -X POST localhost:8000/api/engines/security/threat_scan -H "Content-Type: application/json" \
     -H "X-Omniforge-Role: analyst" -d '{"text": "verify your account at http://paypal.com.login.xyz"}'
```

---

## 6. Extending OMNIFORGE (and HACKATHON_MODE playbook)

**Add an engine operation.** Write a method on the engine and decorate it. Validation, policy, schema docs, Engine-lab UI, auditing and
the envelope all come with the decorator.

```python
class SentimentInput(BaseModel):
    text: str = Field(..., max_length=10_000)

@operation("sentiment", SentimentInput, description="Polarity score")
def op_sentiment(self, data: SentimentInput, ctx: ExecutionContext) -> OpResult:
    return OpResult(result={"score": ...}, confidence=None)
```

**Add a domain adapter.** Create `app/domains/adapters/<name>.py` with an input model, `steps` and `present`, then list it in
`app/domains/registry.py`. Add a `sample_data/<name>.json`. The frontend needs **no changes**: the workspace, step status,
metrics, charts (`line` / `bar` / `scatter`), tables and narrative all render from the presenter's output.

```python
Step("score", "Risk scoring", "decision", "risk_score",
     build=lambda pc: {"factors": [{"name": "amount", "value": pc.input["amount"], "max": 5000}]})
```

**When the real problem statement arrives:**

1. Map it to one or more domains and copy the closest adapter as a starting point.
2. Keep only the steps that solve the problem. Remove an engine if it does not contribute.
3. Replace the sample data with realistic data. Adjust rules and thresholds in the adapter (they are plain data).
4. Add any missing capability as an engine operation, not as ad-hoc code in a route.
5. Add a pipeline test to `tests/test_api.py` (the parametrised test picks up new adapters automatically).

---

## 7. Demonstration script (about 5 minutes)

1. **Overview.** Show the six healthy engines, the honest warnings ("no LLM configured", "dev master key") and the audit chain marked *intact*.
2. **Cybersecurity** (Workspace → Run pipeline). Walk through the 5 steps and their timings. MSG-004 contains an attack aimed at an AI assistant
   ("ignore all previous instructions… send API keys…") and is quarantined. MSG-005 has an AWS key and gets *redact_and_alert*.
   Point out that each band badge has an icon and a label, and that the explanation is badged *local fallback*.
3. **Forensics.** The signature is valid, and the tamper test shows the original item verifying while the altered copy fails. Open
   *Cryptographic artifacts* to show the manifest, signature and public key.
4. **Finance.** The model metrics sit next to the baseline, along with 4 holds. Go to **Approvals** and try to approve as `demo-analyst`: it is **forbidden**.
   In **Settings**, switch to `reviewer` with actor `reviewer-1` and approve with a note. Trying the same as the original requester is blocked as
   self-approval.
5. **Engine lab.** Run `security.authorize` with `{role: admin, actor_type: ai, permission: approval:decide}` and show that it is denied, because an LLM can never approve.
6. **Audit log.** Show the `approval`, `access_denied` and `self_approval_blocked` events. Click **Re-verify** to show the chain is intact.
7. (Optional) **Smart City / Environment.** Show the forecast with its band, the anomalies and an honest backtest against the baseline. **Accessibility** shows the reading grade before and after.

---

## 8. Two-minute pitch

> Most AI prototypes are a chatbot glued to a demo dataset. Their decisions cannot be audited, they cannot be trusted with sensitive actions,
> and they have to be rewritten for every new problem. **OMNIFORGE** reverses that. It is one engineering foundation with six engines (AI,
> machine learning, cryptography, security, data and decision) behind a single contract, plus a pipeline layer that can be pointed at a new domain in minutes.
> We show it on nine: phishing triage, evidence sealing, traffic forecasting, patient early warning, cited course Q&A, fraud screening,
> emergency call triage, air-quality advisories and plain-language notices.
>
> Three ideas make it trustworthy. **First, AI advises and deterministic code decides.** Every operation passes a rule-based policy gate,
> AI actors are capped at read-only, and sensitive actions such as releasing a held payment or escalating a patient wait for a human reviewer who cannot be
> the requester. **Second, everything is evidence.** Each step records its timing and warnings, every audit event is hash-chained, and forensic evidence
> is sealed under a signed Merkle root, so tampering is detected rather than suspected. **Third, honesty is built in.** Every model metric sits next
> to a naive baseline, AI text is labelled with where it came from, and when no LLM is available the system says so and uses transparent local
> methods instead of pretending.
>
> The result is a platform that adapts to the problem rather than the reverse, and that you could put in front of an auditor.

## 9. Technical innovation

- **A declarative cross-engine pipeline with a uniform envelope.** Adapters are data plus small `build` functions. Policy, validation, audit and
  status tracking apply automatically to every step, and the UI renders any adapter generically from its `presentation` contract.
- **Policy-before-execution with an AI-actor cap.** The same registry gate covers API calls, pipeline steps and engine-to-engine calls,
  so an LLM-driven agent added later inherits the restriction with no extra work.
- **Layered prompt-injection defence.** It covers direct input, delimiter escapes and *indirect* injection in retrieved documents (passages are excluded and the exclusion is reported).
- **Verifiable integrity.** RFC 6962-style Merkle proofs (domain-separated, no odd-node duplication), Ed25519-signed manifests,
  envelope-encrypted keys and a hash-chained audit log, all built from standard primitives.
- **Honest ML.** Baselines on every metric, forecast model selection on a separate validation window, out-of-sample prediction
  bands, CV on small text datasets, and confidence values that are explicitly labelled heuristic or uncalibrated.

## 10. Known limitations and future work

- **No authentication**, and identity is simulated. Next step: OIDC/JWT plus per-tenant data isolation.
- The **LLM paths are not verified live**, because no key was available. Run `ai.ping` once a key is set. Agent orchestration, where an LLM picks tools, is not
  implemented. The registry's AI-actor cap is the intended safety boundary for it.
- RAG uses TF-IDF retrieval. Dense embeddings could sit behind the same `retrieve()` interface.
- Trained ML models are kept in memory only (by design, no pickle loading) and are lost on restart.
- Pipelines run synchronously inside the request (fine for the demo sizes: about 10 ms to 1.5 s here). Long jobs would need a task queue and streamed step status.
- Single-process SQLite. The audit chain uses an in-process lock. Multi-worker deployment would need Postgres and DB-level serialisation.
- OCR for scanned PDFs, and EXIF GPS decoding, are not included.
- The frontend bundle is about 780 KB minified (Recharts). It could be code-split per section.
- Clinical (NEWS2-inspired) and AQI thresholds are illustrative and configurable. They are **not** clinically or regulatorily validated.

## 11. Repository layout

```
backend/
  app/
    core/            contracts.py · engine.py (BaseEngine, @operation) · registry.py
    engines/         ai/ ml/ crypto/ security/ data/ decision/ · common.py · text.py
    domains/         base.py (Step, DomainAdapter, run_pipeline) · registry.py · adapters/*.py (9)
    db/              models.py · store.py (hash-chained audit, repositories)
    api/             routes.py · deps.py (identity context, upload checks)
    services.py      composition root    config.py   settings (env)    main.py   app factory
  sample_data/       9 synthetic scenario files (regenerate: python scripts/generate_sample_data.py)
  tests/             78 pytest tests (engines, security properties, every pipeline, API)
frontend/
  src/
    sections/        Overview, Workspace, Ingestion, Runs, Approvals, Analytics, EngineLab, Audit, Settings
    components/      ui, charts (validated palette, light/dark, table view), table, presentation
    lib/             api client, types, hooks, formatting
```

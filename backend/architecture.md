# Architecture Document — Plum Health Insurance Claims Processing System

## 1. Overview

This system automates the adjudication of health insurance claims submitted by employees of TechCorp Solutions Pvt Ltd under the PLUM_GHI_2024 Group Health Insurance policy. A member uploads medical documents (bills, prescriptions, lab reports) alongside claim details. The system classifies documents, extracts structured data using an LLM, applies deterministic policy rules, and produces an auditable decision: `APPROVED`, `PARTIAL`, `REJECTED`, or `MANUAL_REVIEW`.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        React Frontend                           │
│         Claim Form → File Upload → Decision + Trace View        │
└─────────────────────────────┬───────────────────────────────────┘
                              │ HTTP POST /claims/submit
┌─────────────────────────────▼───────────────────────────────────┐
│                     FastAPI Backend                              │
│                   api/routes/claims.py                           │
└─────────────────────────────┬───────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│              Google ADK SequentialAgent (Orchestrator)           │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │Preprocessing │→ │  Document    │→ │  Extraction  │          │
│  │   Agent      │  │  Gate Agent  │  │    Agent     │          │
│  │              │  │              │  │              │          │
│  │ image.py     │  │ doc rules    │  │ Gemini 1.5   │          │
│  │ pdf.py       │  │ from policy  │  │ Flash Vision │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                              │                   │
│                    ┌──────────────┐  ┌───────▼──────┐          │
│                    │  Decision    │← │    Policy    │          │
│                    │   Agent      │  │    Agent     │          │
│                    │              │  │              │          │
│                    │ ClaimResponse│  │ 7 rule checks│          │
│                    │ + trace      │  │ from JSON    │          │
│                    └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

**LLM is used exactly twice per claim** — once to classify document type (Gemini Vision call 1), once to extract structured fields (Gemini Vision call 2). All policy logic is deterministic and reads from `policy_terms.json` at runtime.

---

## 3. Component Descriptions

### 3.1 FastAPI Route (`api/routes/claims.py`)
Accepts multipart form data (member_id, claim_category, treatment_date, claimed_amount, file). Encodes file bytes to base64, builds the initial state dict, creates an ADK session, and runs the orchestrator. Returns a `ClaimResponse` JSON.

### 3.2 Orchestrator (`agents/orchestrator_agent.py`)
A Google ADK `SequentialAgent` that runs five sub-agents in order. It manages shared state across agents and ensures the pipeline fails fast (stops at DocumentGate if documents are wrong) rather than wasting LLM calls on invalid submissions.

### 3.3 Preprocessing Agent (`tools/preprocessing_tool.py`)
Converts uploaded files to a model-ready format. Images are deskewed, denoised, and contrast-enhanced using OpenCV. PDFs are inspected: text PDFs have text extracted directly; scanned/image PDFs are rendered at 2× zoom per page. All output is base64-encoded PNG strings — no raw bytes cross agent boundaries.

### 3.4 Document Gate Agent (`tools/document_tool.py`)
Pure logic — no LLM. Infers document types from filenames and content types, then compares against `policy_terms.json → document_requirements` for the submitted claim category. If required documents are missing, returns a blocking `DocumentError` with a specific actionable message naming exactly which document is missing and what to upload.

### 3.5 Extraction Agent (`tools/extraction_tool.py`)
Sends preprocessed document images or text to Gemini 1.5 Flash Vision with type-specific prompts (one per document type: PRESCRIPTION, HOSPITAL_BILL, LAB_REPORT, PHARMACY_BILL, DISCHARGE_SUMMARY). Parses the returned JSON and records low-confidence fields and validation issues. Confidence score degrades per unreadable field.

### 3.6 Policy Agent (`tools/policy_tool.py`)
Pure logic — no LLM. Reads `policy_terms.json` at runtime and applies seven sequential rule checks: member eligibility, waiting period, exclusions, network hospital, pre-authorization, sub-limits, and co-pay. Each rule returns a `PolicyCheckResult` with status, detail, and any monetary deduction. Hard failures (exclusion match, waiting period active) produce `REJECTED` directly.

### 3.7 Decision Agent (`tools/decision_tool.py`)
Aggregates policy check results, extraction confidence, and any document errors into a final `ClaimResponse`. Applies the decision matrix: any hard failure → `REJECTED`; deductions present → `PARTIAL`; confidence below threshold → `MANUAL_REVIEW`; otherwise → `APPROVED`. Attaches the full trace to the response.

---

## 4. Key Design Decisions

### 4.1 Why SequentialAgent over a custom pipeline
The assignment explicitly rewards multi-agentic architectures. ADK's `SequentialAgent` gives us agent isolation (each agent has its own state scope), structured tool calling, and built-in observability through the event stream — without the overhead of building a custom orchestration loop. The trade-off is ADK's session model adds latency per step; acceptable for a claims adjudication use case where correctness matters more than speed.

### 4.2 Why LLM is used only for extraction
Extraction from messy, handwritten, rubber-stamped Indian medical documents is genuinely hard and not deterministic. Everything else — policy rules, document type checks, decision logic — is deterministic and testable. Mixing LLM reasoning into policy evaluation would make decisions unexplainable and untestable. The separation keeps the system auditable.

### 4.3 Why all images travel as base64 strings
ADK's `FunctionTool` generates a JSON schema for every tool's input and output. Raw `bytes`, numpy arrays, and PIL `Image` objects cannot be JSON-serialised. Converting to base64 strings at the preprocessing boundary means every downstream agent can pass data through ADK's state mechanism without special serialisation handling.

### 4.4 Why policy logic is not hardcoded
The assignment explicitly required this. Reading from `policy_terms.json` at runtime means policy changes (new exclusions, updated sub-limits, new members) require no code deployment — only a file update. The `load_policy_terms()` function uses `lru_cache` so the file is read once per process.

### 4.5 What was considered and rejected

| Option | Why Rejected |
|--------|-------------|
| LangGraph instead of ADK SequentialAgent | ADK was already set up; both solve the same problem. LangGraph has better conditional branching support but adds another dependency. |
| OCR pre-processing (Tesseract) before LLM | Gemini 1.5 Flash Vision outperforms Tesseract on handwritten Indian medical documents. Adding Tesseract adds complexity with no quality gain. |
| Separate microservices per agent | Overkill for this scale. Adds network latency and deployment complexity. A single FastAPI process with agent isolation is sufficient. |
| Storing claims in a database | Out of scope for the assignment. In production this is mandatory for audit and re-processing. |

---

## 5. Failure Handling

| Failure Type | Handling Strategy |
|---|---|
| LLM timeout / 503 | `GeminiClient` retries up to `LLM_MAX_RETRIES` times with 1s, 2s backoff. After exhaustion, extraction returns empty fields with confidence=0. |
| Malformed PDF (MuPDF errors) | `is_text_pdf()` returns `False` on broken streams; pipeline falls back to image rendering. MuPDF errors suppressed with `fitz.TOOLS.mupdf_display_errors(False)`. |
| LLM returns invalid JSON | `_clean_json()` strips markdown fences; `json.loads()` failure is caught and logged. Extraction returns `confidence=0`, `error` field populated. |
| Policy file missing | `load_policy_terms()` raises `PolicyFileNotFoundError` at startup — server refuses to start rather than silently processing claims against empty rules. |
| Individual file fails preprocessing | Error captured in `PreprocessedDocument.error` field; pipeline continues with remaining files. |
| Confidence below threshold | Decision agent routes to `MANUAL_REVIEW` instead of `APPROVED`/`PARTIAL`. Ops team reviews. |

---

## 6. Scalability Analysis — 10× Current Load

Current: ~75,000 claims/year ≈ 210/day ≈ 9/hour.
10× target: 750,000 claims/year ≈ 2,100/day ≈ 90/hour.

### Bottlenecks and mitigations

**Gemini API rate limits** — At 10× load, 2 Gemini calls per claim × 90/hour = 180 calls/hour. Well within free tier limits (1,500/day). At 10 million lives this becomes the critical bottleneck. Mitigation: use Gemini batch API for non-urgent claims; cache extraction results for identical documents using a hash of the file bytes.

**Single FastAPI process** — Current design runs everything in-process. Mitigation: deploy multiple Railway instances behind a load balancer. ADK sessions are in-memory; move to Redis-backed session store for horizontal scaling.

**Synchronous policy engine** — Policy checks are CPU-bound but fast (<5ms). Not a bottleneck at 10×. At 100× consider running policy checks in a thread pool.

**File storage** — Current: `/tmp` on the Railway instance (ephemeral). Mitigation: move uploads to S3/GCS with pre-signed URLs. Files deleted after decision is stored.

**No claim persistence** — Current design has no database. At 10× this is mandatory: store claims, decisions, and traces in Postgres for reprocessing, audit, and analytics.

---

## 7. Limitations of Current Design

1. **No authentication** — Any request with a valid member_id is processed. Production requires JWT/OAuth per employee.
2. **Single file upload** — Route accepts one file. Real claims have 3–5 documents. Extending to `List[UploadFile]` is straightforward.
3. **No fraud detection** — `fraud_thresholds` in policy_terms.json is read but same-day claim count is not checked (requires claim history persistence).
4. **Patient name cross-check missing** — If prescription and bill have different patient names, this is not caught (requires extraction from both documents).
5. **No claim persistence** — Decisions are not stored. Re-querying a claim_id is not possible.
6. **Confidence scoring is heuristic** — Confidence deductions per missing field are fixed weights. A trained classifier would be more accurate.
# Plum Health Insurance – Claims Processing System

This project implements an automated health insurance claims processing system for employees of **TechCorp Solutions Pvt Ltd** under the **PLUM_GHI_2024** group health policy.

Members submit a claim with basic details and one medical document (bill, prescription, report). The system:

- Validates that the right document type has been uploaded for the claim category.
- Extracts structured information from messy medical documents using an LLM.
- Applies deterministic policy rules loaded from `policy_terms.json`.
- Produces a decision: `APPROVED`, `PARTIAL`, `REJECTED`, or `MANUAL_REVIEW`.
- Returns a full trace explaining what was checked, what passed/failed, and why.

---

## 1. Repository Structure

```text
plum-insurance/
  backend/
    api/
      routes/
        claims.py          # /claims/submit endpoint
    agents/
      orchestrator_agent.py # SequentialAgent orchestrator
    tools/
      preprocessing_tool.py # file → PreprocessedDocument
      document_tool.py      # document gate (requirements check)
      extraction_tool.py    # LLM-based extraction
      policy_tool.py        # deterministic policy rules
      decision_tool.py      # Decision → ClaimResponse
    data/
      policy_terms.json     # policy + member configuration
      test_cases.json       # 12 evaluation test cases
    schemas/
      claim.py, decision.py # Pydantic models
    main.py                 # FastAPI app entrypoint
  frontend/
    src/
      pages/SubmitClaim.jsx # claim form + submission UI
      components/
        DecisionBadge.jsx
        TraceViewer.jsx
    index.html
    vite.config.js
  ARCHITECTURE.md           # System architecture explanation
  COMPONENTS.md             # Component contracts / interfaces
  requirements.txt          # Backend dependencies
  README.md                 # This file
```

---

## 2. Running the System Locally

You can run backend and frontend locally and use the browser to submit and review claims.

### 2.1 Backend (FastAPI + Orchestrator)

From the repo root:

```bash
cd backend

# Create virtualenv (optional but recommended)
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies from root requirements.txt
pip install -r ../requirements.txt
```

Set environment variables (at minimum):

```bash
# Windows (PowerShell)
$env:GOOGLE_API_KEY="your-google-api-key"

# macOS/Linux
export GOOGLE_API_KEY="your-google-api-key"
```

Then start the backend:

```bash
uvicorn backend.main:app --reload
```

The backend will be available at:

- `http://localhost:8000`
- Interactive docs at `http://localhost:8000/docs`

### 2.2 Frontend (React + Vite)

In another terminal, from the repo root:

```bash
cd frontend
npm install
```

Create `frontend/.env`:

```env
VITE_API_BASE_URL=http://localhost:8000
```

Start the dev server:

```bash
npm run dev
```

The frontend will be available at:

- `http://localhost:5173`

Open that URL in your browser, fill in the claim form, upload a sample bill, and submit. The UI will display the decision (e.g. APPROVED, PARTIAL) and the full trace.

---

## 3. API Overview

### 3.1 POST `/claims/submit`

- **Method:** `POST`
- **Content-Type:** `multipart/form-data`

Fields:

| Field          | Type        | Required | Description                                              |
|----------------|-------------|----------|----------------------------------------------------------|
| `member_id`    | string      | ✓        | Policy member ID (e.g. `EMP001`)                        |
| `claim_category` | string    | ✓        | `CONSULTATION`, `DIAGNOSTIC`, `PHARMACY`, `DENTAL`, `VISION`, `ALTERNATIVE_MEDICINE` |
| `treatment_date` | string    | ✓        | ISO date `YYYY-MM-DD`                                   |
| `claimed_amount` | float     | ✓        | Amount in INR (> 0)                                     |
| `file`         | UploadFile  | ✓        | Single PDF or image (JPG/PNG/HEIC)                      |

The response is a `ClaimResponse` JSON containing:

- `claim_id`
- `decision` (`APPROVED`, `PARTIAL`, `REJECTED`, `MANUAL_REVIEW`)
- `approved_amount`
- `claimed_amount`
- `confidence` (0.0 – 1.0)
- `reason`
- `rejection_reasons`
- `document_errors`
- `trace` (ordered list of steps with `agent`, `step`, `status`, `detail`)

For full schema details, see `COMPONENTS.md` and `backend/schemas/claim.py`.

---

## 4. Architecture & Components

- **High-level architecture** is documented in `ARCHITECTURE.md`:
  - React SPA frontend submits claims via HTTP.
  - FastAPI backend exposes `/claims/submit`.
  - Google ADK `SequentialAgent` orchestrator coordinates five agents:
    - PreprocessingAgent → `preprocessing_tool`
    - DocumentAgent → `document_tool`
    - ExtractionAgent → `extraction_tool`
    - PolicyAgent → `policy_tool`
    - DecisionAgent → `decision_tool`
  - All policy logic is deterministic and reads from `policy_terms.json`.

- **Component contracts** (inputs, outputs, error behavior) are specified in `COMPONENTS.md` for:
  - `/claims/submit` route
  - Each tool and agent
  - ClaimResponse and TraceStep models

These documents are intended to be sufficient for another engineer to reimplement any component without reading its code.

---

## 5. Evaluation & Test Cases

The repository includes:

- `backend/data/policy_terms.json` – full policy + member configuration.
- `backend/data/test_cases.json` – 12 test cases with expected outcomes.
- `backend/tests/test_cases.json` – additional test artifacts.

An `EVAL.md` report (to be added) will summarize:

- The decision and trace produced by the system for each of the 12 test cases.
- Whether it matches the expected outcome.
- Explanations where behavior differs from the expected result.

You can also use the FastAPI docs (`/docs`) or a small script to invoke `/claims/submit` with each test case’s document and payload.

---

## 6. Deployment

The project is deployable to:

- **Backend:** Railway (FastAPI + Uvicorn, using `uvicorn backend.main:app`).
- **Frontend:** Vercel (Vite + React, reading `VITE_API_BASE_URL`).

Example backend URL (Railway):

```text
https://plum-insurance-production.up.railway.app/
```

Example frontend environment variable (Vercel):

```env
VITE_API_BASE_URL=https://plum-insurance-production.up.railway.app
```

For the assignment, either a deployed URL **or** the local instructions above are sufficient.

---

## 7. Limitations & Future Work

- Single-file upload per claim (real-world claims often include multiple documents).
- No authentication/authorization; any caller with a member_id can submit.
- No persistence layer; claims and decisions are not stored in a database.
- Fraud detection is minimal and does not use historical claim data.
- Confidence scoring is heuristic; could be improved with a learned model.
- Error handling is conservative: internal failures may route to `MANUAL_REVIEW` or generic error messages.

These limitations and scaling considerations are discussed in more detail in `ARCHITECTURE.md`.

---

## 8. How to Navigate This Repo

If you’re reviewing this project:

- Start with `ARCHITECTURE.md` for the high-level design.
- Skim `COMPONENTS.md` to see the contracts and data flow.
- Run the backend and frontend locally using the steps in this README.
- Use `backend/data/test_cases.json` to exercise the policy engine.
- Check the FastAPI docs at `http://localhost:8000/docs` for API exploration.

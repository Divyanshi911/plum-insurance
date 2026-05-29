# Component Contracts — Plum Claims Processing System

Each section defines the exact interface of one component: inputs, outputs, and errors. Another engineer should be able to reimplement any component from this document alone without reading the source code.

---

## 1. POST /claims/submit

**Location:** `api/routes/claims.py`

### Input (multipart/form-data)
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| member_id | string | ✓ | Policy member ID e.g. `EMP001` |
| claim_category | string | ✓ | One of: `CONSULTATION`, `DIAGNOSTIC`, `PHARMACY`, `DENTAL`, `VISION`, `ALTERNATIVE_MEDICINE` |
| treatment_date | string | ✓ | ISO date `YYYY-MM-DD` |
| claimed_amount | float | ✓ | Amount in INR, must be > 0 |
| file | UploadFile | ✓ | PDF, JPG, or PNG |

### Output (200 OK)
```json
{
  "claim_id": "CLAIM-A5BFB8FF2568",
  "decision": "APPROVED",
  "approved_amount": 1350.0,
  "claimed_amount": 1500.0,
  "confidence": 0.60,
  "reason": "Consultation claim approved within sub-limit after applying copay.",
  "rejection_reasons": [],
  "document_errors": [],
  "trace": [
    {
      "agent": "PolicyAgent",
      "step": "Member lookup",
      "status": "PASSED",
      "detail": "Member EMP001 found. Active.",
      "timestamp": 1234567890.123
    }
  ]
}
```

### Errors
| Code | When |
|------|------|
| 422 | Missing required form field |
| 500 | Orchestrator returned no output; policy file missing |

---

## 2. PreprocessingAgent / `preprocess_upload_files`

**Location:** `tools/preprocessing_tool.py`

### Input (state dict)
```json
{
  "documents": [
    {
      "filename": "hospital_bill.jpg",
      "content_type": "image/jpeg",
      "bytes_b64": "<base64 string>"
    }
  ],
  "doc_type_hints": {
    "hospital_bill.jpg": "HOSPITAL_BILL"
  }
}
```

### Output (state dict — adds `preprocessed_json`)
```json
{
  "preprocessed_json": [
    {
      "filename": "hospital_bill.jpg",
      "content_type": "image/jpeg",
      "doc_type_hint": "HOSPITAL_BILL",
      "processed_type": "IMAGE",
      "processed_images_b64": ["<base64 PNG string>"],
      "extracted_text": null,
      "error": null
    }
  ]
}
```

### `processed_type` values
| Value | Meaning |
|-------|---------|
| `IMAGE` | Single image file, preprocessed |
| `TEXT_PDF` | PDF with extractable text |
| `IMAGE_PDF` | Scanned PDF, each page rendered as image |

### Errors
Never raises. Individual file errors are captured in `PreprocessedDocument.error`. Pipeline always continues.

---

## 3. DocumentGateAgent / `document_tool_fn`

**Location:** `tools/document_tool.py`

### Input (state dict)
```json
{
  "raw_claim": {
    "claim_category": "CONSULTATION"
  },
  "documents_meta": [
    { "filename": "rx.jpg", "content_type": "image/jpeg" }
  ],
  "policy_terms": { "document_requirements": { ... } }
}
```

### Output (state dict — adds `doc_json`)
**Pass:**
```json
{
  "doc_json": {
    "ok": true,
    "uploaded_types": ["PRESCRIPTION"],
    "required_types": ["PRESCRIPTION", "HOSPITAL_BILL"],
    "errors": []
  }
}
```

**Fail:**
```json
{
  "doc_json": {
    "ok": false,
    "uploaded_types": ["PRESCRIPTION"],
    "required_types": ["PRESCRIPTION", "HOSPITAL_BILL"],
    "errors": [
      {
        "message": "Missing HOSPITAL_BILL for CONSULTATION claim. Please upload the itemized bill from the clinic.",
        "missing_type": "HOSPITAL_BILL",
        "claim_category": "CONSULTATION"
      }
    ]
  }
}
```

### Rules
- Document type is inferred from filename keywords and content_type
- Required types come from `policy_terms.document_requirements[claim_category].required`
- If `ok = false`, orchestrator must stop pipeline and return the errors to the member
- No LLM calls are made — pure string matching
- Error messages must name the exact missing document type, not a generic message

### Errors
Never raises. Returns `ok: false` with specific errors on any validation failure.

---

## 4. ExtractionAgent / `extraction_tool_fn`

**Location:** `tools/extraction_tool.py`

### Input (state dict)
```json
{
  "preprocessed_json": [ ... ],
  "policy_terms": { ... }
}
```

### Output (state dict — adds `extracted_json`)
```json
{
  "extracted_json": {
    "extracted_documents": [
      {
        "filename": "bill.jpg",
        "doc_type": "HOSPITAL_BILL",
        "fields": {
          "hospital_name": "Apollo Hospitals",
          "bill_number": "CMC/2024/08321",
          "patient_name": "Rajesh Kumar",
          "total_amount": 1500.0,
          "line_items": [
            { "description": "Consultation Fee", "amount": 1000.0 },
            { "description": "CBC Test", "amount": 500.0 }
          ]
        },
        "confidence": 0.88,
        "low_confidence_fields": [],
        "validation_issues": []
      }
    ],
    "extraction_errors": [],
    "low_confidence": false
  }
}
```

### Confidence scoring rules
| Condition | Deduction |
|-----------|-----------|
| Document quality MEDIUM | −0.05 |
| Document quality POOR | −0.20 |
| Each low_confidence_field | −0.04 |
| Missing required field (date, amount) | −0.10 to −0.20 |
| Future date on prescription | −0.30 |
| Amount mismatch on bill | −0.15 |

### LLM calls
- Call 1: classify document type → `document_type`, `quality`, `confidence`, `visible_clues`
- Call 2: extract fields using type-specific prompt → structured JSON per document type

### Errors
LLM timeout after `LLM_TIMEOUT_SEC` × `LLM_MAX_RETRIES` attempts. Returns extraction with `confidence: 0.0` and `error` field. Never raises.

---

## 5. PolicyAgent / `policy_tool_fn`

**Location:** `tools/policy_tool.py`

### Input (state dict)
```json
{
  "raw_claim": {
    "member_id": "EMP001",
    "claim_category": "CONSULTATION",
    "treatment_date": "2024-10-15",
    "claimed_amount": 1500.0
  },
  "extracted_json": { ... },
  "doc_json": { ... },
  "policy_terms": { ... }
}
```

### Output (state dict — adds `policy_json`)
```json
{
  "policy_json": {
    "decision": "APPROVED",
    "approved_amount": 1350.0,
    "claimed_amount": 1500.0,
    "confidence": 0.90,
    "reason": "Consultation claim approved within sub-limit after applying copay.",
    "rejection_reasons": [],
    "policy_checks": [
      { "rule": "member_eligibility", "status": "PASSED", "detail": "EMP001 active since 2024-04-01.", "deduction": 0 },
      { "rule": "waiting_period",     "status": "PASSED", "detail": "196 days since join. No specific waiting period for Viral Fever.", "deduction": 0 },
      { "rule": "exclusions",         "status": "PASSED", "detail": "Viral Fever not in exclusions list.", "deduction": 0 },
      { "rule": "network_hospital",   "status": "PASSED", "detail": "Apollo Hospitals is a network hospital.", "deduction": 0 },
      { "rule": "preauth",            "status": "SKIPPED","detail": "Pre-auth not required for CONSULTATION.", "deduction": 0 },
      { "rule": "sublimits",          "status": "PASSED", "detail": "₹1500 within consultation sub-limit ₹2000.", "deduction": 0 },
      { "rule": "copay",              "status": "PARTIAL","detail": "10% copay applied. Member pays ₹150.", "deduction": 150 }
    ]
  }
}
```

### Decision matrix
| Conditions | Decision |
|-----------|----------|
| Any rule status `FAILED` (hard rules: eligibility, waiting, exclusions) | `REJECTED` |
| All PASSED, total deduction > 0 | `PARTIAL` |
| All PASSED, no deductions | `APPROVED` |
| Extraction confidence < 0.50 | `MANUAL_REVIEW` |

### Seven rules (in order)
1. **member_eligibility** — member_id exists in `policy_terms.members` and join_date is set
2. **waiting_period** — treatment_date minus join_date exceeds `waiting_periods.initial_waiting_period_days`; diagnosis checked against `waiting_periods.specific_conditions`
3. **exclusions** — diagnosis and line items checked against `exclusions.conditions`
4. **network_hospital** — hospital name matched against `network_hospitals` list
5. **preauth** — claim_category checked against `pre_authorization.required_for`
6. **sublimits** — claimed_amount checked against `opd_categories[category].sub_limit`
7. **copay** — `opd_categories[category].copay_percent` applied to post-sublimit amount

### Errors
Raises `PolicyFileNotFoundError` if policy_terms.json is missing. All other errors are captured as `FAILED` rule results with `MANUAL_REVIEW` fallback.

---

## 6. DecisionAgent / `decision_tool_fn`

**Location:** `tools/decision_tool.py`

### Input (state dict)
```json
{
  "policy_json": { ... },
  "doc_json": { ... },
  "extracted_json": { ... }
}
```

### Output (state dict — adds `decision_json`)
```json
{
  "decision_json": {
    "claim_id": "CLAIM-A5BFB8FF2568",
    "decision": "APPROVED",
    "approved_amount": 1350.0,
    "claimed_amount": 1500.0,
    "confidence": 0.60,
    "reason": "Consultation claim approved within sub-limit after applying copay.",
    "rejection_reasons": [],
    "document_errors": [],
    "trace": [ ... ]
  }
}
```

### Errors
Never raises. If `policy_json` is missing, returns `MANUAL_REVIEW` with reason "Policy evaluation did not complete."

---

## 7. ClaimResponse Schema

```python
class ClaimResponse(BaseModel):
    claim_id:          str
    decision:          Literal["APPROVED", "PARTIAL", "REJECTED", "MANUAL_REVIEW"]
    approved_amount:   float
    claimed_amount:    float
    confidence:        float          # 0.0 – 1.0
    reason:            str
    rejection_reasons: list[str]      # ["WAITING_PERIOD", "EXCLUDED_CONDITION", ...]
    document_errors:   list[dict]     # populated when gate fails
    trace:             list[TraceStep]

class TraceStep(BaseModel):
    agent:     str
    step:      str
    status:    Literal["PASSED", "FAILED", "PARTIAL", "SKIPPED", "INFO"]
    detail:    str
    timestamp: float
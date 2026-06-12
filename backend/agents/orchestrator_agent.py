# # backend/agents/orchestrator_agent.py

# from google.adk.agents.llm_agent import LlmAgent
# from google.adk.agents.sequential_agent import SequentialAgent
# from google.adk.tools import FunctionTool

# from backend.tools.document_tool      import document_tool_fn
# from backend.tools.decision_tool      import decision_tool_fn
# from backend.tools.extraction_tool    import extraction_tool_fn
# from backend.tools.policy_tool        import policy_tool_fn
# from backend.tools.preprocessing_tool import preprocess_upload_files

# MODEL = "gemini-1.5-flash"

# preprocessing_tool_wrapped = FunctionTool(func=preprocess_upload_files)
# document_tool_wrapped      = FunctionTool(func=document_tool_fn)
# extraction_tool_wrapped    = FunctionTool(func=extraction_tool_fn)
# policy_tool_wrapped        = FunctionTool(func=policy_tool_fn)
# decision_tool_wrapped      = FunctionTool(func=decision_tool_fn)

# preprocessing_agent = LlmAgent(
#     name="PreprocessingAgent",
#     model=MODEL,
#     instruction="""You are the Preprocessing Agent for a health insurance claims system.
# Convert uploaded documents (images or PDFs) into a clean, model-ready format.
# - Images: deskew, denoise, enhance contrast, output PNG bytes as base64.
# - PDFs: if text PDF extract text; if scanned PDF render pages as images.
# Call the preprocess_upload_files tool with the current state and return its output.""",
#     output_key="preprocessed_json",
#     tools=[preprocessing_tool_wrapped],
# )

# document_agent = LlmAgent(
#     name="DocumentAgent",
#     model=MODEL,
#     instruction="""You are the DocumentGate Agent.
# Verify that the correct document types are present for the claim category.
# - Infer doc types from filenames: PRESCRIPTION, HOSPITAL_BILL, LAB_REPORT, PHARMACY_BILL, DISCHARGE_SUMMARY.
# - Compare against policy_terms.document_requirements for the claim_category.
# - If required docs are missing: return specific errors naming exactly what is missing.
# - Do NOT apply policy rules or call any other LLM.
# Call the document_tool_fn tool with the current state and return its output.""",
#     output_key="doc_json",
#     tools=[document_tool_wrapped],
# )

# extraction_agent = LlmAgent(
#     name="ExtractionAgent",
#     model=MODEL,
#     instruction="""You are the Extraction Agent for medical documents.
# Extract structured fields from preprocessed documents.

# IMPORTANT: The extraction_tool uses OCR-first (pytesseract + regex, no LLM).
# If OCR confidence is below 0.50 for any document, the tool automatically
# falls back to a deterministic low-confidence path.

# You do not need to decide which path to use — extraction_tool_fn handles this.
# Call the extraction_tool_fn tool with the current state and return its output.

# The output must contain:
# - extracted_documents: list of filename, doc_type, fields, confidence, low_confidence_fields, validation_issues
# - extraction_errors: list of error strings
# - low_confidence: bool""",
#     output_key="extracted_json",
#     tools=[extraction_tool_wrapped],
# )

# policy_agent = LlmAgent(
#     name="PolicyAgent",
#     model=MODEL,
#     instruction="""You are the Policy Agent for a health insurance claims system.
# Apply deterministic policy rules from policy_terms.json. Do NOT use free-form LLM reasoning.

# Apply in order:
# 1. member_eligibility — is member_id in policy roster and active?
# 2. waiting_period     — has waiting period passed for this diagnosis?
# 3. exclusions         — is treatment in exclusions list?
# 4. network_hospital   — is hospital in network_hospitals list?
# 5. preauth            — was pre-auth obtained if required?
# 6. sublimits          — is claimed_amount within opd_categories sub_limit?
# 7. copay              — apply copay_percent to get approved_amount

# Return Decision with: decision, approved_amount, claimed_amount, confidence, reason, trace, rejection_reasons.
# Call the policy_tool_fn tool with the current state and return its output.""",
#     output_key="policy_json",
#     tools=[policy_tool_wrapped],
# )

# decision_agent = LlmAgent(
#     name="DecisionAgent",
#     model=MODEL,
#     instruction="""You are the Decision Agent.
# Convert the Decision object from PolicyAgent into a ClaimResponse for the frontend.
# - Generate a claim_id.
# - Map all Decision fields to ClaimResponse.
# - Preserve full trace and document_errors.
# - Do NOT re-apply policy rules.
# Call the decision_tool_fn tool with the current state and return its output.""",
#     output_key="decision_json",
#     tools=[decision_tool_wrapped],
# )

# orchestrator = SequentialAgent(
#     name="OrchestratorAgent",
#     sub_agents=[
#         preprocessing_agent,
#         document_agent,
#         extraction_agent,
#         policy_agent,
#         decision_agent,
#     ],
#     description=(
#         "Coordinates the full claim pipeline in order. "
#         "Stops at DocumentAgent if required documents are missing. "
#         "Final output key: decision_json (ClaimResponse-shaped dict)."
#     ),
# )

# backend/api/routes/claims.py

import base64
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.core.config import load_policy_terms
from backend.schemas.claim import ClaimResponse
from backend.tools.preprocessing_tool import preprocess_upload_files
from backend.tools.document_tool      import document_tool_fn
from backend.tools.extraction_tool    import extraction_tool_fn
from backend.tools.policy_tool        import policy_tool_fn
from backend.tools.decision_tool      import decision_tool_fn

router = APIRouter()


@router.post("/submit", response_model=ClaimResponse)
async def submit_claim(
    member_id:      str        = Form(...),
    claim_category: str        = Form(...),
    treatment_date: str        = Form(...),
    claimed_amount: float      = Form(...),
    file:           UploadFile = File(...),
):
    # ── 1. Build initial state ────────────────────────────────────────────────
    file_bytes = await file.read()

    state: Dict[str, Any] = {
        "raw_claim": {
            "member_id":      member_id,
            "claim_category": claim_category.upper(),
            "treatment_date": treatment_date,
            "claimed_amount": claimed_amount,
        },
        "policy_terms": load_policy_terms(),
        "documents": [
            {
                "filename":     file.filename,
                "content_type": file.content_type or "application/octet-stream",
                "bytes_b64":    base64.b64encode(file_bytes).decode("utf-8"),
            }
        ],
        "documents_meta": [
            {
                "filename":     file.filename,
                "content_type": file.content_type or "application/octet-stream",
            }
        ],
    }

    # ── 2. Run pipeline — tools called directly, no LLM needed ───────────────
    state = preprocess_upload_files(state)   # preprocessing_tool
    state = document_tool_fn(state)          # document gate
    state = extraction_tool_fn(state)        # OCR + regex
    state = policy_tool_fn(state)            # policy rules
    state = decision_tool_fn(state)          # build response

    # ── 3. Return result ──────────────────────────────────────────────────────
    result = state.get("decision_json")
    if not result:
        raise HTTPException(status_code=500, detail="Pipeline produced no output.")

    return ClaimResponse(**result)
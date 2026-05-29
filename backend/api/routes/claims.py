# backend/api/routes/claims.py

import base64
import json
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from backend.agents.orchestrator_agent import orchestrator
from backend.core.config import load_policy_terms
from backend.schemas.claim import ClaimResponse

router = APIRouter()

APP_NAME = "plum_claims"

# ── Create Runner ONCE at module level (outside the route function) ────────────
# Two rules from the ADK source:
#   1. agent= must be provided
#   2. app_name= is required whenever agent= is used (not app=)
_session_service = InMemorySessionService()
_runner = Runner(
    agent=orchestrator,
    app_name=APP_NAME,          # ← required, was missing
    session_service=_session_service,
)


@router.post("/submit", response_model=ClaimResponse)
async def submit_claim(
    member_id:      str        = Form(...),
    claim_category: str        = Form(...),
    treatment_date: str        = Form(...),
    claimed_amount: float      = Form(...),
    file:           UploadFile = File(...),
):
    policy_terms: Dict[str, Any] = load_policy_terms()

    raw_claim: Dict[str, Any] = {
        "member_id":      member_id,
        "claim_category": claim_category.upper(),
        "treatment_date": treatment_date,
        "claimed_amount": claimed_amount,
    }

    file_bytes = await file.read()
    docs_payload: List[Dict[str, Any]] = [
        {
            "filename":     file.filename,
            "content_type": file.content_type or "application/octet-stream",
            "bytes_b64":    base64.b64encode(file_bytes).decode("utf-8"),
        }
    ]
    documents_meta: List[Dict[str, Any]] = [
        {
            "filename":     file.filename,
            "content_type": file.content_type or "application/octet-stream",
        }
    ]

    initial_state: Dict[str, Any] = {
        "raw_claim":      raw_claim,
        "policy_terms":   policy_terms,
        "documents":      docs_payload,
        "documents_meta": documents_meta,
    }

    # ── Session: create one per request ───────────────────────────────────────
    user_id    = member_id
    session_id = f"claim-{uuid.uuid4().hex[:8]}"

    # create_session may be sync depending on ADK version — try await first,
    # fall back to sync if it raises TypeError
    try:
        session = await _session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
    except TypeError:
        session = _session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )

    message = types.Content(
        role="user",
        parts=[types.Part(text=json.dumps(initial_state))],
    )

    # ── Run orchestrator ───────────────────────────────────────────────────────
    final_response_text: str | None = None

    async for event in _runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=message,
    ):
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if part.text:
                    final_response_text = part.text
                    break

    if not final_response_text:
        raise HTTPException(
            status_code=500,
            detail="Orchestrator returned no output. Check agent logs.",
        )

    # ── Strip markdown fences + parse JSON ────────────────────────────────────
    text = final_response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        result: Dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not parse orchestrator output as JSON: {exc}\nRaw: {text[:300]}",
        )

    # decision_agent writes to "decision_json" key — unwrap if present
    if "decision_json" in result:
        result = result["decision_json"]

    return ClaimResponse(**result)
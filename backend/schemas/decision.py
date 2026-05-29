from typing import List, Optional
from pydantic import BaseModel

class TraceStep(BaseModel):
    """
    One step in the explainability trace.

    Example:
    - step: "Document verification"
    - agent: "DocumentGate"
    - status: "FAILED"
    - detail: "Missing HOSPITAL_BILL for CONSULTATION"
    """
    step: str
    agent: str
    status: str  # e.g., "PASSED" | "FAILED" | "PARTIAL" | "SKIPPED"
    detail: str

class DocumentError(BaseModel):
    """
    Problems found with uploaded documents during DocumentGate.

    type:
      - MISSING_REQUIRED
      - WRONG_TYPE
      - UNREADABLE
      - MISMATCHED_PATIENT
      - SYSTEM_ERROR
    """
    type: str
    message: str
    document_types_seen: Optional[List[str]] = None
    document_types_required: Optional[List[str]] = None

class Decision(BaseModel):
    """
    Core decision objects used inside the pipeline.

    This can be converted into the API ClaimResponse later.
    """
    decision: Optional[str]  # "APPROVED" | "PARTIAL" | "REJECTED" | "MANUAL_REVIEW" | None
    approved_amount: float
    claimed_amount: float
    confidence: float
    reason: str
    rejection_reasons: Optional[List[str]] = None
    notes: Optional[str] = None
    trace: List[TraceStep]
    document_errors: List[DocumentError] = []
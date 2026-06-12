# backend/schemas/claim.py
from typing import List, Optional, Any
from pydantic import BaseModel
from backend.schemas.decision import TraceStep, DocumentError

class UploadedDocument(BaseModel):
    filename: str
    content_type: Optional[str] = None

class ClaimSubmission(BaseModel):
    member_id: str
    claim_category: str
    treatment_date: str  # ISO date string
    claimed_amount: float
    documents_meta: List[UploadedDocument] = []

class ClaimResponse(BaseModel):
    claim_id: str
    decision: Optional[str]
    approved_amount: float
    claimed_amount: float
    confidence: float
    reason: str
    notes: Optional[Any] = None
    rejection_reasons: Optional[List[str]] = None
    trace: List[TraceStep]
    document_errors: List[DocumentError] = []
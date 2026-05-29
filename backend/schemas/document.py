# backend/schemas/document.py
from enum import Enum
from typing import Any, Dict, List
from pydantic import BaseModel

class DocType(str, Enum):
    PRESCRIPTION = "PRESCRIPTION"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    LAB_REPORT = "LAB_REPORT"
    PHARMACY_BILL = "PHARMACY_BILL"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    UNKNOWN = "UNKNOWN"

class ExtractedDoc(BaseModel):
    doc_type: DocType
    filename: str
    fields: Dict[str, Any]
    confidence: float
    low_confidence_fields: List[str] = []
    validation_issues: List[str] = []
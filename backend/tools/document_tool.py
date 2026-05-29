# backend/tools/document_tool.py

from typing import List, Dict, Any, Set
from backend.schemas.document import DocType  # your Enum [file:146]
from backend.schemas.claim import UploadedDocument  # your Pydantic model [file:130]
from backend.schemas.decision import DocumentError  # optional reuse [file:129]


def infer_doc_type_from_filename(filename: str) -> DocType:
    name = filename.lower()

    if "rx" in name or "prescription" in name:
        return DocType.PRESCRIPTION
    if "bill" in name or "invoice" in name:
        # can be hospital or pharmacy, but simplest for now:
        if "pharmacy" in name or "chemist" in name:
            return DocType.PHARMACY_BILL
        return DocType.HOSPITAL_BILL
    if "lab" in name or "report" in name or "diagnostic" in name:
        return DocType.LAB_REPORT
    if "discharge" in name:
        return DocType.DISCHARGE_SUMMARY

    return DocType.UNKNOWN


def check_document_requirements(
    claim_category: str,
    documents_meta: List[UploadedDocument],
    document_requirements: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Deterministic DocumentGate tool.

    - Determines doc types from filenames.
    - Compares against required types for claim_category.
    - Returns ok flag, uploaded_types, required_types, and errors list.
    """
    # find rules for category
    category_rules = document_requirements.get(claim_category.upper())
    if not category_rules:
        # if no rules, assume no doc constraints
        return {
            "ok": True,
            "uploaded_types": [],
            "required_types": [],
            "errors": [],
        }

    required_types: Set[str] = set(category_rules.get("required", []))
    optional_types: Set[str] = set(category_rules.get("optional", []))

    uploaded_types: Set[str] = set()
    for doc in documents_meta:
        dt = infer_doc_type_from_filename(doc.filename)
        uploaded_types.add(dt.value)

    missing_required = required_types - uploaded_types

    errors: List[Dict[str, Any]] = []

    if missing_required:
        errors.append(
            {
                "type": "MISSING_REQUIRED",
                "message": (
                    f"You uploaded {sorted(uploaded_types)}. For {claim_category} claims, "
                    f"you must upload {sorted(required_types)}. "
                    f"Missing: {sorted(missing_required)}."
                ),
                "document_types_seen": sorted(uploaded_types),
                "document_types_required": sorted(required_types),
            }
        )

    # optional: flag if all uploaded are UNKNOWN
    if not uploaded_types or uploaded_types == {"UNKNOWN"}:
        errors.append(
            {
                "type": "WRONG_TYPE",
                "message": (
                    "The system could not recognize the document types from filenames. "
                    "Please upload clear PRESCRIPTION / BILL / LAB REPORT docs."
                ),
                "document_types_seen": sorted(uploaded_types),
                "document_types_required": sorted(required_types),
            }
        )

    ok = len(errors) == 0

    return {
        "ok": ok,
        "uploaded_types": sorted(uploaded_types),
        "required_types": sorted(required_types),
        "errors": errors,
    }


# ---------- ADK tool wrapper ----------

def document_tool_fn(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    ADK tool function.

    Expects in state:
      - raw_claim.claim_category
      - documents_meta: list of {filename, content_type} or something you map to UploadedDocument
      - policy_terms.document_requirements

    Writes into state:
      - document_gate_json: the result of check_document_requirements(...)
    """
    raw_claim = state.get("raw_claim") or {}
    policy_terms = state.get("policy_terms") or {}
    claim_category = raw_claim.get("claim_category", "")

    # documents_meta can be derived from state["documents"] or filled earlier in the pipeline
    docs = state.get("documents_meta") or []
    documents_meta = [UploadedDocument(**d) for d in docs]

    document_requirements = policy_terms.get("document_requirements", {})

    gate_result = check_document_requirements(
        claim_category=claim_category,
        documents_meta=documents_meta,
        document_requirements=document_requirements,
    )

    state["document_gate_json"] = gate_result
    return state


# This is what orchestrator_agent must import:
document_tool = document_tool_fn
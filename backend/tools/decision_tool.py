# backend/tools/decision_tool.py

import uuid
from typing import Dict, Any

from backend.schemas.decision import Decision  # internal decision model [file:129]
from backend.schemas.claim import ClaimResponse  # API response model [file:130]


def _generate_claim_id() -> str:
    """Generate a simple unique claim_id."""
    return f"CLAIM-{uuid.uuid4().hex[:12].upper()}"


def _decision_to_claim_response(decision_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a Decision dict into a ClaimResponse dict.
    """
    # Parse into Pydantic model for validation [file:129]
    decision = Decision(**decision_data)

    claim_response = ClaimResponse(
        claim_id=_generate_claim_id(),
        decision=decision.decision,
        approved_amount=decision.approved_amount,
        claimed_amount=decision.claimed_amount,
        confidence=decision.confidence,
        reason=decision.reason,
        notes=decision.notes,
        rejection_reasons=decision.rejection_reasons,
        trace=decision.trace,
        document_errors=decision.document_errors,
    )
    # Return as plain dict for JSON serialization [file:130]
    return claim_response.model_dump()


def decision_tool_fn(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    ADK tool that:
    - reads state['policy_json'] (Decision dict from PolicyAgent),
    - converts it into a ClaimResponse,
    - writes state['decision_json'] with the ClaimResponse.
    """
    decision_data = state.get("policy_json")
    if decision_data is None:
        # nothing to convert; you may choose to raise or just return state
        return state

    claim_response_dict = _decision_to_claim_response(decision_data)
    state["decision_json"] = claim_response_dict
    return state


# Wrap as an ADK FunctionTool so DecisionAgent can call it [web:152]
decision_tool = decision_tool_fn
# backend/tools/policy_tool.py

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


# ── helpers ──────────────────────────────────────────────────────────────────

def _get_member(policy_terms, member_id: str):
    for m in policy_terms["members"]:
        # Skip non-dict entries defensively
        if not isinstance(m, dict):
            continue
        if m.get("member_id") == member_id:
            return m
    return None


def _get_category_config(policy_terms: Dict, category: str) -> Optional[Dict]:
    return policy_terms.get("opd_categories", {}).get(category.lower())


def _parse_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _get_line_items(extracted_json: Dict) -> List[Dict]:
    """Pull all line_items from every extracted document."""
    if not extracted_json:
        return []
    items: List[Dict] = []
    for doc in extracted_json.get("extracted_documents", []):
        for item in doc.get("fields", {}).get("line_items", []):
            items.append(item)
    return items


def _get_diagnosis(extracted_json: Dict) -> str:
    if not extracted_json:
        return ""
    for doc in extracted_json.get("extracted_documents", []):
        d = doc.get("fields", {}).get("diagnosis", "")
        if d:
            return d.lower()
    return ""


def _get_hospital_name(extracted_json: Dict) -> str:
    if not extracted_json:
        return ""
    for doc in extracted_json.get("extracted_documents", []):
        h = doc.get("fields", {}).get("hospital_name", "")
        if h:
            return h
    return ""


def _is_network_hospital(policy_terms: Dict, hospital_name: str) -> bool:
    if not hospital_name:
        return False
    for n in policy_terms.get("network_hospitals", []):
        if n.lower() in hospital_name.lower() or hospital_name.lower() in n.lower():
            return True
    return False


def _check_exclusions(policy_terms: Dict, diagnosis: str, line_items: List[Dict]) -> Optional[str]:
    """Return the matched exclusion string, or None if clean."""
    exclusions = [e.lower() for e in policy_terms.get("exclusions", {}).get("conditions", [])]

    # check diagnosis
    for exc in exclusions:
        if not exc:
            continue
        if exc in diagnosis:
            return exc

    # check line item descriptions
    for item in line_items:
        desc = item.get("description", "").lower()
        for exc in exclusions:
            if exc and exc in desc:
                return exc

    return None


def _check_waiting_period(policy_terms: Dict, member: Dict, treatment_date_str: str, diagnosis: str):
    """
    Returns (blocked: bool, reason: str, eligible_from: str | None).
    """
    join_date = _parse_date(member.get("join_date", ""))
    treatment_date = _parse_date(treatment_date_str)
    if not join_date or not treatment_date:
        return False, "", None

    # initial waiting period
    initial_days = policy_terms["waiting_periods"]["initial_waiting_period_days"]
    if treatment_date < join_date + timedelta(days=initial_days):
        eligible = join_date + timedelta(days=initial_days)
        return (
            True,
            f"Initial {initial_days}-day waiting period not completed.",
            eligible.strftime("%Y-%m-%d"),
        )

    # specific condition waiting periods
    specific = policy_terms["waiting_periods"]["specific_conditions"]
    condition_keywords = {
        "diabetes": ["diabetes", "diabetic", "metformin", "glimepiride", "insulin"],
        "hypertension": ["hypertension", "high blood pressure", "bp", "amlodipine", "atenolol"],
        "thyroid_disorders": ["thyroid", "hypothyroid", "hyperthyroid", "thyroxine"],
        "joint_replacement": ["joint replacement", "knee replacement", "hip replacement"],
        "maternity": ["maternity", "pregnancy", "antenatal", "prenatal", "delivery"],
        "mental_health": ["mental health", "depression", "anxiety", "psychiatry"],
        "obesity_treatment": ["obesity", "weight loss", "bariatric"],
        "hernia": ["hernia"],
        "cataract": ["cataract"],
    }

    for condition, days in specific.items():
        kws = condition_keywords.get(condition, [condition.replace("_", " ")])
        if any(kw in diagnosis for kw in kws):
            eligible = join_date + timedelta(days=days)
            if treatment_date < eligible:
                return (
                    True,
                    f"Waiting period for {condition.replace('_', ' ')} is {days} days. "
                    f"Eligible from {eligible.strftime('%Y-%m-%d')}.",
                    eligible.strftime("%Y-%m-%d"),
                )

    return False, "", None


# ── category handlers ─────────────────────────────────────────────────────────

def _evaluate_consultation(raw_claim, policy_terms, extracted_json, trace, document_errors):
    category_config = _get_category_config(policy_terms, "consultation")
    sub_limit = category_config["sub_limit"]
    copay_pct = category_config["copay_percent"]
    network_discount_pct = category_config.get("network_discount_percent", 0)
    per_claim_limit = policy_terms["coverage"]["per_claim_limit"]
    claimed = raw_claim["claimed_amount"]

    # per-claim limit check
    if claimed > per_claim_limit:
        trace.append(
            {
                "step": "Per-claim limit",
                "agent": "PolicyAgent",
                "status": "FAILED",
                "detail": f"Claimed ₹{claimed} exceeds per_claim_limit ₹{per_claim_limit}.",
            }
        )
        return {
            "decision": "REJECTED",
            "approved_amount": 0,
            "claimed_amount": raw_claim["claimed_amount"],
            "rejection_reasons": ["PER_CLAIM_EXCEEDED"],
            "reason": f"Claimed amount ₹{claimed} exceeds the per-claim limit of ₹{per_claim_limit}.",
            "confidence": 0.95,
            "trace": trace,
            "document_errors": document_errors,
        }

    # network discount
    hospital_name = _get_hospital_name(extracted_json)
    is_network = _is_network_hospital(policy_terms, hospital_name)
    base_amount = claimed
    if is_network and network_discount_pct:
        discount = round(base_amount * network_discount_pct / 100, 2)
        base_amount = round(base_amount - discount, 2)
        trace.append(
            {
                "step": "Network discount",
                "agent": "PolicyAgent",
                "status": "PASSED",
                "detail": f"{hospital_name} is a network hospital. "
                          f"{network_discount_pct}% discount applied: ₹{discount} off → base ₹{base_amount}.",
            }
        )

    # sub-limit cap
    eligible = min(base_amount, sub_limit)
    trace.append(
        {
            "step": "Sub-limit check",
            "agent": "PolicyAgent",
            "status": "PASSED",
            "detail": f"Eligible after sub_limit=₹{sub_limit}: ₹{eligible}.",
        }
    )

    # copay
    copay = round(eligible * copay_pct / 100, 2)
    approved = round(eligible - copay, 2)
    trace.append(
        {
            "step": "Copay application",
            "agent": "PolicyAgent",
            "status": "PASSED",
            "detail": f"Copay {copay_pct}% on ₹{eligible} → copay=₹{copay}, approved=₹{approved}.",
        }
    )

    confidence = 0.95 if not document_errors else 0.6
    return {
        "decision": "APPROVED",
        "approved_amount": approved,
        "claimed_amount": raw_claim["claimed_amount"],
        "reason": "Consultation claim approved within sub-limit after applying copay.",
        "confidence": confidence,
        "trace": trace,
        "document_errors": document_errors,
    }


def _evaluate_dental(raw_claim, policy_terms, extracted_json, trace, document_errors):
    category_config = _get_category_config(policy_terms, "dental")
    sub_limit = category_config["sub_limit"]
    covered_procedures = [p.lower() for p in category_config.get("covered_procedures", [])]
    excluded_procedures = [p.lower() for p in category_config.get("excluded_procedures", [])]
    line_items = _get_line_items(extracted_json)

    if not line_items:
        approved = min(raw_claim["claimed_amount"], sub_limit)
        trace.append(
            {
                "step": "Dental sub-limit",
                "agent": "PolicyAgent",
                "status": "PASSED",
                "detail": f"No line items found. Approved up to sub_limit ₹{sub_limit}: ₹{approved}.",
            }
        )
        return {
            "decision": "APPROVED",
            "approved_amount": approved,
            "claimed_amount": raw_claim["claimed_amount"],
            "reason": "Dental claim approved (no line-item breakdown available).",
            "confidence": 0.7,
            "trace": trace,
            "document_errors": document_errors,
        }

    approved_items: List[Dict[str, Any]] = []
    rejected_items: List[Dict[str, Any]] = []
    approved_total = 0.0

    for item in line_items:
        desc = item.get("description", "").lower()
        amount = item.get("amount", 0)
        is_excluded = any(exc in desc for exc in excluded_procedures)
        is_covered = any(cov in desc for cov in covered_procedures)

        if is_excluded:
            rejected_items.append(
                {
                    "description": item.get("description", ""),
                    "amount": amount,
                    "reason": "Cosmetic/excluded dental procedure",
                }
            )
        elif is_covered:
            approved_items.append(
                {"description": item.get("description", ""), "amount": amount}
            )
            approved_total += amount
        else:
            approved_items.append(
                {
                    "description": item.get("description", ""),
                    "amount": amount,
                    "note": "Not explicitly listed; approved by default",
                }
            )
            approved_total += amount

    approved_total = min(approved_total, sub_limit)

    trace.append(
        {
            "step": "Dental line-item review",
            "agent": "PolicyAgent",
            "status": "PASSED" if not rejected_items else "PARTIAL",
            "detail": f"Approved items: {[i['description'] for i in approved_items]}. "
                      f"Rejected: {[i['description'] for i in rejected_items]}.",
        }
    )

    decision = "PARTIAL" if rejected_items else "APPROVED"
    return {
        "decision": decision,
        "approved_amount": approved_total,
        "claimed_amount": raw_claim["claimed_amount"],
        "reason": (
            "Dental claim partially approved. "
            f"Rejected: {[i['description'] for i in rejected_items] or 'none'}."
            if rejected_items
            else "Dental claim fully approved."
        ),
        "notes": {"approved_items": approved_items, "rejected_items": rejected_items},
        "confidence": 0.9,
        "trace": trace,
        "document_errors": document_errors,
    }


def _evaluate_diagnostic(raw_claim, policy_terms, extracted_json, trace, document_errors):
    category_config = _get_category_config(policy_terms, "diagnostic")
    sub_limit = category_config["sub_limit"]
    pre_auth_threshold = category_config.get("pre_auth_threshold", 10000)
    high_value_tests = [
        t.lower() for t in category_config.get("high_value_tests_requiring_pre_auth", [])
    ]
    claimed = raw_claim["claimed_amount"]

    line_items = _get_line_items(extracted_json)
    diagnosis = _get_diagnosis(extracted_json)
    all_text = diagnosis + " " + " ".join(
        i.get("description", "").lower() for i in line_items
    )

    needs_pre_auth = claimed > pre_auth_threshold and any(
        t in all_text for t in high_value_tests
    )
    pre_auth_ref = raw_claim.get("pre_auth_ref") or (extracted_json or {}).get("pre_auth_ref")

    if needs_pre_auth and not pre_auth_ref:
        trace.append(
            {
                "step": "Pre-auth check",
                "agent": "PolicyAgent",
                "status": "FAILED",
                "detail": f"Claim amount ₹{claimed} > ₹{pre_auth_threshold} for a high-value "
                          f"diagnostic test. Pre-authorization required but not provided.",
            }
        )
        return {
            "decision": "REJECTED",
            "approved_amount": 0,
            "claimed_amount": raw_claim["claimed_amount"],
            "rejection_reasons": ["PRE_AUTH_MISSING"],
            "reason": f"MRI/CT/PET scan above ₹{pre_auth_threshold} requires pre-authorization. "
                      "Please submit a pre-auth reference before resubmitting.",
            "confidence": 0.95,
            "trace": trace,
            "document_errors": document_errors,
        }

    approved = min(claimed, sub_limit)
    trace.append(
        {
            "step": "Diagnostic sub-limit",
            "agent": "PolicyAgent",
            "status": "PASSED",
            "detail": f"Approved ₹{approved} (sub_limit=₹{sub_limit}).",
        }
    )
    return {
        "decision": "APPROVED",
        "approved_amount": approved,
        "claimed_amount": raw_claim["claimed_amount"],
        "reason": "Diagnostic claim approved within sub-limit.",
        "confidence": 0.9,
        "trace": trace,
        "document_errors": document_errors,
    }


def _evaluate_pharmacy(raw_claim, policy_terms, extracted_json, trace, document_errors):
    category_config = _get_category_config(policy_terms, "pharmacy")
    sub_limit = category_config["sub_limit"]
    copay_pct = category_config.get("copay_percent", 0)
    claimed = raw_claim["claimed_amount"]

    approved = min(claimed, sub_limit)
    if copay_pct:
        copay = round(approved * copay_pct / 100, 2)
        approved = round(approved - copay, 2)

    trace.append(
        {
            "step": "Pharmacy sub-limit",
            "agent": "PolicyAgent",
            "status": "PASSED",
            "detail": f"Approved ₹{approved} after sub_limit ₹{sub_limit} and copay {copay_pct}%.",
        }
    )
    return {
        "decision": "APPROVED",
        "approved_amount": approved,
        "claimed_amount": raw_claim["claimed_amount"],
        "reason": "Pharmacy claim approved.",
        "confidence": 0.85,
        "trace": trace,
        "document_errors": document_errors,
    }


def _evaluate_alternative_medicine(raw_claim, policy_terms, extracted_json, trace, document_errors):
    category_config = _get_category_config(policy_terms, "alternative_medicine")
    sub_limit = category_config["sub_limit"]
    claimed = raw_claim["claimed_amount"]
    approved = min(claimed, sub_limit)
    trace.append(
        {
            "step": "Alternative medicine sub-limit",
            "agent": "PolicyAgent",
            "status": "PASSED",
            "detail": f"Approved ₹{approved} (sub_limit=₹{sub_limit}).",
        }
    )
    return {
        "decision": "APPROVED",
        "approved_amount": approved,
        "claimed_amount": raw_claim["claimed_amount"],
        "reason": "Alternative medicine claim approved within sub-limit.",
        "confidence": 0.85,
        "trace": trace,
        "document_errors": document_errors,
    }


def _evaluate_vision(raw_claim, policy_terms, extracted_json, trace, document_errors):
    category_config = _get_category_config(policy_terms, "vision")
    sub_limit = category_config["sub_limit"]
    claimed = raw_claim["claimed_amount"]
    approved = min(claimed, sub_limit)
    trace.append(
        {
            "step": "Vision sub-limit",
            "agent": "PolicyAgent",
            "status": "PASSED",
            "detail": f"Approved ₹{approved} (sub_limit=₹{sub_limit}).",
        }
    )
    return {
        "decision": "APPROVED",
        "approved_amount": approved,
        "claimed_amount": raw_claim["claimed_amount"],
        "reason": "Vision claim approved within sub-limit.",
        "confidence": 0.85,
        "trace": trace,
        "document_errors": document_errors,
    }


# ── fraud check ───────────────────────────────────────────────────────────────

def _check_fraud(raw_claim, policy_terms, trace):
    thresholds = policy_terms.get("fraud_thresholds", {})
    same_day_limit = thresholds.get("same_day_claims_limit", 2)
    same_day_count = raw_claim.get("same_day_claims_count", 0)
    if same_day_count > same_day_limit:
        trace.append(
            {
                "step": "Fraud detection",
                "agent": "PolicyAgent",
                "status": "FAILED",
                "detail": f"Same-day claims count {same_day_count} exceeds limit {same_day_limit}. "
                          "Flagged for manual review.",
            }
        )
        return True
    return False


# ── main entry ────────────────────────────────────────────────────────────────

def policy_tool_fn(state: Dict[str, Any]) -> Dict[str, Any]:
    raw_claim = state["raw_claim"]
    policy_terms = state["policy_terms"]
    extracted_json = state.get("extracted_json") or {}
    document_errors = state.get("document_gate_json", {}).get("errors", [])

    trace: List[Dict[str, Any]] = []
    category = raw_claim.get("claim_category", "").upper()
    claimed = raw_claim["claimed_amount"]
    member_id = raw_claim.get("member_id")
    treatment_date = str(raw_claim.get("treatment_date", ""))

    # 1. Member lookup
    member = _get_member(policy_terms, member_id)
    if not member:
        state["policy_json"] = {
            "decision": "REJECTED",
            "approved_amount": 0,
            "claimed_amount": raw_claim["claimed_amount"],
            "rejection_reasons": ["MEMBER_NOT_FOUND"],
            "reason": f"Member {member_id} not found in policy.",
            "confidence": 1.0,
            "trace": trace,
            "document_errors": document_errors,
        }
        return state

    trace.append(
        {
            "step": "Member lookup",
            "agent": "PolicyAgent",
            "status": "PASSED",
            "detail": f"Member {member['name']} ({member_id}) found. "
                      f"Join date: {member['join_date']}.",
        }
    )

    # 2. Category config
    category_config = _get_category_config(policy_terms, category)
    if not category_config:
        state["policy_json"] = {
            "decision": "MANUAL_REVIEW",
            "approved_amount": 0,
            "claimed_amount": raw_claim["claimed_amount"],
            "reason": f"Category {category} not found in policy.",
            "confidence": 0.4,
            "trace": trace,
            "document_errors": document_errors,
        }
        return state

    trace.append(
        {
            "step": "Policy lookup",
            "agent": "PolicyAgent",
            "status": "PASSED",
            "detail": f"{category} sub_limit=₹{category_config.get('sub_limit')}, "
                      f"copay={category_config.get('copay_percent', 0)}%.",
        }
    )

    # 3. Minimum claim amount
    min_claim = policy_terms.get("submission_rules", {}).get("minimum_claim_amount", 500)
    if claimed < min_claim:
        state["policy_json"] = {
            "decision": "REJECTED",
            "approved_amount": 0,
            "claimed_amount": raw_claim["claimed_amount"],
            "rejection_reasons": ["BELOW_MINIMUM"],
            "reason": f"Claimed amount ₹{claimed} is below minimum ₹{min_claim}.",
            "confidence": 1.0,
            "trace": trace,
            "document_errors": document_errors,
        }
        return state

    # 4. Exclusions check
    diagnosis = _get_diagnosis(extracted_json)
    line_items = _get_line_items(extracted_json)
    exclusion_hit = _check_exclusions(policy_terms, diagnosis, line_items)
    if exclusion_hit:
        trace.append(
            {
                "step": "Exclusions check",
                "agent": "PolicyAgent",
                "status": "FAILED",
                "detail": f"Matched exclusion: '{exclusion_hit}'.",
            }
        )
        state["policy_json"] = {
            "decision": "REJECTED",
            "approved_amount": 0,
            "claimed_amount": raw_claim["claimed_amount"],
            "rejection_reasons": ["EXCLUDED_CONDITION"],
            "reason": (
                "Treatment relates to an excluded condition: "
                f"'{exclusion_hit}'. This is not covered under your policy."
            ),
            "confidence": 0.95,
            "trace": trace,
            "document_errors": document_errors,
        }
        return state

    trace.append(
        {
            "step": "Exclusions check",
            "agent": "PolicyAgent",
            "status": "PASSED",
            "detail": "No exclusions matched.",
        }
    )

    # 5. Waiting period check
    blocked, wp_reason, eligible_from = _check_waiting_period(
        policy_terms, member, treatment_date, diagnosis
    )
    if blocked:
        trace.append(
            {
                "step": "Waiting period check",
                "agent": "PolicyAgent",
                "status": "FAILED",
                "detail": wp_reason,
            }
        )
        state["policy_json"] = {
            "decision": "REJECTED",
            "approved_amount": 0,
            "claimed_amount": raw_claim["claimed_amount"],
            "rejection_reasons": ["WAITING_PERIOD"],
            "reason": wp_reason + (f" Eligible from: {eligible_from}." if eligible_from else ""),
            "confidence": 0.95,
            "trace": trace,
            "document_errors": document_errors,
        }
        return state

    trace.append(
        {
            "step": "Waiting period check",
            "agent": "PolicyAgent",
            "status": "PASSED",
            "detail": "No waiting period restrictions apply.",
        }
    )

    # 6. Fraud check
    is_fraud = _check_fraud(raw_claim, policy_terms, trace)
    if is_fraud:
        state["policy_json"] = {
            "decision": "MANUAL_REVIEW",
            "approved_amount": 0,
            "claimed_amount": raw_claim["claimed_amount"],
            "reason": "Claim flagged for manual review due to fraud signal: excessive same-day claims.",
            "confidence": 0.5,
            "trace": trace,
            "document_errors": document_errors,
        }
        return state

    # 7. Category-specific evaluation
    handler = {
        "CONSULTATION": _evaluate_consultation,
        "DENTAL": _evaluate_dental,
        "DIAGNOSTIC": _evaluate_diagnostic,
        "PHARMACY": _evaluate_pharmacy,
        "ALTERNATIVE_MEDICINE": _evaluate_alternative_medicine,
        "VISION": _evaluate_vision,
    }.get(category)

    if handler:
        result = handler(raw_claim, policy_terms, extracted_json, trace, document_errors)
    else:
        result = {
            "decision": "MANUAL_REVIEW",
            "approved_amount": 0,
            "claimed_amount": raw_claim["claimed_amount"],
            "reason": f"No policy logic implemented for {category}.",
            "confidence": 0.4,
            "trace": trace,
            "document_errors": document_errors,
        }

    state["policy_json"] = result
    return state
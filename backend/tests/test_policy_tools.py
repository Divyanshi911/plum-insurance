# backend/tests/run_policy_on_test_cases.py

import sys
import json
from pathlib import Path
from typing import Dict, Any, List

# Ensure project root (one level above "backend") is on sys.path
THIS_FILE = Path(__file__).resolve()
BACKEND_DIR = THIS_FILE.parents[1]           # ...\plum-insurance\backend
PROJECT_ROOT = BACKEND_DIR.parent           # ...\plum-insurance

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.config import load_policy_terms
from backend.tools.policy_tool import policy_tool_fn
from backend.tools.decision_tool import decision_tool_fn

TEST_CASES_PATH = BACKEND_DIR / "tests" / "test_cases.json"
TEST_RESPONSES_PATH = BACKEND_DIR / "tests" / "test_responses.json"


def build_raw_claim(case_input: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "member_id": case_input["member_id"],
        "claim_category": case_input["claim_category"],
        "treatment_date": case_input["treatment_date"],
        "claimed_amount": case_input["claimed_amount"],
    }


def build_extracted_json(case_input: Dict[str, Any]) -> Dict[str, Any]:
    extracted_documents: List[Dict[str, Any]] = []
    for idx, doc in enumerate(case_input.get("documents", [])):
        content = doc.get("content") or {}
        extracted_documents.append(
            {
                "filename": doc.get("file_name") or doc.get("file_id") or f"doc_{idx}",
                "doc_type": doc.get("actual_type", "UNKNOWN"),
                "fields": content,
                "confidence": 1.0,
                "low_confidence_fields": [],
                "validation_issues": [],
            }
        )

    return {
        "extracted_documents": extracted_documents,
        "extraction_errors": [],
        "low_confidence": False,
    }


def run_case(case: Dict[str, Any], policy_terms: Dict[str, Any]) -> Dict[str, Any]:
    case_id = case["case_id"]
    case_name = case["case_name"]
    inp = case["input"]

    print(f"\n=== {case_id}: {case_name} ===")

    raw_claim = build_raw_claim(inp)
    extracted_json = build_extracted_json(inp)

    # Skip document verification in tests
    document_gate_json = {
        "ok": True,
        "uploaded_types": [],
        "required_types": [],
        "errors": [],
    }

    state: Dict[str, Any] = {
        "raw_claim": raw_claim,
        "policy_terms": policy_terms,
        "extracted_json": extracted_json,
        "document_gate_json": document_gate_json,
    }

    state = policy_tool_fn(state)
    state = decision_tool_fn(state)

    policy_json = state.get("policy_json")
    decision_json = state.get("decision_json")

    print("raw_claim:")
    print(json.dumps(raw_claim, indent=2, ensure_ascii=False))

    print("extracted_json:")
    print(json.dumps(extracted_json, indent=2, ensure_ascii=False))

    print("policy_json:")
    print(json.dumps(policy_json, indent=2, ensure_ascii=False))

    print("decision_json:")
    print(json.dumps(decision_json, indent=2, ensure_ascii=False))

    # Return a structured summary for file output
    return {
        "case_id": case_id,
        "case_name": case_name,
        "raw_claim": raw_claim,
        "extracted_json": extracted_json,
        "policy_json": policy_json,
        "decision_json": decision_json,
    }


def main() -> None:
    if not TEST_CASES_PATH.exists():
        print(f"Could not find {TEST_CASES_PATH.resolve()}")
        return

    test_data = json.loads(TEST_CASES_PATH.read_text(encoding="utf-8"))
    test_cases = test_data.get("test_cases", [])

    policy_terms = load_policy_terms()

    print(f"Loaded {len(test_cases)} test cases from {TEST_CASES_PATH}")

    all_results: List[Dict[str, Any]] = []
    for case in test_cases:
        result = run_case(case, policy_terms)
        all_results.append(result)

    # Save all results to test_responses.json
    output = {
        "source_test_file": str(TEST_CASES_PATH),
        "total_cases": len(all_results),
        "cases": all_results,
    }
    TEST_RESPONSES_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nSaved responses to {TEST_RESPONSES_PATH}")


if __name__ == "__main__":
    main()
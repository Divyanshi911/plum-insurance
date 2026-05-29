# backend/tests/run_test_cases.py

import json
from pathlib import Path

import requests


API_URL = "http://127.0.0.1:8000/claims/submit"
TEST_CASES_PATH = Path("test_cases.json")


def build_dummy_file(doc: dict) -> tuple[str, bytes, str]:
    """
    Build a fake file tuple (filename, content_bytes, mime_type) for requests.

    Uses file_name if present, otherwise file_id, and encodes the `content`
    field as JSON text when available.
    """
    # filename
    filename = doc.get("file_name") or f"{doc['file_id']}.txt"

    # body
    content_obj = doc.get("content")
    if content_obj is not None:
        body = json.dumps(content_obj, ensure_ascii=False).encode("utf-8")
    else:
        # if there's no structured content, just dump the doc dict
        body = json.dumps(doc, ensure_ascii=False).encode("utf-8")

    # use text/plain as a generic content type; your backend treats it as opaque anyway
    return filename, body, "text/plain"


def run_one_case(case: dict) -> None:
    case_id = case["case_id"]
    case_name = case["case_name"]
    inp = case["input"]

    print(f"\n=== {case_id}: {case_name} ===")

    # Pick the first document to attach as the uploaded file
    if not inp["documents"]:
        print("No documents in this test case; skipping.")
        return

    first_doc = inp["documents"][0]
    filename, body, mime = build_dummy_file(first_doc)

    # Build multipart/form-data payload
    files = {
        "file": (filename, body, mime),
    }
    data_form = {
        "member_id": inp["member_id"],
        "claim_category": inp["claim_category"],
        "treatment_date": inp["treatment_date"],
        "claimed_amount": inp["claimed_amount"],
    }

    try:
        resp = requests.post(API_URL, data=data_form, files=files)
    except Exception as e:
        print(f"Request error: {e}")
        return

    print("HTTP status:", resp.status_code)
    try:
        print("Response JSON:")
        print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
    except Exception:
        print("Non-JSON response:")
        print(resp.text)


def main() -> None:
    if not TEST_CASES_PATH.exists():
        print(f"Could not find {TEST_CASES_PATH.resolve()}")
        return

    data = json.loads(TEST_CASES_PATH.read_text(encoding="utf-8"))
    test_cases = data.get("test_cases", [])

    print(f"Loaded {len(test_cases)} test cases from {TEST_CASES_PATH}")
    for case in test_cases:
        run_one_case(case)


if __name__ == "__main__":
    main()
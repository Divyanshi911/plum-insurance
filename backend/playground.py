# backend/playground.py (direct test)

import io
import json
import asyncio
from pathlib import Path
from starlette.datastructures import Headers
from fastapi import UploadFile

from core.config import load_policy_terms
from tools.preprocessing_tool import preprocess_upload_files, PreprocessedDocument  # original async [file:145]
from tools.extraction_tool import extract_structured_from_docs  # original function [file:144]
from tools.document_tool import check_document_requirements
from schemas.claim import UploadedDocument
from tools.policy_tool import policy_tool_fn
from tools.decision_tool import decision_tool_fn


def build_test_state():
    policy_terms = load_policy_terms()
    pdf_path = Path("backend/data/Medical_Bill_Suresh.pdf")
    pdf_bytes = pdf_path.read_bytes()

    return {
        "raw_claim": {
            "member_id": "EMP001",
            "claim_category": "CONSULTATION",
            "treatment_date": "2025-05-01",
            "claimed_amount": 1000.0,
        },
        "documents": [
            {
                "filename": pdf_path.name,
                "content_type": "application/pdf",
                "bytes": pdf_bytes,
            }
        ],
        "policy_terms": policy_terms,
    }


async def main():
    state = build_test_state()

    # 1) Preprocessing
    uploads = []
    for d in state["documents"]:
        headers = Headers({"content-type": d["content_type"]})
        uploads.append(
            UploadFile(
                filename=d["filename"],
                file=io.BytesIO(d["bytes"]),
                headers=headers,
            )
        )
    preprocessed_docs = await preprocess_upload_files(uploads, doc_type_hints=None)
    # If this line throws, preprocessed_docs is None
    state["preprocessed_json"] = [doc.to_dict() for doc in preprocessed_docs]

    # 2) DocumentGate
    docs_meta = [
        UploadedDocument(filename=d["filename"], content_type=d["content_type"])
        for d in state["documents"]
    ]
    state["documents_meta"] = [dm.model_dump() for dm in docs_meta]
    gate_result = check_document_requirements(
        claim_category=state["raw_claim"]["claim_category"],
        documents_meta=docs_meta,
        document_requirements=state["policy_terms"]["document_requirements"],
    )
    state["document_gate_json"] = gate_result

    # 3) Extraction
    pre_docs_objs = [
        PreprocessedDocument(
            filename=d["filename"],
            doc_type_hint=d["doc_type_hint"],
            content_type=d["content_type"],
            processed_type=d["processed_type"],
            processed_images=d["processed_images"],
            extracted_text=d["extracted_text"],
        )
        for d in state["preprocessed_json"]
    ]
    extraction_result = extract_structured_from_docs(pre_docs_objs)
    state["extracted_json"] = extraction_result

    # 4) Policy
    state = policy_tool_fn(state)
    # 5) Decision
    state = decision_tool_fn(state)

    print(json.dumps(state["decision_json"], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
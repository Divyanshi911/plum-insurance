# backend/tools/extraction_tool.py

from typing import List, Dict, Any, Optional
from backend.llm.client import (
    LLMClient,
    LLMAuthError,
    LLMRateLimitError,
    LLMTemporaryError,
    LLMResponseFormatError,
)
from backend.tools.preprocessing_tool import PreprocessedDocument


def build_extraction_prompt(doc: PreprocessedDocument) -> str:
    ...
    # (your existing code unchanged)
    ...


def extract_structured_from_docs(
    preprocessed_docs: List[PreprocessedDocument],
    model: str = "gemini-3.5-flash",
) -> Dict[str, Any]:
    ...
    # (your existing code unchanged)
    ...


# ---------- ADK tool wrapper ----------

def extraction_tool_fn(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    ADK tool function.

    Expects in state:
      - preprocessed_json: list of dicts representing PreprocessedDocument
    Writes into state:
      - extracted_json: the result of extract_structured_from_docs(...)
    """
    preprocessed_list = state.get("preprocessed_json") or []

    # Convert dicts back into PreprocessedDocument objects
    preprocessed_docs: List[PreprocessedDocument] = []
    for d in preprocessed_list:
        doc = PreprocessedDocument(
            filename=d.get("filename"),
            doc_type_hint=d.get("doc_type_hint"),
            content_type=d.get("content_type"),
            processed_type=d.get("processed_type"),
            processed_images=d.get("processed_images"),
            extracted_text=d.get("extracted_text"),
        )
        preprocessed_docs.append(doc)

    extraction_result = extract_structured_from_docs(preprocessed_docs)
    state["extracted_json"] = extraction_result
    return state


# This is what ADK agents should import:
extraction_tool = extraction_tool_fn
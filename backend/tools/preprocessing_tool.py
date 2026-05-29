# backend/tools/preprocessing_tool.py
#
# Two things live here:
#
#   1. PreprocessedDocument  — Pydantic model (ADK can JSON-schema this)
#   2. preprocess_upload_files — the actual ADK tool function
#
# Rules that make this work with FunctionTool:
#   - Every parameter and return type must be JSON-serialisable
#   - No raw bytes, no PIL Image, no numpy array, no UploadFile in signatures
#   - Images travel as base64 strings throughout
#   - Function must be synchronous (FunctionTool handles the event loop)

import base64
import traceback
from typing import Any, Dict, List, Literal, Optional

import cv2
import numpy as np
from pydantic import BaseModel

# ── Your existing preprocessing helpers ──────────────────────────────────────
from backend.preprocessing.img import image_from_bytes, preprocess_image
from backend.preprocessing.pdf import (
    extract_text_from_pdf,
    is_text_pdf,
    pdf_to_images,
)


# ── Fix 1: Pydantic model so ADK can generate JSON schema ────────────────────

class PreprocessedDocument(BaseModel):
    """
    JSON-serialisable result of preprocessing one uploaded file.
    All image data is stored as base64 strings — never raw bytes or numpy arrays.
    """
    filename:        str
    content_type:    str
    doc_type_hint:   Optional[str]  = None

    # "IMAGE" | "TEXT_PDF" | "IMAGE_PDF"
    processed_type:  Literal["IMAGE", "TEXT_PDF", "IMAGE_PDF"]

    # base64-encoded PNG bytes, one entry per page
    processed_images_b64: List[str] = []

    # populated for TEXT_PDF only
    extracted_text: Optional[str]  = None

    # any error that happened during preprocessing for this file
    error:          Optional[str]  = None


# ── Helper: numpy BGR array → base64 PNG string ───────────────────────────────

def _bgr_to_b64(bgr: np.ndarray) -> str:
    _, buf = cv2.imencode(".png", bgr)
    return base64.b64encode(bytes(buf)).decode("utf-8")


# ── Fix 2: actual processing logic (was a stub returning []) ─────────────────

def _process_one(
    filename:     str,
    content_type: str,
    file_bytes:   bytes,
    hint:         Optional[str],
) -> PreprocessedDocument:
    """
    Preprocess a single file. Returns a PreprocessedDocument.
    Never raises — errors are captured in the .error field.
    """
    try:
        if content_type.startswith("image/"):
            bgr        = image_from_bytes(file_bytes)
            processed  = preprocess_image(bgr)
            b64_images = [_bgr_to_b64(processed)]
            return PreprocessedDocument(
                filename=filename,
                content_type=content_type,
                doc_type_hint=hint,
                processed_type="IMAGE",
                processed_images_b64=b64_images,
            )

        elif content_type == "application/pdf":
            if is_text_pdf(file_bytes):
                text = extract_text_from_pdf(file_bytes)
                return PreprocessedDocument(
                    filename=filename,
                    content_type=content_type,
                    doc_type_hint=hint,
                    processed_type="TEXT_PDF",
                    extracted_text=text,
                )
            else:
                page_bgrs  = pdf_to_images(file_bytes)
                b64_images = [
                    _bgr_to_b64(preprocess_image(page))
                    for page in page_bgrs
                ]
                return PreprocessedDocument(
                    filename=filename,
                    content_type=content_type,
                    doc_type_hint=hint,
                    processed_type="IMAGE_PDF",
                    processed_images_b64=b64_images,
                )

        else:
            # Unknown type — pass through as empty IMAGE so pipeline continues
            return PreprocessedDocument(
                filename=filename,
                content_type=content_type,
                doc_type_hint=hint,
                processed_type="IMAGE",
                error=f"Unsupported content_type '{content_type}' — no preprocessing applied.",
            )

    except Exception:
        return PreprocessedDocument(
            filename=filename,
            content_type=content_type,
            doc_type_hint=hint,
            processed_type="IMAGE",
            error=traceback.format_exc(),
        )


# ── Fix 3: ADK tool function — sync, plain dict in / dict out ────────────────

def preprocess_upload_files(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    ADK FunctionTool entry point.

    Reads from state:
        documents: list of {filename, content_type, bytes_b64}
        doc_type_hints (optional): {filename -> hint string}

    Writes to state:
        preprocessed_json: list of PreprocessedDocument dicts

    Never raises — individual file errors are captured per document.
    """
    docs:     List[Dict[str, Any]] = state.get("documents") or []
    hints:    Dict[str, str]       = state.get("doc_type_hints") or {}
    results:  List[Dict[str, Any]] = []

    for d in docs:
        filename     = d.get("filename", "unknown")
        content_type = d.get("content_type", "application/octet-stream")
        b64          = d.get("bytes_b64", "")
        hint         = hints.get(filename)

        try:
            file_bytes = base64.b64decode(b64)
        except Exception as exc:
            results.append(PreprocessedDocument(
                filename=filename,
                content_type=content_type,
                doc_type_hint=hint,
                processed_type="IMAGE",
                error=f"Could not decode base64: {exc}",
            ).model_dump())
            continue

        doc = _process_one(filename, content_type, file_bytes, hint)
        results.append(doc.model_dump())

    state["preprocessed_json"] = results
    return state
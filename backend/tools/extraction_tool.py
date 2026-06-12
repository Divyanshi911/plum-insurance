# backend/tools/extraction_tool.py
# OCR via pytesseract — no PyTorch, no EasyOCR, works on Windows

import base64
import io
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import pytesseract
from PIL import Image

# ── Tell pytesseract where Tesseract is installed ─────────────────────────────
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

CONFIDENCE_FLOOR = 0.50
USE_LLM_FALLBACK = False    # no API credits — pure OCR


def _ocr_image_b64(image_b64: str) -> Tuple[str, float]:
    """
    Run Tesseract on a base64 PNG image.
    Returns (full_text, confidence).
    """
    img_bytes = base64.b64decode(image_b64)
    pil_img   = Image.open(io.BytesIO(img_bytes)).convert("RGB")

    # Get text + per-word confidence data
    data = pytesseract.image_to_data(
        pil_img,
        lang="eng",
        output_type=pytesseract.Output.DICT,
        config="--psm 6"    # assume uniform block of text
    )

    # Filter out empty/low confidence words
    words = []
    confs = []
    for i, word in enumerate(data["text"]):
        word = word.strip()
        conf = int(data["conf"][i])
        if word and conf > 0:
            words.append(word)
            confs.append(conf)

    if not words:
        return "", 0.0

    full_text  = " ".join(words)
    avg_conf   = sum(confs) / len(confs) / 100.0   # normalise 0–100 → 0.0–1.0

    return full_text, avg_conf


def _get_text(doc: Dict[str, Any]) -> Tuple[str, float]:
    """
    Get raw text from a PreprocessedDocument dict.
    TEXT_PDF  → already has text, confidence 1.0 (no OCR needed)
    IMAGE/PDF → run Tesseract on first page image
    """
    if doc.get("processed_type") == "TEXT_PDF":
        text = doc.get("extracted_text") or ""
        return text, 1.0 if text.strip() else 0.0

    images = doc.get("processed_images_b64") or []
    if not images:
        return "", 0.0
    return _ocr_image_b64(images[0])


# ── Regex helpers ──────────────────────────────────────────────────────────────

def _find(pattern, text, flags=re.IGNORECASE):
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None

def _find_amount(text):
    amounts = re.findall(r"(?:Rs\.?|₹|INR)\s*([\d,]+(?:\.\d{1,2})?)", text, re.IGNORECASE)
    if not amounts:
        amounts = re.findall(r"\b(\d{3,6}(?:\.\d{1,2})?)\b", text)
    if not amounts:
        return None
    return max(float(a.replace(",", "")) for a in amounts)

def _find_date(text):
    for p in [r"(\d{2}[-/]\d{2}[-/]\d{4})", r"(\d{4}[-/]\d{2}[-/]\d{2})", r"(\d{1,2}\s+\w{3}\s+\d{4})"]:
        m = re.search(p, text)
        if m:
            return m.group(1)
    return None

def _find_name(label, text):
    return _find(rf"{label}\s*[:\-]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,3}})", text)

def _find_reg(text):
    m = re.search(r"\b((?:KA|MH|DL|TN|GJ|AP|UP|WB|KL|RJ|MP|HR|PB)/\d{4,6}/\d{4})\b", text, re.I)
    return m.group(1) if m else None


def _parse_prescription(text):
    meds = re.findall(r"(?:\d+[\.)\s]|Tab\.?|Cap\.?|Syp\.?)\s*([A-Za-z][^\n]{3,50})", text)
    low  = []
    fields = {
        "doc_type":      "PRESCRIPTION",
        "doctor_name":   _find(r"Dr\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})", text),
        "doctor_reg":    _find_reg(text),
        "hospital_name": _find(r"([A-Za-z\s]{4,30}(?:Hospital|Clinic|Centre))", text),
        "patient_name":  _find_name("Patient", text) or _find_name("Name", text),
        "patient_age":   _find(r"\bAge\s*[:\-]?\s*(\d{1,3})", text),
        "date":          _find_date(text),
        "diagnosis":     _find(r"(?:Diagnosis|Dx)\s*[:\-]\s*([^\n]{3,60})", text),
        "medicines":     [{"name": m.strip()} for m in meds[:10]],
        "investigations":list(set(re.findall(r"\b(CBC|LFT|TSH|MRI|CT\s*Scan|Dengue|Typhoid|ECG)\b", text, re.I))),
    }
    for k in ["doctor_name", "patient_name", "diagnosis", "date"]:
        if not fields[k]: low.append(k)
    fields["low_confidence_fields"] = low
    return fields


def _parse_hospital_bill(text):
    low = []
    total_str = _find(r"(?:Grand\s+)?Total\s*[:\-]?\s*(?:Rs\.?|₹)?\s*([\d,]+(?:\.\d{2})?)", text)
    total     = float(total_str.replace(",", "")) if total_str else _find_amount(text)
    rows = re.findall(r"^(.{10,40}?)\s+(\d{1,6}(?:\.\d{2})?)\s*$", text, re.MULTILINE)
    items = [{"description": d.strip(), "amount": float(a)} for d, a in rows[:15] if float(a) > 0]
    fields = {
        "doc_type":       "HOSPITAL_BILL",
        "hospital_name":  _find(r"^([A-Z][A-Za-z\s]{3,35}(?:Hospital|Clinic|Centre|Medical))", text, re.MULTILINE),
        "bill_number":    _find(r"(?:Bill|Invoice)\s*(?:No|#)\.?\s*[:\-]?\s*([A-Z0-9/\-]{4,20})", text),
        "date":           _find_date(text),
        "patient_name":   _find_name("Patient", text) or _find_name("Name", text),
        "total_amount":   total,
        "line_items":     items,
    }
    for k in ["hospital_name", "total_amount", "patient_name", "bill_number"]:
        if not fields[k]: low.append(k)
    fields["low_confidence_fields"] = low
    return fields


def _parse_lab_report(text):
    rows = re.findall(
        r"^([A-Za-z][A-Za-z0-9\s\(\)]{3,35})\s+([\d\.]+|POSITIVE|NEGATIVE|REACTIVE)\s*([a-zA-Z/%µ]*)\s*([\d\.\-\s]*)?$",
        text, re.MULTILINE | re.IGNORECASE
    )
    tests = [{"name": n.strip(), "result": r.strip(), "unit": u.strip() or None} for n,r,u,_ in rows[:20] if len(n.strip()) > 3]
    low   = []
    fields = {
        "doc_type":      "LAB_REPORT",
        "lab_name":      _find(r"^([A-Z][A-Za-z\s]{3,30}(?:Lab|Diagnostics|Pathology))", text, re.MULTILINE),
        "patient_name":  _find_name("Patient", text) or _find_name("Name", text),
        "sample_date":   _find_date(text),
        "tests":         tests,
    }
    if not fields["patient_name"]: low.append("patient_name")
    if not tests:                  low.append("test_results")
    fields["low_confidence_fields"] = low
    return fields


def _parse_pharmacy_bill(text):
    rows = re.findall(
        r"^([A-Za-z][A-Za-z0-9\s\+\-\.]{4,30})\s+([A-Z0-9]{4,10})?\s*(\d{2}/\d{2,4})?\s*(\d{1,3})\s+([\d\.]+)\s+([\d\.]+)\s*$",
        text, re.MULTILINE
    )
    meds = [{"name": n.strip(), "batch": b or None, "expiry": e or None, "quantity": int(q), "mrp": float(m), "amount": float(a)} for n,b,e,q,m,a in rows[:20]]
    net_str = _find(r"(?:Net|Total)\s*[:\-]?\s*(?:Rs\.?|₹)?\s*([\d,]+(?:\.\d{2})?)", text)
    low = []
    fields = {
        "doc_type":     "PHARMACY_BILL",
        "pharmacy_name":_find(r"^([A-Z][A-Za-z\s]{3,25}(?:Pharmacy|Chemist|Medical))", text, re.MULTILINE),
        "drug_license": _find(r"Drug\s*Lic[:\-]?\s*([A-Z0-9\-]{5,20})", text),
        "bill_number":  _find(r"(?:Bill|Invoice)\s*(?:No|#)\.?\s*[:\-]?\s*([A-Z0-9/\-]{4,20})", text),
        "date":         _find_date(text),
        "patient_name": _find_name("Patient", text) or _find_name("Name", text),
        "medicines":    meds,
        "net_amount":   float(net_str.replace(",", "")) if net_str else _find_amount(text),
    }
    if not meds:                  low.append("medicines")
    if not fields["net_amount"]:  low.append("net_amount")
    fields["low_confidence_fields"] = low
    return fields


def _parse_discharge_summary(text):
    dates = re.findall(r"\d{2}[-/]\d{2}[-/]\d{4}|\d{4}[-/]\d{2}[-/]\d{2}", text)
    low   = []
    fields = {
        "doc_type":        "DISCHARGE_SUMMARY",
        "hospital_name":   _find(r"^([A-Z][A-Za-z\s]{3,35}(?:Hospital|Healthcare))", text, re.MULTILINE),
        "patient_name":    _find_name("Patient", text) or _find_name("Name", text),
        "uhid":            _find(r"(?:UHID|MRN|IP\s*No\.?)\s*[:\-]?\s*([A-Z0-9\-]{4,15})", text),
        "admission_date":  dates[0] if dates else None,
        "discharge_date":  dates[1] if len(dates) > 1 else None,
        "primary_diagnosis": _find(r"(?:Final|Primary|Discharge)?\s*Diagnosis\s*[:\-]\s*([^\n]{3,80})", text),
        "treating_doctor": _find(r"(?:Treating|Consultant)\s*(?:Dr\.?|Doctor)\s*[:\-]?\s*([A-Za-z\s\.]{4,30})", text),
        "total_amount":    _find_amount(text),
    }
    if not fields["patient_name"]:      low.append("patient_name")
    if not fields["primary_diagnosis"]: low.append("diagnosis")
    fields["low_confidence_fields"] = low
    return fields


_PARSERS = {
    "PRESCRIPTION":      _parse_prescription,
    "HOSPITAL_BILL":     _parse_hospital_bill,
    "LAB_REPORT":        _parse_lab_report,
    "PHARMACY_BILL":     _parse_pharmacy_bill,
    "DISCHARGE_SUMMARY": _parse_discharge_summary,
}


def _classify(text, filename=""):
    name, tl = filename.lower(), text.lower()
    if any(k in name for k in ("rx","prescription")):          return "PRESCRIPTION"
    if any(k in name for k in ("discharge","summary")):        return "DISCHARGE_SUMMARY"
    if any(k in name for k in ("lab","report","diagnostic")):  return "LAB_REPORT"
    if any(k in name for k in ("pharmacy","chemist")):         return "PHARMACY_BILL"
    if any(k in name for k in ("bill","invoice")):             return "HOSPITAL_BILL"
    scores = {
        "PRESCRIPTION":      sum(1 for k in ["rx","diagnosis","tab.","prescribed"] if k in tl),
        "HOSPITAL_BILL":     sum(1 for k in ["grand total","gst","bill no","invoice"] if k in tl),
        "LAB_REPORT":        sum(1 for k in ["normal range","result","specimen","haemoglobin"] if k in tl),
        "DISCHARGE_SUMMARY": sum(1 for k in ["admission date","discharge date","uhid"] if k in tl),
        "PHARMACY_BILL":     sum(1 for k in ["drug lic","expiry","batch","mrp"] if k in tl),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "UNKNOWN"


def _score(fields, ocr_conf, doc_type):
    score, issues = ocr_conf, []
    low = fields.get("low_confidence_fields", [])
    score -= len(low) * 0.05
    if low: issues.append(f"Low-confidence fields: {', '.join(low)}")
    if doc_type == "PRESCRIPTION":
        if not fields.get("diagnosis"): score -= 0.10; issues.append("Diagnosis not found")
        if not fields.get("medicines"): score -= 0.15; issues.append("No medicines found")
    elif doc_type == "HOSPITAL_BILL":
        if not fields.get("total_amount"): score -= 0.20; issues.append("Total amount not found")
    elif doc_type == "PHARMACY_BILL":
        if not fields.get("medicines"):   score -= 0.20; issues.append("No medicines found")
    return max(0.0, round(score, 3)), issues


# ─────────────────────────────────────────────────────────────────────────────
# PATH B — Gemini Vision fallback (only when OCR confidence < CONFIDENCE_FLOOR)
# ─────────────────────────────────────────────────────────────────────────────

GEMINI_EXTRACT_PROMPT = """
You are extracting structured data from an Indian medical document.
Return ONLY valid JSON with these fields relevant to the document type:
- document_type (PRESCRIPTION/HOSPITAL_BILL/LAB_REPORT/PHARMACY_BILL/DISCHARGE_SUMMARY)
- patient_name, date, doctor_name
- diagnosis (if prescription/discharge)
- total_amount (if bill)
- medicines list (if prescription/pharmacy)
- low_confidence_fields: list of field names you could not read clearly
- extraction_notes: what made this document difficult

No markdown fences. No explanation. Just the JSON object.
"""

def _llm_fallback(doc: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    """
    Call Gemini Vision on the document when OCR confidence is too low.
    Returns (fields_dict, confidence).
    Falls back to empty fields if Gemini also fails — never raises.
    """
    try:
        import google.generativeai as genai
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            return {"error": "GEMINI_API_KEY not set — LLM fallback unavailable"}, 0.0

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        # Build parts: prompt + image (first page only)
        parts = [GEMINI_EXTRACT_PROMPT]
        images = doc.get("processed_images_b64") or []
        text   = doc.get("extracted_text") or ""

        if images:
            img_bytes = base64.b64decode(images[0])
            pil_img   = Image.open(io.BytesIO(img_bytes))
            parts.append(pil_img)
        elif text:
            parts.append(f"Document text:\n{text}")
        else:
            return {"error": "No image or text available for LLM fallback"}, 0.0

        response = model.generate_content(parts)
        raw = response.text.strip()

        # Strip markdown fences
        if raw.startswith("```"):
            lines = raw.split("\n")[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()

        fields = json.loads(raw)
        # LLM output is higher confidence than failed OCR but not perfect
        confidence = 0.72 - len(fields.get("low_confidence_fields", [])) * 0.05
        return fields, max(0.3, confidence)

    except Exception as exc:
        return {"error": f"LLM fallback failed: {exc}"}, 0.0


# ─────────────────────────────────────────────────────────────────────────────
# ADK TOOL ENTRY POINT
# This is the only function the orchestrator calls.
# ─────────────────────────────────────────────────────────────────────────────

def extraction_tool_fn(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    ADK FunctionTool entry point.

    Decision tree per document:
      1. Run EasyOCR + regex → get (text, ocr_confidence)
      2. If ocr_confidence >= CONFIDENCE_FLOOR → use OCR fields  (Path A)
      3. If ocr_confidence <  CONFIDENCE_FLOOR and USE_LLM_FALLBACK=True
                                               → call Gemini Vision (Path B)
      4. If both fail → return empty fields, confidence=0, flag manual review

    Reads:  state["preprocessed_json"]
    Writes: state["extracted_json"]
    """
    preprocessed_list = state.get("preprocessed_json") or []
    extracted_docs, errors = [], []
    any_low_conf = False

    for doc in preprocessed_list:
        filename = doc.get("filename", "unknown")
        path_used = "ocr"

        try:
            # ── Step 1: OCR ───────────────────────────────────────────────
            raw_text, ocr_conf = _get_text(doc)
            hint     = doc.get("doc_type_hint")
            doc_type = hint if hint in _PARSERS else _classify(raw_text, filename)

            # ── Step 2: decide path ───────────────────────────────────────
            if raw_text.strip() and ocr_conf >= CONFIDENCE_FLOOR:
                # PATH A — OCR is good enough
                parser = _PARSERS.get(doc_type, _parse_hospital_bill)
                fields = parser(raw_text)
                confidence, issues = _score(fields, ocr_conf, doc_type)

            elif USE_LLM_FALLBACK:
                # PATH B — OCR too uncertain, try Gemini Vision
                path_used  = "llm_fallback"
                fields, confidence = _llm_fallback(doc)
                issues = []
                if confidence < CONFIDENCE_FLOOR:
                    issues.append(f"Both OCR (conf={ocr_conf:.2f}) and LLM fallback produced low confidence.")

            else:
                # No LLM — extract what we can, route to MANUAL_REVIEW via low confidence
                parser     = _PARSERS.get(doc_type, _parse_hospital_bill)
                fields     = parser(raw_text) if raw_text.strip() else {}
                confidence = max(0.0, ocr_conf - 0.15)   # penalise for low OCR quality
                issues     = [f"OCR confidence low ({ocr_conf:.0%}). Document may be handwritten or blurry. Routed to manual review."]

            if confidence < CONFIDENCE_FLOOR:
                any_low_conf = True

            extracted_docs.append({
                "filename":              filename,
                "doc_type":              doc_type,
                "fields":                fields,
                "confidence":            confidence,
                "ocr_confidence":        round(ocr_conf, 3),
                "path_used":             path_used,         # visible in trace
                "low_confidence_fields": fields.get("low_confidence_fields", []),
                "validation_issues":     issues,
            })

        except Exception as exc:
            errors.append(f"{filename}: {exc}")
            extracted_docs.append({
                "filename":   filename,
                "doc_type":   "UNKNOWN",
                "fields":     {},
                "confidence": 0.0,
                "path_used":  "error",
                "low_confidence_fields": [],
                "validation_issues": [str(exc)],
            })
            any_low_conf = True

    state["extracted_json"] = {
        "extracted_documents": extracted_docs,
        "extraction_errors":   errors,
        "low_confidence":      any_low_conf,
    }
    return state


extraction_tool = extraction_tool_fn
# backend/preprocessing/pdf.py
import fitz  # PyMuPDF
from typing import List
import numpy as np
from PIL import Image
import cv2
from io import BytesIO

def is_text_pdf(file_bytes: bytes) -> bool:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    page = doc[0]
    text = page.get_text()
    return len(text.strip()) > 50

def extract_text_from_pdf(file_bytes: bytes) -> str:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    texts = []
    for page in doc:
        texts.append(page.get_text())
    return "\n\n".join(texts)

def pdf_to_images(file_bytes: bytes, zoom: float = 2.0) -> List[np.ndarray]:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    images = []
    for page in doc:
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        images.append(bgr)
    return images
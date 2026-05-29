# backend/llm/client.py
import os
from typing import Any, Dict, List, Optional
from google import genai  # adjust import based on SDK you use
from google.genai import types as genai_types  # type: ignore
from backend.core.config import get_env
# GOOGLE_API_KEY="AIzaSyBQfCvrXxhDGxxYaSQL6_dy6w7EoGoIeTA"

class LLMAuthError(Exception):
    pass

class LLMRateLimitError(Exception):
    pass

class LLMTemporaryError(Exception):
    pass

class LLMResponseFormatError(Exception):
    pass

class LLMClient:
    def __init__(self, model: str = "gemini-3.5-flash") -> None:
        api_key = get_env("GEMINI_API_KEY", default=None)
        if not api_key:
            raise LLMAuthError("GEMINI_API_KEY not set")

        self.model = model
        self.client = genai.Client(api_key=api_key)

    def classify_or_extract(
        self,
        prompt: str,
        images: Optional[List[bytes]] = None,
        text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generic LLM call that handles basic errors and parses JSON content.
        """
        parts: List[genai_types.Part] = []

        if text:
            parts.append(genai_types.Part(text=prompt + "\n\n" + text))
        else:
            parts.append(genai_types.Part(text=prompt))

        if images:
            for img_bytes in images:
                parts.append(
                    genai_types.Part(
                        inline_data=genai_types.Blob(
                            mime_type="image/png",
                            data=img_bytes,
                        )
                    )
                )

        try:
            # NOTE: use models.generate_content, not client.generate_content
            response = self.client.models.generate_content(
                model=self.model,
                contents=[genai_types.Content(parts=parts)],
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
        except Exception as e:
            # For now, keep mapping as generic; you can refine with real error classes later.
            message = str(e)
            if "API key" in message or "401" in message or "PERMISSION" in message:
                raise LLMAuthError(message)
            if "429" in message or "RESOURCE_EXHAUSTED" in message:
                raise LLMRateLimitError(message)
            if "500" in message or "UNAVAILABLE" in message:
                raise LLMTemporaryError(message)
            raise

        content = response.candidates[0].content  # type: ignore
        if not content or not content.parts:
            raise LLMResponseFormatError("Empty LLM response")

        json_str = content.parts[0].text
        import json

        try:
            parsed = json.loads(json_str)
        except Exception as exc:
            raise LLMResponseFormatError(f"Invalid JSON: {exc}") from exc

        return parsed
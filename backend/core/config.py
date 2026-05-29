# backend/core/config.py
import os
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
import json

# Load .env from backend root
ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

def get_env(key: str, default: str | None = None) -> str:
    value = os.getenv(key)
    if value is None:
        if default is not None:
            return default
        raise RuntimeError(f"Environment variable {key} is not set")
    return value

def load_policy_terms() -> Dict[str, Any]:
    policy_path = ROOT_DIR / "data" / "policy_terms.json"
    return json.loads(policy_path.read_text(encoding="utf-8"))
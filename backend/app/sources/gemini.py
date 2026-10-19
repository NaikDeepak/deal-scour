import json
import logging
import re
import threading
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlmodel import Session, func, select

from app.domain.models import LlmUsage

logger = logging.getLogger(__name__)

MAX_CALL_COST_PAISE = 10
_GEMINI_LOCK = threading.Lock()


class GeminiExtraction(BaseModel):
    model_config = ConfigDict(strict=True)

    brand: str | None = None
    pack_label: str | None = None
    family_key: str | None = None
    category: str | None = None


class GeminiClient:
    def __init__(self, api_key: str, model: str = "gemini-3.8-flash") -> None:
        self.api_key = api_key
        self.model = model

    def __repr__(self) -> str:
        return f"GeminiClient(model={self.model!r}, key='***')"

    def __str__(self) -> str:
        return repr(self)

    def extract_fields(self, title: str) -> tuple[dict[str, Any] | None, int, int, int]:
        """Calls Gemini REST API to extract product attributes from title.

        Returns (extracted_dict, prompt_tokens, response_tokens, cost_paise).
        Returns (None, 0, 0, 0) on empty key, failure, or invalid output.
        Never leaks api_key in errors or strings.
        """
        if not self.api_key:
            return None, 0, 0, 0

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        prompt = (
            f"You are a grocery catalog extractor. Extract product attributes from this title: '{title}'.\n"
            "Return a strict JSON object with these keys:\n"
            "- brand: string or null\n"
            "- pack_label: string or null (e.g. '500g', '1kg', '907g', '10pcs')\n"
            "- family_key: string or null (snake_case, e.g. 'butter', 'whey_protein', 'paneer')\n"
            "- category: string or null (e.g. 'dairy', 'fitness', 'bakery', 'staples')\n"
            "Do not include any other markdown formatting or commentary."
        )

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }
        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.0,
            },
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    logger.warning("Gemini API error (status %d)", resp.status_code)
                    return None, 0, 0, 0

                data = resp.json()
        except Exception as e:
            # Mask any accidental key leakage
            err_msg = str(e).replace(self.api_key, "***")
            logger.warning("Gemini request failed: %s", err_msg)
            return None, 0, 0, 0

        # Extract tokens
        usage = data.get("usageMetadata", {})
        prompt_tokens = int(usage.get("promptTokenCount", 0))
        response_tokens = int(usage.get("candidatesTokenCount", 0))
        total_tokens = int(usage.get("totalTokenCount", prompt_tokens + response_tokens))

        # Estimate cost in paise (approx: 1 paisa minimum if tokens > 0)
        cost_paise = max(1, (prompt_tokens * 1 + response_tokens * 4) // 100) if total_tokens > 0 else 0

        candidates = data.get("candidates", [])
        if not candidates:
            return None, prompt_tokens, response_tokens, cost_paise

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return None, prompt_tokens, response_tokens, cost_paise

        text_content = parts[0].get("text", "").strip()
        # Clean any accidental markdown code fences
        if text_content.startswith("```"):
            text_content = re.sub(r"^```[a-z]*\s*", "", text_content)
            text_content = re.sub(r"\s*```$", "", text_content)

        try:
            parsed_raw = json.loads(text_content)
            validated = GeminiExtraction.model_validate(parsed_raw)
            result = {
                k: v
                for k, v in validated.model_dump().items()
                if v is not None and str(v).strip() != ""
            }
            return result, prompt_tokens, response_tokens, cost_paise
        except (json.JSONDecodeError, ValidationError):
            logger.warning("Gemini output was not valid JSON")
            return None, prompt_tokens, response_tokens, cost_paise


def is_monthly_cap_reached(
    session: Session,
    household_id: int | None,
    cap_paise: int,
    now: datetime,
) -> bool:
    """Checks whether the global LLM spend has reached the monthly cap (considering reservation)."""
    if cap_paise <= 0:
        return True

    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    query = select(func.coalesce(func.sum(LlmUsage.cost_paise), 0)).where(
        LlmUsage.created_at >= month_start
    )
    total_spent_paise = session.exec(query).one()
    return int(total_spent_paise) + MAX_CALL_COST_PAISE > cap_paise


def call_gemini_extract(
    api_key: str,
    model: str,
    title: str,
) -> tuple[dict[str, Any] | None, int, int, int]:
    """Helper used by autofill module; easily mockable in tests."""
    client = GeminiClient(api_key=api_key, model=model)
    return client.extract_fields(title)

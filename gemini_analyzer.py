"""
Screenshot Processor — Gemini Image Analysis
Sends images to Gemini Flash-Lite via Vertex AI and returns structured JSON.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import vertexai
from vertexai.generative_models import GenerativeModel, Part

from config import GCP_PROJECT_ID, GCP_LOCATION, GEMINI_MODEL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
ANALYSIS_PROMPT = """You are a screenshot analysis assistant. Analyze the image with extreme precision.

RULES:
- Transcribe ALL visible text EXACTLY as written, word for word
- Support Russian, Greek, English, Italian, and any other language
- Do NOT paraphrase or guess — copy text exactly
- Categorize each piece of information
- If the screenshot contains multiple distinct pieces of information, create separate items for each
- If you cannot determine a due date, set it to null
- If you cannot determine priority, default to "medium"

Return ONLY valid JSON in this format:
{
  "summary": "one line description of the screenshot",
  "language": "detected primary language",
  "transcript": "exact text from image, preserve formatting with newlines",
  "filename_suggestion": "2-4 words, lowercase, hyphens, no extension",
  "items": [
    {
      "type": "TASK|EVENT|IDEA|DIARY|REFERENCE|FINANCE",
      "content": "the extracted information, clean and readable",
      "priority": "high|medium|low",
      "due_date": "YYYY-MM-DD if detected, null otherwise"
    }
  ]
}

IMPORTANT: Return ONLY the JSON object, no markdown fences, no extra text."""

# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
_initialized = False


def _ensure_init():
    """Initialize Vertex AI SDK once per cold start."""
    global _initialized
    if not _initialized:
        vertexai.init(project=GCP_PROJECT_ID, location=GCP_LOCATION)
        _initialized = True


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def analyze_image(image_bytes: bytes, mime_type: str = "image/png") -> dict[str, Any]:
    """
    Send an image to Gemini for analysis.

    Args:
        image_bytes: Raw image data.
        mime_type: MIME type of the image (e.g. 'image/png', 'image/jpeg').

    Returns:
        Parsed JSON dict with keys: summary, language, transcript,
        filename_suggestion, items[].

    Raises:
        ValueError: If Gemini returns unparseable output after retries.
    """
    _ensure_init()

    model = GenerativeModel(GEMINI_MODEL)
    image_part = Part.from_data(data=image_bytes, mime_type=mime_type)

    last_error = None
    for attempt in range(3):
        try:
            response = model.generate_content(
                [image_part, ANALYSIS_PROMPT],
                generation_config={
                    "temperature": 0.1,
                    "max_output_tokens": 4096,
                    "response_mime_type": "application/json",
                },
            )

            raw_text = response.text.strip()
            # Strip markdown fences if Gemini adds them despite instructions
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3].strip()

            result = json.loads(raw_text)
            _validate_result(result)
            logger.info("Gemini analysis succeeded: %s", result.get("summary", ""))
            return result

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            last_error = e
            logger.warning(
                "Gemini attempt %d failed (%s), retrying...", attempt + 1, str(e)
            )
            time.sleep(2 ** attempt)  # exponential backoff: 1s, 2s, 4s

    raise ValueError(
        f"Failed to get valid JSON from Gemini after 3 attempts. Last error: {last_error}"
    )


def _validate_result(result: dict) -> None:
    """Validate the structure of a Gemini analysis result."""
    required_keys = {"summary", "language", "transcript", "filename_suggestion", "items"}
    missing = required_keys - set(result.keys())
    if missing:
        raise ValueError(f"Missing required keys: {missing}")

    if not isinstance(result["items"], list):
        raise ValueError("'items' must be a list")

    valid_types = {"TASK", "EVENT", "IDEA", "DIARY", "REFERENCE", "FINANCE"}
    for i, item in enumerate(result["items"]):
        if "type" not in item or "content" not in item:
            raise ValueError(f"Item {i} missing 'type' or 'content'")
        if item["type"] not in valid_types:
            raise ValueError(
                f"Item {i} has invalid type '{item['type']}'. Must be one of {valid_types}"
            )

"""
Screenshot Processor — Gemini Analysis
Sends images and text to Gemini via Vertex AI and returns structured JSON.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import vertexai
from vertexai.generative_models import GenerativeModel, Part

from config import GCP_PROJECT_ID, GCP_LOCATION, GEMINI_MODEL, MAX_TEXT_SIZE

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
ANALYSIS_PROMPT = """You are a screenshot analysis assistant for a photographer's personal knowledge base.

CORE RULES:
- Transcribe ALL visible text EXACTLY as written in the "transcript" field
- Support Russian, Greek, English, Italian, and any other language
- Do NOT paraphrase or guess — copy text exactly in the transcript
- CONSOLIDATE related information into ONE item. An Instagram profile = 1 PERSON, not 20 references
- Maximum 5 items per screenshot. Merge related info into fewer, richer items
- If you cannot determine a due date, set it to null
- If you cannot determine priority, default to "medium"

ITEM TYPES — choose the most specific one:
- BOOKING: Chat/DM conversations about photoshoot inquiries, bookings, scheduling, pricing
- TASK: Action items, to-do items, reminders
- EVENT: Calendar events, meetings, dates, appointments
- IDEA: Thoughts, concepts, plans, brainstorming
- DIARY: Personal reflections, journal entries
- PERSON: Social media profiles, creators, photographers, models, artists, people to follow/contact
- LOCATION: Places, cities, venues, travel destinations, shoot locations
- INSPIRATION: Visual references, outfit ideas, mood/style screenshots, fashion, art, aesthetics
- QUOTE: Motivational quotes, wisdom, song lyrics, memorable phrases, speeches
- LEARNING: Courses, tutorials, workshops, how-to content, educational material
- WISHLIST: Products to buy, gear, gadgets, equipment, items of interest
- FINANCE: Receipts, prices, transactions, bills, credits
- REFERENCE: Articles, links, general information that doesn't fit above categories

WIKILINKS:
- Wrap key concepts, people, places, and topics in [[double brackets]] for Obsidian linking
- Example: "[[Vitamin D]] improves [[calcium]] absorption"
- Be selective — only link meaningful concepts, not common words
- Also add a "linked_concepts" array listing the concepts you linked

CLASSIFICATION GUIDE:
- DM/chat about a photoshoot, session, booking, pricing → BOOKING
- Instagram/social profile screenshot → PERSON (one item with all profile info consolidated)
- Photo of a person/model/outfit → INSPIRATION (describe the visual, style, mood)
- Travel post or location photo → LOCATION
- Screenshot of someone's work/portfolio → PERSON (if focus is the creator) or INSPIRATION (if focus is the visual)
- Chat about travel plans → IDEA or LOCATION depending on content
- GCP/billing screenshot → FINANCE
- Motivational speech, book quote → QUOTE
- Online course, tutorial page → LEARNING
- Product page, gear review → WISHLIST
- For TASK items: also suggest a project category in project_hint

BOOKING STATUS DETECTION:
- If the last message in the chat is FROM the client → status = "need-to-reply"
- If the last message is FROM the photographer (you) → status = "waiting"
- If a date/time is confirmed by both sides → status = "confirmed"

Return ONLY valid JSON in this format:
{
  "summary": "one line description of the screenshot",
  "language": "detected primary language",
  "transcript": "exact text from image, preserve formatting with newlines",
  "filename_suggestion": "2-4 words, lowercase, hyphens, no extension",
  "items": [
    {
      "type": "BOOKING|TASK|EVENT|IDEA|DIARY|REFERENCE|FINANCE|PERSON|LOCATION|INSPIRATION|QUOTE|LEARNING|WISHLIST",
      "content": "clean, readable summary of this item",
      "priority": "high|medium|low",
      "due_date": "YYYY-MM-DD if detected, null otherwise",
      "name": "person's name or place name (for PERSON/LOCATION/BOOKING, null otherwise)",
      "handle": "social media handle like @username (for PERSON/BOOKING, null otherwise)",
      "platform": "Instagram|Fiverr|WhatsApp|Airbnb|Website|etc (for PERSON/BOOKING, null otherwise)",
      "role": "photographer|model|creator|client|etc (for PERSON, null otherwise)",
      "tags": ["style-tag-1", "style-tag-2"],
      "linked_concepts": ["concept1", "concept2"],
      "location": "city, country (if known, null otherwise)",
      "project_hint": "Photography|Personal|Work|Travel|Health (for TASK only, null otherwise)",
      "shoot_type": "portrait|couple|family|event|wedding|editorial|etc (for BOOKING, null otherwise)",
      "status": "need-to-reply|waiting|confirmed (for BOOKING, null otherwise)",
      "questions": ["client question 1", "client question 2"]
    }
  ]
}

IMPORTANT: Return ONLY the JSON object, no markdown fences, no extra text."""

# ---------------------------------------------------------------------------
# Text analysis prompt — for .txt / .md files
# ---------------------------------------------------------------------------
TEXT_ANALYSIS_PROMPT = """You are a knowledge extraction assistant for a personal Obsidian vault (second brain, PARA method).

You are analyzing a text document — likely an LLM conversation, research notes, or personal writing.

CORE RULES:
- Extract up to 10 distinct knowledge items from the text
- Use [[wikilinks]] to wrap key concepts for Obsidian Graph View linking
- Be selective with wikilinks — only meaningful concepts, not common words
- CONSOLIDATE related information — don't create 10 items when 3 would cover it
- Always include a "daily_snippet" — a 1-2 sentence summary of the document

ITEM TYPES — choose the most appropriate:
- TASK: Action items, things to do, follow-ups mentioned in the text
- EVENT: Scheduled events, appointments, meetings discussed
- RECIPE: Food recipes with ingredients and preparation steps
- KNOWLEDGE: Insights, research findings, explanations, how-tos, philosophical ideas, health/nutrition info, tech concepts — anything worth storing
- IDEA: Creative ideas, brainstorming, concepts to explore later
- DIARY: Personal reflections, journal entries
- PERSON: People mentioned who are worth remembering
- LOCATION: Places discussed that are worth saving
- QUOTE: Notable quotes, wisdom, memorable phrases
- LEARNING: Educational content, tutorials, courses discussed
- WISHLIST: Products/items the person wants to buy
- FINANCE: Financial info, prices, transactions
- REFERENCE: General reference info that doesn't fit other categories

KNOWLEDGE TYPE — Dynamic vault path:
For KNOWLEDGE items, suggest where they should live in the vault. Use existing paths where appropriate:
- "3-Resources/Nutrition" for food, diet, supplement info
- "3-Resources/Philosophy" for philosophical ideas, ethics, stoicism
- "3-Resources/Tech" for technology topics
- "2-Areas/Health" for health, fitness, wellness
- "3-Resources/Psychology" for mental models, behavior, mindset
- Or create a new logical path following the PARA pattern

RECIPE TYPE — Structured format:
For RECIPE items, include:
- "ingredients": list of ingredients with quantities
- "steps": list of preparation steps
- "servings": number of servings (if known)
- "prep_time": preparation time (if known)

Return ONLY valid JSON in this format:
{
  "summary": "one line description of the document",
  "language": "detected primary language",
  "filename_suggestion": "2-4 words, lowercase, hyphens, no extension",
  "daily_snippet": "1-2 sentence summary with [[wikilinks]] for the daily note",
  "items": [
    {
      "type": "KNOWLEDGE|TASK|RECIPE|IDEA|EVENT|DIARY|PERSON|LOCATION|QUOTE|LEARNING|WISHLIST|FINANCE|REFERENCE",
      "content": "clean summary with [[wikilinks]] to key concepts",
      "vault_path": "suggested vault path like '3-Resources/Nutrition' (for KNOWLEDGE type, null otherwise)",
      "priority": "high|medium|low",
      "tags": ["tag1", "tag2"],
      "linked_concepts": ["concept1", "concept2"],
      "due_date": "YYYY-MM-DD (for TASK/EVENT, null otherwise)",
      "name": "person/place name (for PERSON/LOCATION, null otherwise)",
      "ingredients": ["item1", "item2"] ,
      "steps": ["step1", "step2"],
      "servings": "number (for RECIPE, null otherwise)",
      "prep_time": "time string (for RECIPE, null otherwise)"
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


def analyze_text(text_content: str) -> dict[str, Any]:
    """
    Send a text document to Gemini for analysis.

    Args:
        text_content: The text content to analyze.

    Returns:
        Parsed JSON dict with keys: summary, language, filename_suggestion,
        daily_snippet, items[].

    Raises:
        ValueError: If Gemini returns unparseable output after retries.
    """
    _ensure_init()

    # Truncate if too large
    if len(text_content.encode('utf-8')) > MAX_TEXT_SIZE:
        text_content = text_content[:MAX_TEXT_SIZE]
        logger.warning("Text truncated to %d bytes (MAX_TEXT_SIZE)", MAX_TEXT_SIZE)

    model = GenerativeModel(GEMINI_MODEL)

    last_error = None
    for attempt in range(3):
        try:
            response = model.generate_content(
                [TEXT_ANALYSIS_PROMPT, f"\n\n---\nDOCUMENT TO ANALYZE:\n---\n\n{text_content}"],
                generation_config={
                    "temperature": 0.1,
                    "max_output_tokens": 8192,
                    "response_mime_type": "application/json",
                },
            )

            raw_text = response.text.strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3].strip()

            result = json.loads(raw_text)
            _validate_text_result(result)
            logger.info("Gemini text analysis succeeded: %s", result.get("summary", ""))
            return result

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            last_error = e
            logger.warning(
                "Gemini text attempt %d failed (%s), retrying...", attempt + 1, str(e)
            )
            time.sleep(2 ** attempt)

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

    valid_types = {"TASK", "EVENT", "IDEA", "DIARY", "REFERENCE", "FINANCE",
                   "PERSON", "LOCATION", "INSPIRATION",
                   "QUOTE", "LEARNING", "WISHLIST", "BOOKING",
                   "RECIPE", "KNOWLEDGE"}
    for i, item in enumerate(result["items"]):
        if "type" not in item or "content" not in item:
            raise ValueError(f"Item {i} missing 'type' or 'content'")
        if item["type"] not in valid_types:
            raise ValueError(
                f"Item {i} has invalid type '{item['type']}'. Must be one of {valid_types}"
            )


def _validate_text_result(result: dict) -> None:
    """Validate the structure of a Gemini text analysis result."""
    required_keys = {"summary", "language", "filename_suggestion", "items"}
    missing = required_keys - set(result.keys())
    if missing:
        raise ValueError(f"Missing required keys: {missing}")

    if not isinstance(result["items"], list):
        raise ValueError("'items' must be a list")

    valid_types = {"TASK", "EVENT", "IDEA", "DIARY", "REFERENCE", "FINANCE",
                   "PERSON", "LOCATION", "INSPIRATION",
                   "QUOTE", "LEARNING", "WISHLIST",
                   "RECIPE", "KNOWLEDGE"}
    for i, item in enumerate(result["items"]):
        if "type" not in item or "content" not in item:
            raise ValueError(f"Item {i} missing 'type' or 'content'")
        if item["type"] not in valid_types:
            raise ValueError(
                f"Item {i} has invalid type '{item['type']}'. Must be one of {valid_types}"
            )


# ---------------------------------------------------------------------------
# 2nd-pass: Generate suggested reply for BOOKING items using FAQ
# ---------------------------------------------------------------------------
BOOKING_REPLY_PROMPT = """You are a photographer's assistant. Based on the client's questions and your FAQ/pricing info, draft a friendly, professional reply.

CLIENT CONVERSATION:
{transcript}

CLIENT QUESTIONS:
{questions}

YOUR FAQ & PRICING INFO:
{faq_content}

RULES:
- Be warm, friendly, professional
- Answer their specific questions using the FAQ data
- If the FAQ doesn't cover something, say "[fill in your answer]"
- Keep it concise — 2-4 sentences max
- Match the language the client used (English, Italian, Russian, etc.)
- Don't be overly formal — match the casual tone of DM conversations

Return ONLY the suggested reply text, no JSON, no formatting."""


def generate_booking_reply(
    transcript: str,
    questions: list[str],
    faq_content: str,
) -> str:
    """
    Generate a suggested reply for a booking inquiry using FAQ context.
    This is the 2nd-pass call, only triggered when BOOKING is detected.

    Args:
        transcript: The original chat transcript from the screenshot.
        questions: List of client questions extracted by Gemini.
        faq_content: Contents of the FAQ.md file.

    Returns:
        Suggested reply text.
    """
    _ensure_init()

    if not faq_content.strip():
        return "[FAQ file is empty — fill in 2-Areas/Clients/Photography Business Info.md with your pricing and info]"

    prompt = BOOKING_REPLY_PROMPT.format(
        transcript=transcript,
        questions="\n".join(f"- {q}" for q in questions) if questions else "(no specific questions detected)",
        faq_content=faq_content,
    )

    model = GenerativeModel(GEMINI_MODEL)
    try:
        response = model.generate_content(
            [prompt],
            generation_config={
                "temperature": 0.7,
                "max_output_tokens": 1024,
            },
        )
        reply = response.text.strip()
        logger.info("Generated booking reply (%d chars)", len(reply))
        return reply
    except Exception as e:
        logger.error("Failed to generate booking reply: %s", e)
        return f"[Could not generate reply: {e}]"


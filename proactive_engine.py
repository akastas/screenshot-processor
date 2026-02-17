"""
Screenshot Processor — Proactive Engine
Uses Gemini to analyze vault state and generate personalized briefings,
nudges, and suggestions that are sent via Telegram.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
from typing import Any

import vertexai
from vertexai.generative_models import GenerativeModel

from config import GCP_PROJECT_ID, GCP_LOCATION, GEMINI_MODEL, PROACTIVE_TIMEZONE

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
MORNING_BRIEFING_PROMPT = """You are a proactive personal assistant for a photographer based in Italy.
You have access to their current dashboard state. Generate a concise, friendly morning briefing.

TODAY: {today}
DAY OF WEEK: {day_of_week}

DASHBOARD STATE:
{dashboard_json}

Generate a briefing as JSON with these fields:
{{
  "greeting": "A warm, personalized good morning message. Mention the day. Keep it short and natural.",
  "bookings": [
    {{"emoji": "🔴 or 🟡 or 🟢", "text": "Client name — what needs to happen (e.g. 'Reply to Andrea about pricing')"}}
  ],
  "tasks": ["task description — keep it short"],
  "events": ["event description with time if known"],
  "suggestions": [
    "1-2 creative or productivity suggestions based on their vault content. Could be: revisit an idea, follow up on inspiration, try a recipe they saved, check out a learning resource, etc."
  ],
  "summary": "One-line summary like 'You have 3 bookings to handle and 2 overdue tasks'"
}}

RULES:
- Be concise — this is for a Telegram message, not an essay
- Prioritize: bookings needing reply > overdue tasks > today's tasks > events > suggestions
- If there are no bookings/tasks, focus on creative suggestions from their recent vault content
- Use the photographer's context — suggest shoot-related things when relevant
- If they have saved ideas or inspiration recently, reference those in suggestions
- Keep suggestions actionable and specific, not generic
- If nothing needs attention, say so cheerfully
- Match the language of their content if it's not English (they use English, Italian, Russian, Greek)
- Return ONLY valid JSON, no markdown fences

IMPORTANT: Return ONLY the JSON object."""

NUDGE_PROMPT = """You are a proactive personal assistant for a photographer. It's midday — check if anything urgent needs attention.

TODAY: {today}
CURRENT TIME: midday

DASHBOARD STATE:
{dashboard_json}

Generate a nudge as JSON with these fields:
{{
  "urgent": ["Only truly urgent items — bookings with need-to-reply status, overdue tasks"],
  "reminders": ["Gentle reminders about upcoming things — tasks due soon, confirmed shoots to prepare for"],
  "ideas": ["One creative suggestion based on their vault content — optional, include only if there's something genuinely interesting to suggest"]
}}

RULES:
- Only include fields if there's something to say
- If nothing is urgent, return empty arrays
- Be brief — 1 short sentence per item
- Don't repeat the morning briefing — focus on what's changed or what they might have forgotten
- Return ONLY valid JSON, no markdown fences

IMPORTANT: Return ONLY the JSON object."""

EVENING_REVIEW_PROMPT = """You are a proactive personal assistant for a photographer. Generate a brief evening review of the day.

TODAY: {today}

DASHBOARD STATE:
{dashboard_json}

Generate a review as JSON:
{{
  "review": "A friendly 1-2 sentence summary of what happened today based on the daily note",
  "still_pending": ["Any bookings still needing reply", "Overdue tasks that weren't done"],
  "tomorrow_preview": ["Things coming up tomorrow or this week that they should be aware of"],
  "goodnight": "A short, warm closing message"
}}

RULES:
- Be encouraging even if things are pending
- Keep it very brief — this is a nighttime message
- If the daily note shows they were productive, acknowledge it
- If bookings are still pending, gently remind without being pushy
- Return ONLY valid JSON, no markdown fences

IMPORTANT: Return ONLY the JSON object."""


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
_initialized = False


def _ensure_init():
    global _initialized
    if not _initialized:
        vertexai.init(project=GCP_PROJECT_ID, location=GCP_LOCATION)
        _initialized = True


# ---------------------------------------------------------------------------
# Briefing generators
# ---------------------------------------------------------------------------
def generate_morning_briefing(dashboard: dict[str, Any]) -> dict[str, Any]:
    """
    Generate a morning briefing from dashboard scan data.

    Args:
        dashboard: Full scan result from dashboard_scanner.full_scan().

    Returns:
        Briefing dict ready for telegram_bot.send_morning_briefing().
    """
    today = date.today()
    prompt = MORNING_BRIEFING_PROMPT.format(
        today=today.isoformat(),
        day_of_week=today.strftime("%A"),
        dashboard_json=_summarize_dashboard(dashboard),
    )
    return _call_gemini(prompt, "morning briefing")


def generate_nudge(dashboard: dict[str, Any]) -> dict[str, Any]:
    """Generate a midday nudge from dashboard scan data."""
    today = date.today()
    prompt = NUDGE_PROMPT.format(
        today=today.isoformat(),
        dashboard_json=_summarize_dashboard(dashboard),
    )
    return _call_gemini(prompt, "nudge")


def generate_evening_review(dashboard: dict[str, Any]) -> dict[str, Any]:
    """Generate an evening review from dashboard scan data."""
    today = date.today()
    prompt = EVENING_REVIEW_PROMPT.format(
        today=today.isoformat(),
        dashboard_json=_summarize_dashboard(dashboard),
    )
    return _call_gemini(prompt, "evening review")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _summarize_dashboard(dashboard: dict[str, Any]) -> str:
    """
    Convert full dashboard scan into a concise text summary for the prompt.
    Keeps it under ~2000 chars to save tokens.
    """
    parts = []

    # Bookings
    bookings = dashboard.get("bookings", {})
    if bookings:
        parts.append("BOOKINGS:")
        for status, clients in bookings.items():
            for c in clients:
                name = c.get("client", "?")
                platform = c.get("platform", "?")
                shoot = c.get("shoot_type", "")
                last_updated = c.get("last_updated", "")
                parts.append(f"  [{status}] {name} — {platform} ({shoot}) last updated: {last_updated}")
    else:
        parts.append("BOOKINGS: None")

    # Daily note
    daily = dashboard.get("daily_note", {})
    tasks = daily.get("tasks", [])
    events = daily.get("events", [])
    diary = daily.get("diary", [])
    if tasks:
        parts.append(f"TODAY'S TASKS ({len(tasks)}):")
        for t in tasks[:10]:
            parts.append(f"  {t}")
    if events:
        parts.append(f"TODAY'S EVENTS ({len(events)}):")
        for e in events[:5]:
            parts.append(f"  {e}")
    if diary:
        parts.append(f"DIARY ENTRIES: {len(diary)}")

    # TickTick
    tt = dashboard.get("ticktick", {})
    overdue = tt.get("overdue", [])
    today_tasks = tt.get("today", [])
    upcoming = tt.get("upcoming", [])
    high_pri = tt.get("high_priority", [])

    if overdue:
        parts.append(f"OVERDUE TASKS ({len(overdue)}):")
        for t in overdue[:5]:
            parts.append(f"  🔴 {t['title']} (project: {t['project']}, due: {t.get('due_date', '?')})")
    if today_tasks:
        parts.append(f"DUE TODAY ({len(today_tasks)}):")
        for t in today_tasks[:5]:
            parts.append(f"  {t['title']} (project: {t['project']})")
    if upcoming:
        parts.append(f"UPCOMING THIS WEEK ({len(upcoming)}):")
        for t in upcoming[:5]:
            parts.append(f"  {t['title']} (due: {t.get('due_date', '?')})")
    if high_pri:
        parts.append(f"HIGH PRIORITY ({len(high_pri)}):")
        for t in high_pri[:3]:
            parts.append(f"  ⚡ {t['title']}")

    # Recent vault activity
    recent = dashboard.get("recent_files", [])
    if recent:
        parts.append("RECENT VAULT CONTENT:")
        for r in recent:
            snippet = r.get("snippet", "")[:200]
            parts.append(f"  [{r['folder']}] {r['name']}: ...{snippet}...")

    return "\n".join(parts)


def _call_gemini(prompt: str, label: str) -> dict[str, Any]:
    """Call Gemini and parse JSON response, with retry."""
    _ensure_init()
    model = GenerativeModel(GEMINI_MODEL)

    last_error = None
    for attempt in range(3):
        try:
            response = model.generate_content(
                [prompt],
                generation_config={
                    "temperature": 0.7,
                    "max_output_tokens": 2048,
                    "response_mime_type": "application/json",
                },
            )

            raw_text = response.text.strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3].strip()

            result = json.loads(raw_text)
            logger.info("Generated %s successfully", label)
            return result

        except (json.JSONDecodeError, Exception) as e:
            last_error = e
            logger.warning("Gemini %s attempt %d failed: %s", label, attempt + 1, e)
            time.sleep(2 ** attempt)

    logger.error("Failed to generate %s after 3 attempts: %s", label, last_error)
    return _fallback_response(label)


def _fallback_response(label: str) -> dict[str, Any]:
    """Return a sensible fallback if Gemini fails."""
    if "briefing" in label:
        return {
            "greeting": "Good morning!",
            "bookings": [],
            "tasks": [],
            "events": [],
            "suggestions": ["Could not generate AI suggestions — check your dashboard manually today."],
            "summary": "AI briefing generation failed — check your vault directly.",
        }
    elif "nudge" in label:
        return {
            "urgent": [],
            "reminders": ["Could not scan dashboard — check manually."],
            "ideas": [],
        }
    elif "review" in label:
        return {
            "review": "Could not generate evening review.",
            "still_pending": [],
            "tomorrow_preview": [],
            "goodnight": "Good night!",
        }
    return {}

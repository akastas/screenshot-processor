"""
Screenshot Processor — Telegram Bot Integration
Sends proactive messages, briefings, and nudges to the user via Telegram.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}"


def is_configured() -> bool:
    """Check if Telegram credentials are available."""
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def send_message(
    text: str,
    parse_mode: str = "Markdown",
    disable_preview: bool = True,
    chat_id: Optional[str] = None,
) -> bool:
    """
    Send a text message via Telegram Bot API.

    Args:
        text: Message text (supports Markdown or HTML based on parse_mode).
        parse_mode: 'Markdown' or 'HTML'.
        disable_preview: Disable link previews in the message.
        chat_id: Override the default chat ID.

    Returns:
        True if sent successfully, False otherwise.
    """
    if not is_configured():
        logger.warning("Telegram not configured, skipping message")
        return False

    url = f"{TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)}/sendMessage"
    payload = {
        "chat_id": chat_id or TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_preview,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info("Telegram message sent (%d chars)", len(text))
            return True
        else:
            logger.error("Telegram API error %d: %s", resp.status_code, resp.text[:300])
            return False
    except Exception as e:
        logger.error("Failed to send Telegram message: %s", e)
        return False


def send_morning_briefing(briefing: dict) -> bool:
    """
    Send a formatted morning briefing message.

    Args:
        briefing: Dict with keys like 'greeting', 'bookings', 'tasks',
                  'events', 'suggestions', 'weather_note'.
    """
    lines = []

    # Header
    greeting = briefing.get("greeting", "Good morning!")
    lines.append(f"*{greeting}*")
    lines.append("")

    # Bookings needing attention
    bookings = briefing.get("bookings", [])
    if bookings:
        lines.append("*Bookings*")
        for b in bookings:
            emoji = b.get("emoji", "📸")
            lines.append(f"{emoji} {b['text']}")
        lines.append("")

    # Tasks for today
    tasks = briefing.get("tasks", [])
    if tasks:
        lines.append("*Tasks*")
        for t in tasks:
            lines.append(f"• {t}")
        lines.append("")

    # Events
    events = briefing.get("events", [])
    if events:
        lines.append("*Events*")
        for e in events:
            lines.append(f"📅 {e}")
        lines.append("")

    # AI suggestions
    suggestions = briefing.get("suggestions", [])
    if suggestions:
        lines.append("*Suggestions*")
        for s in suggestions:
            lines.append(f"💡 {s}")
        lines.append("")

    # Summary stat
    summary = briefing.get("summary", "")
    if summary:
        lines.append(f"_{summary}_")

    text = "\n".join(lines)
    return send_message(text)


def send_nudge(nudge: dict) -> bool:
    """
    Send a midday/evening nudge about things that need attention.

    Args:
        nudge: Dict with keys like 'urgent', 'reminders', 'ideas'.
    """
    lines = []

    urgent = nudge.get("urgent", [])
    if urgent:
        lines.append("*Needs attention*")
        for u in urgent:
            lines.append(f"🔴 {u}")
        lines.append("")

    reminders = nudge.get("reminders", [])
    if reminders:
        lines.append("*Reminders*")
        for r in reminders:
            lines.append(f"• {r}")
        lines.append("")

    ideas = nudge.get("ideas", [])
    if ideas:
        lines.append("*Ideas for today*")
        for i in ideas:
            lines.append(f"💡 {i}")
        lines.append("")

    if not lines:
        lines.append("_All clear — nothing urgent right now._")

    text = "\n".join(lines)
    return send_message(text)


def send_processing_notification(results: list[dict]) -> bool:
    """
    Notify the user when new screenshots have been processed.

    Args:
        results: List of processing result dicts from main.py.
    """
    if not results:
        return False

    lines = [f"*Processed {len(results)} file(s)*", ""]
    for r in results:
        original = r.get("original_name", "?")
        summary = r.get("summary", "")
        routed = r.get("items_routed", {})
        type_str = ", ".join(f"{v} {k}" for k, v in routed.items()) if routed else "no items"
        lines.append(f"• _{original}_ — {summary}")
        lines.append(f"  Routed: {type_str}")

    text = "\n".join(lines)
    return send_message(text)

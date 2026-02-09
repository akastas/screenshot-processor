"""
Screenshot Processor — Markdown Router
Routes analyzed items to the correct Obsidian vault .md files.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional

import drive_ops
import ticktick_client
import booking_manager
from config import ROUTE_MAP, DRIVE_VAULT_ROOT_FOLDER_ID

logger = logging.getLogger(__name__)


def route_items(
    analysis: dict[str, Any],
    source_filename: str,
    target_date: Optional[date] = None,
) -> dict[str, int]:
    """
    Route all items from a Gemini analysis to the correct files.

    Args:
        analysis: Parsed Gemini JSON with 'items', 'summary', etc.
        source_filename: Original screenshot filename (for attribution).
        target_date: Date for the daily note. Defaults to today.

    Returns:
        Dict with counts per type, e.g. {"TASK": 2, "IDEA": 1}.
    """
    today = target_date or date.today()
    items = analysis.get("items", [])
    counts: dict[str, int] = {}

    if not items:
        logger.info("No items to route for %s", source_filename)
        return counts

    # Pre-fetch daily note ID (only created once even if multiple items need it)
    daily_note_id: Optional[str] = None
    needs_daily = any(
        ROUTE_MAP.get(item["type"], {}).get("daily_note_heading") for item in items
    )
    if needs_daily:
        daily_note_id = drive_ops.find_or_create_daily_note(today)

    for item in items:
        item_type = item["type"]
        route = ROUTE_MAP.get(item_type)

        if not route:
            logger.warning("Unknown item type '%s', skipping", item_type)
            continue

        content_block = _format_item(item, source_filename, analysis.get("summary", ""))

        # 1) Append to daily note under correct heading
        heading = route.get("daily_note_heading")
        if heading and daily_note_id:
            try:
                drive_ops.append_to_md(daily_note_id, content_block, under_heading=heading)
                logger.info("Appended %s item to daily note under '%s'", item_type, heading)
            except Exception as e:
                logger.error("Failed to append to daily note: %s", e)

        # 2) Append to extra file (e.g. Events.md, Ideas.md)
        extra_path = route.get("extra_file")
        if extra_path:
            try:
                _append_to_vault_file(extra_path, content_block, today)
            except Exception as e:
                logger.error("Failed to append to %s: %s", extra_path, e)

        # 3) Create TickTick task for TASK items
        if item_type == "TASK" and ticktick_client.is_configured():
            try:
                task_id = ticktick_client.create_task(item, source_filename)
                if task_id:
                    project_name = item.get("project_hint", "Inbox")
                    logger.info("Created TickTick task (project=%s)", project_name)
            except Exception as e:
                logger.error("Failed to create TickTick task: %s", e)

        # 4) Handle BOOKING items — create/update client file + suggest reply
        if route.get("booking"):
            try:
                transcript = analysis.get("transcript", "")
                booking_result = booking_manager.handle_booking(
                    item, source_filename, transcript, today
                )
                logger.info("Booking processed: %s", booking_result.get("client_file"))

                # Also create a TickTick task for the follow-up
                if ticktick_client.is_configured():
                    client_name = item.get("name") or "Client"
                    platform = item.get("platform") or ""
                    status = item.get("status", "need-to-reply")

                    # Status-specific task title
                    if status == "need-to-reply":
                        task_title = f"Reply to {client_name} — {platform}"
                        priority = "high"
                    elif status == "waiting":
                        task_title = f"Follow up with {client_name} — {platform}"
                        priority = "medium"
                    elif status == "confirmed":
                        task_title = f"Prepare shoot for {client_name} — {platform}"
                        priority = "high"
                    else:
                        task_title = f"Booking: {client_name} — {platform}"
                        priority = "medium"

                    follow_up = {
                        "content": task_title,
                        "priority": priority,
                        "due_date": item.get("due_date"),
                        "project_hint": "Photography",
                        "tags": ["booking"],
                    }
                    ticktick_client.create_task(follow_up, source_filename)
            except Exception as e:
                logger.error("Failed to handle booking: %s", e)

        counts[item_type] = counts.get(item_type, 0) + 1

    logger.info("Routed %d items from %s: %s", len(items), source_filename, counts)
    return counts


def create_analysis_record(
    analysis: dict[str, Any],
    source_filename: str,
    archive_folder_id: str,
) -> str:
    """
    Create a .md analysis record in the archive folder.
    Returns the created file's Drive ID.
    """
    suggested_name = analysis.get("filename_suggestion", "analysis")
    record_name = f"{suggested_name}-analysis.md"

    content = f"""---
source: {source_filename}
analyzed: {datetime.now().isoformat()}
language: {analysis.get('language', 'unknown')}
---

# {analysis.get('summary', 'Screenshot Analysis')}

## Transcript
{analysis.get('transcript', '(no text detected)')}

## Items
"""
    for item in analysis.get("items", []):
        priority = item.get("priority", "medium")
        due = item.get("due_date", "")
        due_str = f" (due: {due})" if due else ""
        name = item.get("name", "")
        name_str = f" — {name}" if name else ""
        handle = item.get("handle", "")
        handle_str = f" ({handle})" if handle else ""
        tags = item.get("tags", [])
        tags_str = f" [{', '.join(tags)}]" if tags else ""
        content += f"- **[{item['type']}]** {item['content']}{name_str}{handle_str}{tags_str} — _{priority}{due_str}_\n"

    file_id = drive_ops.create_md_file(archive_folder_id, record_name, content)
    return file_id


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _format_item(item: dict, source_filename: str, summary: str) -> str:
    """Format a single item as an Obsidian-compatible markdown block."""
    item_type = item["type"]
    content = item["content"]
    priority = item.get("priority", "medium")
    due_date = item.get("due_date")
    today = date.today().isoformat()

    lines = []

    if item_type == "TASK":
        # Obsidian task format
        due_str = f" 📅 {due_date}" if due_date else ""
        priority_emoji = {"high": "🔺", "medium": "🔸", "low": "🔹"}.get(priority, "")
        lines.append(f"- [ ] {priority_emoji} {content}{due_str}")

    elif item_type == "PERSON":
        name = item.get("name") or content.split("—")[0].strip()
        handle = item.get("handle") or ""
        platform = item.get("platform") or ""
        role = item.get("role") or "unknown"
        tags = item.get("tags") or []
        location = item.get("location") or ""

        lines.append(f"### {name}")
        if handle:
            lines.append(f"- **Handle:** {handle}")
        if platform:
            lines.append(f"- **Platform:** {platform}")
        lines.append(f"- **Role:** {role}")
        if tags:
            tag_str = ", ".join(tags)
            lines.append(f"- **Tags:** {tag_str}")
        if location:
            lines.append(f"- **Location:** {location}")
        lines.append(f"- **Notes:** {content}")
        lines.append(f"- **Added:** {today}")

    elif item_type == "LOCATION":
        name = item.get("name") or content.split("—")[0].strip()
        location = item.get("location") or ""
        tags = item.get("tags") or []

        lines.append(f"### {name}")
        if location:
            lines.append(f"- **Location:** {location}")
        if tags:
            tag_str = ", ".join(tags)
            lines.append(f"- **Type:** {tag_str}")
        lines.append(f"- **Notes:** {content}")
        lines.append(f"- **Added:** {today}")

    elif item_type == "INSPIRATION":
        tags = item.get("tags") or []

        lines.append(f"### {content[:80]}")
        if tags:
            tag_str = ", ".join(tags)
            lines.append(f"- **Style:** {tag_str}")
        lines.append(f"- **Notes:** {content}")
        lines.append(f"- **Added:** {today}")

    elif item_type == "QUOTE":
        lines.append(f"### {content[:80]}")
        name = item.get("name") or ""
        if name:
            lines.append(f"- **Author:** {name}")
        tags = item.get("tags") or []
        if tags:
            lines.append(f"- **Tags:** {', '.join(tags)}")
        lines.append(f"- **Added:** {today}")

    elif item_type == "LEARNING":
        name = item.get("name") or content[:60]
        platform = item.get("platform") or ""
        tags = item.get("tags") or []

        lines.append(f"### {name}")
        if platform:
            lines.append(f"- **Platform:** {platform}")
        handle = item.get("handle") or ""
        if handle:
            lines.append(f"- **Instructor:** {handle}")
        if tags:
            lines.append(f"- **Topics:** {', '.join(tags)}")
        lines.append(f"- **Notes:** {content}")
        lines.append(f"- **Added:** {today}")

    elif item_type == "WISHLIST":
        lines.append(f"### {content[:80]}")
        tags = item.get("tags") or []
        if tags:
            lines.append(f"- **Category:** {', '.join(tags)}")
        lines.append(f"- **Status:** 🔲 want")
        lines.append(f"- **Notes:** {content}")
        lines.append(f"- **Added:** {today}")

    elif item_type == "FINANCE":
        lines.append(f"| {today} | {content} | `screenshot` |")
    else:
        lines.append(f"- {content}")

    lines.append(f"  - _Source: {source_filename}_")
    return "\n".join(lines)


def _append_to_vault_file(vault_relative_path: str, content: str, today: date) -> None:
    """
    Find a file by its vault-relative path and append content.
    The path is like '2-Areas/Calendar/Events.md' — we split into folder path + filename.
    """
    parts = vault_relative_path.rsplit("/", 1)
    if len(parts) == 2:
        folder_path, filename = parts
    else:
        folder_path, filename = "", parts[0]

    # Resolve folder
    if folder_path:
        folder_id = drive_ops.find_folder_by_path(folder_path)
        if not folder_id:
            logger.error("Could not find vault folder: %s", folder_path)
            return
    else:
        folder_id = DRIVE_VAULT_ROOT_FOLDER_ID

    # Find or create the file
    existing = drive_ops.find_file_by_name(filename, folder_id)
    if existing:
        drive_ops.append_to_md(existing["id"], content)
        logger.info("Appended to existing file: %s", vault_relative_path)
    else:
        # Create with a simple header
        header = f"# {filename.replace('.md', '')}\n\n"
        drive_ops.create_md_file(folder_id, filename, header + content + "\n")
        logger.info("Created new file: %s", vault_relative_path)

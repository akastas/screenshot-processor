"""
Screenshot Processor — Booking Manager
Manages individual client files for photography bookings.
Handles find/create/update of client files in the vault.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Optional

import drive_ops
import gemini_analyzer
from config import VAULT_PATHS, DRIVE_VAULT_ROOT_FOLDER_ID

logger = logging.getLogger(__name__)

# Status emoji mapping
STATUS_EMOJI = {
    "need-to-reply": "🔴",
    "waiting": "🟡",
    "confirmed": "🟢",
    "completed": "✅",
    "cancelled": "❌",
}


def _slugify(name: str) -> str:
    """Convert a name to a filename-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    return slug[:50]


def _build_client_filename(client_name: str, platform: str) -> str:
    """Build a filename like 'maria-instagram.md'."""
    parts = [_slugify(client_name)]
    if platform:
        parts.append(_slugify(platform))
    return "-".join(parts) + ".md"


def _find_clients_folder_id() -> Optional[str]:
    """
    Find or create the 2-Areas/Clients/ folder in Drive.
    Uses find_folder_by_path first, falls back to creating the path.
    """
    clients_path = VAULT_PATHS["clients"]
    folder_id = drive_ops.find_folder_by_path(clients_path)
    if folder_id:
        return folder_id

    # Create the folder path segment by segment
    parts = clients_path.split("/")
    current = DRIVE_VAULT_ROOT_FOLDER_ID
    for part in parts:
        existing = drive_ops.find_folder_by_path(part, root_folder_id=current)
        if existing:
            current = existing
        else:
            current = drive_ops.create_folder(current, part)
            logger.info("Created folder '%s'", part)

    return current


def _find_existing_client_file(
    clients_folder_id: str,
    client_name: str,
    platform: str,
    handle: str,
) -> Optional[str]:
    """
    Search for an existing client file by handle or name+platform.
    Returns the file ID if found, None otherwise.
    """
    files = drive_ops.list_md_files(clients_folder_id)

    # Strategy 1: Match by exact filename
    expected_filename = _build_client_filename(client_name, platform)
    for f in files:
        if f["name"].lower() == expected_filename.lower():
            return f["id"]

    # Strategy 2: Match by handle in filename
    if handle:
        handle_slug = _slugify(handle.lstrip("@"))
        for f in files:
            if handle_slug in f["name"].lower():
                return f["id"]

    return None


def _build_new_client_content(
    item: dict[str, Any],
    source_filename: str,
    today: date,
    suggested_reply: str = "",
) -> str:
    """Build the full markdown content for a new client file."""
    client_name = item.get("name") or "Unknown Client"
    handle = item.get("handle") or ""
    platform = item.get("platform") or "Unknown"
    shoot_type = item.get("shoot_type") or "general"
    status = item.get("status") or "need-to-reply"
    location = item.get("location") or ""
    content = item.get("content") or ""
    questions = item.get("questions") or []
    due_date = item.get("due_date") or ""
    emoji = STATUS_EMOJI.get(status, "🔴")

    frontmatter_lines = [
        "---",
        f"client: {client_name}",
    ]
    if handle:
        frontmatter_lines.append(f'handle: "{handle}"')
    frontmatter_lines.extend([
        f"platform: {platform}",
        f"shoot_type: {shoot_type}",
        f"status: {status}",
    ])
    if location:
        frontmatter_lines.append(f"location: {location}")
    if due_date:
        frontmatter_lines.append(f"date_discussed: {due_date}")
    frontmatter_lines.extend([
        f"created: {today.isoformat()}",
        f"last_updated: {today.isoformat()}",
        f"tags: [booking, {shoot_type}]",
        "---",
    ])

    md_lines = [
        "\n".join(frontmatter_lines),
        "",
        f"# {client_name} — {shoot_type.title()} Session",
        "",
        "## Conversation Log",
        f"### {today.isoformat()} — {platform}",
        f"- {emoji} **Status:** {status}",
        f"- **Summary:** {content}",
    ]

    if questions:
        md_lines.append("- **Questions:**")
        for q in questions:
            md_lines.append(f"  - {q}")

    md_lines.append(f"- _Source: {source_filename}_")

    if suggested_reply:
        md_lines.extend([
            "",
            "## 💬 Suggested Reply",
            f"> {suggested_reply}",
        ])

    md_lines.append("")
    return "\n".join(md_lines)


def _build_update_content(
    item: dict[str, Any],
    source_filename: str,
    today: date,
    suggested_reply: str = "",
) -> str:
    """Build a conversation update block to append to an existing client file."""
    platform = item.get("platform") or "Unknown"
    status = item.get("status") or "need-to-reply"
    content = item.get("content") or ""
    questions = item.get("questions") or []
    emoji = STATUS_EMOJI.get(status, "🔴")

    lines = [
        "",
        f"### {today.isoformat()} — {platform}",
        f"- {emoji} **Status:** {status}",
        f"- **Summary:** {content}",
    ]

    if questions:
        lines.append("- **Questions:**")
        for q in questions:
            lines.append(f"  - {q}")

    lines.append(f"- _Source: {source_filename}_")

    if suggested_reply:
        lines.extend([
            "",
            "#### 💬 Suggested Reply",
            f"> {suggested_reply}",
        ])

    lines.append("")
    return "\n".join(lines)


def _get_faq_content() -> str:
    """Read the FAQ.md file from the vault. Returns empty string if not found."""
    try:
        faq_path = VAULT_PATHS["faq"]
        parts = faq_path.split("/")
        filename = parts[-1]
        folder_path = "/".join(parts[:-1])

        folder_id = drive_ops.find_folder_by_path(folder_path)
        if not folder_id:
            return ""

        file_info = drive_ops.find_file_by_name(filename, folder_id)
        if not file_info:
            return ""

        content = drive_ops.read_md_file(file_info["id"])
        return content or ""
    except Exception as e:
        logger.warning("Could not read FAQ file: %s", e)
        return ""


def _update_frontmatter_status(file_id: str, new_status: str, today: date) -> None:
    """Update the status and last_updated in a client file's YAML frontmatter."""
    try:
        content = drive_ops.read_md_file(file_id)
        if not content:
            return

        # Update status line
        content = re.sub(
            r"^status: .+$",
            f"status: {new_status}",
            content,
            count=1,
            flags=re.MULTILINE,
        )
        # Update last_updated line
        content = re.sub(
            r"^last_updated: .+$",
            f"last_updated: {today.isoformat()}",
            content,
            count=1,
            flags=re.MULTILINE,
        )

        drive_ops._upload_content(file_id, content)
        logger.info("Updated frontmatter status to '%s'", new_status)
    except Exception as e:
        logger.error("Failed to update frontmatter: %s", e)


def handle_booking(
    item: dict[str, Any],
    source_filename: str,
    transcript: str,
    target_date: Optional[date] = None,
) -> dict[str, str]:
    """
    Process a BOOKING item: find/create client file, generate reply if FAQ exists.

    Args:
        item: Gemini item dict with type=BOOKING.
        source_filename: Original screenshot filename.
        transcript: Full transcript for reply generation.
        target_date: Date for the entry.

    Returns:
        Dict with keys: client_file, status, suggested_reply.
    """
    today = target_date or date.today()
    client_name = item.get("name") or "Unknown Client"
    platform = item.get("platform") or "Unknown"
    handle = item.get("handle") or ""
    questions = item.get("questions") or []

    result = {
        "client_file": "",
        "status": item.get("status", "need-to-reply"),
        "suggested_reply": "",
    }

    # Step 1: Get FAQ and generate reply (2nd-pass) if questions exist
    faq_content = _get_faq_content()
    suggested_reply = ""
    if faq_content and questions:
        logger.info("FAQ found, generating suggested reply for %s", client_name)
        suggested_reply = gemini_analyzer.generate_booking_reply(
            transcript=transcript,
            questions=questions,
            faq_content=faq_content,
        )
        result["suggested_reply"] = suggested_reply

    # Step 2: Find or create client file
    clients_folder_id = _find_clients_folder_id()
    if not clients_folder_id:
        logger.error("Could not find/create Clients folder")
        return result

    existing_file_id = _find_existing_client_file(
        clients_folder_id, client_name, platform, handle
    )

    if existing_file_id:
        # Append to existing file
        update_content = _build_update_content(
            item, source_filename, today, suggested_reply
        )
        drive_ops.append_to_md(existing_file_id, update_content)
        _update_frontmatter_status(existing_file_id, item.get("status", "need-to-reply"), today)
        result["client_file"] = f"Updated: {client_name}-{platform}.md"
        logger.info("Updated existing client file for %s", client_name)
    else:
        # Create new file
        filename = _build_client_filename(client_name, platform)
        content = _build_new_client_content(
            item, source_filename, today, suggested_reply
        )
        file_id = drive_ops.create_md_file(clients_folder_id, filename, content)
        result["client_file"] = f"Created: {filename}"
        logger.info("Created new client file: %s (id=%s)", filename, file_id)

    return result

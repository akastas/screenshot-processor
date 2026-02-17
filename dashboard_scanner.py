"""
Screenshot Processor — Dashboard Scanner
Reads the current state of the Obsidian vault to gather context for proactive messaging.
Scans: client bookings, daily note tasks/events, TickTick tasks, recent vault activity.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any, Optional

import drive_ops
import ticktick_client
from config import DRIVE_VAULT_ROOT_FOLDER_ID, VAULT_PATHS, DAILY_NOTES_FOLDER

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Booking pipeline scanner
# ---------------------------------------------------------------------------
def scan_bookings() -> dict[str, list[dict]]:
    """
    Read all client files in 2-Areas/Clients/ and group by booking status.

    Returns:
        Dict keyed by status ('need-to-reply', 'waiting', 'confirmed', etc.)
        with lists of client info dicts.
    """
    clients_path = VAULT_PATHS.get("clients", "2-Areas/Clients")
    folder_id = drive_ops.find_folder_by_path(clients_path)
    if not folder_id:
        logger.warning("Clients folder not found at %s", clients_path)
        return {}

    files = drive_ops.list_md_files(folder_id)
    logger.info("Found %d client files to scan", len(files))

    by_status: dict[str, list[dict]] = {}

    for f in files:
        # Skip non-client files (like the FAQ)
        if "Business Info" in f["name"] or "Pipeline" in f["name"]:
            continue

        try:
            content = drive_ops.read_md_file(f["id"])
            info = _parse_client_frontmatter(content, f["name"])
            if info:
                status = info.get("status", "unknown")
                by_status.setdefault(status, []).append(info)
        except Exception as e:
            logger.warning("Failed to read client file %s: %s", f["name"], e)

    for status, clients in by_status.items():
        logger.info("Booking status '%s': %d clients", status, len(clients))

    return by_status


def _parse_client_frontmatter(content: str, filename: str) -> Optional[dict]:
    """Extract YAML frontmatter fields from a client file."""
    match = re.search(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None

    frontmatter = match.group(1)
    info: dict[str, Any] = {"filename": filename}

    for line in frontmatter.split("\n"):
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key in ("client", "handle", "platform", "shoot_type", "status",
                       "location", "date_discussed", "created", "last_updated"):
                info[key] = value

    return info if "client" in info else None


# ---------------------------------------------------------------------------
# Daily note scanner
# ---------------------------------------------------------------------------
def scan_daily_note(target_date: Optional[date] = None) -> dict[str, list[str]]:
    """
    Read today's daily note and extract tasks, events, and diary entries.

    Returns:
        Dict with keys 'tasks', 'events', 'diary', 'notes' — each a list of strings.
    """
    today = target_date or date.today()
    result: dict[str, list[str]] = {
        "tasks": [],
        "events": [],
        "diary": [],
        "notes": [],
    }

    try:
        daily_folder_id = drive_ops.find_folder_by_path(DAILY_NOTES_FOLDER)
        if not daily_folder_id:
            return result

        filename = f"{today.isoformat()}.md"
        file_info = drive_ops.find_file_by_name(filename, daily_folder_id)
        if not file_info:
            return result

        content = drive_ops.read_md_file(file_info["id"])
        result = _parse_daily_note_sections(content)
    except Exception as e:
        logger.warning("Failed to scan daily note: %s", e)

    return result


def _parse_daily_note_sections(content: str) -> dict[str, list[str]]:
    """Parse a daily note into its headed sections."""
    sections: dict[str, list[str]] = {
        "tasks": [],
        "events": [],
        "diary": [],
        "notes": [],
    }

    heading_map = {
        "## Tasks": "tasks",
        "## Events": "events",
        "## Diary": "diary",
        "## Notes": "notes",
    }

    current_section = None
    for line in content.split("\n"):
        stripped = line.strip()

        # Check if this line is a section heading
        matched = False
        for heading, key in heading_map.items():
            if stripped.startswith(heading):
                current_section = key
                matched = True
                break

        if matched or not current_section:
            continue

        # Stop at next heading
        if stripped.startswith("## "):
            current_section = None
            continue

        # Collect non-empty content lines
        if stripped and stripped != "---":
            sections[current_section].append(stripped)

    return sections


# ---------------------------------------------------------------------------
# TickTick task scanner
# ---------------------------------------------------------------------------
def scan_ticktick_tasks() -> dict[str, list[dict]]:
    """
    Fetch tasks from TickTick and categorize them.

    Returns:
        Dict with keys: 'overdue', 'today', 'upcoming', 'high_priority'.
    """
    result: dict[str, list[dict]] = {
        "overdue": [],
        "today": [],
        "upcoming": [],
        "high_priority": [],
    }

    if not ticktick_client.is_configured():
        return result

    try:
        projects = ticktick_client.list_projects()
        today = date.today()
        tomorrow = today + timedelta(days=1)
        week_from_now = today + timedelta(days=7)

        for project in projects:
            project_id = project.get("id")
            project_name = project.get("name", "Unknown")
            if not project_id:
                continue

            tasks = _fetch_project_tasks(project_id)
            for task in tasks:
                task_info = {
                    "title": task.get("title", ""),
                    "project": project_name,
                    "priority": task.get("priority", 0),
                    "due_date": None,
                    "tags": task.get("tags", []),
                }

                # Parse due date
                due_str = task.get("dueDate", "")
                if due_str:
                    try:
                        due = date.fromisoformat(due_str[:10])
                        task_info["due_date"] = due.isoformat()

                        if due < today:
                            result["overdue"].append(task_info)
                        elif due == today:
                            result["today"].append(task_info)
                        elif due <= week_from_now:
                            result["upcoming"].append(task_info)
                    except ValueError:
                        pass

                # High priority (TickTick priority 5 = high)
                if task.get("priority", 0) >= 5:
                    result["high_priority"].append(task_info)

    except Exception as e:
        logger.error("Failed to scan TickTick tasks: %s", e)

    return result


def _fetch_project_tasks(project_id: str) -> list[dict]:
    """Fetch all incomplete tasks for a TickTick project."""
    from config import TICKTICK_API_BASE, TICKTICK_ACCESS_TOKEN

    try:
        resp = requests.get(
            f"{TICKTICK_API_BASE}/project/{project_id}/data",
            headers={
                "Authorization": f"Bearer {TICKTICK_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("tasks", [])
    except Exception as e:
        logger.warning("Failed to fetch tasks for project %s: %s", project_id, e)
        return []


# Need requests for TickTick API calls
import requests


# ---------------------------------------------------------------------------
# Recent vault activity scanner
# ---------------------------------------------------------------------------
def scan_recent_vault_files(days: int = 3) -> list[dict]:
    """
    List recently modified files in key vault folders to understand recent activity.
    Useful for the AI to generate contextual suggestions.

    Returns:
        List of dicts with 'name', 'folder', 'snippet' (first ~200 chars).
    """
    recent: list[dict] = []
    folders_to_scan = [
        ("ideas", VAULT_PATHS.get("ideas", "")),
        ("inspiration", VAULT_PATHS.get("inspiration", "")),
        ("learning", VAULT_PATHS.get("learning", "")),
        ("quotes", VAULT_PATHS.get("quotes", "")),
    ]

    for label, vault_path in folders_to_scan:
        if not vault_path:
            continue
        parts = vault_path.rsplit("/", 1)
        if len(parts) == 2:
            folder_path, filename = parts
        else:
            continue

        try:
            folder_id = drive_ops.find_folder_by_path(folder_path)
            if not folder_id:
                continue

            file_info = drive_ops.find_file_by_name(filename, folder_id)
            if not file_info:
                continue

            content = drive_ops.read_md_file(file_info["id"])
            # Get last ~500 chars as a snippet of recent additions
            if len(content) > 500:
                snippet = content[-500:]
            else:
                snippet = content

            recent.append({
                "name": filename,
                "folder": label,
                "snippet": snippet,
            })
        except Exception as e:
            logger.warning("Failed to scan %s: %s", label, e)

    return recent


# ---------------------------------------------------------------------------
# Full dashboard scan — combines everything
# ---------------------------------------------------------------------------
def full_scan() -> dict[str, Any]:
    """
    Run a complete dashboard scan: bookings, daily note, TickTick, recent files.
    Returns all data needed for the proactive engine.
    """
    logger.info("Starting full dashboard scan...")

    bookings = scan_bookings()
    daily_note = scan_daily_note()
    ticktick = scan_ticktick_tasks()
    recent_files = scan_recent_vault_files()

    scan_result = {
        "bookings": bookings,
        "daily_note": daily_note,
        "ticktick": ticktick,
        "recent_files": recent_files,
        "scan_date": date.today().isoformat(),
    }

    # Quick stats
    total_bookings = sum(len(v) for v in bookings.values())
    need_reply = len(bookings.get("need-to-reply", []))
    overdue_tasks = len(ticktick.get("overdue", []))
    today_tasks = len(ticktick.get("today", []))

    logger.info(
        "Scan complete: %d bookings (%d need reply), %d overdue tasks, %d today tasks",
        total_bookings, need_reply, overdue_tasks, today_tasks,
    )

    return scan_result

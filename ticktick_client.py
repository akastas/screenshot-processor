"""
Screenshot Processor — TickTick API Client
Creates tasks in TickTick with smart project/tag assignment.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from config import (
    TICKTICK_ACCESS_TOKEN,
    TICKTICK_CLIENT_ID,
    TICKTICK_CLIENT_SECRET,
    TICKTICK_API_BASE,
    TICKTICK_PRIORITY_MAP,
)

logger = logging.getLogger(__name__)

# Cache project list to avoid repeated API calls
_projects_cache: Optional[list[dict]] = None


def _headers() -> dict:
    """Authorization headers for TickTick API."""
    return {
        "Authorization": f"Bearer {TICKTICK_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def is_configured() -> bool:
    """Check if TickTick credentials are available."""
    return bool(TICKTICK_ACCESS_TOKEN)


def list_projects() -> list[dict]:
    """Fetch all TickTick projects (lists). Cached per invocation."""
    global _projects_cache
    if _projects_cache is not None:
        return _projects_cache

    if not is_configured():
        logger.warning("TickTick not configured, skipping")
        return []

    try:
        resp = requests.get(
            f"{TICKTICK_API_BASE}/project",
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        _projects_cache = resp.json()
        logger.info("Fetched %d TickTick projects", len(_projects_cache))
        return _projects_cache
    except Exception as e:
        logger.error("Failed to list TickTick projects: %s", e)
        return []


def find_project_id(name: str) -> Optional[str]:
    """
    Find a TickTick project by name (case-insensitive).
    Returns the project ID or None.
    """
    projects = list_projects()
    name_lower = name.lower()
    for proj in projects:
        if proj.get("name", "").lower() == name_lower:
            return proj["id"]
    return None


def create_project(name: str) -> Optional[str]:
    """Create a new TickTick project and return its ID."""
    if not is_configured():
        return None

    try:
        resp = requests.post(
            f"{TICKTICK_API_BASE}/project",
            headers=_headers(),
            json={"name": name},
            timeout=10,
        )
        resp.raise_for_status()
        project = resp.json()
        project_id = project["id"]
        logger.info("Created TickTick project '%s' (id=%s)", name, project_id)
        # Invalidate cache
        global _projects_cache
        _projects_cache = None
        return project_id
    except Exception as e:
        logger.error("Failed to create TickTick project '%s': %s", name, e)
        return None


def resolve_project(hint: Optional[str]) -> Optional[str]:
    """
    Resolve a project_hint from Gemini to a TickTick project ID.
    If the project doesn't exist, create it.
    Falls back to None (TickTick Inbox) if resolution fails.
    """
    if not hint:
        return None

    project_id = find_project_id(hint)
    if project_id:
        return project_id

    # Auto-create the project
    logger.info("Project '%s' not found, creating it", hint)
    return create_project(hint)


def create_task(item: dict[str, Any], source_filename: str) -> Optional[str]:
    """
    Create a TickTick task from a Gemini analysis item.

    Args:
        item: Gemini item dict with type=TASK, content, priority, due_date, project_hint, tags
        source_filename: Original screenshot filename for context

    Returns:
        Task ID if created, None otherwise.
    """
    if not is_configured():
        logger.warning("TickTick not configured, skipping task creation")
        return None

    content = item.get("content", "")
    priority = TICKTICK_PRIORITY_MAP.get(item.get("priority"), 0)
    due_date = item.get("due_date")
    project_hint = item.get("project_hint")
    tags = item.get("tags", [])

    # Resolve project
    project_id = resolve_project(project_hint)

    # Build task payload
    task_body: dict[str, Any] = {
        "title": content,
        "content": f"Source: {source_filename}",
        "priority": priority,
    }

    if project_id:
        task_body["projectId"] = project_id

    if due_date:
        # TickTick expects ISO format: yyyy-MM-dd'T'HH:mm:ssZ
        task_body["dueDate"] = f"{due_date}T00:00:00+0000"
        task_body["isAllDay"] = True

    if tags:
        task_body["tags"] = tags

    try:
        resp = requests.post(
            f"{TICKTICK_API_BASE}/task",
            headers=_headers(),
            json=task_body,
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
        task_id = result.get("id", "unknown")
        project_name = project_hint or "Inbox"
        logger.info(
            "Created TickTick task '%s' in project '%s' (id=%s)",
            content[:50], project_name, task_id,
        )
        return task_id
    except Exception as e:
        logger.error("Failed to create TickTick task: %s", e)
        return None

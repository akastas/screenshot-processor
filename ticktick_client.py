"""
Screenshot Processor — TickTick API Client
Handles OAuth2 token refresh and task creation via the TickTick Open API.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from config import (
    TICKTICK_API_BASE,
    TICKTICK_PRIORITY_MAP,
    get_secret,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------
_access_token: Optional[str] = None


def _get_access_token() -> str:
    """
    Get a valid access token. Refreshes automatically using the stored refresh token.
    Tokens are cached for the lifetime of the Cloud Function instance.
    """
    global _access_token
    if _access_token:
        return _access_token

    client_id = get_secret("ticktick-client-id")
    client_secret = get_secret("ticktick-client-secret")
    refresh_token = get_secret("ticktick-refresh-token")

    response = requests.post(
        "https://ticktick.com/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    _access_token = data["access_token"]

    # If a new refresh token is provided, we'd want to update Secret Manager.
    # For now we log it — manual update needed if TickTick rotates tokens.
    new_refresh = data.get("refresh_token")
    if new_refresh and new_refresh != refresh_token:
        logger.warning(
            "TickTick issued a NEW refresh token. "
            "Update 'ticktick-refresh-token' in Secret Manager!"
        )

    logger.info("TickTick access token refreshed successfully")
    return _access_token


def _auth_headers() -> dict[str, str]:
    """Return Authorization headers for TickTick API calls."""
    return {
        "Authorization": f"Bearer {_get_access_token()}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Task creation
# ---------------------------------------------------------------------------
def create_task(
    title: str,
    content: str = "",
    priority: str = "medium",
    due_date: Optional[str] = None,
    project_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Create a task in TickTick.

    Args:
        title: Task title.
        content: Optional description / notes.
        priority: 'high', 'medium', 'low', or None.
        due_date: ISO date string 'YYYY-MM-DD' or None.
        project_id: TickTick project/list ID. None = Inbox.

    Returns:
        TickTick API response as dict (contains 'id', 'title', etc.).
    """
    payload: dict[str, Any] = {
        "title": title,
        "content": content,
        "priority": TICKTICK_PRIORITY_MAP.get(priority, 0),
    }

    if due_date:
        # TickTick expects ISO 8601 with timezone
        payload["dueDate"] = f"{due_date}T00:00:00+0000"

    if project_id:
        payload["projectId"] = project_id

    response = requests.post(
        f"{TICKTICK_API_BASE}/task",
        json=payload,
        headers=_auth_headers(),
        timeout=10,
    )
    response.raise_for_status()
    result = response.json()
    logger.info("Created TickTick task: '%s' (id=%s)", title, result.get("id"))
    return result


def create_tasks_from_items(
    items: list[dict[str, Any]],
    source_filename: str,
) -> list[dict[str, Any]]:
    """
    Create TickTick tasks for all TASK-type items.

    Args:
        items: List of items from Gemini analysis.
        source_filename: Screenshot filename for context.

    Returns:
        List of created task responses.
    """
    created = []
    task_items = [item for item in items if item.get("type") == "TASK"]

    for item in task_items:
        try:
            result = create_task(
                title=item["content"],
                content=f"Source: {source_filename}",
                priority=item.get("priority", "medium"),
                due_date=item.get("due_date"),
            )
            created.append(result)
        except requests.RequestException as e:
            logger.error("Failed to create TickTick task '%s': %s", item["content"], e)

    if created:
        logger.info(
            "Created %d/%d TickTick tasks from %s",
            len(created), len(task_items), source_filename,
        )
    return created

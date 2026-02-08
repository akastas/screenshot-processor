"""
Screenshot Processor — Google Drive Operations
Uses a service account for reads/moves/renames.
Uses OAuth2 user credentials (akastas@gmail.com) for file creation.
"""

from __future__ import annotations

import io
import logging
from datetime import date
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
import google.auth
from google.oauth2.credentials import Credentials as UserCredentials

from config import (
    DRIVE_INBOX_FOLDER_ID,
    DRIVE_ARCHIVE_FOLDER_ID,
    DRIVE_VAULT_ROOT_FOLDER_ID,
    DAILY_NOTES_FOLDER,
    DAILY_NOTE_TEMPLATE,
    IMAGE_EXTENSIONS,
    OAUTH_CLIENT_ID_SECRET,
    OAUTH_CLIENT_SECRET_SECRET,
    OAUTH_REFRESH_TOKEN_SECRET,
    get_secret,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service initialization
# ---------------------------------------------------------------------------
_service = None
_user_service = None


def _get_service():
    """Lazy-init the Drive API service using service account (for reads/moves/renames)."""
    global _service
    if _service is None:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        _service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    return _service


def _get_user_service():
    """
    Lazy-init the Drive API service using OAuth2 user credentials.
    Used for file creation (requires storage quota from a real user account).
    """
    global _user_service
    if _user_service is None:
        client_id = get_secret(OAUTH_CLIENT_ID_SECRET)
        client_secret = get_secret(OAUTH_CLIENT_SECRET_SECRET)
        refresh_token = get_secret(OAUTH_REFRESH_TOKEN_SECRET)

        credentials = UserCredentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=["https://www.googleapis.com/auth/drive"],
        )
        _user_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        logger.info("Initialized OAuth2 user-credentials Drive service")
    return _user_service


# ---------------------------------------------------------------------------
# List / query helpers
# ---------------------------------------------------------------------------
def list_images(folder_id: Optional[str] = None) -> list[dict]:
    """
    List image files in the given Drive folder.
    Returns list of dicts with keys: id, name, mimeType.
    """
    folder = folder_id or DRIVE_INBOX_FOLDER_ID
    if not folder:
        raise ValueError("DRIVE_INBOX_FOLDER_ID is not configured")

    service = _get_service()
    results: list[dict] = []
    page_token = None

    while True:
        response = (
            service.files()
            .list(
                q=f"'{folder}' in parents and trashed = false and mimeType contains 'image/'",
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType)",
                pageToken=page_token,
                pageSize=100,
            )
            .execute()
        )
        files = response.get("files", [])
        # Double-check extension (some Drive mimeTypes can be ambiguous)
        for f in files:
            ext = f["name"].rsplit(".", 1)[-1].lower() if "." in f["name"] else ""
            if ext in IMAGE_EXTENSIONS:
                results.append(f)
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    logger.info("Found %d images in folder %s", len(results), folder)
    return results


def find_file_by_name(name: str, parent_folder_id: str) -> Optional[dict]:
    """Find a file by exact name in a specific folder. Returns {id, name} or None."""
    service = _get_service()
    escaped = name.replace("'", "\\'")
    response = (
        service.files()
        .list(
            q=f"name = '{escaped}' and '{parent_folder_id}' in parents and trashed = false",
            spaces="drive",
            fields="files(id, name)",
            pageSize=1,
        )
        .execute()
    )
    files = response.get("files", [])
    return files[0] if files else None


def find_folder_by_path(path: str, root_folder_id: Optional[str] = None) -> Optional[str]:
    """
    Resolve a slash-separated path like '2-Areas/Calendar' to a Drive folder ID.
    Walks down from root_folder_id (defaults to vault root).
    Returns the final folder ID, or None if any segment is missing.
    """
    current = root_folder_id or DRIVE_VAULT_ROOT_FOLDER_ID
    if not current:
        raise ValueError("DRIVE_VAULT_ROOT_FOLDER_ID is not configured")

    service = _get_service()
    parts = [p for p in path.split("/") if p]

    for part in parts:
        escaped = part.replace("'", "\\'")
        response = (
            service.files()
            .list(
                q=(
                    f"name = '{escaped}' and '{current}' in parents "
                    f"and mimeType = 'application/vnd.google-apps.folder' "
                    f"and trashed = false"
                ),
                spaces="drive",
                fields="files(id)",
                pageSize=1,
            )
            .execute()
        )
        files = response.get("files", [])
        if not files:
            logger.warning("Folder segment '%s' not found under %s", part, current)
            return None
        current = files[0]["id"]

    return current


# ---------------------------------------------------------------------------
# Download / read
# ---------------------------------------------------------------------------
def download_image(file_id: str) -> bytes:
    """Download an image file from Drive as raw bytes."""
    service = _get_service()
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


def read_md_file(file_id: str) -> str:
    """Read the text content of a markdown file from Drive."""
    service = _get_service()
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue().decode("utf-8")


# ---------------------------------------------------------------------------
# Write / append / create
# ---------------------------------------------------------------------------
def append_to_md(file_id: str, new_content: str, under_heading: Optional[str] = None) -> None:
    """
    Append content to an existing .md file on Drive.
    If under_heading is given (e.g. '## Tasks'), insert content after that heading.
    Otherwise, append at the end.
    """
    current = read_md_file(file_id)

    if under_heading and under_heading in current:
        # Find the heading position and insert right after it
        idx = current.index(under_heading) + len(under_heading)
        # Skip the newline after the heading
        if idx < len(current) and current[idx] == "\n":
            idx += 1
        updated = current[:idx] + new_content + "\n" + current[idx:]
    else:
        # Append at end
        if not current.endswith("\n"):
            current += "\n"
        updated = current + new_content + "\n"

    _upload_content(file_id, updated)


def create_md_file(folder_id: str, name: str, content: str) -> str:
    """
    Create a new .md file in the given Drive folder.
    Uses OAuth2 user credentials so the file is owned by akastas@gmail.com.
    Returns the new file's ID.
    """
    service = _get_user_service()
    file_metadata = {
        "name": name,
        "parents": [folder_id],
        "mimeType": "text/markdown",
    }
    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")),
        mimetype="text/markdown",
        resumable=True,
    )
    file = service.files().create(
        body=file_metadata, media_body=media, fields="id"
    ).execute()
    logger.info("Created file '%s' (id=%s) in folder %s", name, file["id"], folder_id)
    return file["id"]


def _upload_content(file_id: str, content: str) -> None:
    """Overwrite a file's content on Drive."""
    service = _get_service()
    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")),
        mimetype="text/markdown",
        resumable=True,
    )
    service.files().update(fileId=file_id, media_body=media).execute()


# ---------------------------------------------------------------------------
# Move / rename
# ---------------------------------------------------------------------------
def move_file(file_id: str, new_parent_id: str) -> None:
    """Move a file to a new parent folder."""
    service = _get_service()
    # Get current parents
    file = service.files().get(fileId=file_id, fields="parents").execute()
    previous_parents = ",".join(file.get("parents", []))
    service.files().update(
        fileId=file_id,
        addParents=new_parent_id,
        removeParents=previous_parents,
        fields="id, parents",
    ).execute()
    logger.info("Moved file %s to folder %s", file_id, new_parent_id)


def rename_file(file_id: str, new_name: str) -> None:
    """Rename a file on Drive."""
    service = _get_service()
    service.files().update(
        fileId=file_id, body={"name": new_name}, fields="id, name"
    ).execute()
    logger.info("Renamed file %s to '%s'", file_id, new_name)


# ---------------------------------------------------------------------------
# Daily note
# ---------------------------------------------------------------------------
def find_or_create_daily_note(target_date: date) -> str:
    """
    Find today's daily note by filename convention '{YYYY-MM-DD}.md'.
    If it doesn't exist, create it from template.
    Returns the file ID.
    """
    filename = f"{target_date.isoformat()}.md"

    # Find the Daily Notes folder
    daily_folder_id = find_folder_by_path(DAILY_NOTES_FOLDER)
    if not daily_folder_id:
        raise RuntimeError(
            f"Could not find '{DAILY_NOTES_FOLDER}' folder in vault. "
            "Please create it in Google Drive."
        )

    # Check if note already exists
    existing = find_file_by_name(filename, daily_folder_id)
    if existing:
        logger.info("Found existing daily note: %s", filename)
        return existing["id"]

    # Create from template
    content = DAILY_NOTE_TEMPLATE.format(date=target_date.isoformat())
    file_id = create_md_file(daily_folder_id, filename, content)
    logger.info("Created new daily note: %s", filename)
    return file_id

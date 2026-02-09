"""
Screenshot Processor — Configuration
All sensitive values (tokens, keys) are fetched from GCP Secret Manager at runtime.
"""

import os
from google.cloud import secretmanager

# ---------------------------------------------------------------------------
# GCP Project
# ---------------------------------------------------------------------------
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "screenshot-processor-ak")
GCP_LOCATION = os.environ.get("GCP_LOCATION", "europe-west1")

# ---------------------------------------------------------------------------
# Gemini Model
# ---------------------------------------------------------------------------
GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL", "gemini-2.5-flash"
)

# ---------------------------------------------------------------------------
# Google Drive — Folder IDs (set via env vars or override here after setup)
# ---------------------------------------------------------------------------
DRIVE_INBOX_FOLDER_ID = os.environ.get("DRIVE_INBOX_FOLDER_ID", "1xHPRq1MR2JmQN-f0fnVKOHS-edIsLZoB")
DRIVE_ARCHIVE_FOLDER_ID = os.environ.get("DRIVE_ARCHIVE_FOLDER_ID", "1jHz-UP3-YQ8a5bn__E6UkHo8ylv6rdjj")
DRIVE_VAULT_ROOT_FOLDER_ID = os.environ.get("DRIVE_VAULT_ROOT_FOLDER_ID", "1VKCaMxB639IyfwDHIvZPE4YzhZheTpuq")

# Image file extensions to process
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "heic", "heif", "bmp", "gif"}

# ---------------------------------------------------------------------------
# Obsidian Vault — Path structure inside Google Drive
# These are *relative* folder names under the vault root.
# The actual Drive folder IDs are resolved at runtime via drive_ops.
# ---------------------------------------------------------------------------
DAILY_NOTES_FOLDER = "Daily Notes"
VAULT_PATHS = {
    "events":       "2-Areas/Calendar/Events.md",
    "ideas":        "3-Resources/Ideas/Ideas.md",
    "references":   "3-Resources/References.md",
    "finances":     "2-Areas/Finances/Transactions.md",
    "people":       "3-Resources/People/People.md",
    "places":       "3-Resources/Places/Places.md",
    "inspiration":  "3-Resources/Inspiration/Inspiration.md",
    "quotes":       "3-Resources/Quotes/Quotes.md",
    "learning":     "3-Resources/Learning/Learning.md",
    "wishlist":     "3-Resources/Wishlist/Wishlist.md",
    "clients":      "2-Areas/Clients",
    "faq":          "2-Areas/Clients/FAQ.md",
}

# ---------------------------------------------------------------------------
# Routing table — how each item type is handled
# ---------------------------------------------------------------------------
ROUTE_MAP = {
    "TASK": {
        "daily_note_heading": "## Tasks",
        "ticktick": True,
    },
    "EVENT": {
        "daily_note_heading": "## Events",
        "extra_file": VAULT_PATHS["events"],
    },
    "IDEA": {
        "extra_file": VAULT_PATHS["ideas"],
    },
    "DIARY": {
        "daily_note_heading": "## Diary",
    },
    "REFERENCE": {
        "extra_file": VAULT_PATHS["references"],
    },
    "FINANCE": {
        "extra_file": VAULT_PATHS["finances"],
    },
    "PERSON": {
        "extra_file": VAULT_PATHS["people"],
    },
    "LOCATION": {
        "extra_file": VAULT_PATHS["places"],
    },
    "INSPIRATION": {
        "extra_file": VAULT_PATHS["inspiration"],
    },
    "QUOTE": {
        "extra_file": VAULT_PATHS["quotes"],
    },
    "LEARNING": {
        "extra_file": VAULT_PATHS["learning"],
    },
    "WISHLIST": {
        "extra_file": VAULT_PATHS["wishlist"],
    },
    "BOOKING": {
        "booking": True,
    },
}

# ---------------------------------------------------------------------------
# TickTick — Priority mapping
# ---------------------------------------------------------------------------
TICKTICK_PRIORITY_MAP = {
    "high": 5,
    "medium": 3,
    "low": 1,
    None: 0,
}

TICKTICK_API_BASE = "https://api.ticktick.com/open/v1"

# ---------------------------------------------------------------------------
# OAuth2 User Credentials (for Drive file creation as akastas@gmail.com)
# Passed as environment variables to avoid Secret Manager permission issues.
# ---------------------------------------------------------------------------
OAUTH_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID", "")
OAUTH_CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET", "")
OAUTH_REFRESH_TOKEN = os.environ.get("OAUTH_REFRESH_TOKEN", "")

# ---------------------------------------------------------------------------
# TickTick API credentials (OAuth2)
# ---------------------------------------------------------------------------
TICKTICK_CLIENT_ID = os.environ.get("TICKTICK_CLIENT_ID", "")
TICKTICK_CLIENT_SECRET = os.environ.get("TICKTICK_CLIENT_SECRET", "")
TICKTICK_ACCESS_TOKEN = os.environ.get("TICKTICK_ACCESS_TOKEN", "")

# ---------------------------------------------------------------------------
# Daily note template
# ---------------------------------------------------------------------------
DAILY_NOTE_TEMPLATE = """---
date: {date}
---

## Tasks

## Events

## Diary

## Notes
"""

# ---------------------------------------------------------------------------
# Secret Manager helpers
# ---------------------------------------------------------------------------
_secret_cache: dict[str, str] = {}


def get_secret(secret_id: str) -> str:
    """Fetch a secret from GCP Secret Manager (cached per invocation)."""
    if secret_id in _secret_cache:
        return _secret_cache[secret_id]

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{GCP_PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    value = response.payload.data.decode("UTF-8")
    _secret_cache[secret_id] = value
    return value

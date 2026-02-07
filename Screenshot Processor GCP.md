# Screenshot Processor — GCP Automation

**Status**: Planning
**Goal**: Auto-process screenshots from any device → structured Obsidian notes + TickTick tasks
**Platform**: Google Cloud Platform (Free Trial €250.74 + GDP monthly €83.58)

---

## Architecture

```
Phone/PC screenshot
       ↓
Google Drive (Inbox/Screenshots/)
       ↓  (Cloud Function triggered by Drive file change)
Cloud Function (Python)
       ↓
Gemini Flash 2.0 API (image analysis)
       ↓
Structured output (JSON)
       ↓
  ┌────┴────┐
  ↓         ↓
Google    TickTick
Drive     API
(write    (create
.md       tasks)
files)
```

## Flow — Step by Step

1. **Screenshot taken** on phone or PC
2. Screenshot lands in `Google Drive/ObsidianVault/Inbox/Screenshots/`
3. **Cloud Function** triggers on new file in that folder
4. Function downloads the image, sends to **Gemini Flash 2.0** with analysis prompt
5. Gemini returns structured JSON: transcript, categories, items
6. Function routes output:
   - **TASK** → appends to `Daily Notes/{date}.md` under `## Tasks` AND creates TickTick task via API
   - **EVENT** → appends to daily note + `2-Areas/Calendar/Events.md`
   - **IDEA** → appends to `3-Resources/Ideas/Ideas.md`
   - **DIARY** → appends to daily note under `## Diary`
   - **REFERENCE** → appends to `3-Resources/References.md`
   - **FINANCE** → appends to `2-Areas/Finances/Transactions.md`
7. Function creates analysis `.md` file in `Inbox/Screenshots/Archive/`
8. Function moves original screenshot to `Archive/` with renamed filename
9. Done — Obsidian syncs via Google Drive, TickTick has the tasks

## Components to Build

### 1. Cloud Function (Python)
- **Trigger**: Google Drive API push notification (or Cloud Scheduler polling every 5-15 min)
- **Runtime**: Python 3.11+
- **Dependencies**: `google-cloud-aiplatform`, `google-api-python-client`, `requests`
- **Logic**:
  - List files in `Inbox/Screenshots/` (filter images only)
  - For each image: download → send to Gemini → parse response → route to files → archive
  - Append to existing `.md` files (read current content, append, write back)
  - Create daily note if it doesn't exist

### 2. Gemini Flash 2.0 Prompt
```
You are a screenshot analysis assistant. Analyze the image with extreme precision.

RULES:
- Transcribe ALL visible text EXACTLY as written, word for word
- Support Russian, Greek, English, Italian, and any other language
- Do NOT paraphrase or guess — copy text exactly
- Categorize each piece of information

Return ONLY valid JSON in this format:
{
  "summary": "one line description",
  "language": "detected language",
  "transcript": "exact text from image, preserve formatting",
  "filename_suggestion": "2-4 words, lowercase, hyphens",
  "items": [
    {
      "type": "TASK|EVENT|IDEA|DIARY|REFERENCE|FINANCE",
      "content": "the extracted information",
      "priority": "high|medium|low",
      "due_date": "YYYY-MM-DD if detected, null otherwise"
    }
  ]
}
```

### 3. TickTick Integration
- **Auth**: OAuth2 (register app at developer.ticktick.com)
- **Endpoint**: `POST https://api.ticktick.com/open/v1/task`
- **Payload**:
```json
{
  "title": "Task description from screenshot",
  "content": "Source: screenshot filename\nTranscript context",
  "priority": 0-5,
  "dueDate": "2026-02-07T00:00:00+0000",
  "projectId": "inbox or specific list ID"
}
```
- **Priority mapping**: high→5, medium→3, low→1
- Store OAuth refresh token in **Secret Manager** (not hardcoded)

### 4. Google Drive File Operations
- **Read .md file**: `files.get()` + `files.export()` (or download as text)
- **Append to .md file**: Download content → append new text → `files.update()` with new content
- **Create .md file**: `files.create()` with `text/markdown` mime type in correct folder
- **Move file**: `files.update()` with new `parents[]`
- **Rename file**: `files.update()` with new `name`
- **Service account** needs access to the Drive folder (share folder with service account email)

## Setup Steps

### Phase 1: GCP Setup
- [ ] Create new GCP project "screenshot-processor"
- [ ] Enable APIs: Cloud Functions, Gemini (Vertex AI), Google Drive API, Secret Manager
- [ ] Create service account with Drive access
- [ ] Share Obsidian vault Drive folder with service account

### Phase 2: TickTick Setup
- [ ] Register app at developer.ticktick.com
- [ ] Get OAuth2 client ID + secret
- [ ] Complete OAuth flow, get refresh token
- [ ] Store credentials in GCP Secret Manager

### Phase 3: Core Function
- [ ] Write Cloud Function in Python
- [ ] Implement Gemini image analysis
- [ ] Implement Drive file read/append/create/move
- [ ] Implement TickTick task creation
- [ ] Test with sample screenshots

### Phase 4: Trigger Setup
- [ ] Option A: Cloud Scheduler (poll every 5 min) — simpler
- [ ] Option B: Drive push notifications — real-time but more complex
- [ ] Deploy and monitor

## Cost Estimate

| Component | Monthly Cost |
|-----------|-------------|
| Gemini Flash 2.0 (20 imgs/day) | ~€0.25 |
| Cloud Function (invocations) | ~€0 (free tier: 2M/month) |
| Cloud Scheduler | ~€0 (free tier: 3 jobs) |
| Secret Manager | ~€0 (free tier: 6 active secrets) |
| **Total** | **~€0.25/month** |

Your €83.58/month recurring credit covers this ~330x over.

## Research Prompt for Claude

Use this prompt in Claude.ai to get implementation help:

```
I'm building an automated screenshot processor on Google Cloud Platform. Here's the architecture:

1. Screenshots land in a Google Drive folder
2. A Cloud Function (Python) triggers on new files
3. The function sends images to Gemini Flash 2.0 for analysis
4. Gemini returns structured JSON with: transcript, categories (TASK/EVENT/IDEA/DIARY/REFERENCE/FINANCE), priorities
5. The function writes results to .md files in specific Google Drive folders (Obsidian vault)
6. TASK items also get created as TickTick tasks via their Open API

I need help with:
1. Complete Python Cloud Function code
2. Google Drive API: reading, appending to, creating, and moving .md files using a service account
3. Gemini Flash 2.0 API: sending images and getting structured JSON responses
4. TickTick Open API: OAuth2 flow and task creation
5. Cloud Scheduler or Drive push notifications for triggering
6. Secret Manager for storing API credentials

My GCP project has Free Trial (€250) and Google Developer Program monthly credits (€83/mo).

Give me the complete implementation, file by file, ready to deploy.
```

## Links
- [[Dashboard]] — Main overview
- [[System Documentation]] — Vault structure reference
- TickTick API docs: https://developer.ticktick.com/api
- Gemini API: Vertex AI in GCP console
- Cloud Functions: GCP console → Cloud Functions

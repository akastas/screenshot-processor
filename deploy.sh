#!/usr/bin/env bash
# Screenshot Processor — Deploy to GCP
# Run from the ScreenshotProcessor directory.
#
# Prerequisites:
#   1. gcloud CLI installed and authenticated
#   2. GCP project created and APIs enabled
#   3. Service account created and Drive folder shared with it
#   4. Environment variables set (or edit the defaults below)

set -euo pipefail

# --- Configuration ---
PROJECT_ID="${GCP_PROJECT_ID:-screenshot-processor-ak}"
REGION="${GCP_LOCATION:-europe-west1}"
FUNCTION_NAME="screenshot-processor"
SA_EMAIL="${SA_EMAIL:-screenshot-processor@screenshot-processor-ak.iam.gserviceaccount.com}"
MEMORY="512MB"
TIMEOUT="300s"
SCHEDULE="*/5 * * * *"  # Every 5 minutes
TIMEZONE="${PROACTIVE_TIMEZONE:-Europe/Rome}"

echo "=== Deploying Screenshot Processor ==="
echo "Project:  $PROJECT_ID"
echo "Region:   $REGION"
echo "SA:       $SA_EMAIL"
echo "Timezone: $TIMEZONE"
echo ""

# --- Step 1: Enable required APIs ---
echo ">>> Enabling APIs..."
gcloud services enable \
    cloudfunctions.googleapis.com \
    cloudbuild.googleapis.com \
    cloudscheduler.googleapis.com \
    drive.googleapis.com \
    aiplatform.googleapis.com \
    secretmanager.googleapis.com \
    --project "$PROJECT_ID" \
    --quiet

# --- Load secrets from .env.deploy if it exists ---
if [[ -f .env.deploy ]]; then
    echo ">>> Loading secrets from .env.deploy..."
    source .env.deploy
fi

# Validate OAuth credentials
if [[ -z "$OAUTH_CLIENT_ID" || -z "$OAUTH_CLIENT_SECRET" || -z "$OAUTH_REFRESH_TOKEN" ]]; then
    echo "ERROR: OAuth credentials not set."
    echo "Create a .env.deploy file with:"
    echo "  export OAUTH_CLIENT_ID=your-client-id"
    echo "  export OAUTH_CLIENT_SECRET=your-client-secret"
    echo "  export OAUTH_REFRESH_TOKEN=your-refresh-token"
    exit 1
fi

# TickTick credentials (optional — system works without them)
if [[ -z "${TICKTICK_ACCESS_TOKEN:-}" ]]; then
    echo "WARNING: TICKTICK_ACCESS_TOKEN not set. Tasks won't be created in TickTick."
    echo "Run: python scripts/get_ticktick_token.py to get a token."
    TICKTICK_ENV_VARS=""
else
    TICKTICK_ENV_VARS=",TICKTICK_CLIENT_ID=${TICKTICK_CLIENT_ID:-},TICKTICK_CLIENT_SECRET=${TICKTICK_CLIENT_SECRET:-},TICKTICK_ACCESS_TOKEN=$TICKTICK_ACCESS_TOKEN"
    echo "TickTick: Configured"
fi

# Telegram credentials (optional — proactive features require them)
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
    echo "WARNING: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set."
    echo "Proactive features (briefings, nudges) will be disabled."
    echo "To set up: create a bot via @BotFather, then add to .env.deploy:"
    echo "  export TELEGRAM_BOT_TOKEN=your-bot-token"
    echo "  export TELEGRAM_CHAT_ID=your-chat-id"
    TELEGRAM_ENV_VARS=""
else
    TELEGRAM_ENV_VARS=",TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID,PROACTIVE_TIMEZONE=$TIMEZONE"
    echo "Telegram: Configured"
fi

echo ""
echo ">>> Deploying Cloud Function..."
gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --runtime python311 \
    --trigger-http \
    --entry-point process_screenshots \
    --region "$REGION" \
    --memory "$MEMORY" \
    --timeout "$TIMEOUT" \
    --service-account "$SA_EMAIL" \
    --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID,GCP_LOCATION=$REGION,DRIVE_INBOX_FOLDER_ID=1xHPRq1MR2JmQN-f0fnVKOHS-edIsLZoB,DRIVE_ARCHIVE_FOLDER_ID=1jHz-UP3-YQ8a5bn__E6UkHo8ylv6rdjj,DRIVE_VAULT_ROOT_FOLDER_ID=1VKCaMxB639IyfwDHIvZPE4YzhZheTpuq,OAUTH_CLIENT_ID=$OAUTH_CLIENT_ID,OAUTH_CLIENT_SECRET=$OAUTH_CLIENT_SECRET,OAUTH_REFRESH_TOKEN=$OAUTH_REFRESH_TOKEN$TICKTICK_ENV_VARS$TELEGRAM_ENV_VARS" \
    --project "$PROJECT_ID" \
    --quiet

# Get the function URL
FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" \
    --gen2 \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --format='value(serviceConfig.uri)')

echo ""
echo "Function URL: $FUNCTION_URL"

# --- Step 3: Create Cloud Scheduler jobs ---
echo ""
echo ">>> Setting up Cloud Scheduler..."

# Helper function to create or replace a scheduler job
create_scheduler_job() {
    local JOB_NAME="$1"
    local JOB_SCHEDULE="$2"
    local JOB_BODY="$3"
    local JOB_DESC="$4"

    # Delete existing job if it exists (idempotent)
    gcloud scheduler jobs delete "$JOB_NAME" \
        --location "$REGION" \
        --project "$PROJECT_ID" \
        --quiet 2>/dev/null || true

    gcloud scheduler jobs create http "$JOB_NAME" \
        --schedule "$JOB_SCHEDULE" \
        --uri "$FUNCTION_URL" \
        --http-method POST \
        --location "$REGION" \
        --oidc-service-account-email "$SA_EMAIL" \
        --headers "Content-Type=application/json" \
        --message-body "$JOB_BODY" \
        --time-zone "$TIMEZONE" \
        --project "$PROJECT_ID" \
        --quiet

    echo "  $JOB_DESC"
}

# Job 1: Screenshot processing — every 5 minutes
create_scheduler_job \
    "${FUNCTION_NAME}-trigger" \
    "$SCHEDULE" \
    '{}' \
    "Screenshot processing: every 5 minutes"

# Job 2: Morning briefing — 8:00 AM
create_scheduler_job \
    "${FUNCTION_NAME}-morning-briefing" \
    "0 8 * * *" \
    '{"action": "morning_briefing"}' \
    "Morning briefing: 8:00 AM $TIMEZONE"

# Job 3: Midday nudge — 1:00 PM
create_scheduler_job \
    "${FUNCTION_NAME}-nudge" \
    "0 13 * * *" \
    '{"action": "nudge"}' \
    "Midday nudge: 1:00 PM $TIMEZONE"

# Job 4: Evening review — 9:00 PM
create_scheduler_job \
    "${FUNCTION_NAME}-evening-review" \
    "0 21 * * *" \
    '{"action": "evening_review"}' \
    "Evening review: 9:00 PM $TIMEZONE"

echo ""
echo "=== Deployment complete! ==="
echo ""
echo "Cloud Function:  $FUNCTION_URL"
echo "Scheduler jobs:"
echo "  - Screenshot processing: every 5 minutes"
echo "  - Morning briefing:      8:00 AM $TIMEZONE"
echo "  - Midday nudge:          1:00 PM $TIMEZONE"
echo "  - Evening review:        9:00 PM $TIMEZONE"
echo ""
echo "To test manually:"
echo "  # Process screenshots"
echo "  curl -X POST $FUNCTION_URL -H \"Authorization: bearer \$(gcloud auth print-identity-token)\""
echo ""
echo "  # Morning briefing"
echo "  curl -X POST $FUNCTION_URL -H \"Authorization: bearer \$(gcloud auth print-identity-token)\" -H 'Content-Type: application/json' -d '{\"action\": \"morning_briefing\"}'"
echo ""
echo "  # Midday nudge"
echo "  curl -X POST $FUNCTION_URL -H \"Authorization: bearer \$(gcloud auth print-identity-token)\" -H 'Content-Type: application/json' -d '{\"action\": \"nudge\"}'"
echo ""
echo "  # Evening review"
echo "  curl -X POST $FUNCTION_URL -H \"Authorization: bearer \$(gcloud auth print-identity-token)\" -H 'Content-Type: application/json' -d '{\"action\": \"evening_review\"}'"
echo ""
echo "To view logs:"
echo "  gcloud functions logs read $FUNCTION_NAME --gen2 --region $REGION --project $PROJECT_ID"

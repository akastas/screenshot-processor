"""
Screenshot Processor — Cloud Function Entry Point
HTTP-triggered function called by Cloud Scheduler.
Handles both screenshot processing (every 5 min) and proactive messaging (scheduled).
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import date

import functions_framework

import drive_ops
import gemini_analyzer
import markdown_router
import telegram_bot
import dashboard_scanner
import proactive_engine
from config import (
    DRIVE_INBOX_FOLDER_ID,
    DRIVE_ARCHIVE_FOLDER_ID,
    ROUTE_MAP,
)

# Configure logging to write to stdout (required for Cloud Run / gen2 functions)
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# Max screenshots to process per invocation (avoids Cloud Function timeout)
BATCH_SIZE = 15


@functions_framework.http
def process_screenshots(request):
    """
    Cloud Function entry point (HTTP trigger).
    Routes to the correct handler based on the 'action' field in the request body.

    Actions:
      - (default / no action): Process inbox screenshots
      - "morning_briefing": Scan dashboard and send morning briefing via Telegram
      - "nudge": Scan dashboard and send midday nudge via Telegram
      - "evening_review": Scan dashboard and send evening review via Telegram
    """
    # Parse action from request body
    action = ""
    try:
        body = request.get_json(silent=True) or {}
        action = body.get("action", "")
    except Exception:
        pass

    if action == "morning_briefing":
        return _handle_morning_briefing()
    elif action == "nudge":
        return _handle_nudge()
    elif action == "evening_review":
        return _handle_evening_review()
    else:
        return _handle_process_screenshots()


def _handle_process_screenshots():
    """Original screenshot processing logic."""
    print("=== Screenshot Processor triggered ===", flush=True)
    results = []
    errors = []

    try:
        # 1. List all processable files in inbox (images + text)
        files = drive_ops.list_inbox_files(DRIVE_INBOX_FOLDER_ID)
        if not files:
            print("No files found in inbox.", flush=True)
            return json.dumps({"status": "ok", "message": "No files to process"}), 200

        total_found = len(files)
        batch = files[:BATCH_SIZE]
        print(f"Found {total_found} image(s), processing batch of {len(batch)}", flush=True)

        # 2. Process each image (batched)
        for file_info in batch:
            file_id = file_info["id"]
            filename = file_info["name"]
            mime_type = file_info.get("mimeType", "image/png")
            file_type = file_info.get("file_type", "image")

            try:
                result = _process_single(file_id, filename, mime_type, file_type)
                results.append(result)
            except Exception as e:
                error_msg = f"Error processing {filename}: {str(e)}"
                print(f"ERROR: {error_msg}", flush=True)
                print(traceback.format_exc(), flush=True)
                errors.append(error_msg)

    except Exception as e:
        print(f"FATAL ERROR: {traceback.format_exc()}", flush=True)
        return json.dumps({"status": "error", "error": str(e)}), 500

    # 3. Notify via Telegram if files were processed
    if results and telegram_bot.is_configured():
        try:
            telegram_bot.send_processing_notification(results)
        except Exception as e:
            print(f"Telegram notification failed: {e}", flush=True)

    # 4. Summary
    summary = {
        "status": "ok",
        "processed": len(results),
        "errors": len(errors),
        "results": results,
        "error_details": errors,
    }
    print(f"=== Done. Processed: {len(results)}, Errors: {len(errors)} ===", flush=True)
    return json.dumps(summary, ensure_ascii=False), 200


# ---------------------------------------------------------------------------
# Proactive handlers
# ---------------------------------------------------------------------------
def _handle_morning_briefing():
    """Scan the dashboard and send a morning briefing via Telegram."""
    print("=== Morning Briefing triggered ===", flush=True)

    if not telegram_bot.is_configured():
        msg = "Telegram not configured — skipping morning briefing"
        print(msg, flush=True)
        return json.dumps({"status": "skipped", "reason": msg}), 200

    try:
        # 1. Scan the full dashboard
        dashboard = dashboard_scanner.full_scan()

        # 2. Generate briefing with Gemini
        briefing = proactive_engine.generate_morning_briefing(dashboard)

        # 3. Send via Telegram
        sent = telegram_bot.send_morning_briefing(briefing)

        result = {
            "status": "ok",
            "action": "morning_briefing",
            "sent": sent,
            "briefing": briefing,
        }
        print(f"=== Morning briefing {'sent' if sent else 'failed'} ===", flush=True)
        return json.dumps(result, ensure_ascii=False), 200

    except Exception as e:
        print(f"Morning briefing ERROR: {traceback.format_exc()}", flush=True)
        return json.dumps({"status": "error", "action": "morning_briefing", "error": str(e)}), 500


def _handle_nudge():
    """Scan the dashboard and send a midday nudge via Telegram."""
    print("=== Midday Nudge triggered ===", flush=True)

    if not telegram_bot.is_configured():
        msg = "Telegram not configured — skipping nudge"
        print(msg, flush=True)
        return json.dumps({"status": "skipped", "reason": msg}), 200

    try:
        dashboard = dashboard_scanner.full_scan()
        nudge = proactive_engine.generate_nudge(dashboard)
        sent = telegram_bot.send_nudge(nudge)

        result = {
            "status": "ok",
            "action": "nudge",
            "sent": sent,
            "nudge": nudge,
        }
        print(f"=== Nudge {'sent' if sent else 'failed'} ===", flush=True)
        return json.dumps(result, ensure_ascii=False), 200

    except Exception as e:
        print(f"Nudge ERROR: {traceback.format_exc()}", flush=True)
        return json.dumps({"status": "error", "action": "nudge", "error": str(e)}), 500


def _handle_evening_review():
    """Scan the dashboard and send an evening review via Telegram."""
    print("=== Evening Review triggered ===", flush=True)

    if not telegram_bot.is_configured():
        msg = "Telegram not configured — skipping evening review"
        print(msg, flush=True)
        return json.dumps({"status": "skipped", "reason": msg}), 200

    try:
        dashboard = dashboard_scanner.full_scan()
        review = proactive_engine.generate_evening_review(dashboard)

        # Format and send
        lines = []
        review_text = review.get("review", "")
        if review_text:
            lines.append(f"*Evening Review*\n{review_text}")
            lines.append("")

        pending = review.get("still_pending", [])
        if pending:
            lines.append("*Still pending*")
            for p in pending:
                lines.append(f"• {p}")
            lines.append("")

        preview = review.get("tomorrow_preview", [])
        if preview:
            lines.append("*Coming up*")
            for t in preview:
                lines.append(f"📅 {t}")
            lines.append("")

        goodnight = review.get("goodnight", "Good night!")
        lines.append(f"_{goodnight}_")

        sent = telegram_bot.send_message("\n".join(lines))

        result = {
            "status": "ok",
            "action": "evening_review",
            "sent": sent,
            "review": review,
        }
        print(f"=== Evening review {'sent' if sent else 'failed'} ===", flush=True)
        return json.dumps(result, ensure_ascii=False), 200

    except Exception as e:
        print(f"Evening review ERROR: {traceback.format_exc()}", flush=True)
        return json.dumps({"status": "error", "action": "evening_review", "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Screenshot processing (unchanged)
# ---------------------------------------------------------------------------
def _process_single(file_id: str, filename: str, mime_type: str, file_type: str = "image") -> dict:
    """
    Process a single file end-to-end:
    download → analyze → route → archive
    """
    print(f"--- Processing: {filename} ({file_type}) ---", flush=True)

    if file_type == "text":
        # Text file path
        text_content = drive_ops.read_md_file(file_id)
        print(f"Read {filename} ({len(text_content)} chars)", flush=True)

        # Analyze with Gemini (text prompt)
        analysis = gemini_analyzer.analyze_text(text_content)
        items = analysis.get("items", [])
        item_types = [i.get("type", "?") for i in items]
        print(f"Analysis: {analysis.get('summary', '')} | Items: {item_types}", flush=True)

        # Write daily snippet if present
        daily_snippet = analysis.get("daily_snippet", "")
        if daily_snippet:
            today = date.today()
            daily_note_id = drive_ops.find_or_create_daily_note(today)
            snippet_block = f"- {daily_snippet}\n  - _Source: {filename}_\n"
            try:
                drive_ops.append_to_md(daily_note_id, snippet_block, under_heading="## Notes")
                print(f"Added daily snippet to daily note", flush=True)
            except Exception as e:
                print(f"Failed to write daily snippet: {e}", flush=True)
    else:
        # Image file path (original behavior)
        image_bytes = drive_ops.download_image(file_id)
        print(f"Downloaded {filename} ({len(image_bytes)} bytes)", flush=True)

        analysis = gemini_analyzer.analyze_image(image_bytes, mime_type)
        items = analysis.get("items", [])
        item_types = [i.get("type", "?") for i in items]
        print(f"Analysis: {analysis.get('summary', '')} | Items: {item_types}", flush=True)

    # 3. Route items to Obsidian vault files (also handles TickTick + bookings)
    today = date.today()
    counts = markdown_router.route_items(analysis, filename, today)
    print(f"Routed: {counts}", flush=True)

    # 4. Create analysis record in archive
    analysis_file_id = markdown_router.create_analysis_record(
        analysis, filename, DRIVE_ARCHIVE_FOLDER_ID
    )

    # 5. Rename the file with a descriptive name
    suggested = analysis.get("filename_suggestion", "processed")
    ext = filename.rsplit(".", 1)[-1] if "." in filename else ("md" if file_type == "text" else "png")
    new_name = f"{today.isoformat()}-{suggested}.{ext}"
    drive_ops.rename_file(file_id, new_name)

    # 6. Move original file to archive
    drive_ops.move_file(file_id, DRIVE_ARCHIVE_FOLDER_ID)

    result = {
        "original_name": filename,
        "new_name": new_name,
        "file_type": file_type,
        "summary": analysis.get("summary", ""),
        "items_routed": counts,
    }
    print(f"--- Done: {filename} → {new_name} ---", flush=True)
    return result

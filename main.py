"""
Screenshot Processor — Cloud Function Entry Point
HTTP-triggered function called by Cloud Scheduler every 5 minutes.
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
    Processes all pending screenshots in the inbox folder.
    """
    print("=== Screenshot Processor triggered ===", flush=True)
    results = []
    errors = []

    try:
        # 1. List images in inbox
        images = drive_ops.list_images(DRIVE_INBOX_FOLDER_ID)
        if not images:
            print("No images found in inbox.", flush=True)
            return json.dumps({"status": "ok", "message": "No images to process"}), 200

        total_found = len(images)
        batch = images[:BATCH_SIZE]
        print(f"Found {total_found} image(s), processing batch of {len(batch)}", flush=True)

        # 2. Process each image (batched)
        for image_info in batch:
            file_id = image_info["id"]
            filename = image_info["name"]
            mime_type = image_info.get("mimeType", "image/png")

            try:
                result = _process_single(file_id, filename, mime_type)
                results.append(result)
            except Exception as e:
                error_msg = f"Error processing {filename}: {str(e)}"
                print(f"ERROR: {error_msg}", flush=True)
                print(traceback.format_exc(), flush=True)
                errors.append(error_msg)

    except Exception as e:
        print(f"FATAL ERROR: {traceback.format_exc()}", flush=True)
        return json.dumps({"status": "error", "error": str(e)}), 500

    # 3. Summary
    summary = {
        "status": "ok",
        "processed": len(results),
        "errors": len(errors),
        "results": results,
        "error_details": errors,
    }
    print(f"=== Done. Processed: {len(results)}, Errors: {len(errors)} ===", flush=True)
    return json.dumps(summary, ensure_ascii=False), 200


def _process_single(file_id: str, filename: str, mime_type: str) -> dict:
    """
    Process a single screenshot end-to-end:
    download → analyze → route → archive
    """
    print(f"--- Processing: {filename} ---", flush=True)

    # 1. Download image
    image_bytes = drive_ops.download_image(file_id)
    print(f"Downloaded {filename} ({len(image_bytes)} bytes)", flush=True)

    # 2. Analyze with Gemini
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

    # 5. Rename the screenshot with a descriptive name
    suggested = analysis.get("filename_suggestion", "screenshot")
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "png"
    new_name = f"{today.isoformat()}-{suggested}.{ext}"
    drive_ops.rename_file(file_id, new_name)

    # 6. Move original screenshot to archive
    drive_ops.move_file(file_id, DRIVE_ARCHIVE_FOLDER_ID)

    result = {
        "original_name": filename,
        "new_name": new_name,
        "summary": analysis.get("summary", ""),
        "items_routed": counts,
    }
    print(f"--- Done: {filename} → {new_name} ---", flush=True)
    return result


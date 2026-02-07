"""
Screenshot Processor — Cloud Function Entry Point
HTTP-triggered function called by Cloud Scheduler every 5 minutes.
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import date

import functions_framework

import drive_ops
import gemini_analyzer
import markdown_router
import ticktick_client
from config import (
    DRIVE_INBOX_FOLDER_ID,
    DRIVE_ARCHIVE_FOLDER_ID,
    ROUTE_MAP,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@functions_framework.http
def process_screenshots(request):
    """
    Cloud Function entry point (HTTP trigger).
    Processes all pending screenshots in the inbox folder.
    """
    logger.info("=== Screenshot Processor triggered ===")
    results = []
    errors = []

    try:
        # 1. List images in inbox
        images = drive_ops.list_images(DRIVE_INBOX_FOLDER_ID)
        if not images:
            logger.info("No images found in inbox. Nothing to do.")
            return json.dumps({"status": "ok", "message": "No images to process"}), 200

        logger.info("Found %d image(s) to process", len(images))

        # 2. Process each image
        for image_info in images:
            file_id = image_info["id"]
            filename = image_info["name"]
            mime_type = image_info.get("mimeType", "image/png")

            try:
                result = _process_single(file_id, filename, mime_type)
                results.append(result)
            except Exception as e:
                error_msg = f"Error processing {filename}: {str(e)}"
                logger.error(error_msg)
                logger.error(traceback.format_exc())
                errors.append(error_msg)

    except Exception as e:
        logger.error("Fatal error: %s", traceback.format_exc())
        return json.dumps({"status": "error", "error": str(e)}), 500

    # 3. Summary
    summary = {
        "status": "ok",
        "processed": len(results),
        "errors": len(errors),
        "results": results,
        "error_details": errors,
    }
    logger.info("=== Done. Processed: %d, Errors: %d ===", len(results), len(errors))
    return json.dumps(summary, ensure_ascii=False), 200


def _process_single(file_id: str, filename: str, mime_type: str) -> dict:
    """
    Process a single screenshot end-to-end:
    download → analyze → route → archive
    """
    logger.info("--- Processing: %s ---", filename)

    # 1. Download image
    image_bytes = drive_ops.download_image(file_id)
    logger.info("Downloaded %s (%d bytes)", filename, len(image_bytes))

    # 2. Analyze with Gemini
    analysis = gemini_analyzer.analyze_image(image_bytes, mime_type)
    logger.info("Analysis: %s", analysis.get("summary", ""))

    # 3. Route items to Obsidian vault files
    today = date.today()
    counts = markdown_router.route_items(analysis, filename, today)

    # 4. Create TickTick tasks for TASK items
    ticktick_results = []
    task_items = [item for item in analysis.get("items", []) if item.get("type") == "TASK"]
    if task_items:
        try:
            ticktick_results = ticktick_client.create_tasks_from_items(
                analysis["items"], filename
            )
        except Exception as e:
            logger.error("TickTick integration failed: %s", e)

    # 5. Create analysis record in archive
    analysis_file_id = markdown_router.create_analysis_record(
        analysis, filename, DRIVE_ARCHIVE_FOLDER_ID
    )

    # 6. Rename the screenshot with a descriptive name
    suggested = analysis.get("filename_suggestion", "screenshot")
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "png"
    new_name = f"{today.isoformat()}-{suggested}.{ext}"
    drive_ops.rename_file(file_id, new_name)

    # 7. Move original screenshot to archive
    drive_ops.move_file(file_id, DRIVE_ARCHIVE_FOLDER_ID)

    result = {
        "original_name": filename,
        "new_name": new_name,
        "summary": analysis.get("summary", ""),
        "items_routed": counts,
        "ticktick_tasks_created": len(ticktick_results),
    }
    logger.info("--- Done: %s → %s ---", filename, new_name)
    return result

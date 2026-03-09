from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime

from .logging_config import get_logger
from .message_builder import build_messages
from .pdf_preprocessor import pdf_to_images
from .system_prompt import WRITE_SLIDE_XML_TOOL
from .token_estimator import estimate_tokens

logger = get_logger("dry_run")


def run_dry(
    pdf_path: str,
    dpi: int,
    enable_animations: bool,
    model_name: str,
    batch_size: int,
) -> str:
    """Execute dry-run: prepare everything before the API call and export artifacts."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = f"dry-run-{timestamp}"
    pages_dir = os.path.join(output_dir, "pages")
    os.makedirs(pages_dir, exist_ok=True)

    logger.info("Dry-run output directory: %s", output_dir)

    # Step 1: PDF preprocessing
    pages = pdf_to_images(pdf_path, dpi=dpi)

    for img_bytes, meta in pages:
        page_num = meta["page_num"]
        img_path = os.path.join(pages_dir, f"page_{page_num:03d}.png")
        with open(img_path, "wb") as f:
            f.write(img_bytes)

    # Step 2: Build messages
    logger.info("Building messages...")
    messages = build_messages(pages, enable_animations=enable_animations)

    # Export lightweight messages (image URLs replaced with file paths)
    messages_light = _strip_base64(messages, pages_dir)
    with open(os.path.join(output_dir, "messages.json"), "w") as f:
        json.dump(messages_light, f, ensure_ascii=False, indent=2)

    # Export full messages (with base64, usable for direct API calls)
    with open(os.path.join(output_dir, "messages_full.json"), "w") as f:
        json.dump(messages, f, ensure_ascii=False)
    logger.info("Messages exported")

    # Export tools and system prompt
    with open(os.path.join(output_dir, "tools.json"), "w") as f:
        json.dump([WRITE_SLIDE_XML_TOOL], f, indent=2)
    with open(os.path.join(output_dir, "system_prompt.txt"), "w") as f:
        f.write(messages[0]["content"])

    # Step 3: Token estimation
    logger.info("Estimating tokens...")
    token_est = estimate_tokens(messages, model=model_name)
    with open(os.path.join(output_dir, "token_estimate.json"), "w") as f:
        json.dump(token_est, f, indent=2)

    # Export metadata
    metadata = {
        "timestamp": datetime.now(UTC).isoformat(),
        "pdf_path": os.path.abspath(pdf_path),
        "pdf_pages": len(pages),
        "dpi": dpi,
        "enable_animations": enable_animations,
        "model": model_name,
        "batch_size": batch_size,
        "batches": math.ceil(len(pages) / batch_size),
        "slide_width_pt": pages[0][1]["width_pt"],
        "slide_height_pt": pages[0][1]["height_pt"],
        "token_estimate": token_est,
    }
    with open(os.path.join(output_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    # Print summary
    logger.info("=" * 60)
    logger.info("DRY-RUN SUMMARY")
    logger.info("=" * 60)
    logger.info("  PDF:              %s", pdf_path)
    logger.info("  Pages:            %d", len(pages))
    logger.info(
        "  Slide size:       %.0fpt × %.0fpt",
        pages[0][1]["width_pt"],
        pages[0][1]["height_pt"],
    )
    logger.info("  DPI:              %d", dpi)
    logger.info(
        "  Animations:       %s",
        "enabled" if enable_animations else "disabled",
    )
    logger.info("  Model:            %s", model_name)
    logger.info("  Batches:          %d", metadata["batches"])
    logger.info("-" * 60)
    logger.info("  Text tokens:      %s", f"{token_est['text_tokens']:,}")
    logger.info(
        "  Image tokens:     %s (%d images)",
        f"{token_est['image_tokens']:,}",
        token_est["image_count"],
    )
    logger.info(
        "  Total input:      %s tokens",
        f"{token_est['total_input_tokens']:,}",
    )
    logger.info(
        "  Est. output:      %s tokens",
        f"{token_est['estimated_output_tokens']:,}",
    )
    logger.info(
        "  Est. total:       %s tokens",
        f"{token_est['estimated_total_tokens']:,}",
    )
    logger.info(
        "  Est. cost:        $%.4f",
        token_est["estimated_cost_usd"]["total_cost_usd"],
    )
    logger.info("=" * 60)
    logger.info("  Output dir:       %s/", output_dir)
    logger.info("=" * 60)

    return output_dir


def _strip_base64(messages: list[dict], pages_dir: str) -> list[dict]:
    """Create a copy of messages with base64 images replaced by file paths."""
    import copy

    result = copy.deepcopy(messages)
    img_idx = 0
    for msg in result:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if part.get("type") == "image_url":
                part["image_url"]["url"] = os.path.join(
                    pages_dir, f"page_{img_idx:03d}.png"
                )
                img_idx += 1
    return result

"""Dry-run mode: prepare artifacts without calling the LLM API."""

from __future__ import annotations

import math
import os
from datetime import UTC, datetime

from .artifacts import ArtifactStore
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
    prompt_lang: str = "en",
    reasoning_effort: str = "medium",
) -> str:
    """Execute dry-run: prepare everything before the API call and export artifacts."""
    store = ArtifactStore(pdf_path=pdf_path, dry_run=True)

    store.save_run_params({
        "pdf": os.path.abspath(pdf_path),
        "dpi": dpi,
        "enable_animations": enable_animations,
        "model_name": model_name,
        "batch_size": batch_size,
        "prompt_lang": prompt_lang,
        "reasoning_effort": reasoning_effort,
        "dry_run": True,
    })

    # Step 1: PDF preprocessing
    pages = pdf_to_images(pdf_path, dpi=dpi)
    store.save_page_images(pages)

    # Step 2: Build messages
    logger.info("Building messages...")
    messages = build_messages(pages, enable_animations=enable_animations, prompt_lang=prompt_lang)
    store.save_messages(messages)
    store.save_system_prompt(messages[0]["content"])
    store.save_tools([WRITE_SLIDE_XML_TOOL])

    # Step 3: Token estimation
    logger.info("Estimating tokens...")
    token_est = estimate_tokens(messages, model=model_name, reasoning_effort=reasoning_effort)
    store.save_token_estimate(token_est)

    # Export metadata
    store.save_metadata({
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
        "estimated_response_time_seconds": token_est["estimated_response_time_seconds"],
        "assumed_output_tps": token_est["assumed_output_tps"],
    })

    # Print summary
    cost_info = token_est["estimated_cost_usd"]
    assert isinstance(cost_info, dict)

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
    logger.info("  Batches:          %d", math.ceil(len(pages) / batch_size))
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
    logger.info("  Est. cost:        $%.4f", cost_info["total_cost_usd"])
    logger.info("-" * 60)
    est_time = token_est["estimated_response_time_seconds"]
    logger.info(
        "  Est. response:    ~%.0fs (~%.1f min) at %.0f tok/s",
        est_time,
        est_time / 60,
        token_est["assumed_output_tps"],
    )
    logger.info("=" * 60)
    logger.info("  Output dir:       %s/", store.root)
    logger.info("=" * 60)

    return store.root

"""Dry-run mode: prepare artifacts without calling the LLM API."""

from __future__ import annotations

import math
import os
from datetime import UTC, datetime

from .artifacts import ArtifactStore
from .logging_config import get_logger
from .message_builder import build_messages, get_system_prompt_text
from .pdf_preprocessor import images_from_folder, pdf_to_images
from .system_prompt import WRITE_SLIDE_XML_TOOL, WRITE_SLIDE_XML_TOOL_ANTHROPIC
from .token_estimator import estimate_tokens, recommend_batch_size

logger = get_logger("dry_run")


def run_dry(
    pdf_path: str,
    dpi: int,
    enable_animations: bool,
    model_name: str,
    max_pages: int = 0,
    batch_size: int = 0,
    prompt_lang: str = "en",
    reasoning_effort: str = "medium",
    provider: str = "openai",
    page_indices: list[int] | None = None,
    run_params: dict | None = None,
    output_tps: float = 0,
) -> str:
    """Execute dry-run: prepare everything before the API call and export artifacts.

    ``run_params`` should contain only the CLI arguments explicitly provided by
    the user.  If *None*, a full parameter dict is saved for backward compat.
    ``output_tps`` overrides the assumed output tokens/second (0 = module default).
    """
    is_folder = os.path.isdir(pdf_path)
    store = ArtifactStore(pdf_path=pdf_path, dry_run=True)
    if not is_folder:
        store.copy_input(pdf_path)

    # Auto-calculate batch size if not specified (0 = auto)
    batch_size_auto = batch_size <= 0
    if batch_size_auto:
        batch_size = recommend_batch_size(reasoning_effort=reasoning_effort, output_tps=output_tps)
        logger.info("Auto batch size: %d pages (gateway timeout 600s, reasoning=%s)", batch_size, reasoning_effort)

    if run_params is not None:
        store.save_run_params(run_params)
    else:
        store.save_run_params({
            "pdf": os.path.abspath(pdf_path),
            "api_provider": provider,
            "dpi": dpi,
            "enable_animations": enable_animations,
            "model_name": model_name,
            "max_pages": max_pages,
            "page_indices": page_indices,
            "batch_size": batch_size if not batch_size_auto else 0,
            "prompt_lang": prompt_lang,
            "reasoning_effort": reasoning_effort,
            "dry_run": True,
        })

    # Step 1: Load images (from PDF or folder)
    if is_folder:
        all_pages = images_from_folder(pdf_path)
    else:
        all_pages = pdf_to_images(pdf_path, dpi=dpi)
    if page_indices is not None:
        pages = [p for p in all_pages if p[1]["page_num"] in page_indices]
    elif max_pages > 0:
        pages = all_pages[:max_pages]
    else:
        pages = all_pages
    store.save_page_images(pages)

    n_pages = len(pages)
    n_batches = math.ceil(n_pages / batch_size) if batch_size > 0 else 1
    store.set_batch_count(n_batches)

    # Step 2: Build and save messages per batch
    logger.info("Building messages...")
    sys_prompt_text = get_system_prompt_text(enable_animations, prompt_lang)
    store.save_system_prompt(sys_prompt_text)
    tools_to_save = [WRITE_SLIDE_XML_TOOL_ANTHROPIC] if provider == "anthropic" else [WRITE_SLIDE_XML_TOOL]
    store.save_tools(tools_to_save)

    for batch_idx in range(n_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, n_pages)
        batch_pages = pages[start:end]
        batch_msgs = build_messages(
            batch_pages, enable_animations=enable_animations,
            prompt_lang=prompt_lang, provider=provider,
        )
        store.save_messages(batch_msgs, batch_idx=batch_idx)

    # Step 3: Token estimation (based on first batch, not all pages)
    logger.info("Estimating tokens...")
    first_batch_pages = pages[:batch_size] if n_pages > batch_size else pages
    batch_messages = build_messages(
        first_batch_pages, enable_animations=enable_animations,
        prompt_lang=prompt_lang, provider=provider,
    )
    token_est = estimate_tokens(
        batch_messages, model=model_name, reasoning_effort=reasoning_effort,
        dpi=dpi, output_tps=output_tps,
    )
    store.save_token_estimate(token_est)

    # Estimate totals across all batches
    per_batch_input = token_est["total_input_tokens"]
    per_batch_output = token_est["estimated_output_tokens"]
    per_batch_time = token_est["estimated_response_time_seconds"]
    total_input = per_batch_input * n_batches
    total_output = per_batch_output * n_batches
    total_time = per_batch_time * n_batches

    # Export metadata
    store.save_metadata({
        "timestamp": datetime.now(UTC).isoformat(),
        "runtime_params": {
            "pdf_path": os.path.abspath(pdf_path),
            "api_provider": provider,
            "dpi": dpi,
            "enable_animations": enable_animations,
            "model": model_name,
            "reasoning_effort": reasoning_effort,
            "prompt_lang": prompt_lang,
            "max_pages": max_pages,
            "page_indices": page_indices,
            "batch_size": batch_size,
            "batch_size_auto": batch_size_auto,
            "recommended_batch_size": recommend_batch_size(reasoning_effort=reasoning_effort, output_tps=output_tps),
            "gateway_timeout_seconds": 600,
        },
        "pdf_pages": n_pages,
        "batches": n_batches,
        "slide_width_pt": pages[0][1]["width_pt"],
        "slide_height_pt": pages[0][1]["height_pt"],
        "token_estimate_per_batch": token_est,
        "total_input_tokens": total_input,
        "total_estimated_output_tokens": total_output,
        "total_estimated_tokens": total_input + total_output,
        "total_estimated_response_seconds": round(total_time, 1),
        "assumed_output_tps": token_est["assumed_output_tps"],
    })

    # Print summary
    cost_info = token_est["estimated_cost_usd"]
    assert isinstance(cost_info, dict)

    logger.info("=" * 60)
    logger.info("DRY-RUN SUMMARY")
    logger.info("=" * 60)
    logger.info("  Input:            %s%s", pdf_path, " (folder)" if is_folder else "")
    logger.info("  Pages:            %d", len(pages))
    logger.info(
        "  Slide size:       %.0fpt × %.0fpt",
        pages[0][1]["width_pt"],
        pages[0][1]["height_pt"],
    )
    if not is_folder:
        logger.info("  DPI:              %d", dpi)
    logger.info(
        "  Animations:       %s",
        "enabled" if enable_animations else "disabled",
    )
    logger.info("  Model:            %s", model_name)
    logger.info("  Batch size:       %d (auto)" if batch_size_auto else "  Batch size:       %d", batch_size)
    logger.info("  Batches:          %d", n_batches)
    logger.info("-" * 60)
    logger.info("  Per-batch estimate:")
    logger.info("    Text tokens:    %s", f"{token_est['text_tokens']:,}")
    logger.info(
        "    Image tokens:   %s (%d images)",
        f"{token_est['image_tokens']:,}",
        token_est["image_count"],
    )
    logger.info("    Input tokens:   %s", f"{per_batch_input:,}")
    logger.info("    Output tokens:  ~%s", f"{per_batch_output:,}")
    logger.info("    Response time:  ~%.0fs (~%.1f min)", per_batch_time, per_batch_time / 60)
    if n_batches > 1:
        logger.info("  Total estimate (%d batches):", n_batches)
        logger.info("    Input tokens:   %s", f"{total_input:,}")
        logger.info("    Output tokens:  ~%s", f"{total_output:,}")
        logger.info("    Total tokens:   ~%s", f"{total_input + total_output:,}")
        logger.info("    Response time:  ~%.0fs (~%.1f min)", total_time, total_time / 60)
    logger.info("  Est. cost:        $%.4f", cost_info["total_cost_usd"])
    logger.info("-" * 60)
    logger.info(
        "  Output TPS:       %.0f tok/s (reasoning=%s, ×%.1f)",
        token_est["assumed_output_tps"],
        reasoning_effort,
        token_est["reasoning_multiplier"],
    )
    logger.info("=" * 60)
    logger.info("  Output dir:       %s/", store.root)
    logger.info("=" * 60)

    return store.root

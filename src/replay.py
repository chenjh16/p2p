"""Replay a previous run or dry-run using saved parameters from run_params.json."""

from __future__ import annotations

import json
import os
import sys
import time

from .logging_config import get_logger

logger = get_logger("replay")


def run_replay(source_dir: str) -> None:
    """Re-execute a previous run/dry-run using its saved run_params.json.

    Reads the parameters from ``source_dir/run_params.json``, resolves the
    input PDF (from the copy inside the artifact directory if the original is
    missing), and runs the full conversion or dry-run pipeline.  All new
    artifacts are saved under ``runs/replay-<name>-<timestamp>/``.
    """
    import contextlib

    from .artifacts import ArtifactStore
    from .message_builder import build_messages, get_system_prompt_text
    from .pdf_preprocessor import pdf_to_images, snap_slide_dimensions
    from .postprocessor import postprocess_raster_fills
    from .pptx_assembler import PPTXAssembler
    from .system_prompt import WRITE_SLIDE_XML_TOOL, WRITE_SLIDE_XML_TOOL_ANTHROPIC
    from .token_estimator import ASSUMED_OUTPUT_TPS, estimate_tokens, recommend_batch_size

    params_path = os.path.join(source_dir, "run_params.json")
    if not os.path.isfile(params_path):
        logger.error("run_params.json not found in %s", source_dir)
        sys.exit(1)

    with open(params_path, encoding="utf-8") as f:
        params = json.load(f)

    logger.info("Replaying from: %s", source_dir)
    logger.info("Original parameters: %s", json.dumps(params, indent=2))

    pdf_path = params.get("pdf", "")
    if not os.path.isfile(pdf_path):
        pdf_basename = os.path.basename(pdf_path)
        fallback = os.path.join(source_dir, pdf_basename)
        if os.path.isfile(fallback):
            logger.info("Original PDF not found at %s, using copy from %s", pdf_path, fallback)
            pdf_path = fallback
        else:
            logger.error("Cannot find input PDF: %s (also checked %s)", pdf_path, fallback)
            sys.exit(1)

    is_dry_run = params.get("dry_run", False)
    provider = params.get("api_provider", "openai")
    dpi = params.get("dpi", 192)
    enable_animations = params.get("enable_animations", False)
    model_name = params.get("model_name", "gpt-5.4")
    reasoning_effort = params.get("reasoning_effort", "medium")
    prompt_lang = params.get("prompt_lang", "en")
    batch_size = params.get("batch_size", 0)
    max_pages = params.get("max_pages", 5)
    page_indices = params.get("page_indices")
    skip_postprocess = params.get("skip_postprocess", False)

    if is_dry_run:
        from .dry_run import run_dry

        run_dry(
            pdf_path=pdf_path,
            dpi=dpi,
            enable_animations=enable_animations,
            model_name=model_name,
            max_pages=max_pages,
            batch_size=batch_size,
            prompt_lang=prompt_lang,
            reasoning_effort=reasoning_effort,
            provider=provider,
            page_indices=page_indices,
        )
        return

    # --- Full conversion replay ---
    if provider == "anthropic":
        from .api_client_anthropic import call_anthropic
    else:
        from .api_client import call_llm

    store = ArtifactStore(pdf_path=pdf_path, replay_of=source_dir)
    store.copy_input(pdf_path)

    if batch_size <= 0:
        batch_size = recommend_batch_size(reasoning_effort=reasoning_effort)
        logger.info("Auto batch size: %d pages (gateway timeout 600s, reasoning=%s)", batch_size, reasoning_effort)

    store.save_run_params({
        **params,
        "replay_of": os.path.abspath(source_dir),
    })

    t_start = time.time()

    all_pages = pdf_to_images(pdf_path, dpi=dpi)
    if page_indices is not None:
        pages = [p for p in all_pages if p[1]["page_num"] in page_indices]
    elif max_pages > 0:
        pages = all_pages[:max_pages]
    else:
        pages = all_pages
    store.save_page_images(pages)

    overlap = 2
    n_pages = len(pages)
    slide_xmls: dict[int, str] = {}
    t_api_total = 0.0

    if n_pages <= batch_size:
        batches = [(0, n_pages)]
    else:
        step = batch_size - overlap
        batches = []
        for start in range(0, n_pages, step):
            end = min(start + batch_size, n_pages)
            batches.append((start, end))
            if end >= n_pages:
                break

    n_batches = len(batches)
    logger.info("Replay: processing %d pages in %d batch(es)", n_pages, n_batches)

    total_input_tokens = 0
    total_output_tokens_est = 0
    total_est_response_seconds = 0.0
    batch_token_estimates: list[dict] = []

    for batch_idx, (start, end) in enumerate(batches):
        batch_pages = pages[start:end]
        batch_label = f"batch {batch_idx + 1}/{n_batches} (pages {start}-{end - 1})"
        logger.info("Building messages for %s", batch_label)

        messages = build_messages(
            batch_pages, enable_animations=enable_animations, prompt_lang=prompt_lang, provider=provider
        )

        if batch_idx == 0:
            store.save_messages(messages)
            sys_prompt_text = get_system_prompt_text(enable_animations, prompt_lang)
            store.save_system_prompt(sys_prompt_text)
            tools_to_save = [WRITE_SLIDE_XML_TOOL_ANTHROPIC] if provider == "anthropic" else [WRITE_SLIDE_XML_TOOL]
            store.save_tools(tools_to_save)

        token_est = estimate_tokens(messages, model=model_name, reasoning_effort=reasoning_effort, dpi=dpi)
        batch_token_estimates.append(token_est)
        total_input_tokens += token_est["total_input_tokens"]
        total_output_tokens_est += token_est["estimated_output_tokens"]
        total_est_response_seconds += token_est["estimated_response_time_seconds"]

        if batch_idx == 0:
            store.save_token_estimate(token_est)

        est_time = token_est["estimated_response_time_seconds"]
        logger.info(
            "Estimated response time for %s: ~%.0fs (~%.1f min) at %.0f tok/s",
            batch_label, est_time, est_time / 60, token_est["assumed_output_tps"],
        )

        stream_log = os.path.join(store.root, f"stream_batch{batch_idx}.log")
        logger.info("Calling LLM API for %s (%s)", batch_label, provider)
        t_api_start = time.time()

        if provider == "anthropic":
            sys_prompt_text = get_system_prompt_text(enable_animations, prompt_lang)
            result = call_anthropic(
                messages=messages,
                system_prompt=sys_prompt_text,
                api_key=params.get("api_key", os.getenv("ANTHROPIC_API_KEY", "")),
                api_base_url=params.get("api_base_url", os.getenv("ANTHROPIC_BASE_URL", "")),
                model_name=model_name,
                stream_log_path=stream_log,
                reasoning_effort=reasoning_effort,
                estimated_response_seconds=float(est_time),
            )
        else:
            result = call_llm(
                messages=messages,
                api_base_url=params.get("api_base_url", os.getenv("OPENAI_BASE_URL", "")),
                api_key=params.get("api_key", os.getenv("OPENAI_API_KEY", "")),
                model_name=model_name,
                stream_log_path=stream_log,
                reasoning_effort=reasoning_effort,
                estimated_response_seconds=float(est_time),
            )
        t_api_total += time.time() - t_api_start

        store.save_api_response(result.response_data)
        store.save_stream_chunks(result.raw_chunks)
        store.save_tool_calls(result.tool_calls_raw)
        store.save_reasoning(result.reasoning_text, batch_idx=batch_idx)
        store.save_content_text(result.content_text, batch_idx=batch_idx)

        batch_xmls = result.slide_xmls
        if not batch_xmls:
            logger.error("No slide XMLs received for %s", batch_label)
            continue

        logger.info("Received %d slide XMLs for %s", len(batch_xmls), batch_label)

        if n_batches > 1 and batch_idx > 0 and enable_animations:
            for page_num in range(start, min(start + overlap, end)):
                if page_num in batch_xmls:
                    slide_xmls[page_num] = batch_xmls[page_num]
        slide_xmls.update(batch_xmls)

    if not slide_xmls:
        logger.error("No slide XMLs received from the API")
        sys.exit(1)

    logger.info("Total slide XMLs collected: %d", len(slide_xmls))
    store.save_slide_xmls(slide_xmls)

    raw_w = pages[0][1]["width_pt"]
    raw_h = pages[0][1]["height_pt"]
    snap_w, snap_h, ratio_label = snap_slide_dimensions(raw_w, raw_h)
    logger.info("Slide dimensions: %.0f×%.0f pt (aspect ratio: %s)", snap_w, snap_h, ratio_label)

    output_name = params.get("output", "")
    if not output_name:
        base = os.path.splitext(os.path.basename(pdf_path))[0]
        output_name = f"{base}.pptx"

    assembler = PPTXAssembler(slide_width_pt=snap_w, slide_height_pt=snap_h)
    assembler.assemble(slide_xmls)

    if skip_postprocess:
        assembler.save(output_name)
    else:
        intermediate = output_name + ".tmp"
        assembler.save(intermediate)
        postprocess_raster_fills(
            pptx_path=intermediate,
            pdf_path=pdf_path,
            output_path=output_name,
            dpi=300,
        )
        with contextlib.suppress(OSError):
            os.remove(intermediate)

    store.copy_output(output_name)

    store.save_metadata({
        "replay_of": os.path.abspath(source_dir),
        "runtime_params": {
            "pdf_path": os.path.abspath(pdf_path),
            "output_pptx": os.path.abspath(output_name),
            "api_provider": provider,
            "model": model_name,
            "dpi": dpi,
            "enable_animations": enable_animations,
            "reasoning_effort": reasoning_effort,
            "prompt_lang": prompt_lang,
            "max_pages": max_pages,
            "page_indices": page_indices,
            "batch_size": batch_size,
            "skip_postprocess": skip_postprocess,
        },
        "pdf_pages": n_pages,
        "batches": n_batches,
        "pdf_width_pt": raw_w,
        "pdf_height_pt": raw_h,
        "slide_width_pt": snap_w,
        "slide_height_pt": snap_h,
        "aspect_ratio": ratio_label,
        "token_estimate_per_batch": batch_token_estimates,
        "total_input_tokens": total_input_tokens,
        "total_estimated_output_tokens": total_output_tokens_est,
        "total_estimated_tokens": total_input_tokens + total_output_tokens_est,
        "total_estimated_response_seconds": round(total_est_response_seconds, 1),
        "assumed_output_tps": ASSUMED_OUTPUT_TPS,
        "api_elapsed_seconds": t_api_total,
        "slides_received": len(slide_xmls),
    })

    t_total = time.time() - t_start
    file_size = os.path.getsize(output_name) / (1024 * 1024)
    logger.info("Replay complete: %s (%.1f MB)", output_name, file_size)
    logger.info(
        "Total time: %.1fs | API time: %.1fs (%.0f%%)",
        t_total, t_api_total, (t_api_total / t_total * 100) if t_total > 0 else 0,
    )
    logger.info("Artifacts saved to: %s/", store.root)

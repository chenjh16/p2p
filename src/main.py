"""Entry point for PDF-to-PPTX conversion via CLI."""

from __future__ import annotations

import argparse
import os
import sys
import time


def _parse_args_with_explicit(parser: argparse.ArgumentParser) -> tuple[argparse.Namespace, set[str]]:
    """Parse CLI args and track which ones were explicitly provided by the user.

    Returns the parsed namespace and a set of destination names that the user
    actually typed on the command line (as opposed to falling back to defaults).
    """
    args = parser.parse_args()
    explicit: set[str] = set()
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._HelpAction):  # noqa: SLF001
            continue
        dest = action.dest
        if action.option_strings:
            if any(tok in sys.argv[1:] for tok in action.option_strings):
                explicit.add(dest)
        else:
            explicit.add(dest)
    return args, explicit


def _print_progress(
    logger: object, slide_xmls: dict[int, str], total_pages: int, current_batch: int, total_batches: int
) -> None:
    """Print current conversion progress to help the user decide whether to continue."""
    import logging

    assert isinstance(logger, logging.Logger)
    logger.info("=" * 50)
    logger.info("PROGRESS: %d/%d slides collected so far", len(slide_xmls), total_pages)
    logger.info("  Completed batches: %d/%d", current_batch, total_batches)
    if slide_xmls:
        logger.info("  Slide pages received: %s", sorted(slide_xmls.keys()))
    logger.info("=" * 50)


def _parse_page_spec(spec: str) -> list[int]:
    """Parse a page specification string like '0,2,5-8' into a sorted list of page indices."""
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s.strip()), int(end_s.strip())
            pages.update(range(start, end + 1))
        else:
            pages.add(int(part))
    return sorted(pages)


def main() -> None:
    """Parse CLI args and run the full conversion or dry-run pipeline."""
    parser = argparse.ArgumentParser(
        description="Convert PDF slides to editable PPTX using multimodal LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("pdf", help="Input PDF file path")
    parser.add_argument("-o", "--output", default="", help="Output PPTX file path")

    # API provider selection
    parser.add_argument(
        "--api-provider",
        default=os.getenv("LLM_PROVIDER", "openai"),
        choices=["openai", "anthropic"],
        help="LLM API provider (default: $LLM_PROVIDER or openai)",
    )

    # API configuration (provider-agnostic)
    parser.add_argument(
        "--api-base-url",
        default="",
        help="API Base URL (default: $OPENAI_BASE_URL or $ANTHROPIC_BASE_URL)",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="API Key (default: $OPENAI_API_KEY or $ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--model-name",
        default="",
        help="Model name (default: gpt-5.4 for openai, claude-opus-4-6 for anthropic)",
    )

    # Processing options
    parser.add_argument(
        "--dpi",
        type=int,
        default=192,
        choices=[96, 144, 192, 288],
        help="Rendering DPI for LLM input: 96 (draft), 144 (standard), 192 (high, default), 288 (ultra)",
    )
    parser.add_argument(
        "--enable-animations",
        action="store_true",
        help="Enable animation/transition effects (default: off)",
    )
    parser.add_argument(
        "--reasoning-effort",
        default="medium",
        choices=["low", "medium", "high", "xhigh"],
        help="Reasoning effort for the model (default: medium)",
    )
    parser.add_argument(
        "--prompt-lang",
        default="en",
        choices=["en", "zh"],
        help="System prompt language: en=English, zh=Chinese (default: en)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="Maximum number of pages to convert (0=all, default: 5)",
    )
    parser.add_argument(
        "--pages",
        type=str,
        default="",
        help="Specific pages to convert, e.g. '0,2,5-8' (mutually exclusive with --max-pages)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="Batch size (0=auto based on gateway timeout, default: 0)",
    )
    parser.add_argument(
        "--output-tps",
        type=float,
        default=50.0,
        help="Assumed output tokens per second for time estimation (default: 50)",
    )
    parser.add_argument(
        "--skip-postprocess",
        action="store_true",
        help="Skip raster image post-processing (keep placeholders)",
    )

    # Modes
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry-run: prepare everything but don't call the API",
    )
    parser.add_argument(
        "--replay",
        type=str,
        default="",
        help="Replay a previous run/dry-run from its artifact directory (e.g. runs/run-example1-20260310-123615)",
    )
    parser.add_argument(
        "--continue-run",
        type=str,
        default="",
        dest="continue_run",
        help="Continue a previous incomplete run from its artifact directory, resuming from where it left off",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )

    args, explicit_args = _parse_args_with_explicit(parser)

    # Setup logging first
    from .logging_config import get_logger, setup_logging

    setup_logging(args.log_level)
    logger = get_logger("main")

    # Auto-detect provider from model name when not explicitly set
    provider = args.api_provider
    if "api_provider" not in explicit_args and args.model_name and args.model_name.startswith("claude"):
        provider = "anthropic"
        logger.info("Auto-detected provider: anthropic (from model name %s)", args.model_name)

    # Resolve provider-specific defaults
    if not args.api_key:
        if provider == "anthropic":
            args.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        else:
            args.api_key = os.getenv("OPENAI_API_KEY", "")
    if not args.api_base_url:
        if provider == "anthropic":
            args.api_base_url = os.getenv("ANTHROPIC_BASE_URL", "")
        else:
            args.api_base_url = os.getenv("OPENAI_BASE_URL", "")
    if not args.model_name:
        if provider == "anthropic":
            args.model_name = os.getenv("ANTHROPIC_MODEL_NAME", "claude-opus-4-6")
        else:
            args.model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-5.4")

    # --- Replay mode ---
    if args.replay:
        from .replay import run_replay

        run_replay(args.replay)
        return

    # --- Continue mode ---
    if args.continue_run:
        from .continue_run import run_continue

        run_continue(args.continue_run)
        return

    # When --pages is specified, ignore --max-pages
    if args.pages:
        args.max_pages = 0

    # Validate input
    if not os.path.isfile(args.pdf):
        logger.error("Input file not found: %s", args.pdf)
        sys.exit(1)

    if not args.output and not args.dry_run:
        base = os.path.splitext(os.path.basename(args.pdf))[0]
        args.output = f"{base}.pptx"

    logger.info("Starting PDF → PPTX conversion")
    logger.info("Input: %s", args.pdf)
    logger.info(
        "Options: provider=%s, dpi=%d, animations=%s, model=%s, reasoning=%s",
        provider,
        args.dpi,
        "on" if args.enable_animations else "off",
        args.model_name,
        args.reasoning_effort,
    )

    t_start = time.time()

    # --- Dry-run mode ---
    if args.dry_run:
        from .dry_run import run_dry

        page_indices = _parse_page_spec(args.pages) if args.pages else None
        dry_params: dict = {"pdf": os.path.abspath(args.pdf), "dry_run": True}
        _dry_map = {
            "api_provider": ("api_provider", provider),
            "api_base_url": ("api_base_url", args.api_base_url),
            "api_key": ("api_key", args.api_key),
            "model_name": ("model_name", args.model_name),
            "dpi": ("dpi", args.dpi),
            "enable_animations": ("enable_animations", args.enable_animations),
            "reasoning_effort": ("reasoning_effort", args.reasoning_effort),
            "prompt_lang": ("prompt_lang", args.prompt_lang),
            "max_pages": ("max_pages", args.max_pages),
            "pages": ("pages", args.pages),
            "batch_size": ("batch_size", args.batch_size),
            "output_tps": ("output_tps", args.output_tps),
            "log_level": ("log_level", args.log_level),
        }
        for dest, (key, val) in _dry_map.items():
            if dest in explicit_args:
                dry_params[key] = val
        run_dry(
            pdf_path=args.pdf,
            dpi=args.dpi,
            enable_animations=args.enable_animations,
            model_name=args.model_name,
            max_pages=args.max_pages,
            batch_size=args.batch_size,
            prompt_lang=args.prompt_lang,
            reasoning_effort=args.reasoning_effort,
            provider=provider,
            page_indices=page_indices,
            run_params=dry_params,
            output_tps=args.output_tps,
        )
        return

    # --- Full conversion ---
    import contextlib

    from .artifacts import ArtifactStore
    from .message_builder import build_messages, get_system_prompt_text
    from .pdf_preprocessor import pdf_to_images, snap_slide_dimensions
    from .postprocessor import postprocess_raster_fills
    from .pptx_assembler import PPTXAssembler
    from .system_prompt import WRITE_SLIDE_XML_TOOL, WRITE_SLIDE_XML_TOOL_ANTHROPIC
    from .token_estimator import ASSUMED_OUTPUT_TPS, estimate_tokens, recommend_batch_size

    if provider == "anthropic":
        from .api_client_anthropic import call_anthropic
    else:
        from .api_client import call_llm

    store = ArtifactStore(pdf_path=args.pdf)
    store.copy_input(args.pdf)

    # Auto-calculate batch size if not specified (0 = auto)
    if args.batch_size <= 0:
        batch_size = recommend_batch_size(reasoning_effort=args.reasoning_effort, output_tps=args.output_tps)
        logger.info("Auto batch size: %d pages (gateway timeout 600s, reasoning=%s)", batch_size, args.reasoning_effort)
    else:
        batch_size = args.batch_size

    page_indices = _parse_page_spec(args.pages) if args.pages else None

    run_params: dict = {"pdf": os.path.abspath(args.pdf)}
    _arg_map = {
        "output": ("output", os.path.abspath(args.output) if args.output else ""),
        "api_provider": ("api_provider", provider),
        "api_base_url": ("api_base_url", args.api_base_url),
        "model_name": ("model_name", args.model_name),
        "dpi": ("dpi", args.dpi),
        "enable_animations": ("enable_animations", args.enable_animations),
        "reasoning_effort": ("reasoning_effort", args.reasoning_effort),
        "prompt_lang": ("prompt_lang", args.prompt_lang),
        "max_pages": ("max_pages", args.max_pages),
        "pages": ("pages", args.pages),
        "batch_size": ("batch_size", args.batch_size),
        "output_tps": ("output_tps", args.output_tps),
        "skip_postprocess": ("skip_postprocess", args.skip_postprocess),
        "log_level": ("log_level", args.log_level),
    }
    for dest, (key, val) in _arg_map.items():
        if dest in explicit_args:
            run_params[key] = val
    store.save_run_params(run_params)

    # Step 1: PDF preprocessing
    all_pages = pdf_to_images(args.pdf, dpi=args.dpi)
    if page_indices is not None:
        pages = [p for p in all_pages if p[1]["page_num"] in page_indices]
    elif args.max_pages > 0:
        pages = all_pages[: args.max_pages]
    else:
        pages = all_pages
    store.save_page_images(pages)

    raw_w = pages[0][1]["width_pt"]
    raw_h = pages[0][1]["height_pt"]
    snap_w, snap_h, ratio_label = snap_slide_dimensions(raw_w, raw_h)

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
    logger.info("Processing %d pages in %d batch(es)", n_pages, n_batches)

    total_input_tokens = 0
    total_output_tokens_est = 0
    total_est_response_seconds = 0.0
    batch_token_estimates: list[dict] = []

    def _save_metadata(*, success: bool) -> None:
        store.save_metadata({
            "runtime_params": {
                "pdf_path": os.path.abspath(args.pdf),
                "output_pptx": os.path.abspath(args.output) if args.output else "",
                "api_provider": provider,
                "api_base_url": args.api_base_url,
                "model": args.model_name,
                "dpi": args.dpi,
                "enable_animations": args.enable_animations,
                "reasoning_effort": args.reasoning_effort,
                "prompt_lang": args.prompt_lang,
                "max_pages": args.max_pages,
                "pages": args.pages,
                "page_indices": page_indices,
                "batch_size": batch_size,
                "batch_size_requested": args.batch_size,
                "batch_size_auto": args.batch_size <= 0,
                "recommended_batch_size": recommend_batch_size(
                    reasoning_effort=args.reasoning_effort, output_tps=args.output_tps,
                ),
                "gateway_timeout_seconds": 600,
                "skip_postprocess": args.skip_postprocess,
                "output_tps": args.output_tps,
            },
            "success": success,
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
            "assumed_output_tps": args.output_tps if args.output_tps > 0 else ASSUMED_OUTPUT_TPS,
            "api_elapsed_seconds": t_api_total,
            "slides_received": len(slide_xmls),
        })

    for batch_idx, (start, end) in enumerate(batches):
        batch_pages = pages[start:end]
        batch_label = f"batch {batch_idx + 1}/{n_batches} (pages {start}-{end - 1})"
        logger.info("Building messages for %s", batch_label)

        messages = build_messages(
            batch_pages, enable_animations=args.enable_animations, prompt_lang=args.prompt_lang, provider=provider
        )

        if batch_idx == 0:
            store.save_messages(messages)
            sys_prompt_text = get_system_prompt_text(args.enable_animations, args.prompt_lang)
            store.save_system_prompt(sys_prompt_text)
            tools_to_save = [WRITE_SLIDE_XML_TOOL_ANTHROPIC] if provider == "anthropic" else [WRITE_SLIDE_XML_TOOL]
            store.save_tools(tools_to_save)

        token_est = estimate_tokens(
            messages, model=args.model_name, reasoning_effort=args.reasoning_effort, dpi=args.dpi,
            output_tps=args.output_tps,
        )
        batch_token_estimates.append(token_est)
        total_input_tokens += token_est["total_input_tokens"]
        total_output_tokens_est += token_est["estimated_output_tokens"]
        total_est_response_seconds += token_est["estimated_response_time_seconds"]

        if batch_idx == 0:
            store.save_token_estimate(token_est)

        est_time = token_est["estimated_response_time_seconds"]
        logger.info(
            "Estimated response time for %s: ~%.0fs (~%.1f min) at %.0f tok/s",
            batch_label,
            est_time,
            est_time / 60,
            token_est["assumed_output_tps"],
        )

        stream_log = os.path.join(store.root, f"stream_batch{batch_idx}.log")
        logger.info("Calling LLM API for %s (%s)", batch_label, provider)

        batch_xmls: dict[int, str] = {}
        while True:
            t_api_start = time.time()
            try:
                if provider == "anthropic":
                    sys_prompt_text = get_system_prompt_text(args.enable_animations, args.prompt_lang)
                    result = call_anthropic(
                        messages=messages,
                        system_prompt=sys_prompt_text,
                        api_key=args.api_key,
                        api_base_url=args.api_base_url,
                        model_name=args.model_name,
                        stream_log_path=stream_log,
                        reasoning_effort=args.reasoning_effort,
                        estimated_response_seconds=float(token_est["estimated_response_time_seconds"]),
                    )
                else:
                    result = call_llm(
                        messages=messages,
                        api_base_url=args.api_base_url,
                        api_key=args.api_key,
                        model_name=args.model_name,
                        stream_log_path=stream_log,
                        reasoning_effort=args.reasoning_effort,
                        estimated_response_seconds=float(token_est["estimated_response_time_seconds"]),
                    )
                t_api_total += time.time() - t_api_start

                store.save_api_response(result.response_data)
                store.save_stream_chunks(result.raw_chunks)
                store.save_tool_calls(result.tool_calls_raw)
                store.save_reasoning(result.reasoning_text, batch_idx=batch_idx)
                store.save_content_text(result.content_text, batch_idx=batch_idx)

                batch_xmls = result.slide_xmls
                break

            except Exception as exc:
                t_api_total += time.time() - t_api_start
                logger.error("API error during %s: %s", batch_label, exc)
                _print_progress(logger, slide_xmls, n_pages, batch_idx, n_batches)
                choice = input("Retry this batch? [r]etry / [s]kip to post-processing / [q]uit: ").strip().lower()
                if choice.startswith("r"):
                    logger.info("Retrying %s...", batch_label)
                    continue
                if choice.startswith("s"):
                    logger.info("Skipping remaining batches, proceeding to post-processing...")
                    break
                logger.info("Quitting.")
                _save_metadata(success=False)
                sys.exit(1)

        if not batch_xmls:
            logger.warning("No slide XMLs received for %s", batch_label)
            if batch_idx < n_batches - 1:
                _print_progress(logger, slide_xmls, n_pages, batch_idx, n_batches)
                choice = input("Continue with next batch? [y]es / [s]kip to post-processing: ").strip().lower()
                if choice.startswith("s"):
                    logger.info("Skipping remaining batches, proceeding to post-processing...")
                    break
            continue

        logger.info("Received %d slide XMLs for %s", len(batch_xmls), batch_label)

        # For overlapping pages, prefer the later batch's version (better transition context)
        if n_batches > 1 and batch_idx > 0 and args.enable_animations:
            for page_num in range(start, min(start + overlap, end)):
                if page_num in batch_xmls:
                    slide_xmls[page_num] = batch_xmls[page_num]
        slide_xmls.update(batch_xmls)

    logger.info("Total slide XMLs collected: %d", len(slide_xmls))
    if slide_xmls:
        store.save_slide_xmls(slide_xmls)

    if not slide_xmls:
        logger.error("No slide XMLs received from the API")
        _save_metadata(success=False)
        sys.exit(1)

    logger.info("Slide dimensions: %.0f×%.0f pt (aspect ratio: %s)", snap_w, snap_h, ratio_label)

    assembler = PPTXAssembler(
        slide_width_pt=snap_w,
        slide_height_pt=snap_h,
    )
    assembler.assemble(slide_xmls)

    if args.skip_postprocess:
        assembler.save(args.output)
    else:
        intermediate = args.output + ".tmp"
        assembler.save(intermediate)

        # Build PDF page mapping: PPTX slide position → original PDF page number
        # The LLM numbers slides 0..N-1 sequentially; each maps to pages[i]'s original page_num
        sorted_slide_keys = sorted(slide_xmls.keys())
        pdf_page_map = [pages[k][1]["page_num"] for k in sorted_slide_keys if k < len(pages)]

        # Step 3: Post-process raster fills
        postprocess_raster_fills(
            pptx_path=intermediate,
            pdf_path=args.pdf,
            output_path=args.output,
            dpi=300,
            page_indices=pdf_page_map if page_indices is not None else None,
        )

        with contextlib.suppress(OSError):
            os.remove(intermediate)

    _save_metadata(success=True)
    store.copy_output(args.output)

    t_total = time.time() - t_start
    file_size = os.path.getsize(args.output) / (1024 * 1024)
    logger.info(
        "Conversion complete: %s (%.1f MB)", args.output, file_size
    )
    logger.info(
        "Total time: %.1fs | API time: %.1fs (%.0f%%)",
        t_total,
        t_api_total,
        (t_api_total / t_total * 100) if t_total > 0 else 0,
    )
    logger.info("Artifacts saved to: %s/", store.root)


if __name__ == "__main__":
    main()

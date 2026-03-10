"""Entry point for PDF-to-PPTX conversion via CLI."""

from __future__ import annotations

import argparse
import os
import sys
import time


def main() -> None:
    """Parse CLI args and run the full conversion or dry-run pipeline."""
    parser = argparse.ArgumentParser(
        description="Convert PDF slides to editable PPTX using GPT-5.4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("pdf", help="Input PDF file path")
    parser.add_argument("-o", "--output", default="", help="Output PPTX file path")

    # OpenAI API configuration
    parser.add_argument(
        "--api-base-url",
        default=os.getenv("OPENAI_BASE_URL", ""),
        help="OpenAI API Base URL (default: $OPENAI_BASE_URL)",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("OPENAI_API_KEY", ""),
        help="OpenAI API Key (default: $OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--model-name",
        default=os.getenv("OPENAI_MODEL_NAME", "gpt-5.4"),
        help="Model name (default: $OPENAI_MODEL_NAME or gpt-5.4)",
    )

    # Processing options
    parser.add_argument(
        "--dpi", type=int, default=192, help="Rendering DPI for LLM input (default: 192)"
    )
    parser.add_argument(
        "--enable-animations",
        action="store_true",
        help="Enable animation/transition effects (default: off)",
    )
    parser.add_argument(
        "--reasoning-effort",
        default="high",
        choices=["low", "medium", "high"],
        help="Reasoning effort for the model (default: high)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Batch size for large documents (default: 25)",
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
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )

    args = parser.parse_args()

    # Setup logging first
    from .logging_config import get_logger, setup_logging

    setup_logging(args.log_level)
    logger = get_logger("main")

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
        "Options: dpi=%d, animations=%s, model=%s, reasoning=%s",
        args.dpi,
        "on" if args.enable_animations else "off",
        args.model_name,
        args.reasoning_effort,
    )

    t_start = time.time()

    # --- Dry-run mode ---
    if args.dry_run:
        from .dry_run import run_dry

        run_dry(
            pdf_path=args.pdf,
            dpi=args.dpi,
            enable_animations=args.enable_animations,
            model_name=args.model_name,
            batch_size=args.batch_size,
        )
        return

    # --- Full conversion ---
    import contextlib

    from .api_client import call_llm
    from .artifacts import ArtifactStore
    from .message_builder import build_messages
    from .pdf_preprocessor import pdf_to_images
    from .postprocessor import postprocess_raster_fills
    from .pptx_assembler import PPTXAssembler
    from .system_prompt import WRITE_SLIDE_XML_TOOL
    from .token_estimator import estimate_tokens

    store = ArtifactStore(pdf_path=args.pdf)

    # Step 1: PDF preprocessing
    pages = pdf_to_images(args.pdf, dpi=args.dpi)
    store.save_page_images(pages)

    # Step 2+3: Build messages and call LLM API, with batching for large PDFs
    batch_size = args.batch_size
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

    for batch_idx, (start, end) in enumerate(batches):
        batch_pages = pages[start:end]
        batch_label = f"batch {batch_idx + 1}/{n_batches} (pages {start}-{end - 1})"
        logger.info("Building messages for %s", batch_label)

        messages = build_messages(batch_pages, enable_animations=args.enable_animations)

        if batch_idx == 0:
            store.save_messages(messages)
            store.save_system_prompt(messages[0]["content"])
            store.save_tools([WRITE_SLIDE_XML_TOOL])

        token_est = estimate_tokens(messages, model=args.model_name)
        if batch_idx == 0:
            store.save_token_estimate(token_est)

        stream_log = os.path.join(store.root, f"stream_batch{batch_idx}.log")
        logger.info("Calling LLM API for %s", batch_label)
        t_api_start = time.time()
        result = call_llm(
            messages=messages,
            api_base_url=args.api_base_url,
            api_key=args.api_key,
            model_name=args.model_name,
            stream_log_path=stream_log,
            reasoning_effort=args.reasoning_effort,
        )
        t_api_total += time.time() - t_api_start

        store.save_api_response(result.response_data)
        store.save_stream_chunks(result.raw_chunks)
        store.save_tool_calls(result.tool_calls_raw)

        batch_xmls = result.slide_xmls
        if not batch_xmls:
            logger.error("No slide XMLs received for %s", batch_label)
            continue

        logger.info("Received %d slide XMLs for %s", len(batch_xmls), batch_label)

        # For overlapping pages, prefer the later batch's version (better transition context)
        if n_batches > 1 and batch_idx > 0 and args.enable_animations:
            for page_num in range(start, min(start + overlap, end)):
                if page_num in batch_xmls:
                    slide_xmls[page_num] = batch_xmls[page_num]
        slide_xmls.update(batch_xmls)

    if not slide_xmls:
        logger.error("No slide XMLs received from the API")
        sys.exit(1)

    logger.info("Total slide XMLs collected: %d", len(slide_xmls))
    store.save_slide_xmls(slide_xmls)

    # Step 4: Assemble PPTX
    assembler = PPTXAssembler(
        slide_width_pt=pages[0][1]["width_pt"],
        slide_height_pt=pages[0][1]["height_pt"],
    )
    assembler.assemble(slide_xmls)

    if args.skip_postprocess:
        assembler.save(args.output)
    else:
        intermediate = args.output + ".tmp"
        assembler.save(intermediate)

        # Step 5: Post-process raster fills
        postprocess_raster_fills(
            pptx_path=intermediate,
            pdf_path=args.pdf,
            output_path=args.output,
            dpi=300,
        )

        with contextlib.suppress(OSError):
            os.remove(intermediate)

    # Save run metadata
    store.save_metadata({
        "pdf_path": os.path.abspath(args.pdf),
        "output_pptx": os.path.abspath(args.output),
        "pdf_pages": n_pages,
        "dpi": args.dpi,
        "enable_animations": args.enable_animations,
        "model": args.model_name,
        "batch_size": batch_size,
        "batches": n_batches,
        "slide_width_pt": pages[0][1]["width_pt"],
        "slide_height_pt": pages[0][1]["height_pt"],
        "token_estimate": token_est,
        "api_elapsed_seconds": t_api_total,
        "slides_received": len(slide_xmls),
    })

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

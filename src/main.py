from __future__ import annotations

import argparse
import os
import sys
import time


def main() -> None:
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
        "--dpi", type=int, default=300, help="Rendering DPI (default: 300)"
    )
    parser.add_argument(
        "--enable-animations",
        action="store_true",
        help="Enable animation/transition effects (default: off)",
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
        "Options: dpi=%d, animations=%s, model=%s",
        args.dpi,
        "on" if args.enable_animations else "off",
        args.model_name,
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
    from .api_client import call_llm
    from .message_builder import build_messages
    from .pdf_preprocessor import pdf_to_images
    from .postprocessor import postprocess_raster_fills
    from .pptx_assembler import PPTXAssembler
    from .token_estimator import estimate_tokens

    # Step 1: PDF preprocessing
    pages = pdf_to_images(args.pdf, dpi=args.dpi)

    # Step 2: Build messages
    messages = build_messages(pages, enable_animations=args.enable_animations)

    # Token estimation
    estimate_tokens(messages, model=args.model_name)

    # Step 3: Call LLM API
    t_api_start = time.time()
    slide_xmls = call_llm(
        messages=messages,
        api_base_url=args.api_base_url,
        api_key=args.api_key,
        model_name=args.model_name,
    )
    t_api = time.time() - t_api_start

    if not slide_xmls:
        logger.error("No slide XMLs received from the API")
        sys.exit(1)

    logger.info("Received %d slide XMLs", len(slide_xmls))

    # Step 4: Assemble PPTX
    assembler = PPTXAssembler(
        slide_width_pt=pages[0][1]["width_pt"],
        slide_height_pt=pages[0][1]["height_pt"],
    )
    assembler.assemble(slide_xmls)

    # Save intermediate PPTX (before post-processing)
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
            dpi=args.dpi,
        )

        # Clean up intermediate file
        import contextlib

        with contextlib.suppress(OSError):
            os.remove(intermediate)

    t_total = time.time() - t_start
    file_size = os.path.getsize(args.output) / (1024 * 1024)
    logger.info(
        "Conversion complete: %s (%.1f MB)", args.output, file_size
    )
    logger.info(
        "Total time: %.1fs | API time: %.1fs (%.0f%%)",
        t_total,
        t_api,
        (t_api / t_total * 100) if t_total > 0 else 0,
    )


if __name__ == "__main__":
    main()

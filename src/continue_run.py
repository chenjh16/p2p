"""Continue an incomplete run from its artifact directory."""

from __future__ import annotations

import json
import os
import sys

from .logging_config import get_logger

logger = get_logger("continue")


def run_continue(source_dir: str) -> None:
    """Analyze a previous run directory and resume or post-process.

    Reads ``slides/`` to determine which pages have already been generated,
    then offers the user a choice: continue generating remaining pages, or
    proceed directly to PPTX assembly with whatever slides are available.
    """


    metadata_path = os.path.join(source_dir, "metadata.json")
    slides_dir = os.path.join(source_dir, "slides")

    if not os.path.isdir(source_dir):
        logger.error("Directory not found: %s", source_dir)
        sys.exit(1)

    # Load existing slide XMLs
    existing_xmls: dict[int, str] = {}
    if os.path.isdir(slides_dir):
        for fname in sorted(os.listdir(slides_dir)):
            if fname.startswith("slide_") and fname.endswith(".xml"):
                page_num = int(fname.replace("slide_", "").replace(".xml", ""))
                fpath = os.path.join(slides_dir, fname)
                with open(fpath, encoding="utf-8") as f:
                    existing_xmls[page_num] = f.read()

    # Load metadata to understand the run parameters
    meta: dict = {}
    if os.path.isfile(metadata_path):
        with open(metadata_path, encoding="utf-8") as f:
            meta = json.load(f)

    total_pages = meta.get("pdf_pages", 0)
    expected_pages = set(range(total_pages))
    received_pages = set(existing_xmls.keys())
    missing_pages = sorted(expected_pages - received_pages)

    logger.info("=" * 60)
    logger.info("CONTINUE RUN: %s", source_dir)
    logger.info("=" * 60)
    logger.info("  Total expected pages: %d", total_pages)
    logger.info("  Slides received:      %d", len(received_pages))
    if received_pages:
        logger.info("  Pages received:       %s", sorted(received_pages))
    if missing_pages:
        logger.info("  Pages missing:        %s", missing_pages)
    else:
        logger.info("  All pages received!")
    logger.info("=" * 60)

    if not missing_pages and existing_xmls:
        choice = input("All slides present. Proceed to PPTX assembly? [y]es / [q]uit: ").strip().lower()
        if not choice.startswith("y"):
            return
    elif existing_xmls:
        choice = input(
            f"{len(missing_pages)} pages missing. [c]ontinue generating / [p]ost-process with existing slides / [q]uit: "
        ).strip().lower()
        if choice.startswith("q"):
            return
        if choice.startswith("c"):
            _continue_generation(source_dir, meta, existing_xmls, missing_pages)
            return
    else:
        logger.error("No slides found and no metadata. Cannot continue.")
        sys.exit(1)

    # Post-process with existing slides
    _assemble_pptx(source_dir, meta, existing_xmls)


def _continue_generation(
    source_dir: str,
    meta: dict,
    existing_xmls: dict[int, str],
    missing_pages: list[int],
) -> None:
    """Generate missing slides and then assemble the PPTX."""

    from .message_builder import build_messages, get_system_prompt_text
    from .pdf_preprocessor import pdf_to_images
    from .token_estimator import estimate_tokens, recommend_batch_size

    runtime = meta.get("runtime_params", {})
    pdf_path = runtime.get("pdf_path", "")
    if not pdf_path or not os.path.isfile(pdf_path):
        pdf_copy = os.path.join(source_dir, os.path.basename(pdf_path) if pdf_path else "input.pdf")
        if os.path.isfile(pdf_copy):
            pdf_path = pdf_copy
        else:
            logger.error("Cannot find input PDF: %s", pdf_path)
            sys.exit(1)

    provider = runtime.get("api_provider", "openai")
    model_name = runtime.get("model", "gpt-5.4")
    dpi = runtime.get("dpi", 192)
    enable_animations = runtime.get("enable_animations", False)
    reasoning_effort = runtime.get("reasoning_effort", "medium")
    prompt_lang = runtime.get("prompt_lang", "en")
    output_tps = runtime.get("output_tps", 50.0)

    if provider == "anthropic":
        from .api_client_anthropic import call_anthropic
    else:
        from .api_client import call_llm

    all_pages = pdf_to_images(pdf_path, dpi=dpi)
    missing_page_data = [p for p in all_pages if p[1]["page_num"] in missing_pages]

    if not missing_page_data:
        logger.error("No page data for missing pages")
        sys.exit(1)

    batch_size = recommend_batch_size(reasoning_effort=reasoning_effort, output_tps=output_tps)
    logger.info("Generating %d missing pages in batches of %d", len(missing_page_data), batch_size)

    slide_xmls = dict(existing_xmls)

    for i in range(0, len(missing_page_data), batch_size):
        batch_pages = missing_page_data[i : i + batch_size]
        batch_label = f"continue batch (pages {[p[1]['page_num'] for p in batch_pages]})"
        logger.info("Building messages for %s", batch_label)

        messages = build_messages(batch_pages, enable_animations=enable_animations, prompt_lang=prompt_lang, provider=provider)
        token_est = estimate_tokens(messages, model=model_name, reasoning_effort=reasoning_effort, dpi=dpi, output_tps=output_tps)

        stream_log = os.path.join(source_dir, f"stream_continue_{i}.log")
        logger.info("Calling LLM API for %s (%s)", batch_label, provider)

        try:
            if provider == "anthropic":
                sys_prompt_text = get_system_prompt_text(enable_animations, prompt_lang)
                result = call_anthropic(
                    messages=messages,
                    system_prompt=sys_prompt_text,
                    api_key=os.getenv("ANTHROPIC_API_KEY", ""),
                    api_base_url=os.getenv("ANTHROPIC_BASE_URL", ""),
                    model_name=model_name,
                    stream_log_path=stream_log,
                    reasoning_effort=reasoning_effort,
                    estimated_response_seconds=float(token_est["estimated_response_time_seconds"]),
                )
            else:
                result = call_llm(
                    messages=messages,
                    api_base_url=os.getenv("OPENAI_BASE_URL", ""),
                    api_key=os.getenv("OPENAI_API_KEY", ""),
                    model_name=model_name,
                    stream_log_path=stream_log,
                    reasoning_effort=reasoning_effort,
                    estimated_response_seconds=float(token_est["estimated_response_time_seconds"]),
                )

            if result.slide_xmls:
                slide_xmls.update(result.slide_xmls)
                # Save new slides to the existing artifact directory
                slides_dir = os.path.join(source_dir, "slides")
                os.makedirs(slides_dir, exist_ok=True)
                for pnum, xml in result.slide_xmls.items():
                    with open(os.path.join(slides_dir, f"slide_{pnum:03d}.xml"), "w", encoding="utf-8") as f:
                        f.write(xml)
                logger.info("Received %d slides for %s", len(result.slide_xmls), batch_label)
            else:
                logger.warning("No slides received for %s", batch_label)

        except Exception as exc:
            logger.error("API error during %s: %s", batch_label, exc)
            logger.info("Progress: %d/%d slides", len(slide_xmls), meta.get("pdf_pages", 0))
            choice = input("Retry? [r]etry / [s]kip to post-processing / [q]uit: ").strip().lower()
            if choice.startswith("r"):
                continue
            if choice.startswith("q"):
                return
            break

    _assemble_pptx(source_dir, meta, slide_xmls)


def _assemble_pptx(source_dir: str, meta: dict, slide_xmls: dict[int, str]) -> None:
    """Assemble PPTX from collected slide XMLs."""
    import contextlib

    from .pdf_preprocessor import pdf_to_images
    from .postprocessor import postprocess_raster_fills
    from .pptx_assembler import PPTXAssembler

    runtime = meta.get("runtime_params", {})
    pdf_path = runtime.get("pdf_path", "")
    if not os.path.isfile(pdf_path):
        pdf_copy = os.path.join(source_dir, os.path.basename(pdf_path) if pdf_path else "input.pdf")
        if os.path.isfile(pdf_copy):
            pdf_path = pdf_copy

    page_indices = runtime.get("page_indices")
    skip_postprocess = runtime.get("skip_postprocess", False)

    if not slide_xmls:
        logger.error("No slides to assemble")
        return

    logger.info("Assembling PPTX from %d slides...", len(slide_xmls))

    snap_w = meta.get("slide_width_pt", 720)
    snap_h = meta.get("slide_height_pt", 405)

    assembler = PPTXAssembler(slide_width_pt=snap_w, slide_height_pt=snap_h)
    assembler.assemble(slide_xmls)

    base = os.path.splitext(os.path.basename(pdf_path))[0]
    output_name = os.path.join(source_dir, f"{base}_continued.pptx")

    if skip_postprocess or not os.path.isfile(pdf_path):
        assembler.save(output_name)
    else:
        intermediate = output_name + ".tmp"
        assembler.save(intermediate)

        all_pages = pdf_to_images(pdf_path, dpi=72)
        pages_for_map = (
            [p for p in all_pages if p[1]["page_num"] in page_indices] if page_indices else all_pages
        )

        sorted_keys = sorted(slide_xmls.keys())
        pdf_page_map = [pages_for_map[k][1]["page_num"] for k in sorted_keys if k < len(pages_for_map)]

        postprocess_raster_fills(
            pptx_path=intermediate,
            pdf_path=pdf_path,
            output_path=output_name,
            dpi=300,
            page_indices=pdf_page_map if page_indices else None,
        )
        with contextlib.suppress(OSError):
            os.remove(intermediate)

    logger.info("PPTX saved: %s", output_name)

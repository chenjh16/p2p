"""Build LLM messages from PDF page images for OpenAI and Anthropic APIs."""

from __future__ import annotations

import base64

from .logging_config import get_logger
from .system_prompt import get_animation_section, get_system_prompt

logger = get_logger("msg_builder")


def _build_task_text(n: int, slide_w: float, slide_h: float) -> str:
    """Build the shared task instruction text used by both providers."""
    emu_w = int(slide_w * 12700)
    emu_h = int(slide_h * 12700)
    return (
        f"\n--- Task ---\n"
        f"Convert each of the {n} slide images above into OOXML (Office Open XML) "
        f"PresentationML format — the native XML representation used inside PPTX files.\n"
        f"Slide dimensions: {emu_w} EMU × {emu_h} EMU ({slide_w}pt × {slide_h}pt).\n\n"
        f"CRITICAL: You have only ONE response to complete this entire task. "
        f"In this single response, you MUST make exactly {n} parallel tool calls to "
        f"write_slide_xml — one for each page (page_num 0 through {n - 1}). "
        f"Do NOT stop after converting just one page. Convert ALL {n} pages now.\n\n"
        f"REMINDER — Atomic Reconstruction: Decompose every visual region into its smallest "
        f"independently rebuildable units. Each distinct shape, text label, arrow, line, or "
        f"filled region must be a separate PowerPoint object. Diagrams made of basic shapes "
        f"and connectors MUST be vectorized — never use a single raster placeholder for them. "
        f"Tables MUST use native <a:tbl> elements. Only use raster placeholders for genuine "
        f"photographs or complex artistic illustrations. Apply the 20%% font size reduction rule."
    )


def build_messages(
    pages: list[tuple[bytes, dict]],
    enable_animations: bool = False,
    prompt_lang: str = "en",
    provider: str = "openai",
) -> list[dict]:
    """Build the LLM messages array for a single API call.

    For OpenAI: returns messages with system role and image_url content blocks.
    For Anthropic: returns messages with image content blocks (system prompt separate).
    """
    if provider == "anthropic":
        return _build_messages_anthropic(pages, enable_animations, prompt_lang)
    return _build_messages_openai(pages, enable_animations, prompt_lang)


def get_system_prompt_text(enable_animations: bool = False, prompt_lang: str = "en") -> str:
    """Return the full system prompt text (used by Anthropic which takes it as a separate param)."""
    system_prompt = get_system_prompt(prompt_lang)
    if enable_animations:
        system_prompt += get_animation_section(prompt_lang)
    return system_prompt


def _build_messages_openai(
    pages: list[tuple[bytes, dict]],
    enable_animations: bool,
    prompt_lang: str,
) -> list[dict]:
    """Build OpenAI Chat Completions messages with image_url content blocks.

    Page labels use batch-local indices (0 to N-1) so the LLM returns
    page_num values that match the batch_page_map in the caller.
    """
    system_prompt = get_system_prompt_text(enable_animations, prompt_lang)

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
    ]

    user_content: list[dict] = []
    n = len(pages)
    slide_w = pages[0][1]["width_pt"]
    slide_h = pages[0][1]["height_pt"]

    user_content.append({
        "type": "text",
        "text": f"Below are {n} slide page images to convert. Slide dimensions: {slide_w}pt × {slide_h}pt.",
    })

    for batch_idx, (img_bytes, _meta) in enumerate(pages):
        user_content.append({"type": "text", "text": f"\n--- Page {batch_idx} ---"})
        b64 = base64.b64encode(img_bytes).decode()
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
        })

    user_content.append({"type": "text", "text": _build_task_text(n, slide_w, slide_h)})
    messages.append({"role": "user", "content": user_content})

    logger.info("Messages assembled (OpenAI): %d content parts (%d images)", len(user_content), len(pages))
    return messages


def _build_messages_anthropic(
    pages: list[tuple[bytes, dict]],
    enable_animations: bool,  # noqa: ARG001 — used via get_system_prompt_text in caller
    prompt_lang: str,  # noqa: ARG001
) -> list[dict]:
    """Build Anthropic Messages API content blocks with base64 image sources.

    Note: system prompt is passed separately to the Anthropic API, not in messages.
    Page labels use batch-local indices (0 to N-1) so the LLM returns
    page_num values that match the batch_page_map in the caller.
    """
    user_content: list[dict] = []
    n = len(pages)
    slide_w = pages[0][1]["width_pt"]
    slide_h = pages[0][1]["height_pt"]

    user_content.append({
        "type": "text",
        "text": f"Below are {n} slide page images to convert. Slide dimensions: {slide_w}pt × {slide_h}pt.",
    })

    for batch_idx, (img_bytes, _meta) in enumerate(pages):
        user_content.append({"type": "text", "text": f"\n--- Page {batch_idx} ---"})
        b64 = base64.b64encode(img_bytes).decode()
        user_content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": b64},
        })

    user_content.append({"type": "text", "text": _build_task_text(n, slide_w, slide_h)})

    messages: list[dict] = [{"role": "user", "content": user_content}]

    logger.info("Messages assembled (Anthropic): %d content parts (%d images)", len(user_content), len(pages))
    return messages

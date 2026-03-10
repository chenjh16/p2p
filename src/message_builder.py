"""Build OpenAI Chat Completions messages from PDF page images."""

from __future__ import annotations

import base64

from .logging_config import get_logger
from .system_prompt import get_animation_section, get_system_prompt

logger = get_logger("msg_builder")


def build_messages(
    pages: list[tuple[bytes, dict]],
    enable_animations: bool = False,
    prompt_lang: str = "en",
) -> list[dict]:
    """Build the OpenAI Chat Completions messages array for a single API call."""
    system_prompt = get_system_prompt(prompt_lang)
    if enable_animations:
        system_prompt += get_animation_section(prompt_lang)

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
    ]

    user_content: list[dict] = []

    n = len(pages)
    slide_w = pages[0][1]["width_pt"]
    slide_h = pages[0][1]["height_pt"]
    emu_w = int(slide_w * 12700)
    emu_h = int(slide_h * 12700)

    user_content.append({
        "type": "text",
        "text": f"Below are {n} slide page images to convert. Slide dimensions: {slide_w}pt × {slide_h}pt.",
    })

    for img_bytes, meta in pages:
        page_num = meta["page_num"]

        user_content.append(
            {"type": "text", "text": f"\n--- Page {page_num} ---"}
        )

        b64 = base64.b64encode(img_bytes).decode()
        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{b64}",
                "detail": "high",
            },
        })

    user_content.append({
        "type": "text",
        "text": (
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
        ),
    })

    messages.append({"role": "user", "content": user_content})

    total_parts = len(user_content)
    logger.info(
        "Messages assembled: %d content parts (%d images)",
        total_parts,
        len(pages),
    )
    return messages

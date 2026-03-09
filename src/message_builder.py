from __future__ import annotations

import base64

from .logging_config import get_logger
from .system_prompt import ANIMATION_DISABLED_ADDENDUM, SYSTEM_PROMPT

logger = get_logger("msg_builder")


def build_messages(
    pages: list[tuple[bytes, dict]],
    enable_animations: bool = False,
) -> list[dict]:
    """Build the OpenAI Chat Completions messages array for a single API call."""
    system_prompt = SYSTEM_PROMPT
    if not enable_animations:
        system_prompt += ANIMATION_DISABLED_ADDENDUM

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
    ]

    user_content: list[dict] = []

    slide_w = pages[0][1]["width_pt"]
    slide_h = pages[0][1]["height_pt"]
    user_content.append(
        {
            "type": "text",
            "text": (
                f"Analyze the following {len(pages)} slide pages and generate "
                f"the corresponding PresentationML slide XML for each page.\n"
                f"Slide dimensions: {slide_w}pt × {slide_h}pt "
                f"({int(slide_w * 12700)} EMU × {int(slide_h * 12700)} EMU).\n"
                f"Call write_slide_xml once for each page."
            ),
        }
    )

    for img_bytes, meta in pages:
        page_num = meta["page_num"]

        user_content.append(
            {"type": "text", "text": f"\n--- Page {page_num} ---"}
        )

        b64 = base64.b64encode(img_bytes).decode()
        user_content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64}",
                    "detail": "high",
                },
            }
        )

    messages.append({"role": "user", "content": user_content})

    total_parts = len(user_content)
    logger.info(
        "Messages assembled: %d content parts (%d images)",
        total_parts,
        len(pages),
    )
    return messages

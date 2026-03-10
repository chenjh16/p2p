"""Estimate token usage and cost for LLM API calls.

Supports model-aware image token calculation for both OpenAI and Anthropic providers:

- **OpenAI (GPT-5.4, GPT-5.3, GPT-4.1, GPT-4o, etc.)**: Uses tile-based tokenization.
  Images are first scaled so the shortest side is 768px, then fitted within 2048×2048,
  then divided into 512×512 tiles. Each tile costs 170 tokens + 85 base tokens.
  Low-detail images are a flat 85 tokens.
  Reference: https://platform.openai.com/docs/guides/images-vision#tile-based-image-tokenization

- **Anthropic (Claude Opus-4.6, Claude Sonnet, etc.)**: Uses pixel-area formula.
  Images larger than 1568px on the long edge or >1.15 megapixels are resized first.
  Token count = (width_px × height_px) / 750.
  Reference: https://docs.anthropic.com/en/docs/build-with-claude/vision#calculate-image-costs
"""

from __future__ import annotations

import math

import tiktoken

from .logging_config import get_logger

logger = get_logger("token_est")


REASONING_EFFORT_MULTIPLIERS: dict[str, float] = {
    "low": 1.0,
    "medium": 1.5,
    "high": 2.5,
    "xhigh": 4.0,
}


def _openai_image_tokens(width_px: int, height_px: int, detail: str = "high") -> int:
    """Calculate image tokens for OpenAI models using tile-based tokenization.

    Algorithm (for detail="high"):
      1. Scale the image so the shortest side is 768px (maintain aspect ratio).
      2. Scale to fit within 2048×2048 (maintain aspect ratio).
      3. Divide into 512×512 tiles (ceiling on each dimension).
      4. tokens = 85 (base) + 170 × num_tiles

    For detail="low": flat 85 tokens regardless of size.

    Reference: https://platform.openai.com/docs/guides/images-vision#tile-based-image-tokenization
    """
    BASE_TOKENS = 85
    TILE_TOKENS = 170

    if detail == "low":
        return BASE_TOKENS

    if width_px <= 0 or height_px <= 0:
        return BASE_TOKENS

    w, h = float(width_px), float(height_px)

    # Step 1: fit within 2048×2048
    if w > 2048 or h > 2048:
        scale = min(2048 / w, 2048 / h)
        w, h = w * scale, h * scale

    # Step 2: scale shortest side to 768px
    short_side = min(w, h)
    if short_side > 768:
        scale = 768 / short_side
        w, h = w * scale, h * scale

    # Step 3: count 512×512 tiles
    tiles_x = math.ceil(w / 512)
    tiles_y = math.ceil(h / 512)
    num_tiles = tiles_x * tiles_y

    return BASE_TOKENS + TILE_TOKENS * num_tiles


def _anthropic_image_tokens(width_px: int, height_px: int) -> int:
    """Calculate image tokens for Anthropic Claude models using pixel-area formula.

    Algorithm:
      1. If the long edge > 1568px or total pixels > 1.15 megapixels (1_323_200),
         resize proportionally so both constraints are met.
      2. tokens = (width_px × height_px) / 750

    Reference: https://docs.anthropic.com/en/docs/build-with-claude/vision#calculate-image-costs
    """
    if width_px <= 0 or height_px <= 0:
        return 0

    w, h = float(width_px), float(height_px)

    # Resize if long edge > 1568 or total pixels > 1.15 megapixels
    max_edge = 1568
    max_pixels = 1_323_200  # ~1.15 megapixels

    long_edge = max(w, h)
    if long_edge > max_edge:
        scale = max_edge / long_edge
        w, h = w * scale, h * scale

    if w * h > max_pixels:
        scale = math.sqrt(max_pixels / (w * h))
        w, h = w * scale, h * scale

    return math.ceil((w * h) / 750)


def _is_anthropic_model(model: str) -> bool:
    """Check if the model name indicates an Anthropic Claude model."""
    return "claude" in model.lower()


def _estimate_image_tokens_for_part(part: dict, model: str, dpi: int) -> int:
    """Estimate tokens for a single image content block.

    Handles both OpenAI format (type: "image_url") and Anthropic format (type: "image").
    Uses the DPI to estimate pixel dimensions from the rendering resolution.
    """
    # Default slide image dimensions at given DPI (16:9 aspect ratio)
    # A 720pt × 405pt slide at 288 DPI → 2880×1620 px
    default_w = int(720 * dpi / 72)
    default_h = int(405 * dpi / 72)

    if part.get("type") == "image_url":
        detail = part.get("image_url", {}).get("detail", "high")
        return _openai_image_tokens(default_w, default_h, detail)

    if part.get("type") == "image":
        if _is_anthropic_model(model):
            return _anthropic_image_tokens(default_w, default_h)
        return _openai_image_tokens(default_w, default_h)

    return 0


def estimate_tokens(
    messages: list[dict],
    model: str = "gpt-5.4",
    reasoning_effort: str = "medium",
    dpi: int = 288,
    output_tps: float = 0,
) -> dict:
    """Estimate token consumption for the given messages.

    Args:
        messages: The LLM messages array (OpenAI or Anthropic format).
        model: Model name, used to select the appropriate token calculation method.
        reasoning_effort: Reasoning effort level (affects estimated response time).
        dpi: Image rendering DPI, used to estimate pixel dimensions for token calculation.
        output_tps: Assumed output tokens per second. 0 means use the module default.
    """
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")

    text_tokens = 0
    image_count = 0
    image_tokens = 0

    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            text_tokens += len(enc.encode(content))
        elif isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    text_tokens += len(enc.encode(part["text"]))
                elif part.get("type") in ("image_url", "image"):
                    image_count += 1
                    image_tokens += _estimate_image_tokens_for_part(part, model, dpi)

    text_tokens += 4  # message framing overhead
    total_input = text_tokens + image_tokens

    # Output estimate: ~9000 tokens per slide XML + 2000 overhead
    # Calibrated from actual runs — typical slides with shapes, tables, and styling
    # produce 7000–12000 tokens of PresentationML XML per page.
    estimated_output = image_count * OUTPUT_TOKENS_PER_PAGE + OUTPUT_OVERHEAD_TOKENS

    assumed_output_tps = output_tps if output_tps > 0 else ASSUMED_OUTPUT_TPS
    reasoning_multiplier = REASONING_EFFORT_MULTIPLIERS.get(reasoning_effort, 1.5)
    est_response_seconds = (estimated_output / assumed_output_tps) * reasoning_multiplier

    result = {
        "text_tokens": text_tokens,
        "image_count": image_count,
        "image_tokens": image_tokens,
        "total_input_tokens": total_input,
        "estimated_output_tokens": estimated_output,
        "estimated_total_tokens": total_input + estimated_output,
        "estimated_cost_usd": _estimate_cost(total_input, estimated_output),
        "assumed_output_tps": assumed_output_tps,
        "reasoning_effort": reasoning_effort,
        "reasoning_multiplier": reasoning_multiplier,
        "estimated_response_time_seconds": round(est_response_seconds, 1),
    }

    logger.info(
        "Token estimate: %s input + ~%s output = ~%s total",
        f"{total_input:,}",
        f"{estimated_output:,}",
        f"{total_input + estimated_output:,}",
    )
    cost_info = result["estimated_cost_usd"]
    assert isinstance(cost_info, dict)
    logger.info("Estimated cost: $%.4f", cost_info["total_cost_usd"])
    logger.info(
        "Estimated response time: ~%.0fs (~%.1f min) at %.0f tok/s (reasoning=%s, ×%.1f)",
        est_response_seconds,
        est_response_seconds / 60,
        assumed_output_tps,
        reasoning_effort,
        reasoning_multiplier,
    )
    return result


GATEWAY_TIMEOUT_SECONDS = 600
OUTPUT_TOKENS_PER_PAGE = 9000
OUTPUT_OVERHEAD_TOKENS = 2000
ASSUMED_OUTPUT_TPS = 50.0


def recommend_batch_size(
    reasoning_effort: str = "medium",
    gateway_timeout: float = GATEWAY_TIMEOUT_SECONDS,
    output_tps: float = 0,
) -> int:
    """Calculate the maximum batch size that fits within the gateway timeout.

    The gateway imposes a hard timeout (default 600s / 10 minutes). Each page
    generates approximately 3000 output tokens plus a fixed 2000-token overhead
    per batch. At the configured tok/s (ASSUMED_OUTPUT_TPS) with the reasoning
    effort multiplier, we calculate how many pages can fit in one request.

    Returns at least 1 to ensure progress.
    """
    tps = output_tps if output_tps > 0 else ASSUMED_OUTPUT_TPS
    multiplier = REASONING_EFFORT_MULTIPLIERS.get(reasoning_effort, 1.5)
    overhead_seconds = (OUTPUT_OVERHEAD_TOKENS / tps) * multiplier
    available_seconds = gateway_timeout - overhead_seconds
    if available_seconds <= 0:
        return 1
    seconds_per_page = (OUTPUT_TOKENS_PER_PAGE / tps) * multiplier
    max_pages = int(available_seconds / seconds_per_page)
    return max(1, max_pages)


def _estimate_cost(input_tokens: int, output_tokens: int) -> dict:
    """Estimate cost based on placeholder pricing (may vary)."""
    pricing = {
        "input_per_1m": 2.50,
        "output_per_1m": 10.00,
    }
    input_cost = input_tokens / 1_000_000 * pricing["input_per_1m"]
    output_cost = output_tokens / 1_000_000 * pricing["output_per_1m"]
    return {
        "input_cost_usd": round(input_cost, 4),
        "output_cost_usd": round(output_cost, 4),
        "total_cost_usd": round(input_cost + output_cost, 4),
        "pricing_note": "Estimated based on placeholder pricing. Actual costs may vary.",
    }

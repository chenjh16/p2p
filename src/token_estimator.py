"""Estimate token usage and cost for LLM API calls."""

from __future__ import annotations

import tiktoken

from .logging_config import get_logger

logger = get_logger("token_est")


def estimate_tokens(messages: list[dict], model: str = "gpt-5.4") -> dict:
    """Estimate token consumption for the given messages."""
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
                elif part.get("type") == "image_url":
                    image_count += 1
                    detail = part["image_url"].get("detail", "auto")
                    if detail == "low":
                        image_tokens += 85
                    else:
                        # high detail: ~12 tiles for a typical slide image + 85 base
                        image_tokens += 170 * 12 + 85

    text_tokens += 4  # message framing overhead
    total_input = text_tokens + image_tokens

    # Output estimate: ~3000 tokens per slide XML + 2000 overhead
    estimated_output = image_count * 3000 + 2000

    result = {
        "text_tokens": text_tokens,
        "image_count": image_count,
        "image_tokens": image_tokens,
        "total_input_tokens": total_input,
        "estimated_output_tokens": estimated_output,
        "estimated_total_tokens": total_input + estimated_output,
        "estimated_cost_usd": _estimate_cost(total_input, estimated_output),
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
    return result


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

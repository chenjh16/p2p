"""Anthropic API client for streaming Claude calls with tool extraction."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable

import anthropic
import httpx

from .api_client import LLMResult
from .logging_config import get_logger
from .system_prompt import WRITE_SLIDE_XML_TOOL_ANTHROPIC

logger = get_logger("api_anthropic")


def call_anthropic(
    messages: list[dict],
    system_prompt: str,
    api_key: str = "",
    api_base_url: str = "",
    model_name: str = "claude-opus-4-6",
    max_tokens: int = 128000,
    stream_log_path: str = "",
    reasoning_effort: str = "medium",
    estimated_response_seconds: float = 0,
    on_slide_ready: Callable[[int, str], None] | None = None,
) -> LLMResult:
    """Call the Anthropic Messages API with streaming and extract slide XMLs from tool_use blocks.

    Timeout: connect=30s (TCP+TLS), read=max(estimated_response_seconds*3, 600)s.
    When ``on_slide_ready`` is provided, each completed tool_use block triggers an
    immediate callback with (page_num, slide_xml) for instant disk persistence.
    """
    min_timeout = 600
    timeout_seconds = max(estimated_response_seconds * 3, min_timeout)
    connect_timeout = 30.0
    timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout)

    client_kwargs: dict = {"timeout": timeout, "max_retries": 0}
    if api_key:
        client_kwargs["api_key"] = api_key
    if api_base_url:
        client_kwargs["base_url"] = api_base_url
    client = anthropic.Anthropic(**client_kwargs)

    tools = [WRITE_SLIDE_XML_TOOL_ANTHROPIC]

    logger.info(
        "HTTP timeout: connect=%.0fs, read/stream=%.0fs (3× estimated ~%.0fs), no retries",
        connect_timeout,
        timeout_seconds,
        estimated_response_seconds,
    )
    logger.info(
        "Calling %s API (streaming, tool_use, max_tokens=%d)...",
        model_name,
        max_tokens,
    )
    t0 = time.time()

    create_kwargs: dict = {
        "model": model_name,
        "system": system_prompt,
        "messages": messages,
        "tools": tools,
        "tool_choice": {"type": "any"},
        "max_tokens": max_tokens,
    }

    is_adaptive_model = any(model_name.startswith(p) for p in ("claude-opus-4-6", "claude-sonnet-4-6"))

    if is_adaptive_model:
        create_kwargs["thinking"] = {"type": "adaptive"}
        effort_level = _effort_level(reasoning_effort)
        if effort_level != "high":
            create_kwargs["output_config"] = {"effort": effort_level}
        logger.info("Adaptive thinking (effort=%s, reasoning=%s)", effort_level, reasoning_effort)
    else:
        thinking_budget = _thinking_budget(reasoning_effort, max_tokens)
        if thinking_budget > 0:
            create_kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
            logger.info("Extended thinking enabled: budget=%d tokens (reasoning=%s)", thinking_budget, reasoning_effort)

    log_file = (  # noqa: SIM115
        open(stream_log_path, "w", encoding="utf-8") if stream_log_path else None  # pylint: disable=consider-using-with
    )

    try:
        slide_xmls, response_data, raw_events, tool_calls_raw, content_text, reasoning_text = _stream_response(
            client, create_kwargs, log_file, on_slide_ready=on_slide_ready
        )
    finally:
        if log_file:
            log_file.close()

    elapsed = time.time() - t0
    response_data["elapsed_seconds"] = round(elapsed, 2)
    response_data["content_text"] = content_text
    response_data["reasoning_text"] = reasoning_text
    sys.stderr.write("\n")
    sys.stderr.flush()

    logger.info("API streaming complete in %.1fs", elapsed)

    usage = response_data.get("usage") or {}
    output_tokens = usage.get("output_tokens", 0)
    input_tokens = usage.get("input_tokens", 0)

    if output_tokens and elapsed > 0:
        tps = output_tokens / elapsed
        response_data["output_tokens_per_second"] = round(tps, 1)
        logger.info(
            "Usage: %s input, %s output (%.1f tok/s) | Stop: %s",
            f"{input_tokens:,}" if input_tokens else "?",
            f"{output_tokens:,}" if output_tokens else "?",
            tps,
            response_data.get("stop_reason", "?"),
        )

    if tool_calls_raw:
        logger.info("Tool calls: %d × write_slide_xml (%d slides received)", len(tool_calls_raw), len(slide_xmls))
    else:
        logger.warning("No tool_use blocks received from the model!")
        if content_text:
            logger.warning("Model returned text instead of tool calls:")
            for line in content_text.strip().splitlines()[:10]:
                logger.warning("  %s", line)

    return LLMResult(
        slide_xmls=slide_xmls,
        response_data=response_data,
        raw_chunks=raw_events,
        tool_calls_raw=tool_calls_raw,
        content_text=content_text,
        reasoning_text=reasoning_text,
    )


def _effort_level(reasoning_effort: str) -> str:
    """Map CLI reasoning effort to Anthropic adaptive-thinking effort level.

    Anthropic supports: low, medium, high (default), max (Opus 4.6 only).
    """
    mapping = {
        "low": "low",
        "medium": "medium",
        "high": "high",
        "xhigh": "max",
    }
    return mapping.get(reasoning_effort, "high")


def _thinking_budget(reasoning_effort: str, max_tokens: int) -> int:
    """Map reasoning effort to an extended thinking budget (0 = disabled).

    Used only for older models (Opus 4.5, Sonnet 4.5, etc.) that don't support
    adaptive thinking.
    """
    budgets = {
        "low": 0,
        "medium": min(16000, max_tokens // 4),
        "high": min(64000, max_tokens // 2),
        "xhigh": min(128000, max_tokens),
    }
    return budgets.get(reasoning_effort, 0)


def _flush_tool_block(
    tb: dict,
    idx: int,
    slide_xmls: dict[int, str],
    on_slide_ready: Callable[[int, str], None] | None,
) -> None:
    """Parse a completed tool_use block and save the slide XML immediately."""
    if tb["name"] != "write_slide_xml":
        logger.warning("Unexpected tool call: %s", tb["name"])
        return
    try:
        args = json.loads(tb["input_json"])
    except json.JSONDecodeError:
        logger.error("Failed to parse tool_use input (index %d)", idx)
        return
    page_num = args.get("page_num")
    slide_xml = args.get("slide_xml", "")
    if page_num is not None:
        slide_xmls[page_num] = slide_xml
        logger.debug("Slide %3d: %d chars XML", page_num, len(slide_xml))
        if on_slide_ready:
            on_slide_ready(page_num, slide_xml)


def _stream_response(
    client: anthropic.Anthropic,
    create_kwargs: dict,
    log_file,  # type: ignore[type-arg]
    *,
    on_slide_ready: Callable[[int, str], None] | None = None,
) -> tuple[dict[int, str], dict, list[dict], list[dict], str, str]:
    """Stream the Anthropic response, printing to stderr and accumulating tool_use blocks."""
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_blocks: dict[int, dict] = {}
    raw_events: list[dict] = []
    current_block_idx: int = -1
    current_block_type: str = ""
    stop_reason: str | None = None
    model: str = ""
    usage_data: dict = {}
    slide_xmls: dict[int, str] = {}

    def _write(text: str) -> None:
        sys.stderr.write(text)
        sys.stderr.flush()
        if log_file:
            log_file.write(text)
            log_file.flush()

    with client.messages.stream(**create_kwargs) as stream:
        for event in stream:
            event_dict = event.model_dump() if hasattr(event, "model_dump") else {"type": str(type(event).__name__)}
            raw_events.append(event_dict)
            event_type = getattr(event, "type", "")

            if event_type == "message_start":
                msg = getattr(event, "message", None)
                if msg:
                    model = getattr(msg, "model", "") or ""
                    u = getattr(msg, "usage", None)
                    if u:
                        usage_data["input_tokens"] = getattr(u, "input_tokens", 0)

            elif event_type == "content_block_start":
                current_block_idx = getattr(event, "index", current_block_idx + 1)
                cb = getattr(event, "content_block", None)
                if cb:
                    current_block_type = getattr(cb, "type", "")
                    if current_block_type == "tool_use":
                        tool_blocks[current_block_idx] = {
                            "id": getattr(cb, "id", ""),
                            "name": getattr(cb, "name", ""),
                            "input_json": "",
                        }
                        _write(f"\n[tool_call #{len(tool_blocks) - 1}: {getattr(cb, 'name', '')}]\n")
                    elif current_block_type == "thinking":
                        if not reasoning_parts:
                            _write("\n[reasoning]\n")
                    elif current_block_type == "text":
                        if not content_parts:
                            _write("\n[content]\n")

            elif event_type == "content_block_delta":
                delta = getattr(event, "delta", None)
                if delta:
                    delta_type = getattr(delta, "type", "")
                    if delta_type == "text_delta":
                        text = getattr(delta, "text", "")
                        if text:
                            content_parts.append(text)
                            _write(text)
                    elif delta_type == "thinking_delta":
                        thinking = getattr(delta, "thinking", "")
                        if thinking:
                            reasoning_parts.append(thinking)
                            _write(thinking)
                    elif delta_type == "input_json_delta":
                        partial = getattr(delta, "partial_json", "")
                        if partial and current_block_idx in tool_blocks:
                            tool_blocks[current_block_idx]["input_json"] += partial
                            _write(partial)

            elif event_type == "content_block_stop":
                block_idx = getattr(event, "index", current_block_idx)
                if block_idx in tool_blocks:
                    _flush_tool_block(tool_blocks[block_idx], block_idx, slide_xmls, on_slide_ready)

            elif event_type == "message_delta":
                delta = getattr(event, "delta", None)
                if delta:
                    stop_reason = getattr(delta, "stop_reason", None)
                u = getattr(event, "usage", None)
                if u:
                    usage_data["output_tokens"] = getattr(u, "output_tokens", 0)

    content_text = "".join(content_parts)
    reasoning_text = "".join(reasoning_parts)

    tool_calls_raw: list[dict] = []
    for idx in sorted(tool_blocks.keys()):
        tb = tool_blocks[idx]
        tool_calls_raw.append({
            "index": idx,
            "id": tb["id"],
            "name": tb["name"],
            "arguments_raw": tb["input_json"],
        })
        if idx not in {k for k in slide_xmls}:
            _flush_tool_block(tb, idx, slide_xmls, on_slide_ready)

    slide_sizes = {str(p): len(x) for p, x in sorted(slide_xmls.items())}
    response_data: dict = {
        "model": model,
        "stop_reason": stop_reason,
        "usage": usage_data,
        "event_count": len(raw_events),
        "tool_call_count": len(tool_blocks),
        "slide_pages_received": sorted(slide_xmls.keys()),
        "slide_xml_sizes_chars": slide_sizes,
        "total_xml_chars": sum(slide_sizes.values()),
        "content_text_length": len(content_text),
        "reasoning_text_length": len(reasoning_text),
    }

    return slide_xmls, response_data, raw_events, tool_calls_raw, content_text, reasoning_text

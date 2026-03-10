"""OpenAI Responses API client for streaming LLM calls with function call extraction.

Uses the newer ``client.responses.create()`` endpoint instead of Chat Completions.
Recommended when routing through providers like IKunCode that support the Responses API.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from typing import IO, Any

import httpx
import openai

from .. import ApiConfig
from ..logging_config import get_logger
from ..system_prompt import WRITE_SLIDE_XML_TOOL_RESPONSES
from .openai_client import LLMResult

logger = get_logger("api_responses")

_DEFAULT_API_CFG = ApiConfig()


def call_llm_responses(
    messages: list[dict[str, Any]],
    api_cfg: ApiConfig = _DEFAULT_API_CFG,
    max_tokens: int = 128000,
    stream_log_path: str = "",
    reasoning_effort: str = "medium",
    estimated_response_seconds: float = 0,
    on_slide_ready: Callable[[int, str], None] | None = None,
) -> LLMResult:
    """Call the OpenAI Responses API with streaming and extract slide XMLs from function calls.

    The Responses API uses ``client.responses.create()`` with ``input`` items
    instead of ``messages``, and ``instructions`` instead of a system message.
    Streaming events are semantic (``response.function_call_arguments.delta``, etc.).
    """
    min_timeout = 600
    timeout_seconds = max(estimated_response_seconds * 3, min_timeout)
    connect_timeout = 30.0
    timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout)

    client_kwargs: dict[str, Any] = {"timeout": timeout, "max_retries": 0}
    if api_cfg.api_base_url:
        client_kwargs["base_url"] = api_cfg.api_base_url
    if api_cfg.api_key:
        client_kwargs["api_key"] = api_cfg.api_key
    if api_cfg.extra_headers:
        client_kwargs["default_headers"] = api_cfg.extra_headers

    client = openai.OpenAI(**client_kwargs)

    logger.info(
        "HTTP timeout: connect=%.0fs, read/stream=%.0fs (3× estimated ~%.0fs), no retries",
        connect_timeout,
        timeout_seconds,
        estimated_response_seconds,
    )

    instructions, input_items = _convert_messages_to_input(messages)

    tools = [WRITE_SLIDE_XML_TOOL_RESPONSES]

    logger.info(
        "Calling %s Responses API (streaming, function_call, reasoning=%s, max_tokens=%d)...",
        api_cfg.model_name,
        reasoning_effort,
        max_tokens,
    )
    t0 = time.time()

    create_kwargs: dict[str, Any] = {
        "model": api_cfg.model_name,
        "input": input_items,
        "tools": tools,
        "stream": True,
    }
    if instructions:
        create_kwargs["instructions"] = instructions
    if reasoning_effort:
        create_kwargs["reasoning"] = {"effort": reasoning_effort}
    create_kwargs["max_output_tokens"] = max_tokens

    stream = client.responses.create(**create_kwargs)

    log_file = open(stream_log_path, "w", encoding="utf-8") if stream_log_path else None  # noqa: SIM115

    try:
        stream_result = _consume_stream(stream, log_file, on_slide_ready=on_slide_ready)
    finally:
        if log_file:
            log_file.close()

    slide_xmls, response_data, raw_events, tool_calls_raw, content_text, reasoning_text = stream_result
    elapsed = time.time() - t0
    response_data["elapsed_seconds"] = round(elapsed, 2)
    response_data["content_text"] = content_text
    response_data["reasoning_text"] = reasoning_text
    sys.stderr.write("\n")
    sys.stderr.flush()

    logger.info("Responses API streaming complete in %.1fs", elapsed)

    usage = response_data.get("usage") or {}
    input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens")
    output_tokens = usage.get("output_tokens") or usage.get("completion_tokens")

    if output_tokens and elapsed > 0:
        tps = output_tokens / elapsed
        response_data["output_tokens_per_second"] = round(tps, 1)
        logger.info(
            "Usage: %s input, %s output (%.1f tok/s)",
            f"{input_tokens:,}" if isinstance(input_tokens, int) else "?",
            f"{output_tokens:,}" if isinstance(output_tokens, int) else "?",
            tps,
        )

    if tool_calls_raw:
        logger.info("Function calls: %d × write_slide_xml (%d slides received)", len(tool_calls_raw), len(slide_xmls))
    else:
        logger.warning("No function calls received from the model!")
        if content_text:
            logger.warning("Model returned content text instead of function calls:")
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


def _convert_messages_to_input(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Convert Chat Completions messages to Responses API input format.

    Returns (instructions, input_items) where instructions is the system prompt
    and input_items is the list of input items for the Responses API.
    """
    instructions = ""
    input_items: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            instructions = content if isinstance(content, str) else ""
            continue

        if isinstance(content, str):
            input_items.append({"role": role, "content": content})
        elif isinstance(content, list):
            converted: list[dict[str, Any]] = []
            for part in content:
                ptype = part.get("type", "")
                if ptype == "text":
                    converted.append({"type": "input_text", "text": part["text"]})
                elif ptype == "image_url":
                    url = part["image_url"]["url"]
                    detail = part["image_url"].get("detail", "auto")
                    converted.append({
                        "type": "input_image",
                        "image_url": url,
                        "detail": detail,
                    })
            input_items.append({"role": role, "content": converted})

    return instructions, input_items


def _flush_function_call(
    name: str,
    arguments: str,
    call_id: str,
    idx: int,
    slide_xmls: dict[int, str],
    on_slide_ready: Callable[[int, str], None] | None,
) -> dict[str, Any] | None:
    """Parse a completed function call and save the slide XML immediately."""
    if name != "write_slide_xml":
        logger.warning("Unexpected function call: %s", name)
        return None
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError:
        logger.error("Failed to parse function call arguments (index %d)", idx)
        return None
    page_num = args.get("page_num")
    slide_xml = args.get("slide_xml", "")
    if page_num is not None:
        slide_xmls[page_num] = slide_xml
        logger.debug("Slide %3d: %d chars XML", page_num, len(slide_xml))
        if on_slide_ready:
            on_slide_ready(page_num, slide_xml)
    return {"index": idx, "id": call_id, "name": name, "arguments_raw": arguments}


def _consume_stream(
    stream: Any,
    log_file: IO[str] | None,
    *,
    on_slide_ready: Callable[[int, str], None] | None = None,
) -> tuple[dict[int, str], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], str, str]:
    """Consume the Responses API streaming events."""
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    raw_events: list[dict[str, Any]] = []
    slide_xmls: dict[int, str] = {}
    tool_calls_raw: list[dict[str, Any]] = []

    current_fc_idx: int = 0
    current_fc_name: str = ""
    current_fc_args: str = ""
    current_fc_call_id: str = ""
    in_function_call: bool = False

    model: str = ""
    usage_data: dict[str, Any] | None = None

    def _write(text: str) -> None:
        sys.stderr.write(text)
        sys.stderr.flush()
        if log_file:
            log_file.write(text)
            log_file.flush()

    for event in stream:
        event_dict = event.model_dump() if hasattr(event, "model_dump") else {}
        raw_events.append(event_dict)
        event_type = getattr(event, "type", "")

        if event_type == "response.created":
            resp = getattr(event, "response", None)
            if resp:
                model = getattr(resp, "model", "") or ""

        elif event_type == "response.output_item.added":
            item = getattr(event, "item", None)
            if item:
                item_type = getattr(item, "type", "")
                if item_type == "function_call":
                    if in_function_call:
                        result = _flush_function_call(
                            current_fc_name, current_fc_args, current_fc_call_id,
                            current_fc_idx, slide_xmls, on_slide_ready,
                        )
                        if result:
                            tool_calls_raw.append(result)
                    current_fc_name = getattr(item, "name", "") or ""
                    current_fc_call_id = getattr(item, "call_id", "") or ""
                    current_fc_args = ""
                    current_fc_idx = getattr(event, "output_index", current_fc_idx + 1)
                    in_function_call = True
                    _write(f"\n[function_call #{current_fc_idx}: {current_fc_name}]\n")

        elif event_type == "response.function_call_arguments.delta":
            delta = getattr(event, "delta", "")
            if delta:
                current_fc_args += delta
                _write(delta)

        elif event_type == "response.function_call_arguments.done":
            arguments = getattr(event, "arguments", current_fc_args)
            result = _flush_function_call(
                current_fc_name, arguments, current_fc_call_id,
                current_fc_idx, slide_xmls, on_slide_ready,
            )
            if result:
                tool_calls_raw.append(result)
            in_function_call = False

        elif event_type == "response.output_text.delta":
            delta = getattr(event, "delta", "")
            if delta:
                if not content_parts:
                    _write("\n[content]\n")
                content_parts.append(delta)
                _write(delta)

        elif event_type == "response.reasoning.delta":
            delta = getattr(event, "delta", "")
            if delta:
                if not reasoning_parts:
                    _write("\n[reasoning]\n")
                reasoning_parts.append(delta)
                _write(delta)

        elif event_type == "response.completed":
            resp = getattr(event, "response", None)
            if resp:
                u = getattr(resp, "usage", None)
                if u:
                    usage_data = {
                        "input_tokens": getattr(u, "input_tokens", 0),
                        "output_tokens": getattr(u, "output_tokens", 0),
                        "total_tokens": getattr(u, "total_tokens", 0),
                    }

    if in_function_call and current_fc_args:
        result = _flush_function_call(
            current_fc_name, current_fc_args, current_fc_call_id,
            current_fc_idx, slide_xmls, on_slide_ready,
        )
        if result:
            tool_calls_raw.append(result)

    content_text = "".join(content_parts)
    reasoning_text = "".join(reasoning_parts)

    slide_sizes = {str(p): len(x) for p, x in sorted(slide_xmls.items())}
    response_data: dict[str, Any] = {
        "model": model,
        "usage": usage_data,
        "event_count": len(raw_events),
        "tool_call_count": len(tool_calls_raw),
        "slide_pages_received": sorted(slide_xmls.keys()),
        "slide_xml_sizes_chars": slide_sizes,
        "total_xml_chars": sum(slide_sizes.values()),
        "content_text_length": len(content_text),
        "reasoning_text_length": len(reasoning_text),
    }

    return slide_xmls, response_data, raw_events, tool_calls_raw, content_text, reasoning_text

"""OpenAI API client for streaming LLM calls with tool extraction."""

from __future__ import annotations

import json
import sys
import time

import httpx
import openai

from .logging_config import get_logger
from .system_prompt import WRITE_SLIDE_XML_TOOL

logger = get_logger("api_client")


class LLMResult:
    """Container for LLM API call results."""

    def __init__(
        self,
        slide_xmls: dict[int, str],
        response_data: dict,
        raw_chunks: list[dict],
        tool_calls_raw: list[dict],
        content_text: str,
        reasoning_text: str,
    ):
        self.slide_xmls = slide_xmls
        self.response_data = response_data
        self.raw_chunks = raw_chunks
        self.tool_calls_raw = tool_calls_raw
        self.content_text = content_text
        self.reasoning_text = reasoning_text


def call_llm(
    messages: list[dict],
    api_base_url: str = "",
    api_key: str = "",
    model_name: str = "gpt-5.4",
    max_tokens: int = 128000,
    stream_log_path: str = "",
    reasoning_effort: str = "medium",
    estimated_response_seconds: float = 0,
) -> LLMResult:
    """Call the LLM API with streaming and extract slide XMLs from tool calls.

    Streams output to stderr in real-time and writes to stream_log_path.
    The timeout is set dynamically: max(estimated_response_seconds * 3, 600) seconds,
    ensuring enough headroom for slow responses.
    """
    min_timeout = 600
    timeout_seconds = max(estimated_response_seconds * 3, min_timeout)
    timeout = httpx.Timeout(timeout_seconds, connect=30.0)

    client_kwargs: dict = {"timeout": timeout, "max_retries": 0}
    if api_base_url:
        client_kwargs["base_url"] = api_base_url
    if api_key:
        client_kwargs["api_key"] = api_key
    client = openai.OpenAI(**client_kwargs)

    logger.info(
        "HTTP timeout: %.0fs (3× estimated ~%.0fs response), no retries",
        timeout_seconds,
        estimated_response_seconds,
    )

    tools = [WRITE_SLIDE_XML_TOOL]

    logger.info(
        "Calling %s API (streaming, tool_calling, parallel, reasoning=%s, max_tokens=%d)...",
        model_name,
        reasoning_effort,
        max_tokens,
    )
    t0 = time.time()

    create_kwargs: dict = {
        "model": model_name,
        "messages": messages,
        "tools": tools,
        "tool_choice": "required",
        "parallel_tool_calls": True,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if reasoning_effort:
        create_kwargs["reasoning_effort"] = reasoning_effort

    stream = client.chat.completions.create(**create_kwargs)  # type: ignore[call-overload]

    log_file = open(stream_log_path, "w", encoding="utf-8") if stream_log_path else None  # noqa: SIM115

    try:
        stream_result = _consume_stream(stream, log_file)
    finally:
        if log_file:
            log_file.close()

    slide_xmls, response_data, raw_chunks, tool_calls_raw, content_text, reasoning_text = stream_result
    elapsed = time.time() - t0
    response_data["elapsed_seconds"] = round(elapsed, 2)
    response_data["content_text"] = content_text
    response_data["reasoning_text"] = reasoning_text
    sys.stderr.write("\n")
    sys.stderr.flush()

    logger.info("API streaming complete in %.1fs", elapsed)

    usage = response_data.get("usage") or {}
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")

    if completion_tokens and elapsed > 0:
        tps = completion_tokens / elapsed
        response_data["output_tokens_per_second"] = round(tps, 1)
        logger.info(
            "Usage: %s input, %s output (%.1f tok/s) | Finish: %s",
            f"{prompt_tokens:,}" if isinstance(prompt_tokens, int) else "?",
            f"{completion_tokens:,}" if isinstance(completion_tokens, int) else "?",
            tps,
            response_data.get("finish_reason", "?"),
        )
    elif prompt_tokens or completion_tokens:
        logger.info(
            "Usage: %s input, %s output | Finish: %s",
            f"{prompt_tokens:,}" if isinstance(prompt_tokens, int) else "?",
            f"{completion_tokens:,}" if isinstance(completion_tokens, int) else "?",
            response_data.get("finish_reason", "?"),
        )

    if tool_calls_raw:
        logger.info("Tool calls: %d × write_slide_xml (%d slides received)", len(tool_calls_raw), len(slide_xmls))
    else:
        logger.warning("No tool calls received from the model!")
        if content_text:
            logger.warning("Model returned content text instead of tool calls:")
            for line in content_text.strip().splitlines()[:10]:
                logger.warning("  %s", line)

    return LLMResult(
        slide_xmls=slide_xmls,
        response_data=response_data,
        raw_chunks=raw_chunks,
        tool_calls_raw=tool_calls_raw,
        content_text=content_text,
        reasoning_text=reasoning_text,
    )


def _consume_stream(
    stream,  # type: ignore[type-arg]
    log_file,  # type: ignore[type-arg]
) -> tuple[dict[int, str], dict, list[dict], list[dict], str, str]:
    """Consume the streaming response, printing to stderr and accumulating tool calls."""
    tool_calls_acc: dict[int, dict] = {}
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    finish_reason: str | None = None
    model: str = ""
    usage_data: dict | None = None
    raw_chunks: list[dict] = []
    chunk_count = 0
    current_tc_idx: int | None = None

    def _write(text: str) -> None:
        sys.stderr.write(text)
        sys.stderr.flush()
        if log_file:
            log_file.write(text)
            log_file.flush()

    for chunk in stream:
        chunk_count += 1
        chunk_dict = chunk.model_dump() if hasattr(chunk, "model_dump") else {}
        raw_chunks.append(chunk_dict)

        if chunk.model and not model:
            model = chunk.model

        if chunk.usage:
            usage_data = {
                "prompt_tokens": chunk.usage.prompt_tokens,
                "completion_tokens": chunk.usage.completion_tokens,
                "total_tokens": chunk.usage.total_tokens,
            }

        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta
        if chunk.choices[0].finish_reason:
            finish_reason = chunk.choices[0].finish_reason

        if delta.content:
            if not content_parts:
                _write("\n[content]\n")
            content_parts.append(delta.content)
            _write(delta.content)

        reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
        if reasoning:
            if not reasoning_parts:
                _write("\n[reasoning]\n")
            reasoning_parts.append(reasoning)
            _write(reasoning)

        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in tool_calls_acc:
                    tool_calls_acc[idx] = {
                        "id": tc_delta.id or "",
                        "name": "",
                        "arguments": "",
                    }
                if tc_delta.function:
                    if tc_delta.function.name:
                        tool_calls_acc[idx]["name"] = tc_delta.function.name
                    if tc_delta.function.arguments:
                        frag = tc_delta.function.arguments
                        tool_calls_acc[idx]["arguments"] += frag

                        if idx != current_tc_idx:
                            if current_tc_idx is not None:
                                _write("\n")
                            name = tool_calls_acc[idx]["name"] or "write_slide_xml"
                            _write(f"\n[tool_call #{idx}: {name}]\n")
                            current_tc_idx = idx

                        _write(frag)

    content_text = "".join(content_parts)
    reasoning_text = "".join(reasoning_parts)

    slide_xmls: dict[int, str] = {}
    tool_calls_raw: list[dict] = []

    for idx in sorted(tool_calls_acc.keys()):
        tc = tool_calls_acc[idx]
        tool_calls_raw.append({
            "index": idx,
            "id": tc["id"],
            "name": tc["name"],
            "arguments_raw": tc["arguments"],
        })

        if tc["name"] != "write_slide_xml":
            logger.warning("Unexpected tool call: %s", tc["name"])
            continue
        try:
            args = json.loads(tc["arguments"])
        except json.JSONDecodeError:
            logger.error("Failed to parse tool call arguments (index %d)", idx)
            continue

        page_num = args.get("page_num")
        slide_xml = args.get("slide_xml", "")
        if page_num is not None:
            slide_xmls[page_num] = slide_xml
            logger.debug("Slide %3d: %d chars XML", page_num, len(slide_xml))

    slide_sizes = {str(p): len(x) for p, x in sorted(slide_xmls.items())}
    response_data: dict = {
        "model": model,
        "finish_reason": finish_reason,
        "usage": usage_data,
        "chunk_count": chunk_count,
        "tool_call_count": len(tool_calls_acc),
        "slide_pages_received": sorted(slide_xmls.keys()),
        "slide_xml_sizes_chars": slide_sizes,
        "total_xml_chars": sum(slide_sizes.values()),
        "content_text_length": len(content_text),
        "reasoning_text_length": len(reasoning_text),
    }

    return slide_xmls, response_data, raw_chunks, tool_calls_raw, content_text, reasoning_text

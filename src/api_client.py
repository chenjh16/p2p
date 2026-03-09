from __future__ import annotations

import json
import time

import openai

from .logging_config import get_logger
from .system_prompt import WRITE_SLIDE_XML_TOOL

logger = get_logger("api_client")


def call_llm(
    messages: list[dict],
    api_base_url: str = "",
    api_key: str = "",
    model_name: str = "gpt-5.4",
    max_tokens: int = 128000,
) -> dict[int, str]:
    """Call the LLM API and extract slide XMLs from tool calls.

    Returns a dict mapping page_num -> slide_xml.
    """
    client_kwargs: dict = {}
    if api_base_url:
        client_kwargs["base_url"] = api_base_url
    if api_key:
        client_kwargs["api_key"] = api_key
    client = openai.OpenAI(**client_kwargs)

    tools = [WRITE_SLIDE_XML_TOOL]

    logger.info(
        "Calling %s API (tool_calling, parallel, max_tokens=%d)...",
        model_name,
        max_tokens,
    )
    t0 = time.time()

    response = client.chat.completions.create(  # type: ignore[call-overload]
        model=model_name,
        messages=messages,
        tools=tools,
        tool_choice="required",
        parallel_tool_calls=True,
        max_tokens=max_tokens,
    )

    elapsed = time.time() - t0
    choice = response.choices[0]
    usage = response.usage

    logger.info("API response received in %.1fs", elapsed)
    if usage:
        logger.info(
            "Usage: %d input tokens, %d output tokens | Finish reason: %s",
            usage.prompt_tokens,
            usage.completion_tokens,
            choice.finish_reason,
        )

    slide_xmls: dict[int, str] = {}
    tool_calls = choice.message.tool_calls or []
    logger.info("Tool calls: %d × write_slide_xml", len(tool_calls))

    for tc in tool_calls:
        if tc.function.name != "write_slide_xml":
            logger.warning("Unexpected tool call: %s", tc.function.name)
            continue
        try:
            args = json.loads(tc.function.arguments)
        except json.JSONDecodeError:
            logger.error(
                "Failed to parse tool call arguments for %s", tc.id
            )
            continue

        page_num = args.get("page_num")
        slide_xml = args.get("slide_xml", "")
        if page_num is not None:
            slide_xmls[page_num] = slide_xml
            logger.debug(
                "Slide %3d: %d chars XML",
                page_num,
                len(slide_xml),
            )

    return slide_xmls

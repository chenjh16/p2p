"""Persist intermediate artifacts (images, messages, slide XMLs) from the pipeline."""

from __future__ import annotations

import json
import os
from datetime import datetime

from .logging_config import get_logger

logger = get_logger("artifacts")


class ArtifactStore:
    """Manages saving intermediate artifacts from the conversion pipeline."""

    def __init__(self, pdf_path: str, *, dry_run: bool = False):
        base = os.path.splitext(os.path.basename(pdf_path))[0]
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        prefix = "dry-run" if dry_run else "run"
        self.root = f"{prefix}-{base}-{timestamp}"
        self.pages_dir = os.path.join(self.root, "pages")
        self.slides_dir = os.path.join(self.root, "slides")
        os.makedirs(self.pages_dir, exist_ok=True)
        os.makedirs(self.slides_dir, exist_ok=True)
        self._api_response_idx = 0
        self._stream_chunks_idx = 0
        logger.info("Artifact directory: %s/", self.root)

    def save_page_images(self, pages: list[tuple[bytes, dict]]) -> None:
        """Write each page image to a PNG file in the pages directory."""
        for img_bytes, meta in pages:
            page_num = meta["page_num"]
            path = os.path.join(self.pages_dir, f"page_{page_num:03d}.png")
            with open(path, "wb") as f:
                f.write(img_bytes)
        logger.info("Saved %d page images", len(pages))

    def save_messages(self, messages: list[dict], pages_dir: str | None = None) -> None:
        """Save messages to JSON (light and full variants)."""
        light = _strip_base64(messages, pages_dir or self.pages_dir)
        with open(os.path.join(self.root, "messages.json"), "w", encoding="utf-8") as f:
            json.dump(light, f, ensure_ascii=False, indent=2)
        with open(os.path.join(self.root, "messages_full.json"), "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False)
        logger.info("Saved messages (light + full)")

    def save_system_prompt(self, prompt: str) -> None:
        """Write the system prompt to a text file."""
        with open(os.path.join(self.root, "system_prompt.txt"), "w", encoding="utf-8") as f:
            f.write(prompt)

    def save_tools(self, tools: list[dict]) -> None:
        """Write tool definitions to JSON."""
        with open(os.path.join(self.root, "tools.json"), "w", encoding="utf-8") as f:
            json.dump(tools, f, indent=2)

    def save_token_estimate(self, token_est: dict) -> None:
        """Write token estimate and cost info to JSON."""
        with open(os.path.join(self.root, "token_estimate.json"), "w", encoding="utf-8") as f:
            json.dump(token_est, f, indent=2)
        logger.info("Saved token estimate")

    def save_api_response(self, response_data: dict) -> None:
        """Write API response metadata to JSON."""
        suffix = f"_{self._api_response_idx}" if self._api_response_idx > 0 else ""
        path = os.path.join(self.root, f"api_response{suffix}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(response_data, f, ensure_ascii=False, indent=2)
        self._api_response_idx += 1
        logger.info("Saved API response → %s", os.path.basename(path))

    def save_stream_chunks(self, chunks: list[dict]) -> None:
        """Write raw stream chunks to JSONL."""
        suffix = f"_{self._stream_chunks_idx}" if self._stream_chunks_idx > 0 else ""
        path = os.path.join(self.root, f"stream_chunks{suffix}.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for chunk in chunks:
                f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        self._stream_chunks_idx += 1
        logger.info("Saved %d stream chunks → %s", len(chunks), os.path.basename(path))

    def save_tool_calls(self, tool_calls: list[dict]) -> None:
        """Write tool call payloads to JSON."""
        suffix = f"_{self._api_response_idx - 1}" if self._api_response_idx > 1 else ""
        path = os.path.join(self.root, f"tool_calls{suffix}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(tool_calls, f, ensure_ascii=False, indent=2)
        logger.info("Saved %d tool calls → %s", len(tool_calls), os.path.basename(path))

    def save_slide_xmls(self, slide_xmls: dict[int, str]) -> None:
        """Write each slide XML to a separate file in the slides directory."""
        for page_num, xml_str in sorted(slide_xmls.items()):
            path = os.path.join(self.slides_dir, f"slide_{page_num:03d}.xml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(xml_str)
        logger.info("Saved %d slide XMLs", len(slide_xmls))

    def save_metadata(self, metadata: dict) -> None:
        """Write run metadata (paths, counts, timing) to JSON."""
        with open(os.path.join(self.root, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

    def save_run_params(self, params: dict) -> None:
        """Write the CLI / execution parameters used for this run."""
        with open(os.path.join(self.root, "run_params.json"), "w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False, indent=2)
        logger.info("Saved run parameters")

    def save_reasoning(self, reasoning_text: str, batch_idx: int = 0) -> None:
        """Write the model's thinking/reasoning output to a text file."""
        if not reasoning_text:
            return
        suffix = f"_{batch_idx}" if batch_idx > 0 else ""
        path = os.path.join(self.root, f"reasoning{suffix}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(reasoning_text)
        logger.info("Saved reasoning (%d chars) → %s", len(reasoning_text), os.path.basename(path))

    def save_content_text(self, content_text: str, batch_idx: int = 0) -> None:
        """Write the model's non-tool-call content output to a text file."""
        if not content_text:
            return
        suffix = f"_{batch_idx}" if batch_idx > 0 else ""
        path = os.path.join(self.root, f"content{suffix}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content_text)
        logger.info("Saved content text (%d chars) → %s", len(content_text), os.path.basename(path))


def _strip_base64(messages: list[dict], pages_dir: str) -> list[dict]:
    """Create a copy of messages with base64 images replaced by file paths."""
    import copy

    result = copy.deepcopy(messages)
    img_idx = 0
    for msg in result:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if part.get("type") == "image_url":
                part["image_url"]["url"] = os.path.join(
                    pages_dir, f"page_{img_idx:03d}.png"
                )
                img_idx += 1
    return result

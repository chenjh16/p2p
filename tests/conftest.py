"""Shared fixtures for all test modules."""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import fitz
import pytest

MOCK_OPENAI_PORT = 19876
MOCK_ANTHROPIC_PORT = 19877
MOCK_BASE_URL = f"http://127.0.0.1:{MOCK_OPENAI_PORT}/v1"
MOCK_ANTHROPIC_URL = f"http://127.0.0.1:{MOCK_ANTHROPIC_PORT}"

SAMPLE_SLIDE_XML = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr/>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="2" name="Title"/>
          <p:cNvSpPr txBox="1"/>
          <p:nvPr/>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm>
            <a:off x="914400" y="914400"/>
            <a:ext cx="7315200" cy="914400"/>
          </a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        </p:spPr>
        <p:txBody>
          <a:bodyPr wrap="square" rtlCol="0"/>
          <a:lstStyle/>
          <a:p>
            <a:r>
              <a:rPr lang="en-US" sz="2400"/>
              <a:t>Test Slide Page {page_num}</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>"""


def _build_sse_response(page_count: int) -> str:
    """Build a streaming SSE response with tool calls for each page."""
    chunks = []

    for page_num in range(page_count):
        slide_xml = SAMPLE_SLIDE_XML.format(page_num=page_num)
        args_json = json.dumps({"page_num": page_num, "slide_xml": slide_xml})

        chunk_data = {
            "id": f"chatcmpl-test-{page_num}",
            "object": "chat.completion.chunk",
            "model": "mock-gpt-5.4",
            "choices": [{
                "index": 0,
                "delta": {
                    "tool_calls": [{
                        "index": page_num,
                        "id": f"call_{page_num}",
                        "type": "function",
                        "function": {
                            "name": "write_slide_xml",
                            "arguments": args_json,
                        },
                    }],
                },
                "finish_reason": None,
            }],
        }
        chunks.append(f"data: {json.dumps(chunk_data)}\n\n")

    finish_chunk = {
        "id": "chatcmpl-test-done",
        "object": "chat.completion.chunk",
        "model": "mock-gpt-5.4",
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 500 * page_count,
            "total_tokens": 1000 + 500 * page_count,
        },
    }
    chunks.append(f"data: {json.dumps(finish_chunk)}\n\n")
    chunks.append("data: [DONE]\n\n")

    return "".join(chunks)


def _build_anthropic_sse_response(page_count: int) -> str:
    """Build Anthropic-format streaming SSE response with tool_use content blocks."""
    events = []

    events.append(
        f"event: message_start\n"
        f"data: {json.dumps({'type': 'message_start', 'message': {'id': 'msg_test', 'type': 'message', 'role': 'assistant', 'model': 'mock-claude', 'content': [], 'usage': {'input_tokens': 1000, 'output_tokens': 0}}})}\n\n"
    )

    for page_num in range(page_count):
        slide_xml = SAMPLE_SLIDE_XML.format(page_num=page_num)
        args_json = json.dumps({"page_num": page_num, "slide_xml": slide_xml})

        events.append(
            f"event: content_block_start\n"
            f"data: {json.dumps({'type': 'content_block_start', 'index': page_num, 'content_block': {'type': 'tool_use', 'id': f'toolu_{page_num}', 'name': 'write_slide_xml', 'input': {}}})}\n\n"
        )
        events.append(
            f"event: content_block_delta\n"
            f"data: {json.dumps({'type': 'content_block_delta', 'index': page_num, 'delta': {'type': 'input_json_delta', 'partial_json': args_json}})}\n\n"
        )
        events.append(
            f"event: content_block_stop\n"
            f"data: {json.dumps({'type': 'content_block_stop', 'index': page_num})}\n\n"
        )

    events.append(
        f"event: message_delta\n"
        f"data: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': {'output_tokens': 500 * page_count}})}\n\n"
    )
    events.append(
        f"event: message_stop\n"
        f"data: {json.dumps({'type': 'message_stop'})}\n\n"
    )

    return "".join(events)


class MockOpenAIHandler(BaseHTTPRequestHandler):
    """Mock handler that returns streaming tool call responses."""

    page_count = 1

    def do_POST(self):  # noqa: N802
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len)) if content_len else {}

        messages = body.get("messages", [])
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                MockOpenAIHandler.page_count = sum(
                    1 for p in content if p.get("type") == "image_url"
                )

        sse_body = _build_sse_response(MockOpenAIHandler.page_count)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(sse_body.encode())

    def log_message(self, format, *args):  # noqa: A002
        pass


class MockAnthropicHandler(BaseHTTPRequestHandler):
    """Mock handler for Anthropic Messages API streaming responses."""

    page_count = 1

    def do_POST(self):  # noqa: N802
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len)) if content_len else {}

        messages = body.get("messages", [])
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                MockAnthropicHandler.page_count = sum(
                    1 for p in content if p.get("type") == "image"
                )

        sse_body = _build_anthropic_sse_response(MockAnthropicHandler.page_count)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(sse_body.encode())

    def log_message(self, format, *args):  # noqa: A002
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mock_server():
    """Start a mock OpenAI server for the test module."""
    server = HTTPServer(("127.0.0.1", MOCK_OPENAI_PORT), MockOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.2)
    yield server
    server.shutdown()


@pytest.fixture(scope="module")
def mock_anthropic_server():
    """Start a mock Anthropic server for the test module."""
    server = HTTPServer(("127.0.0.1", MOCK_ANTHROPIC_PORT), MockAnthropicHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.2)
    yield server
    server.shutdown()


@pytest.fixture()
def sample_pdf(tmp_path):
    """Create a minimal 2-page PDF."""
    pdf_path = str(tmp_path / "test.pdf")
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=720, height=405)
        page.insert_text((100, 200), f"Test Page {i}", fontsize=24)
    doc.save(pdf_path)
    doc.close()
    return pdf_path


@pytest.fixture()
def three_page_pdf(tmp_path):
    """Create a 3-page PDF for batch/continue testing."""
    pdf_path = str(tmp_path / "three.pdf")
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page(width=720, height=405)
        page.insert_text((100, 200), f"Page {i}", fontsize=20)
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def create_partial_run(tmp_path, pdf_path, *, pages_received: list[int], total_pages: int = 3) -> str:
    """Create a fake partial run directory with some slides for continue-run tests."""
    import shutil

    run_dir = str(tmp_path / "runs" / "run-test-20260310-120000")
    slides_dir = os.path.join(run_dir, "slides")
    pages_dir = os.path.join(run_dir, "pages")
    os.makedirs(slides_dir, exist_ok=True)
    os.makedirs(pages_dir, exist_ok=True)

    shutil.copy2(pdf_path, os.path.join(run_dir, os.path.basename(pdf_path)))

    for pnum in pages_received:
        xml = SAMPLE_SLIDE_XML.format(page_num=pnum)
        with open(os.path.join(slides_dir, f"slide_{pnum:03d}.xml"), "w") as f:
            f.write(xml)

    metadata = {
        "success": False,
        "pdf_pages": total_pages,
        "slide_width_pt": 720,
        "slide_height_pt": 405,
        "aspect_ratio": "16:9",
        "slides_received": len(pages_received),
        "runtime_params": {
            "pdf_path": os.path.abspath(pdf_path),
            "api_provider": "openai",
            "model": "gpt-5.4",
            "dpi": 96,
            "enable_animations": False,
            "reasoning_effort": "medium",
            "prompt_lang": "en",
            "output_tps": 50.0,
            "skip_postprocess": True,
            "page_indices": None,
        },
    }
    with open(os.path.join(run_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f)

    return run_dir

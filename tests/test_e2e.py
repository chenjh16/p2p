"""End-to-end test using a mock OpenAI-compatible server."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import fitz
import pytest
from pptx import Presentation

MOCK_PORT = 19876
MOCK_BASE_URL = f"http://127.0.0.1:{MOCK_PORT}/v1"

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


class MockOpenAIHandler(BaseHTTPRequestHandler):
    """Mock handler that returns streaming tool call responses."""

    page_count = 1

    def do_POST(self):  # noqa: N802
        """Handle POST requests to the chat completions endpoint."""
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
        """Suppress request logging."""


@pytest.fixture(scope="module")
def mock_server():
    """Start a mock OpenAI server for the test module."""
    server = HTTPServer(("127.0.0.1", MOCK_PORT), MockOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.2)
    yield server
    server.shutdown()


@pytest.fixture()
def sample_pdf(tmp_path):
    """Create a minimal 2-page PDF for testing."""
    pdf_path = str(tmp_path / "test.pdf")
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=720, height=405)
        page.insert_text((100, 200), f"Test Page {i}", fontsize=24)
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def test_dry_run(sample_pdf, tmp_path):
    """Dry-run should produce artifacts without calling the API."""
    os.chdir(tmp_path)
    from src.dry_run import run_dry
    from src.logging_config import setup_logging

    setup_logging("WARNING")
    output_dir = run_dry(
        pdf_path=sample_pdf,
        dpi=96,
        enable_animations=False,
        model_name="gpt-5.4",
        batch_size=25,
    )

    assert os.path.isdir(output_dir)
    assert os.path.isfile(os.path.join(output_dir, "metadata.json"))
    assert os.path.isfile(os.path.join(output_dir, "messages.json"))
    assert os.path.isfile(os.path.join(output_dir, "system_prompt.txt"))
    assert os.path.isfile(os.path.join(output_dir, "token_estimate.json"))
    assert os.path.isfile(os.path.join(output_dir, "run_params.json"))
    assert os.path.isfile(os.path.join(output_dir, "pages", "page_000.png"))
    assert os.path.isfile(os.path.join(output_dir, "pages", "page_001.png"))

    with open(os.path.join(output_dir, "metadata.json")) as f:
        meta = json.load(f)
    assert meta["pdf_pages"] == 2
    assert meta["dpi"] == 96

    shutil.rmtree(output_dir)


def test_e2e_conversion(mock_server, sample_pdf, tmp_path):
    """Full conversion with mock server should produce a valid PPTX."""
    os.chdir(tmp_path)
    output_pptx = str(tmp_path / "output.pptx")

    from src.api_client import call_llm
    from src.artifacts import ArtifactStore
    from src.logging_config import setup_logging
    from src.message_builder import build_messages
    from src.pdf_preprocessor import pdf_to_images
    from src.pptx_assembler import PPTXAssembler
    from src.token_estimator import estimate_tokens

    setup_logging("WARNING")

    pages = pdf_to_images(sample_pdf, dpi=96)
    assert len(pages) == 2

    store = ArtifactStore(pdf_path=sample_pdf)
    store.save_page_images(pages)

    messages = build_messages(pages, enable_animations=False)
    store.save_messages(messages)

    token_est = estimate_tokens(messages, model="gpt-5.4")
    assert token_est["image_count"] == 2

    stream_log = os.path.join(store.root, "stream.log")
    result = call_llm(
        messages=messages,
        api_base_url=MOCK_BASE_URL,
        api_key="test-key",
        model_name="mock-gpt-5.4",
        stream_log_path=stream_log,
        reasoning_effort="",
    )

    assert len(result.slide_xmls) == 2
    assert 0 in result.slide_xmls
    assert 1 in result.slide_xmls
    assert result.response_data["finish_reason"] == "stop"
    assert result.response_data["tool_call_count"] == 2
    assert result.reasoning_text == ""

    store.save_slide_xmls(result.slide_xmls)
    store.save_api_response(result.response_data)

    assembler = PPTXAssembler(
        slide_width_pt=pages[0][1]["width_pt"],
        slide_height_pt=pages[0][1]["height_pt"],
    )
    assembler.assemble(result.slide_xmls)
    assembler.save(output_pptx)

    assert os.path.isfile(output_pptx)
    prs = Presentation(output_pptx)
    assert len(prs.slides) == 2

    slide0 = prs.slides[0]
    texts = [shape.text for shape in slide0.shapes if hasattr(shape, "text")]
    assert any("Test Slide Page 0" in t for t in texts)

    slide1 = prs.slides[1]
    texts = [shape.text for shape in slide1.shapes if hasattr(shape, "text")]
    assert any("Test Slide Page 1" in t for t in texts)

    shutil.rmtree(store.root)
    os.remove(output_pptx)


def test_xml_validator():
    """XML validator should fix common issues and produce valid XML."""
    from src.xml_validator import validate_and_fix

    good_xml = SAMPLE_SLIDE_XML.format(page_num=0)
    result = validate_and_fix(good_xml, 0)
    assert "<p:sld" in result

    fenced = f"```xml\n{good_xml}\n```"
    result = validate_and_fix(fenced, 0)
    assert "<p:sld" in result
    assert "```" not in result

    bad_xml = "<p:sld><broken"
    result = validate_and_fix(bad_xml, 0)
    assert "<p:sld" in result
    assert "ErrorInfo" in result or "<p:sld" in result

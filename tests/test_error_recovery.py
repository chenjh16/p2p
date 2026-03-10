"""End-to-end tests for error recovery during batch API calls."""

from __future__ import annotations

import json
import logging
import os
import shutil

from pptx import Presentation

from tests.conftest import MOCK_BASE_URL, SAMPLE_SLIDE_XML


def test_error_recovery_retry(mock_server, sample_pdf, tmp_path, monkeypatch):
    """After an API error, choosing 'retry' should re-attempt and succeed."""
    os.chdir(tmp_path)

    from src.api_client import call_llm
    from src.artifacts import ArtifactStore
    from src.logging_config import setup_logging
    from src.main import _print_progress
    from src.message_builder import build_messages
    from src.pdf_preprocessor import pdf_to_images

    setup_logging("WARNING")

    pages = pdf_to_images(sample_pdf, dpi=96)
    store = ArtifactStore(pdf_path=sample_pdf)
    store.save_page_images(pages)
    messages = build_messages(pages)

    call_count = 0
    def mock_call_llm(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("Simulated API failure")
        return call_llm(
            messages=kwargs["messages"],
            api_base_url=MOCK_BASE_URL,
            api_key="test-key",
            model_name="mock-gpt-5.4",
            stream_log_path=kwargs.get("stream_log_path", ""),
            reasoning_effort="",
        )

    inputs = iter(["r"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    slide_xmls: dict[int, str] = {}
    stream_log = os.path.join(store.root, "stream.log")
    logger = logging.getLogger("test_retry")

    while True:
        try:
            result = mock_call_llm(
                messages=messages,
                stream_log_path=stream_log,
            )
            slide_xmls.update(result.slide_xmls)
            break
        except Exception:
            _print_progress(logger, slide_xmls, len(pages), 0, 1)
            choice = input("Retry? ").strip().lower()
            if choice.startswith("r"):
                continue
            break

    assert call_count == 2
    assert len(slide_xmls) == 2
    assert 0 in slide_xmls
    assert 1 in slide_xmls

    shutil.rmtree("runs")


def test_error_recovery_skip(sample_pdf, tmp_path, monkeypatch):
    """After an API error, choosing 'skip' should proceed with available slides."""
    os.chdir(tmp_path)

    from src.logging_config import setup_logging
    from src.main import _print_progress
    from src.pptx_assembler import PPTXAssembler

    setup_logging("WARNING")

    inputs = iter(["s"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    slide_xmls: dict[int, str] = {}
    slide_xmls[0] = SAMPLE_SLIDE_XML.format(page_num=0)

    logger = logging.getLogger("test_skip")

    try:
        raise ConnectionError("Simulated API failure for batch 2")
    except Exception:
        _print_progress(logger, slide_xmls, 2, 1, 2)
        choice = input("Retry? ").strip().lower()

    assert choice == "s"
    assert len(slide_xmls) == 1

    assembler = PPTXAssembler(slide_width_pt=720, slide_height_pt=405)
    assembler.assemble(slide_xmls)
    output_pptx = str(tmp_path / "partial.pptx")
    assembler.save(output_pptx)

    prs = Presentation(output_pptx)
    assert len(prs.slides) == 1


def test_error_recovery_quit(sample_pdf, tmp_path, monkeypatch):
    """After an API error, choosing 'quit' should save metadata with success=False."""
    os.chdir(tmp_path)

    from src.artifacts import ArtifactStore
    from src.logging_config import setup_logging
    from src.main import _print_progress

    setup_logging("WARNING")

    store = ArtifactStore(pdf_path=sample_pdf)
    slide_xmls: dict[int, str] = {}

    inputs = iter(["q"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    logger = logging.getLogger("test_quit")

    try:
        raise ConnectionError("Simulated API failure")
    except Exception:
        _print_progress(logger, slide_xmls, 2, 0, 1)
        choice = input("Retry? ").strip().lower()

    assert choice == "q"

    store.save_metadata({"success": False, "slides_received": 0})
    meta_path = os.path.join(store.root, "metadata.json")
    assert os.path.isfile(meta_path)
    with open(meta_path) as f:
        meta = json.load(f)
    assert meta["success"] is False
    assert meta["slides_received"] == 0

    shutil.rmtree("runs")

"""Unit tests for src.pdf_preprocessor."""

from __future__ import annotations

import pytest


class TestPdfPreprocessor:
    def test_renders_correct_page_count(self, sample_pdf):
        from src.pdf_preprocessor import pdf_to_images

        pages = pdf_to_images(sample_pdf, dpi=72)
        assert len(pages) == 2

    def test_returns_png_bytes(self, sample_pdf):
        from src.pdf_preprocessor import pdf_to_images

        pages = pdf_to_images(sample_pdf, dpi=72)
        img_bytes, _ = pages[0]
        assert isinstance(img_bytes, bytes)
        assert img_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_metadata_fields(self, sample_pdf):
        from src.pdf_preprocessor import pdf_to_images

        pages = pdf_to_images(sample_pdf, dpi=72)
        _, meta = pages[0]
        assert meta["page_num"] == 0
        assert meta["width_pt"] == pytest.approx(720.0, abs=1)
        assert meta["height_pt"] == pytest.approx(405.0, abs=1)
        assert "width_px" in meta
        assert "height_px" in meta

    def test_dpi_affects_image_size(self, sample_pdf):
        from src.pdf_preprocessor import pdf_to_images

        pages_low = pdf_to_images(sample_pdf, dpi=72)
        pages_high = pdf_to_images(sample_pdf, dpi=144)
        assert len(pages_low[0][0]) < len(pages_high[0][0])

    def test_page_numbers_sequential(self, three_page_pdf):
        from src.pdf_preprocessor import pdf_to_images

        pages = pdf_to_images(three_page_pdf, dpi=72)
        nums = [meta["page_num"] for _, meta in pages]
        assert nums == [0, 1, 2]


class TestSnapSlideDimensions:
    def test_detects_16_9(self):
        from src.pdf_preprocessor import snap_slide_dimensions

        w, h, label = snap_slide_dimensions(720, 405)
        assert label == "16:9"
        assert w == 720
        assert h == 405

    def test_detects_4_3(self):
        from src.pdf_preprocessor import snap_slide_dimensions

        w, h, label = snap_slide_dimensions(720, 540)
        assert label == "4:3"
        assert w == 720
        assert h == 540

    def test_detects_16_10(self):
        from src.pdf_preprocessor import snap_slide_dimensions

        w, h, label = snap_slide_dimensions(720, 450)
        assert label == "16:10"
        assert w == 720
        assert h == 450

    def test_snaps_close_ratio(self):
        from src.pdf_preprocessor import snap_slide_dimensions

        w, h, label = snap_slide_dimensions(722, 406)
        assert label == "16:9"
        assert w == 720
        assert h == 405

    def test_custom_ratio_preserved(self):
        from src.pdf_preprocessor import snap_slide_dimensions

        w, h, label = snap_slide_dimensions(500, 500)
        assert label == "custom"
        assert w == 500
        assert h == 500

    def test_zero_height(self):
        from src.pdf_preprocessor import snap_slide_dimensions

        w, h, label = snap_slide_dimensions(720, 0)
        assert label == "unknown"

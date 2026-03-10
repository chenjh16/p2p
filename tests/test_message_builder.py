"""Unit tests for src.message_builder."""

from __future__ import annotations


class TestMessageBuilder:
    def test_builds_system_and_user_messages(self, sample_pdf):
        from src.message_builder import build_messages
        from src.pdf_preprocessor import pdf_to_images

        pages = pdf_to_images(sample_pdf, dpi=72)
        messages = build_messages(pages, enable_animations=False)

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_system_prompt_contains_key_sections(self, sample_pdf):
        from src.message_builder import build_messages
        from src.pdf_preprocessor import pdf_to_images

        pages = pdf_to_images(sample_pdf, dpi=72)
        messages = build_messages(pages)

        system = messages[0]["content"]
        assert "PresentationML" in system
        assert "write_slide_xml" in system
        assert "Font Size Calibration" in system
        assert "Atomic Reconstruction" in system

    def test_animation_section_included_when_enabled(self, sample_pdf):
        from src.message_builder import build_messages
        from src.pdf_preprocessor import pdf_to_images

        pages = pdf_to_images(sample_pdf, dpi=72)

        msgs_off = build_messages(pages, enable_animations=False)
        msgs_on = build_messages(pages, enable_animations=True)

        assert "Morph" not in msgs_off[0]["content"]
        assert "Morph" in msgs_on[0]["content"]

    def test_user_message_contains_images(self, sample_pdf):
        from src.message_builder import build_messages
        from src.pdf_preprocessor import pdf_to_images

        pages = pdf_to_images(sample_pdf, dpi=72)
        messages = build_messages(pages)

        user_content = messages[1]["content"]
        image_parts = [p for p in user_content if p.get("type") == "image_url"]
        assert len(image_parts) == 2

    def test_task_instruction_at_end(self, sample_pdf):
        from src.message_builder import build_messages
        from src.pdf_preprocessor import pdf_to_images

        pages = pdf_to_images(sample_pdf, dpi=72)
        messages = build_messages(pages)

        user_content = messages[1]["content"]
        last_text = user_content[-1]
        assert last_text["type"] == "text"
        assert "CRITICAL" in last_text["text"]
        assert "exactly 2 parallel tool calls" in last_text["text"]
        assert "Atomic Reconstruction" in last_text["text"]
        assert "font size reduction" in last_text["text"]

    def test_chinese_prompt(self, sample_pdf):
        from src.message_builder import build_messages
        from src.pdf_preprocessor import pdf_to_images

        pages = pdf_to_images(sample_pdf, dpi=72)
        messages = build_messages(pages, prompt_lang="zh")

        system = messages[0]["content"]
        assert "演示文稿重建引擎" in system
        assert "原子化重建" in system

    def test_slide_dimensions_in_message(self, sample_pdf):
        from src.message_builder import build_messages
        from src.pdf_preprocessor import pdf_to_images

        pages = pdf_to_images(sample_pdf, dpi=72)
        messages = build_messages(pages)

        user_content = messages[1]["content"]
        text_parts = [p["text"] for p in user_content if p.get("type") == "text"]
        combined = " ".join(text_parts)
        assert "720" in combined
        assert "405" in combined


class TestMessageBuilderAnthropic:
    def test_anthropic_messages_no_system_role(self, sample_pdf):
        from src.message_builder import build_messages
        from src.pdf_preprocessor import pdf_to_images

        pages = pdf_to_images(sample_pdf, dpi=72)
        messages = build_messages(pages, provider="anthropic")

        for msg in messages:
            assert msg["role"] != "system"

    def test_anthropic_messages_use_image_blocks(self, sample_pdf):
        from src.message_builder import build_messages
        from src.pdf_preprocessor import pdf_to_images

        pages = pdf_to_images(sample_pdf, dpi=72)
        messages = build_messages(pages, provider="anthropic")

        user_content = messages[0]["content"]
        image_blocks = [p for p in user_content if p.get("type") == "image"]
        assert len(image_blocks) == 2
        for block in image_blocks:
            assert "source" in block
            assert block["source"].get("type") == "base64"

    def test_anthropic_task_instruction_present(self, sample_pdf):
        from src.message_builder import build_messages
        from src.pdf_preprocessor import pdf_to_images

        pages = pdf_to_images(sample_pdf, dpi=72)
        messages = build_messages(pages, provider="anthropic")

        user_content = messages[0]["content"]
        text_blocks = [p for p in user_content if p.get("type") == "text"]
        last_text = text_blocks[-1]
        assert "CRITICAL" in last_text["text"]
        assert "parallel tool calls" in last_text["text"]

    def test_get_system_prompt_text(self):
        from src.message_builder import get_system_prompt_text

        prompt = get_system_prompt_text(enable_animations=False, prompt_lang="en")
        assert "presentation reconstruction engine" in prompt
        assert "write_slide_xml" in prompt

    def test_get_system_prompt_text_with_animations(self):
        from src.message_builder import get_system_prompt_text

        prompt = get_system_prompt_text(enable_animations=True)
        assert "Morph" in prompt

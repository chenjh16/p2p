"""Unit tests for src.system_prompt."""

from __future__ import annotations


class TestSystemPrompt:
    def test_get_system_prompt_en(self):
        from src.system_prompt import get_system_prompt

        prompt = get_system_prompt("en")
        assert "presentation reconstruction engine" in prompt
        assert "Atomic Reconstruction" in prompt

    def test_get_system_prompt_zh(self):
        from src.system_prompt import get_system_prompt

        prompt = get_system_prompt("zh")
        assert "演示文稿重建引擎" in prompt
        assert "原子化重建" in prompt

    def test_get_animation_section_en(self):
        from src.system_prompt import get_animation_section

        section = get_animation_section("en")
        assert "Morph Transition" in section

    def test_get_animation_section_zh(self):
        from src.system_prompt import get_animation_section

        section = get_animation_section("zh")
        assert "Morph 转场" in section

    def test_default_is_english(self):
        from src.system_prompt import SYSTEM_PROMPT, SYSTEM_PROMPT_EN

        assert SYSTEM_PROMPT == SYSTEM_PROMPT_EN

    def test_tool_definition_structure(self):
        from src.system_prompt import WRITE_SLIDE_XML_TOOL

        assert WRITE_SLIDE_XML_TOOL["type"] == "function"
        func = WRITE_SLIDE_XML_TOOL["function"]
        assert func["name"] == "write_slide_xml"
        params = func["parameters"]
        assert "page_num" in params["properties"]
        assert "slide_xml" in params["properties"]
        assert params["required"] == ["page_num", "slide_xml"]

    def test_anthropic_tool_definition_structure(self):
        from src.system_prompt import WRITE_SLIDE_XML_TOOL_ANTHROPIC

        assert "name" in WRITE_SLIDE_XML_TOOL_ANTHROPIC
        assert WRITE_SLIDE_XML_TOOL_ANTHROPIC["name"] == "write_slide_xml"
        assert "description" in WRITE_SLIDE_XML_TOOL_ANTHROPIC
        assert "input_schema" in WRITE_SLIDE_XML_TOOL_ANTHROPIC
        schema = WRITE_SLIDE_XML_TOOL_ANTHROPIC["input_schema"]
        assert "properties" in schema
        assert "page_num" in schema["properties"]
        assert "slide_xml" in schema["properties"]
        assert "required" in schema
        assert schema["required"] == ["page_num", "slide_xml"]

    def test_font_calibration_in_prompt(self):
        from src.system_prompt import get_system_prompt

        prompt = get_system_prompt("en")
        assert "REDUCE it by 20%" in prompt
        assert "sz=1600" in prompt

    def test_table_requirement_in_prompt(self):
        from src.system_prompt import get_system_prompt

        prompt = get_system_prompt("en")
        assert "NEVER use a raster placeholder for any table" in prompt

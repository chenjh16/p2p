"""System prompts and tool definitions for the LLM presentation reconstruction.

Prompt text is loaded from markdown files in ``src/prompts/`` at runtime.
Tool definitions (JSON structures) remain here as they are code, not prose.
"""

from .prompts import get_animation_section, get_system_prompt  # noqa: F401

__all__ = [
    "get_system_prompt",
    "get_animation_section",
    "WRITE_SLIDE_XML_TOOL",
    "WRITE_SLIDE_XML_TOOL_ANTHROPIC",
    "WRITE_SLIDE_XML_TOOL_RESPONSES",
]

WRITE_SLIDE_XML_TOOL = {
    "type": "function",
    "function": {
        "name": "write_slide_xml",
        "description": (
            "Write the PresentationML XML for one slide page. "
            "Call this tool once for each page in the PDF."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "page_num": {
                    "type": "integer",
                    "description": "The PDF page number for this slide (0-indexed)",
                },
                "slide_xml": {
                    "type": "string",
                    "description": (
                        "Complete PresentationML slide XML content "
                        "(<p:sld> root element) containing all shapes, text, "
                        "styles, animations, etc. for this page"
                    ),
                },
            },
            "required": ["page_num", "slide_xml"],
        },
    },
}

WRITE_SLIDE_XML_TOOL_RESPONSES = {
    "type": "function",
    "name": "write_slide_xml",
    "description": (
        "Write the PresentationML XML for one slide page. "
        "Call this tool once for each page in the PDF."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "page_num": {
                "type": "integer",
                "description": "The PDF page number for this slide (0-indexed)",
            },
            "slide_xml": {
                "type": "string",
                "description": (
                    "Complete PresentationML slide XML content "
                    "(<p:sld> root element) containing all shapes, text, "
                    "styles, animations, etc. for this page"
                ),
            },
        },
        "required": ["page_num", "slide_xml"],
    },
}

WRITE_SLIDE_XML_TOOL_ANTHROPIC = {
    "name": "write_slide_xml",
    "description": (
        "Write the PresentationML XML for one slide page. "
        "Call this tool once for each page in the PDF."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "page_num": {
                "type": "integer",
                "description": "The PDF page number for this slide (0-indexed)",
            },
            "slide_xml": {
                "type": "string",
                "description": (
                    "Complete PresentationML slide XML content "
                    "(<p:sld> root element) containing all shapes, text, "
                    "styles, animations, etc. for this page"
                ),
            },
        },
        "required": ["page_num", "slide_xml"],
    },
}

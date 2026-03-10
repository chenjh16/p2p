"""Prompt management: loads system prompts from markdown files at runtime."""

from __future__ import annotations

import functools
import os

_PROMPTS_DIR = os.path.dirname(__file__)


@functools.cache
def _load(filename: str) -> str:
    path = os.path.join(_PROMPTS_DIR, filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


def get_system_prompt(lang: str = "en") -> str:
    """Return the system prompt for the given language ('en' or 'zh')."""
    return _load(f"system_{lang}.md") if lang in ("en", "zh") else _load("system_en.md")


def get_animation_section(lang: str = "en") -> str:
    """Return the animation section for the given language ('en' or 'zh')."""
    return _load(f"animation_{lang}.md") if lang in ("en", "zh") else _load("animation_en.md")

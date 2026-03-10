"""PDF-to-PPTX conversion tool using multimodal LLM."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ApiConfig:
    """Immutable bundle of API connection parameters passed across modules."""

    api_key: str = ""
    api_base_url: str = ""
    model_name: str = ""

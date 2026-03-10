"""Backward-compatible re-export; actual implementation in src.api.openai_client."""

from .api.openai_client import _DEFAULT_API_CFG, LLMResult, call_llm  # noqa: F401

__all__ = ["LLMResult", "call_llm", "_DEFAULT_API_CFG"]

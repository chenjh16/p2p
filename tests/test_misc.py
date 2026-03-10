"""Unit tests for api_client_anthropic and logging_config."""

from __future__ import annotations


class TestAnthropicEffortLevel:
    def test_effort_level_mapping(self):
        from src.api_client_anthropic import _effort_level

        assert _effort_level("low") == "low"
        assert _effort_level("medium") == "medium"
        assert _effort_level("high") == "high"
        assert _effort_level("xhigh") == "max"

    def test_effort_level_unknown_defaults_to_high(self):
        from src.api_client_anthropic import _effort_level

        assert _effort_level("none") == "high"
        assert _effort_level("") == "high"
        assert _effort_level("unknown") == "high"


class TestAnthropicThinkingBudget:
    def test_thinking_budget_mapping(self):
        from src.api_client_anthropic import _thinking_budget

        max_tokens = 128000
        low = _thinking_budget("low", max_tokens)
        medium = _thinking_budget("medium", max_tokens)
        high = _thinking_budget("high", max_tokens)
        xhigh = _thinking_budget("xhigh", max_tokens)
        none_val = _thinking_budget("none", max_tokens)
        empty_val = _thinking_budget("", max_tokens)

        assert low == 0
        assert medium > 0
        assert high > medium
        assert xhigh > high
        assert xhigh == min(128000, max_tokens)
        assert none_val == 0
        assert empty_val == 0


class TestLoggingConfig:
    def test_setup_logging_does_not_raise(self):
        from src.logging_config import setup_logging

        setup_logging("WARNING")

    def test_get_logger_returns_logger(self):
        import logging

        from src.logging_config import get_logger

        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_module"

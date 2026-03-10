"""Unit tests for src.token_estimator."""

from __future__ import annotations


class TestTokenEstimator:
    def test_estimates_text_tokens(self):
        from src.token_estimator import estimate_tokens

        messages = [{"role": "system", "content": "You are a helpful assistant."}]
        result = estimate_tokens(messages, model="gpt-4")
        assert result["text_tokens"] > 0
        assert result["image_count"] == 0
        assert result["image_tokens"] == 0

    def test_counts_images(self, sample_pdf):
        from src.message_builder import build_messages
        from src.pdf_preprocessor import pdf_to_images
        from src.token_estimator import estimate_tokens

        pages = pdf_to_images(sample_pdf, dpi=72)
        messages = build_messages(pages)
        result = estimate_tokens(messages)

        assert result["image_count"] == 2
        assert result["image_tokens"] > 0
        assert result["total_input_tokens"] == result["text_tokens"] + result["image_tokens"]

    def test_cost_estimate_structure(self):
        from src.token_estimator import estimate_tokens

        messages = [{"role": "user", "content": "Hello"}]
        result = estimate_tokens(messages)

        cost = result["estimated_cost_usd"]
        assert isinstance(cost, dict)
        assert "input_cost_usd" in cost
        assert "output_cost_usd" in cost
        assert "total_cost_usd" in cost
        assert cost["total_cost_usd"] >= 0

    def test_output_estimate_scales_with_images(self, sample_pdf):
        from src.message_builder import build_messages
        from src.pdf_preprocessor import pdf_to_images
        from src.token_estimator import estimate_tokens

        pages = pdf_to_images(sample_pdf, dpi=72)
        result_2 = estimate_tokens(build_messages(pages))
        result_1 = estimate_tokens(build_messages(pages[:1]))

        assert result_2["estimated_output_tokens"] > result_1["estimated_output_tokens"]

    def test_estimated_response_time(self):
        from src.token_estimator import estimate_tokens

        messages = [{"role": "user", "content": "Hello"}]
        result = estimate_tokens(messages, reasoning_effort="medium")

        assert "assumed_output_tps" in result
        assert result["assumed_output_tps"] == 50.0
        assert result["reasoning_effort"] == "medium"
        assert result["reasoning_multiplier"] == 1.5
        assert "estimated_response_time_seconds" in result
        expected_time = (result["estimated_output_tokens"] / 50.0) * 1.5
        assert abs(result["estimated_response_time_seconds"] - round(expected_time, 1)) < 0.2

    def test_estimated_response_time_high_reasoning(self):
        from src.token_estimator import estimate_tokens

        messages = [{"role": "user", "content": "Hello"}]
        result_high = estimate_tokens(messages, reasoning_effort="high")
        result_low = estimate_tokens(messages, reasoning_effort="low")

        assert result_high["reasoning_multiplier"] == 2.5
        assert result_low["reasoning_multiplier"] == 1.0
        assert result_high["estimated_response_time_seconds"] > result_low["estimated_response_time_seconds"]

    def test_openai_image_tokens_high_detail(self):
        from src.token_estimator import _openai_image_tokens

        tokens = _openai_image_tokens(2880, 1620, "high")
        assert tokens == 85 + 170 * 6  # 1105

    def test_openai_image_tokens_low_detail(self):
        from src.token_estimator import _openai_image_tokens

        tokens = _openai_image_tokens(2880, 1620, "low")
        assert tokens == 85

    def test_anthropic_image_tokens(self):
        from src.token_estimator import _anthropic_image_tokens

        tokens = _anthropic_image_tokens(2880, 1620)
        assert tokens > 0
        assert tokens < 2000

    def test_anthropic_image_tokens_small(self):
        from src.token_estimator import _anthropic_image_tokens

        tokens = _anthropic_image_tokens(200, 200)
        assert tokens == 54

    def test_anthropic_vs_openai_different_counts(self):
        from src.token_estimator import _anthropic_image_tokens, _openai_image_tokens

        openai_tokens = _openai_image_tokens(1920, 1080, "high")
        anthropic_tokens = _anthropic_image_tokens(1920, 1080)
        assert openai_tokens != anthropic_tokens

    def test_custom_output_tps(self):
        from src.token_estimator import estimate_tokens

        messages = [{"role": "user", "content": "Hello"}]
        result = estimate_tokens(messages, output_tps=100.0)
        assert result["assumed_output_tps"] == 100.0

    def test_output_tps_affects_response_time(self):
        from src.token_estimator import estimate_tokens

        messages = [{"role": "user", "content": "Hello"}]
        est_slow = estimate_tokens(messages, output_tps=25.0)
        est_fast = estimate_tokens(messages, output_tps=200.0)
        assert est_slow["estimated_response_time_seconds"] > est_fast["estimated_response_time_seconds"]

"""Unit tests for provider_config and OpenAI Responses API client."""

from __future__ import annotations

import json
import os


class TestLoadProviderConfig:
    def test_matching_url_prefix_returns_use_responses_api_and_extra_headers(
        self, tmp_path, monkeypatch
    ):
        """Matching URL prefix returns correct use_responses_api and extra_headers."""
        config = {
            "providers": [
                {
                    "url_prefix": "https://api.example.com",
                    "use_responses_api": True,
                    "headers": {"X-Custom-Header": "custom-value"},
                }
            ]
        }
        config_path = tmp_path / ".p2p.config"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
        monkeypatch.setattr(os.path, "expanduser", lambda x: str(tmp_path))

        from src.provider_config import load_provider_config

        result = load_provider_config(
            "https://api.example.com/v1/chat/completions", "sk-test-key"
        )
        assert result["use_responses_api"] is True
        assert result["extra_headers"]["X-Custom-Header"] == "custom-value"

    def test_non_matching_url_returns_empty_dict(self, tmp_path, monkeypatch):
        """Non-matching URL returns empty dict."""
        config = {
            "providers": [
                {
                    "url_prefix": "https://api.example.com",
                    "use_responses_api": True,
                }
            ]
        }
        config_path = tmp_path / ".p2p.config"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
        monkeypatch.setattr(os.path, "expanduser", lambda x: str(tmp_path))

        from src.provider_config import load_provider_config

        result = load_provider_config(
            "https://other-provider.com/v1", "sk-test-key"
        )
        assert result == {}

    def test_no_config_file_returns_empty_dict(self, tmp_path, monkeypatch):
        """No config file returns empty dict."""
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
        monkeypatch.setattr(
            os.path, "expanduser", lambda x: str(tmp_path)
        )  # avoid picking up real ~/.p2p.config

        from src.provider_config import load_provider_config

        result = load_provider_config(
            "https://api.example.com/v1", "sk-test-key"
        )
        assert result == {}

    def test_headers_from_key_generates_bearer_api_key(self, tmp_path, monkeypatch):
        """headers_from_key generates 'Bearer <api_key>' correctly."""
        config = {
            "providers": [
                {
                    "url_prefix": "https://api.example.com",
                    "headers_from_key": ["Authorization", "X-Api-Key"],
                }
            ]
        }
        config_path = tmp_path / ".p2p.config"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
        monkeypatch.setattr(os.path, "expanduser", lambda x: str(tmp_path))

        from src.provider_config import load_provider_config

        result = load_provider_config(
            "https://api.example.com/v1", "sk-secret-123"
        )
        assert result["extra_headers"]["Authorization"] == "Bearer sk-secret-123"
        assert result["extra_headers"]["X-Api-Key"] == "Bearer sk-secret-123"


class TestApiConfig:
    def test_accepts_use_responses_api_and_extra_headers(self):
        """ApiConfig dataclass accepts use_responses_api and extra_headers fields."""
        from src import ApiConfig

        cfg = ApiConfig(
            use_responses_api=True,
            extra_headers={"Authorization": "Bearer sk-xxx", "X-Custom": "value"},
        )
        assert cfg.use_responses_api is True
        assert cfg.extra_headers["Authorization"] == "Bearer sk-xxx"
        assert cfg.extra_headers["X-Custom"] == "value"


class TestConvertMessagesToInput:
    def test_system_messages_extracted_as_instructions(self):
        """System messages are extracted as instructions."""
        from src.api.openai_responses_client import _convert_messages_to_input

        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        instructions, input_items = _convert_messages_to_input(messages)
        assert instructions == "You are a helpful assistant."
        assert len(input_items) == 1
        assert input_items[0]["role"] == "user"
        assert input_items[0]["content"] == "Hello"

    def test_image_url_content_blocks_converted_to_input_image(self):
        """image_url content blocks are converted to input_image format."""
        from src.api.openai_responses_client import _convert_messages_to_input

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "https://example.com/image.png",
                            "detail": "high",
                        },
                    },
                ],
            }
        ]
        instructions, input_items = _convert_messages_to_input(messages)
        assert instructions == ""
        assert len(input_items) == 1
        content = input_items[0]["content"]
        assert len(content) == 2
        assert content[0] == {"type": "input_text", "text": "Describe this image"}
        assert content[1] == {
            "type": "input_image",
            "image_url": "https://example.com/image.png",
            "detail": "high",
        }

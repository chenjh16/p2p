"""Load provider-specific configuration from .p2p.config files.

Searches for ``.p2p.config`` in the current working directory, then in the
user's home directory (``~/.p2p.config``).  The first file found is used.

The file is JSON with a ``providers`` array.  Each entry has:
  - ``url_prefix``  (str):  matched against the API base URL
  - ``use_responses_api`` (bool, optional): use the OpenAI Responses API
  - ``headers`` (dict, optional): extra HTTP headers to inject
  - ``headers_from_key`` (list[str], optional): header names whose value
    should be set to ``Bearer <api_key>`` at runtime
"""

from __future__ import annotations

import json
import os
from typing import Any

from .logging_config import get_logger

logger = get_logger("provider_cfg")

_CONFIG_FILENAME = ".p2p.config"


def _find_config() -> str | None:
    """Return the path to the first .p2p.config found, or None."""
    candidates = [
        os.path.join(os.getcwd(), _CONFIG_FILENAME),
        os.path.join(os.path.expanduser("~"), _CONFIG_FILENAME),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def load_provider_config(api_base_url: str, api_key: str) -> dict[str, Any]:
    """Return provider-specific overrides for the given base URL.

    Returns a dict with optional keys:
      - ``use_responses_api`` (bool)
      - ``extra_headers`` (dict[str, str])

    If no matching provider is found, returns an empty dict.
    """
    config_path = _find_config()
    if not config_path:
        return {}

    try:
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read %s: %s", config_path, exc)
        return {}

    providers = data.get("providers", [])
    for entry in providers:
        prefix = entry.get("url_prefix", "")
        if prefix and api_base_url.startswith(prefix):
            logger.info("Matched provider config for %s (from %s)", prefix, config_path)
            result: dict[str, Any] = {}

            if "use_responses_api" in entry:
                result["use_responses_api"] = bool(entry["use_responses_api"])

            headers: dict[str, str] = dict(entry.get("headers", {}))
            for hdr_name in entry.get("headers_from_key", []):
                headers[hdr_name] = f"Bearer {api_key}"
            if headers:
                result["extra_headers"] = headers

            return result

    return {}

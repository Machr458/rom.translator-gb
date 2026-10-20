import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server import OPENAI_COMPATIBLE_BASE_URLS, PROVIDERS, _call_llm


@pytest.mark.parametrize(
    ("provider", "model", "base_url"),
    [
        ("groq", "llama-3.3-70b-versatile", "https://api.groq.com/openai/v1"),
        ("freetheai", "fta/ocz/glm-5.3-flash-free", "https://api.freetheai.org/v1"),
        ("freetheai", "fta/ocz/deepseek-v4.1-flash-free", "https://api.freetheai.org/v1"),
        ("freetheai", "fta/ocz/nemotron-3.5-lightning-free", "https://api.freetheai.org/v1"),
    ],
)
def test_openai_compatible_provider_dispatch(provider, model, base_url):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="PONG"))]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=response))
        )
    )

    with patch("openai.AsyncOpenAI", return_value=client) as openai_client:
        result = asyncio.run(_call_llm("test prompt", provider, model, "test-key"))

    assert result == "PONG"
    openai_client.assert_called_once_with(api_key="test-key", base_url=base_url)
    client.chat.completions.create.assert_awaited_once()


def test_new_provider_defaults_are_listed():
    assert OPENAI_COMPATIBLE_BASE_URLS["groq"] == "https://api.groq.com/openai/v1"
    assert OPENAI_COMPATIBLE_BASE_URLS["freetheai"] == "https://api.freetheai.org/v1"
    for provider in ("groq", "freetheai"):
        info = PROVIDERS[provider]
        assert info["default"] in {model["id"] for model in info["models"]}


def test_freetheai_catalog_uses_current_free_model_ids():
    model_ids = {model["id"] for model in PROVIDERS["freetheai"]["models"]}

    assert PROVIDERS["freetheai"]["default"] == "fta/ocz/glm-5.3-flash-free"
    assert "fta/ocz/deepseek-v4.1-flash-free" in model_ids
    assert "fta/ocz/nemotron-3.5-lightning-free" in model_ids
    assert not any(model_id.startswith("fta/zai/") for model_id in model_ids)
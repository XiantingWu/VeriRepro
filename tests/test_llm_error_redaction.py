from __future__ import annotations

import pytest
import requests

from reproagent.llm import LLMConfig, LLMUnavailableError, OpenAICompatibleClient


def test_request_failure_does_not_persist_private_endpoint() -> None:
    secret_endpoint = "https://private-gateway.internal.example/v1"
    client = OpenAICompatibleClient(
        LLMConfig(base_url=secret_endpoint, api_key="secret-key", model="reasoner")
    )

    def fail_post(payload):
        del payload
        raise requests.ConnectTimeout(
            f"connection timed out while calling {secret_endpoint}/chat/completions"
        )

    client._post = fail_post  # type: ignore[method-assign]

    with pytest.raises(LLMUnavailableError) as exc_info:
        client.complete_json(system="system", user="user")

    rendered = str(exc_info.value)
    assert "ConnectTimeout" in rendered
    assert "private-gateway" not in rendered
    assert secret_endpoint not in rendered
    assert exc_info.value.__suppress_context__ is True

    assert client.last_usage is not None
    assert client.last_usage["error"] == "ConnectTimeout"
    assert secret_endpoint not in str(client.last_usage)
    assert "secret-key" not in str(client.last_usage)

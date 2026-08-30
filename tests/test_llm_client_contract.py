from __future__ import annotations

from typing import Any

import pytest
import requests

from reproagent import llm
from reproagent.llm import (
    LLMConfig,
    LLMUnavailableError,
    OpenAICompatibleClient,
    capture_model_usage,
)

_LLM_ENV_VARS = (
    "VERIREPRO_LLM_BASE_URL",
    "VERIREPRO_LITELLM_BASE_URL",
    "REPROAGENT_LITELLM_BASE_URL",
    "LITELLM_BASE_URL",
    "OPENAI_BASE_URL",
    "VERIREPRO_LLM_API_KEY",
    "VERIREPRO_LITELLM_API_KEY",
    "REPROAGENT_LITELLM_API_KEY",
    "LITELLM_API_KEY",
    "OPENAI_API_KEY",
    "VERIREPRO_LLM_MODEL",
    "VERIREPRO_LITELLM_MODEL",
    "REPROAGENT_LITELLM_MODEL",
    "LITELLM_MODEL",
    "VERIREPRO_LLM_TIMEOUT",
    "VERIREPRO_LITELLM_TIMEOUT",
    "REPROAGENT_LITELLM_TIMEOUT",
    "VERIREPRO_LLM_REASONING_EFFORT",
    "VERIREPRO_LITELLM_REASONING_EFFORT",
    "REPROAGENT_LITELLM_REASONING_EFFORT",
)

_PUBLIC_USAGE_FIELDS = {
    "request_model",
    "response_model",
    "duration_seconds",
    "request_count",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_tokens",
    "reasoning_tokens",
    "cost_usd",
    "error",
}


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        body: Any = None,
        json_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self._body = body
        self._json_error = json_error
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def json(self) -> Any:
        if self._json_error is not None:
            raise self._json_error
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code} error")


@pytest.fixture
def clean_llm_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in _LLM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _client(**overrides: str) -> OpenAICompatibleClient:
    config_kwargs = {"base_url": "https://llm.example", "api_key": "k", "model": "model-x"}
    config_kwargs.update(overrides)
    return OpenAICompatibleClient(LLMConfig(**config_kwargs))


def _chat_body(content: str = '{"answer": 42}', *, model: str = "server-model") -> dict[str, Any]:
    return {
        "model": model,
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
            "prompt_tokens_details": {"cached_tokens": 4},
            "completion_tokens_details": {"reasoning_tokens": 2},
        },
        "response_cost": 0.25,
    }


def _stub_post(client: OpenAICompatibleClient, *responses: FakeResponse) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    queue = list(responses)

    def post(payload: dict[str, Any]) -> FakeResponse:
        payloads.append(payload)
        return queue.pop(0)

    client._post = post  # type: ignore[method-assign]
    return payloads


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://api.example.com", "https://api.example.com/v1/chat/completions"),
        ("https://api.example.com/", "https://api.example.com/v1/chat/completions"),
        ("https://api.example.com/v1", "https://api.example.com/v1/chat/completions"),
        ("https://api.example.com/v1/", "https://api.example.com/v1/chat/completions"),
        (
            "https://api.example.com/v1/chat/completions",
            "https://api.example.com/v1/chat/completions",
        ),
    ],
)
def test_chat_completions_url_normalization(base_url: str, expected: str) -> None:
    assert LLMConfig(base_url=base_url, api_key="k", model="m").chat_completions_url == expected


def test_from_env_prefers_verirepro_llm_namespace(
    clean_llm_env: pytest.MonkeyPatch,
) -> None:
    clean_llm_env.setenv("VERIREPRO_LLM_BASE_URL", "https://preferred.example")
    clean_llm_env.setenv("VERIREPRO_LITELLM_BASE_URL", "https://veri.example")
    clean_llm_env.setenv("LITELLM_BASE_URL", "https://generic.example")
    clean_llm_env.setenv("OPENAI_BASE_URL", "https://openai.example")
    clean_llm_env.setenv("VERIREPRO_LLM_API_KEY", "preferred-key")
    clean_llm_env.setenv("VERIREPRO_LITELLM_API_KEY", "veri-key")
    clean_llm_env.setenv("LITELLM_API_KEY", "generic-key")
    clean_llm_env.setenv("VERIREPRO_LLM_MODEL", "preferred-model")
    clean_llm_env.setenv("VERIREPRO_LITELLM_MODEL", "veri-model")

    assert LLMConfig.from_env() == LLMConfig(
        base_url="https://preferred.example",
        api_key="preferred-key",
        model="preferred-model",
        timeout=120,
    )


def test_from_env_prefers_verirepro_namespace(clean_llm_env: pytest.MonkeyPatch) -> None:
    clean_llm_env.setenv("VERIREPRO_LITELLM_BASE_URL", "https://veri.example")
    clean_llm_env.setenv("LITELLM_BASE_URL", "https://generic.example")
    clean_llm_env.setenv("OPENAI_BASE_URL", "https://openai.example")
    clean_llm_env.setenv("LITELLM_API_KEY", "generic-key")
    clean_llm_env.setenv("VERIREPRO_LITELLM_API_KEY", "veri-key")
    clean_llm_env.setenv("LITELLM_MODEL", "generic-model")

    assert LLMConfig.from_env() == LLMConfig(
        base_url="https://veri.example",
        api_key="veri-key",
        model="generic-model",
        timeout=120,
    )


def test_from_env_falls_back_to_legacy_namespace(clean_llm_env: pytest.MonkeyPatch) -> None:
    clean_llm_env.setenv("REPROAGENT_LITELLM_BASE_URL", "https://legacy.example")
    clean_llm_env.setenv("VERIREPRO_LITELLM_API_KEY", "newer-key")
    clean_llm_env.setenv("REPROAGENT_LITELLM_API_KEY", "legacy-key")

    config = LLMConfig.from_env(model="explicit-model")

    assert config is not None
    assert config.base_url == "https://legacy.example"
    assert config.api_key == "legacy-key"
    assert config.model == "explicit-model"


def test_from_env_uses_openai_namespace(clean_llm_env: pytest.MonkeyPatch) -> None:
    clean_llm_env.setenv("OPENAI_BASE_URL", "https://openai.example/v1")
    clean_llm_env.setenv("OPENAI_API_KEY", "oai-key")

    config = LLMConfig.from_env(model="explicit-model")
    assert config is not None
    assert config.base_url == "https://openai.example/v1"
    assert config.api_key == "oai-key"
    assert config.model == "explicit-model"


def test_from_env_requires_model(clean_llm_env: pytest.MonkeyPatch) -> None:
    clean_llm_env.setenv("LITELLM_BASE_URL", "https://generic.example")
    assert LLMConfig.from_env() is None


def test_from_env_returns_none_without_configuration(clean_llm_env: pytest.MonkeyPatch) -> None:
    assert LLMConfig.from_env() is None


def test_from_env_resolves_model_alias_precedence(clean_llm_env: pytest.MonkeyPatch) -> None:
    clean_llm_env.setenv("LITELLM_BASE_URL", "https://generic.example")
    clean_llm_env.setenv("LITELLM_MODEL", "fallback-model")
    assert LLMConfig.from_env().model == "fallback-model"
    clean_llm_env.setenv("REPROAGENT_LITELLM_MODEL", "legacy-model")
    assert LLMConfig.from_env().model == "legacy-model"
    clean_llm_env.setenv("VERIREPRO_LITELLM_MODEL", "veri-model")
    assert LLMConfig.from_env().model == "veri-model"
    clean_llm_env.setenv("VERIREPRO_LLM_MODEL", "preferred-model")
    assert LLMConfig.from_env().model == "preferred-model"


def test_from_env_timeout_prefers_verirepro_llm_namespace(
    clean_llm_env: pytest.MonkeyPatch,
) -> None:
    clean_llm_env.setenv("LITELLM_BASE_URL", "https://generic.example")
    clean_llm_env.setenv("LITELLM_MODEL", "m")
    clean_llm_env.setenv("REPROAGENT_LITELLM_TIMEOUT", "7")
    clean_llm_env.setenv("VERIREPRO_LITELLM_TIMEOUT", "9")
    clean_llm_env.setenv("VERIREPRO_LLM_TIMEOUT", "11")
    assert LLMConfig.from_env().timeout == 11


def test_from_env_timeout_falls_back_to_legacy_aliases(
    clean_llm_env: pytest.MonkeyPatch,
) -> None:
    clean_llm_env.setenv("LITELLM_BASE_URL", "https://generic.example")
    clean_llm_env.setenv("LITELLM_MODEL", "m")
    clean_llm_env.setenv("REPROAGENT_LITELLM_TIMEOUT", "7")
    assert LLMConfig.from_env().timeout == 7


def test_from_env_api_key_isolation_for_openai_path(
    clean_llm_env: pytest.MonkeyPatch,
) -> None:
    clean_llm_env.setenv("LITELLM_BASE_URL", "https://gateway.example")
    clean_llm_env.setenv("LITELLM_MODEL", "m")
    clean_llm_env.setenv("OPENAI_API_KEY", "unrelated-oai-key")
    assert LLMConfig.from_env().api_key == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 120),
        ("9", 9),
        ("1", 1),
        ("3600", 3600),
        ("0", None),
        ("-4", None),
        ("3601", None),
        ("soon", None),
    ],
)
def test_timeout_env_validation(
    clean_llm_env: pytest.MonkeyPatch,
    raw: str | None,
    expected: int | None,
) -> None:
    clean_llm_env.setenv("LITELLM_BASE_URL", "https://generic.example")
    clean_llm_env.setenv("LITELLM_MODEL", "m")
    if raw is not None:
        clean_llm_env.setenv("REPROAGENT_LITELLM_TIMEOUT", raw)
    if expected is None:
        with pytest.raises(
            LLMUnavailableError,
            match="must be an integer in \\[1, 3600\\] seconds",
        ):
            LLMConfig.from_env()
    else:
        assert LLMConfig.from_env().timeout == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, None), (False, None), (7, 7), ("12", 12), (-1, None), ("x", None), (None, None)],
)
def test_safe_int_coercion(value: Any, expected: int | None) -> None:
    assert llm._safe_int(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, None),
        (3.5, 3.5),
        ("0.25", 0.25),
        (-0.1, None),
        (float("nan"), None),
        (float("inf"), None),
        ("nan", None),
        ("junk", None),
        (None, None),
    ],
)
def test_safe_float_coercion(value: Any, expected: float | None) -> None:
    assert llm._safe_float(value) == expected


def test_complete_json_posts_openai_payload_and_records_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    seen: dict[str, Any] = {}

    def fake_requests_post(url: str, **kwargs: Any) -> FakeResponse:
        seen.update(
            {
                "url": url,
                "headers": kwargs["headers"],
                "payload": kwargs["json"],
                "timeout": kwargs["timeout"],
            }
        )
        return FakeResponse(body=_chat_body())

    monkeypatch.setattr(llm.requests, "post", fake_requests_post)

    result = client.complete_json(system="sys prompt", user="usr prompt", temperature=0.3)

    assert result == {"answer": 42}
    assert seen["url"] == "https://llm.example/v1/chat/completions"
    assert seen["timeout"] == client.config.timeout
    assert seen["headers"]["Authorization"] == "Bearer k"
    assert seen["headers"]["Content-Type"] == "application/json"
    payload = seen["payload"]
    assert payload["model"] == "model-x"
    assert payload["messages"] == [
        {"role": "system", "content": "sys prompt"},
        {"role": "user", "content": "usr prompt"},
    ]
    assert payload["temperature"] == 0.3
    assert payload["max_tokens"] == 6000
    assert payload["response_format"] == {"type": "json_object"}

    usage = client.last_usage
    assert usage is not None
    assert usage["request_model"] == "model-x"
    assert usage["response_model"] == "server-model"
    assert usage["prompt_tokens"] == 11
    assert usage["completion_tokens"] == 7
    assert usage["total_tokens"] == 18
    assert usage["cached_tokens"] == 4
    assert usage["reasoning_tokens"] == 2
    assert usage["cost_usd"] == 0.25
    assert usage["request_count"] == 1
    assert "error" not in usage


def test_complete_json_omits_auth_header_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(api_key="")
    seen: dict[str, Any] = {}

    def fake_requests_post(url: str, **kwargs: Any) -> FakeResponse:
        del url
        seen["headers"] = kwargs["headers"]
        return FakeResponse(body=_chat_body())

    monkeypatch.setattr(llm.requests, "post", fake_requests_post)
    client.complete_json(system="s", user="u")

    assert "Authorization" not in seen["headers"]
    assert seen["headers"]["Content-Type"] == "application/json"


def test_complete_json_adds_reasoning_effort_only_when_configured(
    clean_llm_env: pytest.MonkeyPatch,
) -> None:
    default_client = _client()
    payloads = _stub_post(default_client, FakeResponse(body=_chat_body()))
    default_client.complete_json(system="s", user="u")
    assert "reasoning_effort" not in payloads[0]

    clean_llm_env.setenv("VERIREPRO_LITELLM_REASONING_EFFORT", "high")
    configured_client = _client()
    payloads = _stub_post(configured_client, FakeResponse(body=_chat_body()))
    configured_client.complete_json(system="s", user="u")
    assert payloads[0]["reasoning_effort"] == "high"

    clean_llm_env.setenv("VERIREPRO_LLM_REASONING_EFFORT", "low")
    preferred_client = _client()
    payloads = _stub_post(preferred_client, FakeResponse(body=_chat_body()))
    preferred_client.complete_json(system="s", user="u")
    assert payloads[0]["reasoning_effort"] == "low"

    clean_llm_env.setenv("REPROAGENT_LITELLM_REASONING_EFFORT", "medium")
    clean_llm_env.delenv("VERIREPRO_LLM_REASONING_EFFORT")
    clean_llm_env.delenv("VERIREPRO_LITELLM_REASONING_EFFORT")
    legacy_client = _client()
    payloads = _stub_post(legacy_client, FakeResponse(body=_chat_body()))
    legacy_client.complete_json(system="s", user="u")
    assert payloads[0]["reasoning_effort"] == "medium"


@pytest.mark.parametrize("status_code", [400, 404, 422])
def test_complete_json_retries_once_without_response_format(status_code: int) -> None:
    client = _client()
    payloads = _stub_post(
        client,
        FakeResponse(status_code=status_code),
        FakeResponse(body=_chat_body()),
    )

    assert client.complete_json(system="s", user="u") == {"answer": 42}
    assert len(payloads) == 2
    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in payloads[1]
    assert client.last_usage is not None
    assert client.last_usage["request_count"] == 2
    assert "error" not in client.last_usage


def test_complete_json_http_error_becomes_redacted_typed_error() -> None:
    client = _client()
    _stub_post(client, FakeResponse(status_code=500))

    with pytest.raises(LLMUnavailableError, match=r"Model endpoint request failed \(HTTPError\)"):
        client.complete_json(system="s", user="u")

    assert client.last_usage is not None
    assert client.last_usage["error"] == "HTTPError"
    assert client.last_usage["request_count"] == 1
    assert client.last_usage["prompt_tokens"] is None
    assert "llm.example" not in str(client.last_usage)


def test_complete_json_second_stage_failure_still_typed() -> None:
    client = _client()
    _stub_post(
        client,
        FakeResponse(status_code=400),
        FakeResponse(status_code=500),
    )

    with pytest.raises(LLMUnavailableError, match=r"request failed \(HTTPError\)") as exc_info:
        client.complete_json(system="s", user="u")

    assert exc_info.value.__suppress_context__ is True
    assert client.last_usage is not None
    assert client.last_usage["error"] == "HTTPError"
    assert client.last_usage["request_count"] == 2


@pytest.mark.parametrize(
    ("exc_type", "error_name"),
    [
        (requests.Timeout, "Timeout"),
        (requests.ConnectTimeout, "ConnectTimeout"),
        (requests.ConnectionError, "ConnectionError"),
        (requests.ReadTimeout, "ReadTimeout"),
    ],
)
def test_complete_json_transport_failures_are_typed_and_redacted(
    exc_type: type[requests.RequestException],
    error_name: str,
) -> None:
    client = _client()

    def fail_post(payload: dict[str, Any]) -> FakeResponse:
        del payload
        raise exc_type(f"POST https://llm.example/v1/chat/completions leaked {error_name}")

    client._post = fail_post  # type: ignore[method-assign]

    with pytest.raises(LLMUnavailableError) as exc_info:
        client.complete_json(system="s", user="u")

    message = str(exc_info.value)
    assert error_name in message
    assert "llm.example" not in message
    assert exc_info.value.__suppress_context__ is True
    assert client.last_usage is not None
    assert client.last_usage["error"] == error_name
    assert "llm.example" not in str(client.last_usage)


def test_complete_json_does_not_leak_stale_usage_after_failure() -> None:
    client = _client()
    _stub_post(client, FakeResponse(body=_chat_body()))
    client.complete_json(system="s", user="u")
    assert client.last_usage is not None
    assert client.last_usage["total_tokens"] == 18

    def fail_post(payload: dict[str, Any]) -> FakeResponse:
        del payload
        raise requests.Timeout("slow upstream")

    client._post = fail_post  # type: ignore[method-assign]
    with pytest.raises(LLMUnavailableError):
        client.complete_json(system="s", user="u")

    assert client.last_usage is not None
    assert client.last_usage["error"] == "Timeout"
    assert client.last_usage["prompt_tokens"] is None
    assert client.last_usage["total_tokens"] is None


@pytest.mark.parametrize(
    ("response_kwargs", "fragment"),
    [
        ({"body": [1, 2]}, "unexpected response shape"),
        (
            {"body": {}, "json_error": ValueError("not JSON")},
            "unexpected response shape",
        ),
        ({"body": {"choices": []}}, "unexpected response shape"),
        ({"body": {"choices": [{"message": {}}]}}, "unexpected response shape"),
        ({"body": {"choices": [{"message": {"content": None}}]}}, "was not text or JSON"),
        ({"body": {"choices": [{"message": {"content": 3.14}}]}}, "was not text or JSON"),
    ],
)
def test_complete_json_shape_failures_are_typed(
    response_kwargs: dict[str, Any],
    fragment: str,
) -> None:
    client = _client()
    _stub_post(client, FakeResponse(**response_kwargs))

    with pytest.raises(LLMUnavailableError, match=fragment):
        client.complete_json(system="s", user="u")


def test_complete_json_returns_structured_dict_content_directly() -> None:
    body = _chat_body()
    body["choices"][0]["message"]["content"] = {"answer": {"nested": True}}
    client = _client()
    _stub_post(client, FakeResponse(body=body))

    assert client.complete_json(system="s", user="u") == {"answer": {"nested": True}}


def test_parse_json_object_accepts_supported_encodings() -> None:
    parse = OpenAICompatibleClient._parse_json_object
    assert parse('{"a": 1}') == {"a": 1}
    assert parse('  {"a": 1}  ') == {"a": 1}
    assert parse('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse('```\n{"a": 1}\n```') == {"a": 1}
    assert parse('Sure! Here it is: {"a": 1}. Done.') == {"a": 1}
    assert parse('{"a": 1} trailing prose') == {"a": 1}


@pytest.mark.parametrize(
    "text",
    ["[1, 2]", "{oops", "no braces at all", '{"a": ', '```json\n{"a": 1'],
)
def test_parse_json_object_rejects_non_objects(text: str) -> None:
    with pytest.raises(LLMUnavailableError, match="did not return a JSON object"):
        OpenAICompatibleClient._parse_json_object(text)


@pytest.mark.parametrize(
    ("body", "expected_cost"),
    [
        (
            {
                "response_cost": 0.5,
                "response_cost_usd": 9.0,
                "_hidden_params": {"response_cost": 7.0},
            },
            0.5,
        ),
        ({"response_cost_usd": 9.0, "_hidden_params": {"response_cost": 7.0}}, 9.0),
        ({"_hidden_params": {"response_cost": 7.25}}, 7.25),
        ({}, None),
        ({"response_cost": True}, None),
        ({"response_cost": -2}, None),
        ({"response_cost": float("nan")}, None),
        ({"response_cost": "1.5"}, 1.5),
    ],
)
def test_record_usage_cost_precedence_and_sanitization(
    body: dict[str, Any],
    expected_cost: float | None,
) -> None:
    client = _client()
    client._record_usage(body, duration_seconds=1.5, request_count=3)

    usage = client.last_usage
    assert usage is not None
    assert usage["cost_usd"] == expected_cost
    assert usage["duration_seconds"] == 1.5
    assert usage["request_count"] == 3


def test_record_usage_sanitizes_token_details() -> None:
    client = _client()
    client._record_usage(
        {
            "usage": {
                "prompt_tokens": True,
                "completion_tokens": "12",
                "total_tokens": -1,
                "prompt_tokens_details": {"cached_tokens": "junk"},
                "completion_tokens_details": {"reasoning_tokens": False},
            },
            "usage_garbage": "dropped",
        },
        duration_seconds=0.25,
        request_count=1,
    )

    usage = client.last_usage
    assert usage == {
        "request_model": "model-x",
        "response_model": "model-x",
        "duration_seconds": 0.25,
        "request_count": 1,
        "prompt_tokens": None,
        "completion_tokens": 12,
        "total_tokens": None,
        "cached_tokens": None,
        "reasoning_tokens": None,
        "cost_usd": None,
    }
    assert "usage_garbage" not in usage


def test_capture_model_usage_collects_public_snapshots_then_resets() -> None:
    client = _client(api_key="secret-key-value")
    _stub_post(client, FakeResponse(body=_chat_body()), FakeResponse(body=_chat_body()))

    with capture_model_usage() as records:
        client.complete_json(system="s", user="u")
        client.complete_json(system="s", user="u")
        assert len(records) == 2
        for record in records:
            assert set(record) <= _PUBLIC_USAGE_FIELDS
            serialized = str(record)
            assert "secret-key-value" not in serialized
            assert "llm.example" not in serialized

    with capture_model_usage() as fresh:
        assert fresh == []


def test_capture_usage_is_bounded_and_skips_empty_snapshots() -> None:
    with capture_model_usage() as records:
        llm._capture_usage(None)
        llm._capture_usage({})
        llm._capture_usage([])
        assert records == []

        for index in range(llm._MAX_CAPTURED_USAGE_RECORDS + 8):
            llm._capture_usage({"request_model": f"m{index}"})

        assert len(records) == llm._MAX_CAPTURED_USAGE_RECORDS
        assert records[-1]["request_model"] == "m31"


def test_capture_is_opt_in_outside_context() -> None:
    client = _client()
    _stub_post(client, FakeResponse(body=_chat_body()))

    token_before = llm._CAPTURED_USAGE.get()
    assert token_before is None
    client.complete_json(system="s", user="u")
    assert llm._CAPTURED_USAGE.get() is None

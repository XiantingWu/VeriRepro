from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import requests

from .usage import public_model_usage


class LLMUnavailableError(RuntimeError):
    """Raised when the configured OpenAI-compatible endpoint cannot be used."""


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


_MIN_LLM_TIMEOUT = 1
_MAX_LLM_TIMEOUT = 3600


def _parse_llm_timeout(value: str) -> int:
    try:
        timeout = int(value)
    except ValueError:
        raise LLMUnavailableError(
            "Model endpoint timeout must be an integer in [1, 3600] seconds"
        ) from None
    if not _MIN_LLM_TIMEOUT <= timeout <= _MAX_LLM_TIMEOUT:
        raise LLMUnavailableError("Model endpoint timeout must be an integer in [1, 3600] seconds")
    return timeout


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    timeout: int = 120

    @classmethod
    def from_env(cls, *, model: str | None = None) -> LLMConfig | None:
        # The VERIREPRO_LLM_* namespace is preferred; the remaining names are
        # legacy 0.x environment aliases retained for compatibility.
        preferred_base = _first_env("VERIREPRO_LLM_BASE_URL")
        veri_base = _first_env("VERIREPRO_LITELLM_BASE_URL")
        legacy_base = _first_env("REPROAGENT_LITELLM_BASE_URL")
        litellm_base = _first_env("LITELLM_BASE_URL")
        openai_base = _first_env("OPENAI_BASE_URL")

        if preferred_base or veri_base:
            base_url = preferred_base or veri_base
            api_key = _first_env(
                "VERIREPRO_LLM_API_KEY",
                "VERIREPRO_LITELLM_API_KEY",
                "REPROAGENT_LITELLM_API_KEY",
                "LITELLM_API_KEY",
            )
        elif legacy_base:
            base_url = legacy_base
            api_key = _first_env(
                "VERIREPRO_LLM_API_KEY",
                "REPROAGENT_LITELLM_API_KEY",
                "VERIREPRO_LITELLM_API_KEY",
                "LITELLM_API_KEY",
            )
        elif litellm_base:
            base_url = litellm_base
            api_key = _first_env(
                "VERIREPRO_LLM_API_KEY",
                "LITELLM_API_KEY",
                "VERIREPRO_LITELLM_API_KEY",
                "REPROAGENT_LITELLM_API_KEY",
            )
        elif openai_base:
            base_url = openai_base
            api_key = _first_env("OPENAI_API_KEY")
        else:
            return None

        resolved_model = (
            model
            or _first_env(
                "VERIREPRO_LLM_MODEL",
                "VERIREPRO_LITELLM_MODEL",
                "REPROAGENT_LITELLM_MODEL",
                "LITELLM_MODEL",
            )
        ).strip()
        if not resolved_model:
            return None
        timeout = _parse_llm_timeout(
            _first_env(
                "VERIREPRO_LLM_TIMEOUT",
                "VERIREPRO_LITELLM_TIMEOUT",
                "REPROAGENT_LITELLM_TIMEOUT",
                default="120",
            )
        )
        return cls(base_url=base_url, api_key=api_key, model=resolved_model, timeout=timeout)

    @property
    def chat_completions_url(self) -> str:
        root = self.base_url.rstrip("/")
        if root.endswith("/chat/completions"):
            return root
        if root.endswith("/v1"):
            return f"{root}/chat/completions"
        return f"{root}/v1/chat/completions"


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def _nested_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


# Capture is deliberately opt-in. Normal VeriRepro use does not retain a
# process-global history of model calls. ContextVar keeps concurrent task
# contexts isolated, while a hard cap bounds benchmark-side memory use.
_CAPTURED_USAGE: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "verirepro_captured_model_usage", default=None
)
_MAX_CAPTURED_USAGE_RECORDS = 32


def _capture_usage(usage: dict[str, Any] | None) -> None:
    records = _CAPTURED_USAGE.get()
    if records is None or len(records) >= _MAX_CAPTURED_USAGE_RECORDS:
        return
    snapshot = public_model_usage(usage)
    if snapshot:
        records.append(snapshot)


@contextmanager
def capture_model_usage() -> Iterator[list[dict[str, Any]]]:
    """Capture non-secret model telemetry only inside the current context.

    The returned list is populated as OpenAI-compatible calls complete. It is
    reset automatically on exit, so separate benchmark tasks cannot inherit a
    previous task's telemetry. Prompts, response content, endpoint URLs, keys,
    headers, and future unrecognized fields are never captured.
    """
    records: list[dict[str, Any]] = []
    token = _CAPTURED_USAGE.set(records)
    try:
        yield records
    finally:
        _CAPTURED_USAGE.reset(token)


class OpenAICompatibleClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.last_usage: dict[str, Any] | None = None

    def _post(self, payload: dict[str, Any]) -> requests.Response:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return requests.post(
            self.config.chat_completions_url,
            headers=headers,
            json=payload,
            timeout=self.config.timeout,
        )

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        candidate = text.strip()
        if candidate.startswith("```json"):
            candidate = candidate[7:]
        elif candidate.startswith("```"):
            candidate = candidate[3:]
        if candidate.endswith("```"):
            candidate = candidate[:-3]
        candidate = candidate.strip()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()
        for index, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise LLMUnavailableError("Model endpoint did not return a JSON object")

    def _record_usage(
        self,
        body: dict[str, Any],
        *,
        duration_seconds: float,
        request_count: int,
    ) -> None:
        usage = _nested_dict(body.get("usage"))
        prompt_details = _nested_dict(usage.get("prompt_tokens_details"))
        completion_details = _nested_dict(usage.get("completion_tokens_details"))
        hidden = _nested_dict(body.get("_hidden_params"))
        cost = body.get("response_cost")
        if cost is None:
            cost = body.get("response_cost_usd")
        if cost is None:
            cost = hidden.get("response_cost")

        self.last_usage = {
            "request_model": self.config.model,
            "response_model": str(body.get("model") or self.config.model),
            "duration_seconds": round(duration_seconds, 6),
            "request_count": request_count,
            "prompt_tokens": _safe_int(usage.get("prompt_tokens")),
            "completion_tokens": _safe_int(usage.get("completion_tokens")),
            "total_tokens": _safe_int(usage.get("total_tokens")),
            "cached_tokens": _safe_int(prompt_details.get("cached_tokens")),
            "reasoning_tokens": _safe_int(completion_details.get("reasoning_tokens")),
            "cost_usd": _safe_float(cost),
        }
        _capture_usage(self.last_usage)

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 6000,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        reasoning_effort = _first_env(
            "VERIREPRO_LLM_REASONING_EFFORT",
            "VERIREPRO_LITELLM_REASONING_EFFORT",
            "REPROAGENT_LITELLM_REASONING_EFFORT",
        )
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort

        started = time.monotonic()
        request_count = 0
        self.last_usage = None
        try:
            request_count += 1
            response = self._post(payload)
            if response.status_code in {400, 404, 422}:
                fallback = dict(payload)
                fallback.pop("response_format", None)
                request_count += 1
                response = self._post(fallback)
            response.raise_for_status()
        except requests.RequestException as exc:
            error_name = type(exc).__name__
            self.last_usage = {
                "request_model": self.config.model,
                "response_model": None,
                "duration_seconds": round(time.monotonic() - started, 6),
                "request_count": request_count,
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "cached_tokens": None,
                "reasoning_tokens": None,
                "cost_usd": None,
                "error": error_name,
            }
            _capture_usage(self.last_usage)
            # requests exceptions often embed the complete endpoint URL/host.
            # Reports and support diagnostics must not persist configured private
            # gateway details, so retain only the exception class. Suppress the
            # chained requests exception as well so a CLI traceback cannot reveal it.
            raise LLMUnavailableError(f"Model endpoint request failed ({error_name})") from None

        try:
            body = response.json()
            if not isinstance(body, dict):
                raise TypeError("response JSON was not an object")
            self._record_usage(
                body,
                duration_seconds=time.monotonic() - started,
                request_count=request_count,
            )
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailableError(
                "Model endpoint returned an unexpected response shape"
            ) from exc

        if isinstance(content, dict):
            return content
        if not isinstance(content, str):
            raise LLMUnavailableError("Model endpoint response content was not text or JSON")
        return self._parse_json_object(content)

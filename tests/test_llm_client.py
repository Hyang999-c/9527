from __future__ import annotations

import json

import httpx
import pytest

from aspirin_agent.errors import LLMError
from aspirin_agent.llm_client import LLMClient


def make_client(handler, **kwargs) -> LLMClient:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return LLMClient(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        client=client,
        retries=kwargs.pop("retries", 3),
        backoff=0,
        sleep=lambda _: None,
        **kwargs,
    )


def ok_response(content: str = '{"evidence": []}') -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def test_complete_sends_expected_payload() -> None:
    captured: dict = {}
    headers: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        headers.update(request.headers)
        return ok_response()

    output = make_client(handler).complete(
        [{"role": "user", "content": "hi"}], temperature=0.2, max_tokens=100
    )

    assert output == '{"evidence": []}'
    assert captured["model"] == "test-model"
    assert captured["temperature"] == 0.2
    assert captured["max_tokens"] == 100
    assert captured["response_format"] == {"type": "json_object"}
    assert headers["authorization"] == "Bearer test-key"


def test_json_mode_can_be_disabled() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return ok_response("plain text")

    assert make_client(handler).complete([{"role": "user", "content": "x"}], json_mode=False) == "plain text"
    assert "response_format" not in captured


def test_from_settings_without_key_returns_none(monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert LLMClient.from_settings({}) is None


def test_from_settings_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://env.test/v1")
    monkeypatch.setenv("LLM_MODEL", "env-model")

    client = LLMClient.from_settings({"llm": {"timeout_seconds": 5}})

    assert client is not None
    assert client.api_key == "k"
    assert client.base_url == "https://env.test/v1"
    assert client.model == "env-model"
    client.close()


def test_retry_on_429_then_success() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, text="rate limited")
        return ok_response()

    assert make_client(handler).complete([{"role": "user", "content": "x"}])
    assert calls["count"] == 2


def test_gives_up_after_retries() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(500, text="boom")

    with pytest.raises(LLMError):
        make_client(handler).complete([{"role": "user", "content": "x"}])
    assert calls["count"] == 3


def test_400_with_response_format_falls_back() -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        payloads.append(payload)
        if len(payloads) == 1:
            return httpx.Response(400, text="response_format not supported")
        return ok_response()

    output = make_client(handler).complete([{"role": "user", "content": "x"}])

    assert output == '{"evidence": []}'
    assert len(payloads) == 2
    assert "response_format" in payloads[0]
    assert "response_format" not in payloads[1]


def test_non_retryable_400_raises() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(401, text="bad key")

    with pytest.raises(LLMError):
        make_client(handler).complete([{"role": "user", "content": "x"}], json_mode=False)
    assert calls["count"] == 1


def test_missing_choices_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(LLMError):
        make_client(handler).complete([{"role": "user", "content": "x"}])


def test_empty_content_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]})

    with pytest.raises(LLMError):
        make_client(handler).complete([{"role": "user", "content": "x"}])

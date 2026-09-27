import time

import httpx
import openai
import pytest

import config
from agent.llm_client import LLMError, OpenAILLMClient


def test_client_refuses_to_construct_without_an_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        OpenAILLMClient()


def test_client_defaults_to_the_pinned_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = OpenAILLMClient()
    assert client.model == "gpt-4o-mini"


def test_the_client_keeps_no_copy_of_the_key_in_its_own_state(monkeypatch):
    """A key leaked into a traceback ends up in a screenshot.

    Asserting only on `repr()` was vacuous: `__repr__` is hard-coded to
    `OpenAILLMClient(model=...)` and could not contain the key under any
    implementation. `client.__dict__` is the falsifiable version — adding the
    obvious convenience `self.api_key = api_key` to `__init__` fails this test,
    and that attribute is exactly what a `st.exception()` or a debugger dump
    would surface.

    The key does still live inside the vendored SDK object
    (`client._client.api_key`); that is the SDK's storage, not ours. The
    complementary guard for the path that actually reaches a user's screen is
    `test_auth_error_message_does_not_leak_the_key` below.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value")
    client = OpenAILLMClient()
    assert "sk-secret-value" not in repr(client)
    assert "sk-secret-value" not in str(client.__dict__)


def _client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    return OpenAILLMClient()


def _fake_response(status_code: int = 401) -> httpx.Response:
    """openai's APIStatusError subclasses read response.request/status_code/
    headers in their own __init__, so a bare None fails construction — build a
    minimal real httpx.Response instead."""
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return httpx.Response(status_code=status_code, request=request)


def test_auth_error_is_not_retried(monkeypatch):
    """A bad key fails the same way on attempt 3 as on attempt 1 — don't sleep."""
    client = _client(monkeypatch)
    attempts = []

    def call():
        attempts.append(1)
        raise openai.AuthenticationError("Incorrect API key provided: sk-tes***test",
                                         response=_fake_response(), body=None)

    started = time.monotonic()
    with pytest.raises(LLMError):
        client._with_retries(call)
    assert len(attempts) == 1
    assert time.monotonic() - started < 1.0


def test_auth_error_message_does_not_leak_the_key(monkeypatch):
    client = _client(monkeypatch)

    def call():
        raise openai.AuthenticationError("Incorrect API key provided: sk-tes***test",
                                         response=_fake_response(), body=None)

    with pytest.raises(LLMError) as excinfo:
        client._with_retries(call)
    assert "sk-tes" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None  # not chained: keeps the key out of tracebacks


def test_transient_error_is_retried_then_wrapped(monkeypatch):
    client = _client(monkeypatch)
    attempts = []

    def call():
        attempts.append(1)
        raise openai.APIConnectionError(request=None)

    with pytest.raises(LLMError):
        client._with_retries(call)
    assert len(attempts) == config.MAX_RETRIES + 1


def test_transient_success_after_one_failure(monkeypatch):
    client = _client(monkeypatch)
    calls = []

    def call():
        calls.append(1)
        if len(calls) == 1:
            raise openai.APIConnectionError(request=None)
        return "ok"

    result, latency_ms = client._with_retries(call)
    assert result == "ok"
    assert latency_ms >= 0

"""Thin OpenAI wrapper. The only module in the project that imports `openai`.

Uses Structured Outputs so responses are schema-valid by construction rather
than by parsing and hoping.
"""
import time
from dataclasses import dataclass
from typing import Any, Protocol

import openai
from openai import OpenAI
from pydantic import BaseModel

import config

# Only these are worth retrying. Everything else — bad key, bad schema, bad
# request — fails the same way on attempt three as on attempt one.
_RETRYABLE = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
)


class LLMError(Exception):
    """Any failure talking to the model. Never carries the API key."""


@dataclass
class LLMResult:
    value: Any
    raw: str
    tokens: int
    latency_ms: int


class LLMClient(Protocol):
    def parse(self, system: str, user: str, schema: type[BaseModel],
              *, temperature: float) -> LLMResult: ...

    def complete(self, system: str, user: str, *, temperature: float) -> LLMResult: ...


class OpenAILLMClient:
    def __init__(self, model: str = config.DEFAULT_MODEL):
        api_key = config.get_api_key()
        if not api_key:
            raise LLMError(
                "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        self.model = model
        self._client = OpenAI(api_key=api_key, timeout=config.REQUEST_TIMEOUT_SECONDS)

    def __repr__(self) -> str:
        return f"OpenAILLMClient(model={self.model!r})"

    def parse(self, system: str, user: str, schema: type[BaseModel],
              *, temperature: float = 0.1) -> LLMResult:
        def call():
            return self._client.chat.completions.parse(
                model=self.model,
                temperature=temperature,
                response_format=schema,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
            )

        response, latency_ms = self._with_retries(call)
        message = response.choices[0].message
        if message.refusal:
            raise LLMError(f"Model refused the request: {message.refusal}")
        if message.parsed is None:
            raise LLMError("Model returned no parseable content.")
        return LLMResult(
            value=message.parsed,
            raw=message.content or "",
            tokens=response.usage.total_tokens if response.usage else 0,
            latency_ms=latency_ms,
        )

    def complete(self, system: str, user: str, *, temperature: float = 0.4) -> LLMResult:
        def call():
            return self._client.chat.completions.create(
                model=self.model,
                temperature=temperature,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
            )

        response, latency_ms = self._with_retries(call)
        return LLMResult(
            value=response.choices[0].message.content or "",
            raw=response.choices[0].message.content or "",
            tokens=response.usage.total_tokens if response.usage else 0,
            latency_ms=latency_ms,
        )

    def _with_retries(self, call):
        """Exponential backoff on transient failures only.

        A non-retryable failure (bad key, bad schema, bad request) is known on
        attempt one and would fail the same way on attempt three — retrying it
        just burns time.sleep(2**attempt) for nothing. It's raised immediately,
        unchained (`from None`): that's what keeps a key-bearing SDK message
        (e.g. AuthenticationError's "Incorrect API key provided: sk-tes***test")
        out of any traceback Streamlit renders. Do not "helpfully" restore the
        chain here.
        """
        started = time.monotonic()
        last_error: Exception | None = None
        for attempt in range(config.MAX_RETRIES + 1):
            try:
                result = call()
                return result, int((time.monotonic() - started) * 1000)
            except _RETRYABLE as exc:
                last_error = exc
                if attempt < config.MAX_RETRIES:
                    time.sleep(2 ** attempt)
            except Exception as exc:
                raise LLMError(f"Model call failed: {type(exc).__name__}") from None
        raise LLMError(f"Model call failed after {config.MAX_RETRIES + 1} attempts: "
                       f"{type(last_error).__name__}") from last_error

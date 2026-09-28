"""Chat completions from Groq (SPEC-05 §7), with backoff and a fallback model.

The only module that imports the `openai` SDK (Groq's API is OpenAI-compatible).
It returns raw text: parsing and validating it is the agent's job, so this layer
knows nothing about suggestions. JSON mode, no tool calling (fragile on Groq).
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

import openai
from openai.types.chat import ChatCompletionMessageParam

from backend.app.config import Settings

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
TEMPERATURE = 0.1
TIMEOUT_SECONDS = 30.0
BACKOFF_SECONDS = (1.0, 2.0, 4.0)
"""Waits between attempts on one model before moving to the next (429 / 5xx / network)."""


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int


class LLMUnavailableError(RuntimeError):
    """No model answered: rate limits, outages, or a bad key."""


class ChatModel(Protocol):
    def complete(self, messages: Sequence[Message]) -> Completion: ...


class GroqChat:
    """Tries each model in turn; on each, retries transient failures with backoff."""

    def __init__(
        self,
        api_key: str,
        models: Sequence[str],
        *,
        base_url: str = GROQ_BASE_URL,
        sleep: Callable[[float], None] = time.sleep,
        client: openai.OpenAI | None = None,
    ) -> None:
        if not models:
            raise ValueError("at least one model is required")
        self.models = tuple(models)
        self._sleep = sleep
        # The SDK's own retries are off: backoff and fallback are ours (§7). Without a key
        # there is no client, and every call fails as unavailable (the agent escalates).
        self._client = client
        if client is None and api_key:
            self._client = openai.OpenAI(
                api_key=api_key, base_url=base_url, timeout=TIMEOUT_SECONDS, max_retries=0
            )

    @classmethod
    def from_settings(cls, settings: Settings) -> "GroqChat":
        return cls(
            settings.groq_api_key.get_secret_value(),
            [settings.groq_model, settings.groq_fallback_model],
        )

    def complete(self, messages: Sequence[Message]) -> Completion:
        if self._client is None:
            raise LLMUnavailableError("GROQ_API_KEY is not set")
        errors: list[str] = []
        for model in self.models:
            for wait in (*BACKOFF_SECONDS, None):
                try:
                    return self._call(model, messages)
                except openai.APIStatusError as exc:
                    if (generation := _failed_generation(exc)) is not None:
                        # Groq rejected the model's own output as invalid JSON. That is
                        # bad output, not an outage: hand it back for the agent to retry.
                        return Completion(generation, model, 0, 0)
                    errors.append(f"{model}: HTTP {exc.status_code}")
                    if not _transient(exc.status_code):
                        if exc.status_code in (401, 403):
                            raise LLMUnavailableError(f"{model}: HTTP {exc.status_code}") from exc
                        break  # e.g. model not found: try the next model
                except openai.APIConnectionError as exc:  # includes timeouts
                    errors.append(f"{model}: {type(exc).__name__}")
                if wait is None:
                    break
                self._sleep(wait)
        raise LLMUnavailableError("; ".join(errors))

    def _call(self, model: str, messages: Sequence[Message]) -> Completion:
        assert self._client is not None
        response = self._client.chat.completions.create(
            model=model,
            messages=[_param(m) for m in messages],
            temperature=TEMPERATURE,
            response_format={"type": "json_object"},
        )
        usage = response.usage
        return Completion(
            text=response.choices[0].message.content or "",
            model=model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )


def _param(message: Message) -> ChatCompletionMessageParam:
    match message.role:
        case "system":
            return {"role": "system", "content": message.content}
        case "user":
            return {"role": "user", "content": message.content}
        case "assistant":
            return {"role": "assistant", "content": message.content}


def _transient(status: int) -> bool:
    return status == 429 or status >= 500


def _failed_generation(exc: openai.APIStatusError) -> str | None:
    """The rejected output from Groq's `json_validate_failed` error, if that is what this is."""
    if exc.status_code != 400 or not isinstance(exc.body, dict):
        return None
    error = exc.body.get("error", exc.body)
    if not isinstance(error, dict) or error.get("code") != "json_validate_failed":
        return None
    generation = error.get("failed_generation")
    return generation if isinstance(generation, str) else ""

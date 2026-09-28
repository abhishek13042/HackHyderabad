"""SPEC-05 §7: Groq calls, backoff and fallback, with a fake SDK client."""

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx2
import openai
import pytest

from backend.app.llm import (
    BACKOFF_SECONDS,
    MAX_RETRY_AFTER_SECONDS,
    RATE_LIMIT_BACKOFF_SECONDS,
    TEMPERATURE,
    GroqChat,
    LLMUnavailableError,
    Message,
)

REQUEST = httpx2.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
MESSAGES = [Message("system", "rules"), Message("user", "facts")]


def status_error(
    status: int, body: object = None, headers: dict[str, str] | None = None
) -> openai.APIStatusError:
    response = httpx2.Response(status, request=REQUEST, headers=headers)
    return openai.APIStatusError(f"HTTP {status}", response=response, body=body)


def reply(text: str = '{"ok": true}') -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30),
    )


class FakeClient:
    """Stands in for `openai.OpenAI`: replays outcomes, records requests."""

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **request: Any) -> Any:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def chat(*outcomes: Any) -> tuple[GroqChat, FakeClient, list[float]]:
    client = FakeClient(*outcomes)
    waits: list[float] = []
    groq = GroqChat("key", ["primary", "fallback"], sleep=waits.append,
                    client=cast(openai.OpenAI, client))  # fmt: skip
    return groq, client, waits


def test_request_uses_json_mode_and_low_temperature() -> None:
    groq, client, waits = chat(reply())
    completion = groq.complete(MESSAGES)
    assert (completion.text, completion.model) == ('{"ok": true}', "primary")
    assert (completion.prompt_tokens, completion.completion_tokens) == (120, 30)
    (request,) = client.requests
    assert request["response_format"] == {"type": "json_object"}
    assert request["temperature"] == TEMPERATURE
    assert request["messages"] == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "facts"},
    ]
    assert "tools" not in request and waits == []


def test_rate_limit_backs_off_then_succeeds() -> None:
    groq, _, waits = chat(status_error(429), status_error(503), reply())
    assert groq.complete(MESSAGES).model == "primary"
    assert waits == [RATE_LIMIT_BACKOFF_SECONDS[0], BACKOFF_SECONDS[1]]


def test_rate_limit_honours_retry_after_up_to_a_cap() -> None:
    groq, _, waits = chat(
        status_error(429, headers={"retry-after": "7"}),
        status_error(429, headers={"retry-after": "600"}),
        status_error(429, headers={"retry-after": "soon"}),
        reply(),
    )
    assert groq.complete(MESSAGES).model == "primary"
    # at least the rate-limit backoff, longer if Groq asks, never past the cap
    assert waits == [7.0, MAX_RETRY_AFTER_SECONDS, RATE_LIMIT_BACKOFF_SECONDS[2]]


def test_retry_after_is_ignored_on_server_errors() -> None:
    groq, _, waits = chat(status_error(503, headers={"retry-after": "9"}), reply())
    assert groq.complete(MESSAGES).model == "primary"
    assert waits == [1.0]


def test_falls_back_after_backoff_is_exhausted() -> None:
    failures = [status_error(429)] * (len(BACKOFF_SECONDS) + 1)
    groq, client, waits = chat(*failures, reply())
    assert groq.complete(MESSAGES).model == "fallback"
    assert waits == list(RATE_LIMIT_BACKOFF_SECONDS)
    assert [r["model"] for r in client.requests] == ["primary"] * 4 + ["fallback"]


def test_network_errors_count_as_transient() -> None:
    groq, _, waits = chat(openai.APITimeoutError(request=REQUEST), reply())
    assert groq.complete(MESSAGES).model == "primary" and waits == [1.0]


def test_unknown_model_moves_on_without_waiting() -> None:
    groq, _, waits = chat(status_error(404), reply())
    assert groq.complete(MESSAGES).model == "fallback" and waits == []


def test_bad_key_fails_at_once() -> None:
    groq, client, _ = chat(status_error(401))
    with pytest.raises(LLMUnavailableError, match="401"):
        groq.complete(MESSAGES)
    assert len(client.requests) == 1


def test_no_key_is_unavailable_without_a_request() -> None:
    """The app still starts without GROQ_API_KEY; suggestions escalate (SPEC-05 §8)."""
    with pytest.raises(LLMUnavailableError, match="GROQ_API_KEY"):
        GroqChat("", ["primary"]).complete(MESSAGES)


def test_everything_down() -> None:
    groq, _, _ = chat(*[status_error(500)] * 8)
    with pytest.raises(LLMUnavailableError, match=r"primary: HTTP 500.*fallback: HTTP 500"):
        groq.complete(MESSAGES)


def test_rejected_json_is_returned_as_bad_output() -> None:
    body = {"error": {"code": "json_validate_failed", "failed_generation": "{not json"}}
    groq, _, waits = chat(status_error(400, body))
    completion = groq.complete(MESSAGES)
    assert (completion.text, completion.model, waits) == ("{not json", "primary", [])


def test_needs_a_model() -> None:
    with pytest.raises(ValueError, match="model"):
        GroqChat("key", [])


def test_only_the_llm_module_imports_the_sdk() -> None:
    app = Path(__file__).resolve().parents[1] / "app"
    importers = {
        path.name
        for path in app.rglob("*.py")
        if re.search(r"^(?:import|from) openai\b", path.read_text(encoding="utf-8"), re.MULTILINE)
    }
    assert importers == {"llm.py"}

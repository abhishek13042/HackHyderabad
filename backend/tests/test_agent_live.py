"""SPEC-05 AC-05-6 against the real Groq API: April, every client, memory off.

Skipped without GROQ_API_KEY in `.env`. Run with `pytest -m groq -s` to see the
suggestions. April has 10 groups, so about 10 calls.
"""

from collections import Counter

import pytest

from backend.app.agent import MESSAGE_ACTIONS, Agent, AgentContext, Guardrail
from backend.app.config import get_settings
from backend.app.domain.entities import ReconException, Vendor
from backend.app.domain.enums import ExceptionType
from backend.app.domain.policy import ALLOWED_ACTIONS
from backend.app.llm import GroqChat
from backend.app.matcher import Detail, ExceptionGroup, reconcile
from backend.datagen.build import build_dataset
from backend.datagen.cast import CLIENTS, PERIODS

pytestmark = pytest.mark.groq


def april_groups() -> list[tuple[ExceptionGroup, AgentContext]]:
    dataset = build_dataset(42)
    items = []
    for client in CLIENTS:
        open_missing: list[ReconException] = []
        for period in PERIODS:
            books = dataset.books[(client.client_id, period)]
            twob = dataset.twob[(client.client_id, period)]
            result = reconcile(client.client_id, period, books, twob, open_missing)
            closed = [late.exception for late in result.late_arrivals]
            open_missing = [e for e in open_missing if e not in closed] + [
                e for e in result.exceptions if e.type is ExceptionType.MISSING_IN_2B
            ]
        for group in result.groups:  # the last period: April
            name = str(group.exceptions[0].details[Detail.SUPPLIER_NAME])
            vendor = Vendor(gstin=group.key.vendor_gstin, name=name.title())
            items.append((group, AgentContext(client=client, vendor=vendor, memory_on=False)))
    return items


def test_ac_05_6_april_run_reaches_the_user_safely() -> None:
    settings = get_settings()
    if not settings.groq_api_key.get_secret_value():
        pytest.skip("GROQ_API_KEY not set")
    items = april_groups()
    suggestions = Agent(GroqChat.from_settings(settings)).suggest_all(items)

    events = Counter(e.rule for s in suggestions for e in s.guardrail_events)
    for s in suggestions:
        print(f"{s.group_key}  {s.action:<13} {s.confidence_label:<6} {s.reasoning}")
        assert s.action in ALLOWED_ACTIONS[s.group_key.exception_type]
        assert (s.vendor_message is not None) == (s.action in MESSAGE_ACTIONS)
        assert s.prompt_tokens > 0 and s.latency_ms > 0
    print("guardrail events:", dict(events))
    assert events[Guardrail.AI_UNAVAILABLE] == 0
    assert events[Guardrail.INVALID_OUTPUT] <= 1

"""SPEC-05: the agent, with a scripted LLM. Guardrails, retries, prompts, bookkeeping."""

import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pytest

from backend.app.agent import (
    MAX_LISTED_INVOICES,
    SYSTEM_PROMPT,
    Agent,
    AgentContext,
    AgentOutput,
    DriftInfo,
    Guardrail,
    Suggestion,
    TrustInfo,
    apply_guardrails,
    parse_output,
    user_message,
)
from backend.app.domain.entities import Client, GroupKey, ReconException, Vendor
from backend.app.domain.enums import Action, ExceptionType, Flag, RootCause, TrustLevel
from backend.app.domain.gstin import make_gstin
from backend.app.domain.policy import ALLOWED_ACTIONS
from backend.app.llm import Completion, LLMUnavailableError, Message
from backend.app.matcher import Detail, ExceptionGroup
from backend.app.memory import MemoryRecord
from backend.datagen.cast import PLANTED_VENDORS, RELIABLE_VENDORS

CLIENT = Client(
    client_id="C01",
    name="Sri Balaji Textiles",
    gstin=make_gstin("36", "AAKFS9876P"),
    business_type="Textile trader",
)
VENDOR = Vendor(gstin=make_gstin("36", "AABCR1234F"), name="Reddy Steels")
PERIOD = "2026-04"

KRISHNA_AT_C01 = MemoryRecord(
    id="9f1c-uuid-1",
    text="March 2026: At client Sri Balaji Textiles, vendor Reddy Steels (GSTIN …) had 2 invoices "
    "missing from GSTR-2B.\nThe accountant accepted it.",
    metadata={"client_id": "C01"},
)
AT_C03 = MemoryRecord(
    id="9f1c-uuid-2",
    text="February 2026: At client Vega Electronics Distributors, vendor Reddy Steels filed late.",
)


class ScriptedChat:
    """Returns the given answers in order and records what it was asked."""

    def __init__(self, *answers: str | Exception) -> None:
        self.answers = list(answers)
        self.calls: list[list[Message]] = []

    def complete(self, messages: Sequence[Message]) -> Completion:
        self.calls.append(list(messages))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return Completion(answer, "test-model", prompt_tokens=1000, completion_tokens=100)


def answer(**changes: Any) -> str:
    values: dict[str, Any] = {
        "action": "DEFER",
        "root_cause": "LATE_FILING",
        "flags": [],
        "confidence": 0.9,
        "reasoning": "Reddy Steels filed late in March and it arrived (M1).",
        "cited_memory_ids": ["M1"],
        "vendor_message": None,
    } | changes
    return json.dumps(values)


def exception(
    exception_type: ExceptionType = ExceptionType.MISSING_IN_2B, number: str = "RS/0467",
    **details: Any,
) -> ReconException:  # fmt: skip
    return ReconException(
        client_id="C01", period=PERIOD, type=exception_type, vendor_gstin=VENDOR.gstin,
        itc_at_risk=Decimal("16200"),
        details={Detail.INVOICE_NO: number, Detail.INVOICE_DATE: "2026-04-03",
                 Detail.BOOK_TOTAL: "106200.00", **details},
    )  # fmt: skip


def group(exception_type: ExceptionType = ExceptionType.MISSING_IN_2B, *exceptions: ReconException
          ) -> ExceptionGroup:  # fmt: skip
    key = GroupKey(client_id="C01", period=PERIOD, vendor_gstin=VENDOR.gstin,
                   exception_type=exception_type)  # fmt: skip
    return ExceptionGroup(key, exceptions or (exception(exception_type),))


def context(**changes: Any) -> AgentContext:
    values: dict[str, Any] = {
        "client": CLIENT,
        "vendor": VENDOR,
        "memories": (KRISHNA_AT_C01, AT_C03),
    } | changes
    return AgentContext(**values)


def suggest(*answers: str | Exception, g: ExceptionGroup | None = None,
            ctx: AgentContext | None = None) -> Suggestion:  # fmt: skip
    return Agent(ScriptedChat(*answers)).suggest(g or group(), ctx or context())


def rules(suggestion: Suggestion) -> list[Guardrail]:
    return [event.rule for event in suggestion.guardrail_events]


# --- The happy path ----------------------------------------------------------


def test_valid_answer_passes_through() -> None:
    s = suggest(answer(), ctx=context(trust=TrustInfo(TrustLevel.AUTO, 3, 0)))
    assert (s.action, s.root_cause, s.llm_confidence, s.final_confidence) == (
        Action.DEFER, RootCause.LATE_FILING, 0.9, 0.9,
    )  # fmt: skip
    assert s.cited_memory_ids == ("9f1c-uuid-1",)  # the real id, not "M1"
    assert s.guardrail_events == ()
    assert s.group_key == group().key and s.memory_on


def test_confidence_is_capped_by_trust() -> None:
    assert suggest(answer()).final_confidence == 0.6  # level 0 OBSERVE
    s = suggest(answer(), ctx=context(trust=TrustInfo(TrustLevel.SUGGEST, 2, 0)))
    assert s.final_confidence == 0.85
    assert s.confidence_label == "High"


# --- AC-05-1 … AC-05-5: guardrails -------------------------------------------


@pytest.mark.parametrize("exception_type", list(ExceptionType))
def test_ac_05_1_disallowed_action_becomes_escalate(exception_type: ExceptionType) -> None:
    disallowed = next(a for a in Action if a not in ALLOWED_ACTIONS[exception_type])
    s = suggest(answer(action=disallowed.value), g=group(exception_type))
    assert s.action is Action.ESCALATE
    assert Guardrail.UNSAFE_ACTION in rules(s)


@pytest.mark.parametrize(
    "exception_type", [ExceptionType.MISSING_IN_2B, ExceptionType.ITC_INELIGIBLE]
)
def test_accept_is_never_allowed_where_credit_is_missing(exception_type: ExceptionType) -> None:
    assert suggest(answer(action="ACCEPT"), g=group(exception_type)).action is Action.ESCALATE


def test_ac_05_2_unknown_citation_is_removed() -> None:
    s = suggest(answer(cited_memory_ids=["M1", "M7", "m_1a2b", "M1"]))
    assert s.cited_memory_ids == ("9f1c-uuid-1",)
    (event,) = s.guardrail_events
    assert event.rule is Guardrail.BAD_CITATION and "M7, m_1a2b" in event.detail


def test_ac_05_3_invalid_twice_then_valid() -> None:
    chat = ScriptedChat("not json", answer(action="PAY_EVERYTHING"), answer())
    s = Agent(chat).suggest(group(), context())
    assert s.action is Action.DEFER and s.guardrail_events == ()
    assert len(chat.calls) == 3
    retry = chat.calls[2]
    assert retry[-4].content == "not json"
    assert "action" in retry[-1].content  # the second error names the bad field
    assert (s.prompt_tokens, s.completion_tokens) == (3000, 300)


def test_ac_05_3_invalid_three_times_escalates() -> None:
    s = suggest("{", "[]", answer(confidence=7))
    assert (s.action, s.final_confidence) == (Action.ESCALATE, 0)
    assert rules(s) == [Guardrail.INVALID_OUTPUT]
    assert s.raw_output == answer(confidence=7)


def test_ac_05_4_drift_turns_defer_into_chase() -> None:
    drift = DriftInfo(("RS/2025-26/0441",), overdue_days=68, typical_lag_days=30)
    s = suggest(answer(), ctx=context(drift=drift))
    assert s.action is Action.CHASE_VENDOR
    assert Flag.PATTERN_DRIFT in s.flags
    assert rules(s) == [Guardrail.DRIFT_OVERRIDE, Guardrail.MISSING_MESSAGE]


@pytest.mark.parametrize("action", ["CHASE_VENDOR", "HOLD_PAYMENT"])
def test_ac_05_5_vendor_contact_always_has_a_message(action: str) -> None:
    s = suggest(answer(action=action, vendor_message="  "))
    assert s.vendor_message and "RS/0467 (₹1,06,200.00)" in s.vendor_message
    assert CLIENT.gstin in s.vendor_message
    assert Guardrail.MISSING_MESSAGE in rules(s)
    assert ("holding the GST portion" in s.vendor_message) == (action == "HOLD_PAYMENT")


def test_llm_message_is_kept_and_dropped_where_not_needed() -> None:
    kept = suggest(answer(action="CHASE_VENDOR", vendor_message="Dear Reddy Steels, please file."))
    assert kept.vendor_message == "Dear Reddy Steels, please file."
    assert suggest(answer(vendor_message="Hello")).vendor_message is None


def test_g3_history_without_citation_caps_confidence() -> None:
    s = suggest(answer(cited_memory_ids=[], reasoning="Reddy Steels usually files late."))
    assert s.llm_confidence == 0.9
    assert s.final_confidence == 0.5
    assert rules(s) == [Guardrail.UNGROUNDED]


def test_g3_plain_before_is_not_a_claim() -> None:
    s = suggest(answer(action="CHASE_VENDOR", cited_memory_ids=[], vendor_message="Hi",
                       reasoning="No memories. Chase before more credit is lost."))  # fmt: skip
    assert s.guardrail_events == ()


def test_g4_large_accepted_difference_escalates() -> None:
    small = exception(ExceptionType.AMOUNT_MISMATCH, **{Detail.AMOUNT_DIFF: "-8.00"})
    large = exception(ExceptionType.AMOUNT_MISMATCH, "RS/0470", **{Detail.AMOUNT_DIFF: "-1500.00"})
    t = ExceptionType.AMOUNT_MISMATCH
    assert suggest(answer(action="ACCEPT"), g=group(t, small)).action is Action.ACCEPT
    s = suggest(answer(action="ACCEPT"), g=group(t, small, large))
    assert s.action is Action.ESCALATE and rules(s) == [Guardrail.LARGE_DIFF]


def test_g5_cross_client_flag_needs_another_clients_memory() -> None:
    flagged = {"flags": ["cross client risk"]}
    s = suggest(answer(**flagged, cited_memory_ids=["M1"]))  # M1 is this client's own memory
    assert s.flags == () and rules(s) == [Guardrail.UNGROUNDED_FLAG]
    s = suggest(answer(**flagged, cited_memory_ids=["M2"]))  # M2 names another client
    assert s.flags == (Flag.CROSS_CLIENT_RISK,) and s.guardrail_events == ()


# --- AC-05-6: a hostile model never gets an unsafe action through ------------


@pytest.mark.parametrize("exception_type", list(ExceptionType))
@pytest.mark.parametrize("action", list(Action))
def test_ac_05_6_every_action_ends_allowed(exception_type: ExceptionType, action: Action) -> None:
    drift = DriftInfo(("X/1",), 70, 30)
    s = suggest(answer(action=action.value), g=group(exception_type), ctx=context(drift=drift))
    assert s.action in ALLOWED_ACTIONS[exception_type]
    assert (s.vendor_message is not None) == (
        s.action in {Action.CHASE_VENDOR, Action.HOLD_PAYMENT}
    )


# --- Failures ----------------------------------------------------------------


def test_ai_unavailable_escalates_and_keeps_the_ui_usable() -> None:
    s = suggest(LLMUnavailableError("both models: HTTP 503"))
    assert (s.action, s.final_confidence, s.model) == (Action.ESCALATE, 0, "")
    assert rules(s) == [Guardrail.AI_UNAVAILABLE]
    assert "unavailable" in s.reasoning


def test_context_must_match_the_group() -> None:
    other = Vendor(gstin=make_gstin("36", "AAHFC1180D"), name="Other")
    with pytest.raises(ValueError, match="vendor"):
        suggest(answer(), ctx=context(vendor=other))


# --- Parsing -----------------------------------------------------------------


def test_parse_forgives_casing_fences_and_thinking() -> None:
    text = '<think>hmm {not this}</think>```json\n' + answer(
        action="chase vendor", root_cause="Late-Filing", flags=["recurring_issue"]
    ) + "\n```"  # fmt: skip
    output = parse_output(text)
    assert (output.action, output.root_cause, output.flags) == (
        Action.CHASE_VENDOR, RootCause.LATE_FILING, (Flag.RECURRING_ISSUE,),
    )  # fmt: skip


def test_parse_explains_what_is_wrong() -> None:
    with pytest.raises(ValueError, match="confidence"):
        parse_output(answer(confidence=1.5))
    with pytest.raises(ValueError, match="no JSON"):
        parse_output("I think you should defer.")


def test_reasoning_is_cut_to_60_words() -> None:
    output = parse_output(answer(reasoning=" ".join(["word"] * 80)))
    assert len(output.reasoning.split()) == 61 and output.reasoning.endswith("…")


def test_guardrails_are_pure() -> None:
    output = AgentOutput.model_validate_json(answer(action="ACCEPT"))
    first = apply_guardrails(output, group(), context())
    assert first == apply_guardrails(output, group(), context())
    assert output.action is Action.ACCEPT  # the input is untouched


# --- Prompt ------------------------------------------------------------------


def test_user_message_has_the_facts() -> None:
    text = user_message(group(), context(trust=TrustInfo(TrustLevel.OBSERVE, 1, 1)))
    assert text.splitlines()[:5] == [
        "EXCEPTION GROUP",
        "client: Sri Balaji Textiles (C01) · state 36 · period: April 2026",
        f"vendor: Reddy Steels · GSTIN {VENDOR.gstin} · state 36 · status ACTIVE",
        "type: MISSING_IN_2B · invoices: 1 · ITC at risk: ₹16,200.00",
        "- RS/0467 dated 03-04-2026, books total ₹1,06,200.00",
    ]
    assert "ALLOWED: CHASE_VENDOR, DEFER, ESCALATE, HOLD_PAYMENT" in text
    assert "TRUST: level 0 OBSERVE · 1 correct, 1 wrong" in text
    assert "DRIFT: none detected" in text
    assert "[M1] (this client) March 2026: At client Sri Balaji Textiles" in text
    assert "\n[M2] February 2026" in text  # no metadata, no tag


def test_memories_say_which_client_they_came_from() -> None:
    other = KRISHNA_AT_C01.model_copy(
        update={"metadata": {"client_id": "C03", "period": "2026-03"}}
    )
    text = user_message(group(), context(memories=(other,)))
    assert "[M1] (another client C03 · March 2026) March 2026: At client" in text


def test_ac_05_7_memory_off_prompt_has_no_memory() -> None:
    drift = DriftInfo(("RS/2025-26/0441",), overdue_days=68, typical_lag_days=30)
    ctx = context(memory_on=False, trust=TrustInfo(TrustLevel.AUTO, 5, 0), drift=drift)
    chat = ScriptedChat(answer(cited_memory_ids=[]))
    s = Agent(chat).suggest(group(), ctx)
    (system, user) = chat.calls[0]
    assert system.content == SYSTEM_PROMPT
    assert user.content.endswith("TRUST: memory is off, level 0 OBSERVE\n"
                                 "DRIFT: none detected\nMEMORIES: memory is off.")  # fmt: skip
    for memory in (KRISHNA_AT_C01, AT_C03):
        assert memory.text.split("\n")[0] not in user.content
    assert not s.memory_on and s.final_confidence == 0.6  # trust ignored when OFF


def test_memory_off_citations_are_all_invalid() -> None:
    s = suggest(answer(), ctx=context(memory_on=False))
    assert s.cited_memory_ids == () and Guardrail.BAD_CITATION in rules(s)


def test_large_groups_list_ten_invoices() -> None:
    many = tuple(exception(number=f"RS/{n:04d}") for n in range(25))
    text = user_message(group(ExceptionType.MISSING_IN_2B, *many), context())
    assert text.count("\n- RS/") == MAX_LISTED_INVOICES
    assert "- … and 15 more (included in the totals)" in text


T, D = ExceptionType, Detail


@pytest.mark.parametrize(
    ("exception_type", "details", "fact"),
    [
        (T.AMOUNT_MISMATCH, {D.TWOB_TOTAL: "106205.00", D.AMOUNT_DIFF: "5.00"},
         "books ₹1,06,200.00, GSTR-2B ₹1,06,205.00, difference ₹5.00"),
        (T.TAX_HEAD_MISMATCH, {D.BOOK_TAX_HEAD: "INTRA", D.TWOB_TAX_HEAD: "INTER"},
         "books charged CGST+SGST, GSTR-2B shows IGST"),
        (T.GSTIN_MISMATCH, {D.BOOK_GSTIN: "X1", D.TWOB_GSTIN: "X2"},
         "booked under GSTIN X1, GSTR-2B shows GSTIN X2"),
        (T.ITC_INELIGIBLE, {D.TWOB_TOTAL: "5900.00"},
         "GSTR-2B total ₹5,900.00, ITC not available: no reason given"),
        (T.MISSING_IN_BOOKS, {D.TWOB_TOTAL: "5900.00", D.SUPPLIER_PERIOD: "2026-03"},
         "GSTR-2B total ₹5,900.00, vendor filed it for March 2026"),
    ],
)  # fmt: skip
def test_invoice_facts_per_type(exception_type: ExceptionType, details: dict[str, str],
                                fact: str) -> None:  # fmt: skip
    text = user_message(group(exception_type, exception(exception_type, **details)), context())
    assert f"- RS/0467 dated 03-04-2026, {fact}" in text


def test_system_prompt_examples_use_a_fictional_vendor() -> None:
    assert "Surya Fasteners" in SYSTEM_PROMPT
    for vendor in (*PLANTED_VENDORS, *RELIABLE_VENDORS):
        assert vendor.name not in SYSTEM_PROMPT
        assert vendor.pan not in SYSTEM_PROMPT


# --- AC-05-8 and concurrency -------------------------------------------------


def test_ac_05_8_latency_and_tokens_are_recorded() -> None:
    ticks = iter([10.0, 10.25])
    s = Agent(ScriptedChat(answer()), clock=lambda: next(ticks)).suggest(group(), context())
    assert (s.latency_ms, s.prompt_tokens, s.completion_tokens, s.model) == (
        250, 1000, 100, "test-model",
    )  # fmt: skip


def test_suggest_all_keeps_order() -> None:
    types = [
        ExceptionType.MISSING_IN_2B,
        ExceptionType.AMOUNT_MISMATCH,
        ExceptionType.ITC_INELIGIBLE,
    ]

    class Echo:
        def complete(self, messages: Sequence[Message]) -> Completion:
            allowed = messages[-1].content.split("ALLOWED: ")[1].split(",")[0].strip()
            return Completion(answer(action=allowed, cited_memory_ids=[]), "m", 1, 1)

    results = Agent(Echo()).suggest_all([(group(t), context()) for t in types])
    assert [s.group_key.exception_type for s in results] == types

"""Agent / decision engine (SPEC-05).

For one exception group: facts from the matcher, what memory recalled, and the
trust and drift signals go into one prompt; the LLM's JSON comes back; code
guardrails (§5) then make it safe. The LLM proposes, code disposes: nothing it
returns can produce a disallowed action, an uncited claim of history, or a
confidence above what trust allows.

Memories are shown to the LLM as M1, M2, …: short ids are easier to cite
correctly than server UUIDs, and are mapped back before anything is stored.
"""

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from backend.app.domain.entities import Client, GroupKey, ReconException, Vendor
from backend.app.domain.enums import Action, ExceptionType, Flag, RootCause, TaxHead, TrustLevel
from backend.app.domain.periods import label
from backend.app.domain.policy import (
    ALLOWED_ACTIONS,
    CONFIDENCE_CAPS,
    MAX_ACCEPTABLE_DIFF,
    is_action_allowed,
)
from backend.app.llm import ChatModel, LLMUnavailableError, Message
from backend.app.matcher import Detail, ExceptionGroup
from backend.app.memory import MemoryRecord
from backend.app.memory_text import rupees

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")
MAX_ATTEMPTS = 3
"""The first answer plus two retries with the validation error (G7)."""
MAX_REASONING_WORDS = 60
MAX_LISTED_INVOICES = 10
MAX_PARALLEL_CALLS = 3
"""Groq free-tier rate limits."""
UNGROUNDED_CONFIDENCE = 0.5
MESSAGE_ACTIONS = frozenset({Action.CHASE_VENDOR, Action.HOLD_PAYMENT})

# Words that claim history (G3). "before" only in phrases like "seen before", since
# "chase before the deadline" makes no claim about the past.
_HISTORY_CLAIM = re.compile(
    r"\b(?:previous(?:ly)?|last (?:month|time|quarter|year)|usually|always|again|earlier"
    r"|in the past|typically|as usual|every month"
    r"|(?:seen|happened|handled|resolved|occurred|done|filed) before)\b",
    re.IGNORECASE,
)
_CLIENT_IN_TEXT = re.compile(r"\bAt client ([^,]+),")


# --- Inputs ------------------------------------------------------------------


@dataclass(frozen=True)
class TrustInfo:
    """Trust in this pattern (vendor + exception type), computed by SPEC-06."""

    level: TrustLevel = TrustLevel.OBSERVE
    correct: int = 0
    wrong: int = 0


@dataclass(frozen=True)
class DriftInfo:
    """The vendor broke its usual lag (SPEC-06)."""

    overdue_invoices: tuple[str, ...]
    overdue_days: int
    typical_lag_days: int


@dataclass(frozen=True)
class AgentContext:
    client: Client
    vendor: Vendor
    memories: tuple[MemoryRecord, ...] = ()
    trust: TrustInfo = field(default_factory=TrustInfo)
    drift: DriftInfo | None = None
    memory_on: bool = True
    """OFF: no memories, trust level 0 and no drift, whatever was passed in (SPEC-04 §10).
    Drift is learned from history, so it is memory too."""

    def effective(self) -> "AgentContext":
        if self.memory_on:
            return self
        return replace(self, memories=(), trust=TrustInfo(), drift=None)


# --- Outputs -----------------------------------------------------------------


class Guardrail(StrEnum):
    UNSAFE_ACTION = "UNSAFE_ACTION"
    """G1: action not allowed for the exception type."""
    BAD_CITATION = "BAD_CITATION"
    """G2: cited a memory that wasn't provided."""
    UNGROUNDED = "UNGROUNDED"
    """G3: claimed history without citing any memory."""
    LARGE_DIFF = "LARGE_DIFF"
    """G4: accepted a large amount difference."""
    UNGROUNDED_FLAG = "UNGROUNDED_FLAG"
    """G5: cross-client risk without a memory from another client."""
    DRIFT_OVERRIDE = "DRIFT_OVERRIDE"
    """G6: the vendor's pattern broke; deferring is no longer safe."""
    INVALID_OUTPUT = "INVALID_OUTPUT"
    """G7: no valid answer after all retries."""
    MISSING_MESSAGE = "MISSING_MESSAGE"
    """G8: an action that needs a vendor message came without one; drafted from a template."""
    AI_UNAVAILABLE = "AI_UNAVAILABLE"
    """No model answered; escalated so the accountant can still work."""


class _Value(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GuardrailEvent(_Value):
    rule: Guardrail
    detail: str


class AgentOutput(BaseModel):
    """What the LLM must return (§3). Casing and spacing of enum values are forgiven."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    action: Action
    root_cause: RootCause
    flags: tuple[Flag, ...] = ()
    confidence: float = Field(ge=0, le=1)
    reasoning: str = Field(min_length=1)
    cited_memory_ids: tuple[str, ...] = ()
    vendor_message: str | None = None

    @field_validator("action", "root_cause", mode="before")
    @classmethod
    def _enum_name(cls, value: Any) -> Any:
        return _enum_name(value)

    @field_validator("flags", mode="before")
    @classmethod
    def _enum_names(cls, value: Any) -> Any:
        return [_enum_name(v) for v in value] if isinstance(value, list) else value

    @field_validator("reasoning")
    @classmethod
    def _at_most_60_words(cls, value: str) -> str:
        words = value.split()
        if len(words) <= MAX_REASONING_WORDS:
            return " ".join(words)
        return " ".join(words[:MAX_REASONING_WORDS]) + " …"

    @field_validator("vendor_message")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None


def _enum_name(value: Any) -> Any:
    """`"chase vendor"` / `"Chase-Vendor"` → `"CHASE_VENDOR"`."""
    if not isinstance(value, str):
        return value
    return re.sub(r"[\s-]+", "_", value.strip()).upper()


class Suggestion(_Value):
    """One suggestion for one exception group, as stored (§3)."""

    group_key: GroupKey
    memory_on: bool
    action: Action
    root_cause: RootCause
    flags: tuple[Flag, ...]
    llm_confidence: float
    final_confidence: float
    reasoning: str
    cited_memory_ids: tuple[str, ...]
    """Real memory ids (not the M1, M2 shown to the LLM)."""
    vendor_message: str | None
    guardrail_events: tuple[GuardrailEvent, ...]
    model: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    raw_output: str | None
    attempts: int = 1
    """LLM calls made for this suggestion: 1 is a valid answer first time, 0 no model."""

    @property
    def confidence_label(self) -> str:
        """D9: the UI shows a label; the number is only on hover."""
        if self.final_confidence >= 0.8:
            return "High"
        return "Medium" if self.final_confidence >= 0.5 else "Low"


# --- Prompt ------------------------------------------------------------------


def aliases(memories: Sequence[MemoryRecord]) -> dict[str, MemoryRecord]:
    return {f"M{n}": memory for n, memory in enumerate(memories, start=1)}


def user_message(group: ExceptionGroup, ctx: AgentContext) -> str:
    """The facts for one group (§6). Deterministic: same inputs, same text."""
    ctx = ctx.effective()
    key, client, vendor = group.key, ctx.client, ctx.vendor
    lines = [
        "EXCEPTION GROUP",
        f"client: {client.name} ({client.client_id}) · state {client.state_code} "
        f"· period: {label(key.period)}",
        f"vendor: {vendor.name} · GSTIN {vendor.gstin} · state {vendor.state_code} "
        f"· status {vendor.registration_status}",
        f"type: {key.exception_type} · invoices: {len(group.exceptions)} "
        f"· ITC at risk: {rupees(group.itc_at_risk)}",
    ]
    listed = sorted(group.exceptions, key=_invoice_order)
    lines += [_invoice_line(e) for e in listed[:MAX_LISTED_INVOICES]]
    if len(listed) > MAX_LISTED_INVOICES:
        lines.append(f"- … and {len(listed) - MAX_LISTED_INVOICES} more (included in the totals)")
    lines.append("ALLOWED: " + ", ".join(sorted(ALLOWED_ACTIONS[key.exception_type])))
    lines.append(_trust_line(ctx))
    lines.append(_drift_line(ctx.drift))
    lines += _memory_lines(ctx)
    return "\n".join(lines)


def _invoice_order(exception: ReconException) -> tuple[str, str]:
    details = exception.details
    return str(details.get(Detail.INVOICE_DATE)), str(details.get(Detail.INVOICE_NO))


def _invoice_line(exception: ReconException) -> str:
    d = exception.details
    number = d.get(Detail.INVOICE_NO, "(no number)")
    raw_date = d.get(Detail.INVOICE_DATE)
    dated = f" dated {date.fromisoformat(raw_date):%d-%m-%Y}" if isinstance(raw_date, str) else ""
    match exception.type:
        case ExceptionType.MISSING_IN_2B:
            fact = f"books total {_money(d, Detail.BOOK_TOTAL)}"
        case ExceptionType.MISSING_IN_BOOKS:
            fact = (
                f"GSTR-2B total {_money(d, Detail.TWOB_TOTAL)}, "
                f"vendor filed it for {label(str(d[Detail.SUPPLIER_PERIOD]))}"
                if Detail.SUPPLIER_PERIOD in d
                else f"GSTR-2B total {_money(d, Detail.TWOB_TOTAL)}"
            )
        case ExceptionType.AMOUNT_MISMATCH:
            fact = (
                f"books {_money(d, Detail.BOOK_TOTAL)}, GSTR-2B {_money(d, Detail.TWOB_TOTAL)}, "
                f"difference {_money(d, Detail.AMOUNT_DIFF)} (GSTR-2B minus books)"
            )
        case ExceptionType.TAX_HEAD_MISMATCH:
            fact = (
                f"books charged {_head(d.get(Detail.BOOK_TAX_HEAD))}, "
                f"GSTR-2B shows {_head(d.get(Detail.TWOB_TAX_HEAD))}"
            )
        case ExceptionType.GSTIN_MISMATCH:
            fact = (
                f"booked under GSTIN {d.get(Detail.BOOK_GSTIN)}, "
                f"GSTR-2B shows GSTIN {d.get(Detail.TWOB_GSTIN)}"
            )
        case ExceptionType.ITC_INELIGIBLE:
            reason = d.get(Detail.ITC_UNAVAILABLE_REASON) or "no reason given"
            fact = f"GSTR-2B total {_money(d, Detail.TWOB_TOTAL)}, ITC not available: {reason}"
    return f"- {number}{dated}, {fact}"


def _money(details: Mapping[str, Any], key: Detail) -> str:
    value = details.get(key)
    return rupees(Decimal(str(value))) if value is not None else "unknown"


def _head(value: Any) -> str:
    try:
        return {TaxHead.INTRA: "CGST+SGST", TaxHead.INTER: "IGST"}[TaxHead(value)]
    except ValueError:
        return "no tax"


def _trust_line(ctx: AgentContext) -> str:
    if not ctx.memory_on:
        return "TRUST: memory is off, level 0 OBSERVE"
    t = ctx.trust
    return f"TRUST: level {t.level.value} {t.level.name} · {t.correct} correct, {t.wrong} wrong"


def _drift_line(drift: DriftInfo | None) -> str:
    if drift is None:
        return "DRIFT: none detected"
    return (
        f"DRIFT: invoices {', '.join(drift.overdue_invoices)} overdue by {drift.overdue_days} "
        f"days (typical lag about {drift.typical_lag_days} days)"
    )


def _memory_lines(ctx: AgentContext) -> list[str]:
    if not ctx.memory_on:
        return ["MEMORIES: memory is off."]
    if not ctx.memories:
        return ["MEMORIES: none available."]
    return ["MEMORIES (cite by id):"] + [
        f"[{alias}] {_provenance(memory, ctx.client)}{' '.join(memory.text.split())}"
        for alias, memory in aliases(ctx.memories).items()
    ]


def _provenance(memory: MemoryRecord, client: Client) -> str:
    """`(another client C01 · March 2026) `: where a memory came from, from its metadata.

    Hindsight rewrites retained text into extracted facts, which often drop the client's
    name, so without this the model can't tell another client's history from this one's.
    """
    client_id, period = memory.metadata.get("client_id"), memory.metadata.get("period")
    parts = []
    if client_id:
        parts.append(
            "this client" if client_id == client.client_id else f"another client {client_id}"
        )
    if period:
        parts.append(label(period))
    return f"({' · '.join(parts)}) " if parts else ""


# --- Parsing -----------------------------------------------------------------


def parse_output(text: str) -> AgentOutput:
    """The JSON object in the model's answer. Raises ValueError with a readable reason."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)  # reasoning models
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object found")
    try:
        return AgentOutput.model_validate(json.loads(text[start : end + 1]))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(map(str, error['loc'])) or 'answer'}: {error['msg']}"
            for error in exc.errors(include_url=False)
        )
        raise ValueError(problems) from exc


# --- Guardrails (§5) ---------------------------------------------------------


def apply_guardrails(
    output: AgentOutput, group: ExceptionGroup, ctx: AgentContext
) -> tuple[AgentOutput, list[GuardrailEvent]]:
    """Make an answer safe. Pure: the same answer and facts always give the same result."""
    ctx = ctx.effective()
    known = aliases(ctx.memories)
    events: list[GuardrailEvent] = []
    exception_type = group.key.exception_type
    action, flags, confidence = output.action, list(output.flags), output.confidence

    # G2: only memories we actually provided can be cited.
    cited = list(dict.fromkeys(output.cited_memory_ids))
    unknown = [c for c in cited if c not in known]
    if unknown:
        cited = [c for c in cited if c in known]
        events.append(_event(Guardrail.BAD_CITATION, f"dropped unknown ids {', '.join(unknown)}"))

    # G6: a broken pattern means deferring is no longer safe.
    if ctx.drift is not None:
        changes = []
        if Flag.PATTERN_DRIFT not in flags:
            flags.append(Flag.PATTERN_DRIFT)
            changes.append("added PATTERN_DRIFT")
        if action is Action.DEFER:
            action = Action.CHASE_VENDOR
            changes.append("DEFER → CHASE_VENDOR")
        if changes:
            events.append(_event(Guardrail.DRIFT_OVERRIDE, "; ".join(changes)))

    # G1: SPEC-01 INV-1.
    if not is_action_allowed(exception_type, action):
        events.append(_event(Guardrail.UNSAFE_ACTION, f"{action} not allowed for {exception_type}"))
        action = Action.ESCALATE

    # G4: a large difference is never simply accepted.
    if exception_type is ExceptionType.AMOUNT_MISMATCH and action is Action.ACCEPT:
        largest = max((abs(_diff(e)) for e in group.exceptions), default=Decimal(0))
        if largest > MAX_ACCEPTABLE_DIFF:
            events.append(_event(Guardrail.LARGE_DIFF, f"difference {rupees(largest)}"))
            action = Action.ESCALATE

    # G3: history claimed but not cited.
    if not cited and (claim := _HISTORY_CLAIM.search(output.reasoning)):
        if confidence > UNGROUNDED_CONFIDENCE:
            confidence = UNGROUNDED_CONFIDENCE
        events.append(_event(Guardrail.UNGROUNDED, f'"{claim.group(0)}" with no citation'))

    # G5: cross-client risk needs a cited memory about another client.
    if Flag.CROSS_CLIENT_RISK in flags and not any(
        _about_other_client(known[c], ctx.client) for c in cited
    ):
        flags.remove(Flag.CROSS_CLIENT_RISK)
        events.append(_event(Guardrail.UNGROUNDED_FLAG, "no cited memory from another client"))

    # G8: the vendor message belongs to the actions that contact the vendor.
    message = output.vendor_message if action in MESSAGE_ACTIONS else None
    if action in MESSAGE_ACTIONS and message is None:
        message = vendor_message(group, ctx, action)
        events.append(_event(Guardrail.MISSING_MESSAGE, "drafted from the template"))

    safe = output.model_copy(
        update={
            "action": action,
            "flags": tuple(flags),
            "confidence": confidence,
            "cited_memory_ids": tuple(cited),
            "vendor_message": message,
        }
    )
    return safe, events


def _event(rule: Guardrail, detail: str) -> GuardrailEvent:
    return GuardrailEvent(rule=rule, detail=detail)


def _diff(exception: ReconException) -> Decimal:
    value = exception.details.get(Detail.AMOUNT_DIFF)
    return Decimal(str(value)) if value is not None else Decimal(0)


def _about_other_client(memory: MemoryRecord, client: Client) -> bool:
    if client_id := memory.metadata.get("client_id"):
        return client_id != client.client_id
    # Consolidated memories carry no metadata; our templates name the client.
    named = _CLIENT_IN_TEXT.search(memory.text)
    return named is not None and named.group(1).strip() != client.name


_VENDOR_PROBLEM: dict[ExceptionType, str] = {
    ExceptionType.MISSING_IN_2B: "do not appear in our GSTR-2B for {month}. Please file them in "
    "your GSTR-1 against our GSTIN {gstin} and confirm the filing date.",
    ExceptionType.AMOUNT_MISMATCH: "show a different amount in our GSTR-2B for {month} than on "
    "the invoice. Please amend your GSTR-1 to match the invoice.",
    ExceptionType.TAX_HEAD_MISMATCH: "are reported under a different tax head (IGST vs CGST+SGST) "
    "in our GSTR-2B for {month}. Please check and amend your GSTR-1.",
    ExceptionType.GSTIN_MISMATCH: "appear in our GSTR-2B for {month} under a different GSTIN "
    "than in our records. Please confirm the GSTIN you invoiced from.",
    ExceptionType.ITC_INELIGIBLE: "are marked as not eligible for input tax credit in our GSTR-2B "
    "for {month}. Please check and amend your GSTR-1.",
    ExceptionType.MISSING_IN_BOOKS: "appear in our GSTR-2B for {month}, but we have no copy. "
    "Please send us the invoices.",
}


def _invoice_total(exception: ReconException) -> str:
    side = Detail.BOOK_TOTAL if Detail.BOOK_TOTAL in exception.details else Detail.TWOB_TOTAL
    return _money(exception.details, side)


def vendor_message(group: ExceptionGroup, ctx: AgentContext, action: Action) -> str:
    """A plain, specific message used when the LLM didn't write one."""
    invoices = ", ".join(
        f"{e.details.get(Detail.INVOICE_NO, '(no number)')} ({_invoice_total(e)})"
        for e in sorted(group.exceptions, key=_invoice_order)[:MAX_LISTED_INVOICES]
    )
    problem = _VENDOR_PROBLEM[group.key.exception_type].format(
        month=label(group.key.period), gstin=ctx.client.gstin
    )
    hold = (
        " Until then we are holding the GST portion of the payment."
        if action is Action.HOLD_PAYMENT
        else ""
    )
    return f"Dear {ctx.vendor.name}, invoices {invoices} {problem}{hold} Thank you."


# --- The agent ---------------------------------------------------------------


class Agent:
    def __init__(self, llm: ChatModel, *, clock: Callable[[], float] = time.perf_counter) -> None:
        self.llm = llm
        self._clock = clock

    def suggest(self, group: ExceptionGroup, ctx: AgentContext) -> Suggestion:
        _check_context(group, ctx)
        ctx = ctx.effective()
        messages = [Message("system", SYSTEM_PROMPT), Message("user", user_message(group, ctx))]
        started = self._clock()
        usage = _Usage()
        try:
            output = self._ask(messages, usage)
        except LLMUnavailableError as exc:
            output = _escalation("The AI is unavailable, so this needs a manual review.")
            usage.events.append(_event(Guardrail.AI_UNAVAILABLE, str(exc)))
        safe, events = apply_guardrails(output, group, ctx)
        known = aliases(ctx.memories)
        return Suggestion(
            group_key=group.key,
            memory_on=ctx.memory_on,
            action=safe.action,
            root_cause=safe.root_cause,
            flags=safe.flags,
            llm_confidence=output.confidence,
            final_confidence=min(safe.confidence, CONFIDENCE_CAPS[ctx.trust.level]),
            reasoning=safe.reasoning,
            cited_memory_ids=tuple(known[c].id for c in safe.cited_memory_ids),
            vendor_message=safe.vendor_message,
            guardrail_events=(*usage.events, *events),
            model=usage.model,
            latency_ms=round((self._clock() - started) * 1000),
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            raw_output=usage.raw_output,
            attempts=usage.attempts,
        )

    def suggest_all(self, items: Sequence[tuple[ExceptionGroup, AgentContext]]) -> list[Suggestion]:
        """Suggestions in input order, at most MAX_PARALLEL_CALLS in flight."""
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CALLS) as pool:
            return list(pool.map(lambda item: self.suggest(*item), items))

    def _ask(self, messages: list[Message], usage: "_Usage") -> AgentOutput:
        """G7: retry invalid answers with the reason; escalate after MAX_ATTEMPTS."""
        for _ in range(MAX_ATTEMPTS):
            completion = self.llm.complete(messages)
            usage.add(completion.model, completion.prompt_tokens, completion.completion_tokens)
            usage.raw_output = completion.text
            try:
                return parse_output(completion.text)
            except ValueError as exc:
                reason = str(exc)
            messages = [
                *messages,
                Message("assistant", completion.text or "(empty answer)"),
                Message(
                    "user",
                    f"That answer was invalid ({reason}). Return the corrected JSON object only.",
                ),
            ]
        usage.events.append(
            _event(Guardrail.INVALID_OUTPUT, f"no valid answer in {MAX_ATTEMPTS} attempts")
        )
        return _escalation("The AI's answer was invalid, so this needs a manual review.")


@dataclass
class _Usage:
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw_output: str | None = None
    attempts: int = 0
    events: list[GuardrailEvent] = field(default_factory=list)

    def add(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.attempts += 1
        self.model = model
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens


def _escalation(reasoning: str) -> AgentOutput:
    return AgentOutput(
        action=Action.ESCALATE, root_cause=RootCause.UNKNOWN, confidence=0, reasoning=reasoning
    )


def _check_context(group: ExceptionGroup, ctx: AgentContext) -> None:
    if ctx.client.client_id != group.key.client_id:
        raise ValueError(f"context is for client {ctx.client.client_id}, group {group.key}")
    if ctx.vendor.gstin != group.key.vendor_gstin:
        raise ValueError(f"context is for vendor {ctx.vendor.gstin}, group {group.key}")

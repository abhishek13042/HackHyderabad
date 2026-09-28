"""API request and response bodies (SPEC-07 §3). Money is always a 2-decimal string."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.enums import Action, DecidedBy, ExceptionType, TrustLevel
from backend.app.domain.money import Money

ConfidenceLabel = Literal["HIGH", "MEDIUM", "LOW"]


def confidence_label(confidence: float) -> ConfidenceLabel:
    """SPEC-07 §3: HIGH at 0.8 and above, MEDIUM at 0.5 and above."""
    if confidence >= 0.8:
        return "HIGH"
    return "MEDIUM" if confidence >= 0.5 else "LOW"


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Requests ----------------------------------------------------------------


class DecisionIn(Body):
    action: Action
    note: str | None = Field(default=None, max_length=2000)


class ResetIn(Body):
    confirm: Literal["RESET"]


# --- System and reference data -----------------------------------------------


class Health(BaseModel):
    ok: bool
    db: Literal["up", "down"]
    seeded: bool
    hindsight: Literal["up", "down"]
    llm: Literal["up", "down"]
    bank_id: str
    firm: str
    pending_retains: int


class ClientOut(BaseModel):
    id: str
    name: str
    gstin: str
    business: str


class PeriodOut(BaseModel):
    period: str
    has_books: bool
    has_2b: bool
    run_status: str | None
    run_id: str | None
    open_groups: int
    auto_resolved: int


class UploadOut(BaseModel):
    rows_books: int
    rows_2b: int
    warnings: list[str]


# --- Runs --------------------------------------------------------------------


class Accepted(BaseModel):
    run_id: str


class Progress(BaseModel):
    step: str | None
    done: int
    total: int


class RunSummary(BaseModel):
    groups: int
    exceptions: int
    matched: int
    auto_resolved: int
    auto_resolved_keys: list[str]
    itc_at_risk: Money
    flags: dict[str, int]
    drift: list[str]
    late_arrivals: int
    outcomes: int
    memory_degraded: bool


class RunOut(BaseModel):
    run_id: str
    client_id: str
    period: str
    status: Literal["running", "done", "failed"]
    progress: Progress
    memory_on: bool
    summary: RunSummary | None
    error: str | None
    started_at: str
    finished_at: str | None


class JobOut(BaseModel):
    job_id: str
    kind: str
    status: Literal["running", "done", "failed"]
    done: int
    total: int
    error: str | None
    result: dict[str, Any]


# --- Groups and decisions ----------------------------------------------------


class VendorRef(BaseModel):
    gstin: str
    name: str


class InvoiceOut(BaseModel):
    invoice_no: str | None
    date: str | None
    total: Money | None
    tax: Money | None
    itc_at_risk: Money
    details: dict[str, Any]


class CitedMemory(BaseModel):
    id: str
    text: str
    period: str | None
    client_id: str | None
    occurred_at: str | None


class SuggestionOut(BaseModel):
    action: Action
    root_cause: str
    flags: list[str]
    confidence_label: ConfidenceLabel
    final_confidence: float
    """A score between 0 and 1, not money."""
    reasoning: str
    vendor_message: str | None
    cited_memories: list[CitedMemory]
    guardrail_events: list[str]
    guardrail_details: list[dict[str, Any]]
    memory_on: bool
    model: str


class TrustOut(BaseModel):
    level: TrustLevel
    name: str
    streak_action: Action | None
    streak: int
    correct: int
    wrong: int


class DecisionOut(BaseModel):
    id: int | None
    group_key: str
    action: Action
    suggested_action: Action | None
    accepted_suggestion: bool
    decided_by: DecidedBy
    note: str | None
    decided_at: str


class GroupOut(BaseModel):
    group_key: str
    vendor: VendorRef
    type: ExceptionType
    invoices: list[InvoiceOut]
    itc_at_risk: Money
    suggestion: SuggestionOut | None
    trust: TrustOut | None
    decision: DecisionOut | None
    allowed_actions: list[Action]


# --- Memory, trust, insights -------------------------------------------------


class OutcomeOut(BaseModel):
    status: str
    checked_in_period: str
    evidence: dict[str, Any]


class HistoryRow(BaseModel):
    period: str
    client_id: str
    type: ExceptionType
    action: Action
    decided_by: DecidedBy
    note: str | None
    outcome: OutcomeOut | None


class DriftOut(BaseModel):
    vendor_gstin: str
    period: str
    evidence: dict[str, Any]


class PatternOut(BaseModel):
    vendor: VendorRef
    type: ExceptionType
    period: str
    level: TrustLevel
    name: str
    streak_action: Action | None
    streak: int
    correct: int
    wrong: int


class VendorOut(BaseModel):
    gstin: str
    name: str
    registration_status: str
    known: bool
    clients: list[str]
    history: list[HistoryRow]
    trust: list[PatternOut]
    profile: str | None
    drift_events: list[DriftOut]


class CurvePoint(BaseModel):
    period: str
    accuracy_on: float | None
    accuracy_off: float | None
    auto_rate: float | None


class InsightStats(BaseModel):
    period: str | None
    runs: int
    groups: int
    decisions: int
    accepted_suggestions: int
    overrides: int
    auto_resolved: int
    itc_at_risk: Money
    drift_events: int
    cross_client_warnings: int
    guardrails_applied: int
    patterns_auto: int


class InsightsOut(BaseModel):
    summary: str | None
    memory_offline: bool
    learning_curve: list[CurvePoint]
    learning_curve_source: str | None
    stats: InsightStats


class MemoryEventOut(BaseModel):
    id: int
    ts: str
    op: str
    kind: str | None
    summary: str
    result_count: int | None
    latency_ms: int | None
    ok: bool
    error: str | None


class RecallOut(BaseModel):
    query: str
    memories: list[CitedMemory]


class ResetOut(BaseModel):
    reset: bool

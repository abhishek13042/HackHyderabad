"""Memory, trust and insight views (SPEC-07 §3)."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query

from backend.app.domain.enums import DecidedBy, Flag, TrustLevel
from backend.app.domain.periods import validate_period
from backend.app.memory import MemoryRecord
from backend.app.memory_text import monthly_insights_query, vendor_profile_query
from backend.app.routers.common import (
    ServicesDep,
    SessionDep,
    cited_memory,
    invalid,
    memory_offline,
    not_found,
    vendor_ref,
)
from backend.app.schemas import (
    CurvePoint,
    DriftOut,
    HistoryRow,
    InsightsOut,
    InsightStats,
    MemoryEventOut,
    OutcomeOut,
    PatternOut,
    RecallOut,
    VendorOut,
)
from backend.app.services import Session
from backend.app.store import TrustRow

LEARNING_CURVE_FILE = "learning_curve.json"
"""Written by `python -m evals.report` into each `evals/results/<run_id>/` (SPEC-09)."""

router = APIRouter()


@router.get("/vendors/{gstin}")
def vendor(gstin: str, services: ServicesDep, session: SessionDep) -> VendorOut:
    store = session.store
    known = store.vendor(gstin)
    decisions = store.decisions(vendor_gstin=gstin)
    if known is None and not decisions:
        raise not_found(f"no vendor {gstin}")
    ref = vendor_ref(session, gstin)
    history = []
    for d in decisions:
        assert d.id is not None
        outcome = store.outcome(d.id)
        history.append(
            HistoryRow(
                period=d.group_key.period,
                client_id=d.group_key.client_id,
                type=d.group_key.exception_type,
                action=d.final_action,
                decided_by=d.decided_by,
                note=d.note,
                outcome=OutcomeOut(
                    status=outcome.status.value,
                    checked_in_period=outcome.checked_in_period,
                    evidence=outcome.evidence,
                )
                if outcome
                else None,
            )
        )
    profile = services.memory.reflect(
        vendor_profile_query(ref.name, gstin), purpose="vendor_profile", tags=(f"vendor:{gstin}",)
    )
    return VendorOut(
        gstin=gstin,
        name=ref.name,
        registration_status=known.registration_status.value if known else "UNKNOWN",
        known=known is not None,
        clients=sorted({d.group_key.client_id for d in decisions}),
        history=history,
        trust=[_pattern(session, row) for row in store.latest_trust() if row.vendor_gstin == gstin],
        profile=profile,
        drift_events=[
            DriftOut(vendor_gstin=e.vendor_gstin, period=e.period, evidence=e.evidence)
            for e in store.drift_events(gstin)
        ],
    )


@router.get("/trust")
def trust(session: SessionDep) -> list[PatternOut]:
    return [_pattern(session, row) for row in session.store.latest_trust()]


def _pattern(session: Session, row: TrustRow) -> PatternOut:
    t = row.trust
    return PatternOut(
        vendor=vendor_ref(session, row.vendor_gstin),
        type=row.exception_type,
        period=row.period,
        level=t.level,
        name=TrustLevel(t.level).name,
        streak_action=t.streak_action,
        streak=t.streak,
        correct=t.correct,
        wrong=t.wrong,
    )


@router.get("/insights")
def insights(services: ServicesDep, session: SessionDep, period: str | None = None) -> InsightsOut:
    """The month's learnings from memory (reflect), numbers from SQLite, and the eval curve."""
    if period is not None:
        try:
            period = validate_period(period)
        except ValueError as exc:
            raise invalid(str(exc)) from exc
    else:
        period = session.store.last_run_period_any()
    summary = (
        services.memory.reflect(monthly_insights_query(period), purpose="insights")
        if period
        else None
    )
    curve, source = learning_curve(services.results_dir)
    return InsightsOut(
        summary=summary,
        memory_offline=not services.memory.online,
        learning_curve=curve,
        learning_curve_source=source,
        stats=_stats(session, period),
    )


def _stats(session: Session, period: str | None) -> InsightStats:
    store = session.store
    runs = [
        run
        for client in store.clients()
        if period and (run := store.latest_run(client.client_id, period)) is not None
    ]
    groups = [g for run in runs for g in store.groups(run.id)]
    suggestions = [s for run in runs for s in store.suggestions(run.id).values()]
    decisions = store.decisions(period=period) if period else []
    by_accountant = [d for d in decisions if d.decided_by is DecidedBy.ACCOUNTANT]
    return InsightStats(
        period=period,
        runs=len(runs),
        groups=len(groups),
        decisions=len(decisions),
        accepted_suggestions=sum(d.final_action is d.suggested_action for d in by_accountant),
        overrides=sum(
            d.suggested_action is not None and d.final_action is not d.suggested_action
            for d in by_accountant
        ),
        auto_resolved=sum(d.decided_by is DecidedBy.AUTO for d in decisions),
        itc_at_risk=sum((g.itc_at_risk for g in groups), Decimal("0.00")),
        drift_events=sum(e.period == period for e in store.drift_events()),
        cross_client_warnings=sum(Flag.CROSS_CLIENT_RISK in s.flags for s in suggestions),
        guardrails_applied=sum(len(s.guardrail_events) for s in suggestions),
        patterns_auto=sum(row.trust.level is TrustLevel.AUTO for row in store.latest_trust()),
    )


def learning_curve(results_dir: Path) -> tuple[list[CurvePoint], str | None]:
    """From the newest eval run that has one; empty before any evals were run."""
    if not results_dir.is_dir():
        return [], None
    for run_dir in sorted((p for p in results_dir.iterdir() if p.is_dir()), reverse=True):
        path = run_dir / LEARNING_CURVE_FILE
        if path.is_file():
            points = json.loads(path.read_text(encoding="utf-8"))
            return [CurvePoint.model_validate(p) for p in points], run_dir.name
    return [], None


# --- Memory ------------------------------------------------------------------


@router.get("/memory/events")
def memory_events(
    session: SessionDep,
    since: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    latest: bool = False,
) -> list[MemoryEventOut]:
    """Oldest first after `since`; with `latest`, the newest `limit` events (still oldest first)."""
    events = session.store.memory_events(since, limit, latest=latest)
    return [MemoryEventOut.model_validate(e) for e in events]


@router.get("/memory/recall")
def recall(
    q: Annotated[str, Query(min_length=1, max_length=500)], services: ServicesDep
) -> RecallOut:
    recalled = services.memory.recall(q, purpose="ask")
    if not recalled.online:
        raise memory_offline()
    return RecallOut(query=q, memories=[cited_memory(_dump(m)) for m in recalled.records])


def _dump(record: MemoryRecord) -> dict[str, object]:
    return record.model_dump(mode="json")

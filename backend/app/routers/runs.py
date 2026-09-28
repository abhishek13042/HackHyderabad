"""Reconciliation runs and their exception groups (SPEC-07 §3)."""

import logging
from collections import Counter
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, status

from backend.app.domain.policy import ALLOWED_ACTIONS
from backend.app.matcher import Detail, ExceptionGroup
from backend.app.pipeline import PipelineError
from backend.app.routers.common import (
    ServicesDep,
    SessionDep,
    cited_memory,
    claim_work,
    conflict,
    decision_out,
    find_client,
    not_found,
    trust_out,
    vendor_ref,
)
from backend.app.schemas import (
    Accepted,
    GroupOut,
    InvoiceOut,
    Progress,
    RunOut,
    RunSummary,
    SuggestionOut,
    confidence_label,
)
from backend.app.services import Services
from backend.app.store import RunRow, Store, StoredSuggestion, StoreError

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/reconciliations/{client_id}/{period}/run", status_code=status.HTTP_202_ACCEPTED)
def start_run(
    client_id: str,
    period: str,
    services: ServicesDep,
    session: SessionDep,
    background: BackgroundTasks,
    memory: Literal["on", "off"] = "on",
) -> Accepted:
    """Checks and records the run, then does the work in the background; poll `/runs/{id}`."""
    client = find_client(session, client_id)
    if period not in session.store.periods(client.client_id):
        raise not_found(f"no data for {client.client_id} in {period}")
    claim_work(services, "start a run")
    try:
        row = session.pipeline.start(client.client_id, period, memory_on=memory == "on")
    except PipelineError as exc:
        services.work.release()
        raise conflict(str(exc)) from exc
    except BaseException:
        services.work.release()
        raise
    background.add_task(_execute, services, row.id)
    return Accepted(run_id=row.id)


def _execute(services: Services, run_id: str) -> None:
    try:
        with services.session() as session:
            session.pipeline.execute(run_id)
    except Exception:
        # The run row already says why it failed; the traceback is for the server log.
        logger.exception("run %s failed", run_id)
    finally:
        services.work.release()


@router.get("/runs/{run_id}")
def get_run(run_id: str, session: SessionDep) -> RunOut:
    try:
        row = session.store.run(run_id)
    except StoreError as exc:
        raise not_found(f"no run {run_id}") from exc
    return run_out(session.store, row)


def run_out(store: Store, row: RunRow) -> RunOut:
    progress = row.progress or {}
    total = progress.get("steps", 7)
    done = total if row.status == "done" else max(progress.get("step_no", 1) - 1, 0)
    return RunOut(
        run_id=row.id,
        client_id=row.client_id,
        period=row.period,
        status=row.status,
        progress=Progress(step=progress.get("step"), done=done, total=total),
        memory_on=row.memory_on,
        summary=_summary(store, row) if row.status == "done" else None,
        error=row.error,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def _summary(store: Store, row: RunRow) -> RunSummary:
    s: dict[str, Any] = row.summary
    flags: Counter[str] = Counter()
    for suggestion in store.suggestions(row.id).values():
        flags.update(suggestion.flags)
    return RunSummary(
        groups=s["groups"],
        exceptions=s["exceptions"],
        matched=s["matched"],
        auto_resolved=len(s["auto_resolved"]),
        auto_resolved_keys=s["auto_resolved"],
        itc_at_risk=Decimal(s["itc_at_risk"]),
        flags={"PATTERN_DRIFT": 0, "CROSS_CLIENT_RISK": 0, **flags},
        drift=s["drift"],
        late_arrivals=s["late_arrivals"],
        outcomes=s["outcomes"],
        memory_degraded=s["memory_offline"],
    )


# --- Groups ------------------------------------------------------------------


@router.get("/reconciliations/{client_id}/{period}/groups")
def groups(client_id: str, period: str, session: SessionDep) -> list[GroupOut]:
    """The latest run's exception groups, largest ITC at risk first."""
    store = session.store
    client = find_client(session, client_id)
    run = store.latest_run(client.client_id, period)
    if run is None:
        raise not_found(f"{client.client_id} {period} has not been reconciled")
    suggestions = store.suggestions(run.id)
    trusts = store.trust_snapshot(run.id)
    out = []
    for group in store.groups(run.id):
        key = group.key
        trust = trusts.get((key.vendor_gstin, key.exception_type))
        decision = store.current_decision(key)
        suggestion = suggestions.get(str(key))
        out.append(
            GroupOut(
                group_key=str(key),
                vendor=vendor_ref(session, key.vendor_gstin),
                type=key.exception_type,
                invoices=_invoices(group),
                itc_at_risk=group.itc_at_risk,
                suggestion=_suggestion(suggestion) if suggestion else None,
                trust=trust_out(trust) if trust else None,
                decision=decision_out(decision) if decision else None,
                allowed_actions=sorted(ALLOWED_ACTIONS[key.exception_type]),
            )
        )
    return sorted(out, key=lambda g: (-g.itc_at_risk, g.group_key))


def _invoices(group: ExceptionGroup) -> list[InvoiceOut]:
    out = []
    for e in sorted(group.exceptions, key=lambda e: str(e.details.get(Detail.INVOICE_NO, ""))):
        d = e.details
        total = d.get(Detail.BOOK_TOTAL) or d.get(Detail.TWOB_TOTAL)
        tax = d.get(Detail.BOOK_GST)
        out.append(
            InvoiceOut(
                invoice_no=_text(d.get(Detail.INVOICE_NO)),
                date=_text(d.get(Detail.INVOICE_DATE)),
                total=Decimal(str(total)) if total is not None else None,
                tax=Decimal(str(tax)) if tax is not None else None,
                itc_at_risk=e.itc_at_risk,
                details=dict(d),
            )
        )
    return out


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def _suggestion(s: StoredSuggestion) -> SuggestionOut:
    return SuggestionOut(
        action=s.action,
        root_cause=s.root_cause,
        flags=s.flags,
        confidence_label=confidence_label(s.final_confidence),
        final_confidence=s.final_confidence,
        reasoning=s.reasoning,
        vendor_message=s.vendor_message,
        cited_memories=[cited_memory(m) for m in s.cited_memories],
        guardrail_events=[e["rule"] for e in s.guardrail_events],
        guardrail_details=s.guardrail_events,
        memory_on=s.memory_on,
        model=s.model,
    )

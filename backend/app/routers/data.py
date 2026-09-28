"""Health, reference data and uploads (SPEC-07 §3)."""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Form, UploadFile

from backend.app.domain.enums import DecidedBy
from backend.app.domain.periods import validate_period
from backend.app.ingest import IngestError, read_gstr2b, read_purchase_register
from backend.app.routers.common import (
    ServicesDep,
    SessionDep,
    claim_work,
    conflict,
    find_client,
    invalid,
)
from backend.app.schemas import ClientOut, Health, PeriodOut, UploadOut
from backend.app.services import DEFAULT_FIRM_NAME

router = APIRouter()


@router.get("/health")
def health(services: ServicesDep, session: SessionDep) -> Health:
    """Also retries Hindsight when it was down, so the offline banner clears by itself."""
    try:
        seeded = session.store.has_data()
        db_up = True
    except sqlite3.Error:
        seeded, db_up = False, False
    memory = services.memory
    if db_up and not memory.online and memory.ensure_bank(services.bank_profile(session.store)):
        memory.replay_queue()
    return Health(
        ok=db_up,
        db="up" if db_up else "down",
        seeded=seeded,
        hindsight="up" if memory.online else "down",
        llm="up" if services.llm_configured else "down",
        bank_id=services.bank_id,
        firm=services.firm_name(session.store) if db_up else DEFAULT_FIRM_NAME,
        pending_retains=memory.pending() if db_up else 0,
    )


@router.get("/clients")
def clients(session: SessionDep) -> list[ClientOut]:
    return [
        ClientOut(id=c.client_id, name=c.name, gstin=c.gstin, business=c.business_type)
        for c in session.store.clients()
    ]


@router.get("/periods")
def periods(session: SessionDep, client_id: str) -> list[PeriodOut]:
    store = session.store
    client = find_client(session, client_id)
    out = []
    for period, (books, twob) in store.upload_counts(client.client_id).items():
        run = store.latest_run(client.client_id, period)
        open_groups = 0
        if run is not None:
            open_groups = sum(store.current_decision(g.key) is None for g in store.groups(run.id))
        decisions = store.decisions(client_id=client.client_id, period=period)
        out.append(
            PeriodOut(
                period=period,
                has_books=books > 0,
                has_2b=twob > 0,
                run_status=run.status if run else None,
                run_id=run.id if run else None,
                open_groups=open_groups,
                auto_resolved=sum(d.decided_by is DecidedBy.AUTO for d in decisions),
            )
        )
    return out


@router.post("/uploads")
def upload(
    services: ServicesDep,
    session: SessionDep,
    client_id: Annotated[str, Form()],
    period: Annotated[str, Form()],
    purchase_register: UploadFile,
    gstr2b: UploadFile,
) -> UploadOut:
    """Replace a client-period's files, while nothing has been decided on them yet."""
    store = session.store
    client = find_client(session, client_id)
    try:
        period = validate_period(period)
    except ValueError as exc:
        raise invalid(str(exc)) from exc
    try:
        books = read_purchase_register(
            purchase_register.file.read().decode("utf-8-sig"), client, period
        )
        twob = read_gstr2b(gstr2b.file.read(), client, period)
    except UnicodeDecodeError as exc:
        raise invalid("the purchase register must be UTF-8 CSV") from exc
    except IngestError as exc:
        raise invalid(str(exc)) from exc

    claim_work(services, "replace uploaded data")
    try:
        if store.has_decisions(client.client_id, period):
            raise conflict(f"{client.client_id} {period} already has decisions; reset the demo")
        last = store.last_run_period(client.client_id)
        if last is not None and last > period:
            raise conflict(f"{client.client_id} has already run {last}, after {period}")
        store.discard_runs(client.client_id, period)
        store.replace_period(client.client_id, period, books, twob)
    finally:
        services.work.release()

    warnings = []
    if not books:
        warnings.append("the purchase register has no rows")
    if not twob:
        warnings.append("GSTR-2B has no invoices")
    gstins = {i.supplier_gstin for i in books} | {e.supplier_gstin for e in twob}
    unknown = {g for g in gstins if store.vendor(g) is None}
    if unknown:
        warnings.append(f"{len(unknown)} supplier GSTIN(s) are not in the vendor master")
    return UploadOut(rows_books=len(books), rows_2b=len(twob), warnings=warnings)

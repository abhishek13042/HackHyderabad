"""The accountant's decisions and undo of automatic ones (SPEC-07 §3, SPEC-06 §7)."""

from fastapi import APIRouter

from backend.app.domain.entities import GroupKey
from backend.app.domain.enums import DecidedBy
from backend.app.domain.policy import is_action_allowed
from backend.app.routers.common import (
    SessionDep,
    conflict,
    decision_out,
    group_key,
    invalid,
    not_found,
)
from backend.app.schemas import DecisionIn, DecisionOut
from backend.app.services import Session

router = APIRouter()


@router.post("/exceptions/{key}/decision")
def decide(key: str, body: DecisionIn, session: SessionDep) -> DecisionOut:
    """Record (or replace) the decision. An override needs a note: it is the most useful
    memory Recon gets."""
    parsed = _checked(session, key, body)
    suggested = session.store.suggested_action(parsed)
    if suggested is not None and body.action is not suggested and not _note(body):
        raise invalid(f"overriding the suggested {suggested} needs a note saying why")
    return decision_out(session.pipeline.decide(parsed, body.action, _note(body)))


@router.post("/exceptions/{key}/undo")
def undo(key: str, body: DecisionIn, session: SessionDep) -> DecisionOut:
    """Replace an automatic decision; it counts as an override and resets the pattern's trust."""
    parsed = _checked(session, key, body)
    current = session.store.current_decision(parsed)
    if current is None or current.decided_by is not DecidedBy.AUTO:
        raise conflict(f"{parsed} was not resolved automatically")
    if body.action is current.final_action:
        raise invalid(f"undo must choose an action other than {body.action}")
    if not _note(body):
        raise invalid("undoing an automatic decision needs a note saying why")
    return decision_out(session.pipeline.undo(parsed, body.action, _note(body)))


def _checked(session: Session, key: str, body: DecisionIn) -> GroupKey:
    parsed = group_key(key)
    if session.store.group(parsed) is None:
        raise not_found(f"no exception group {parsed}")
    if not is_action_allowed(parsed.exception_type, body.action):
        raise invalid(f"{body.action} is not allowed for {parsed.exception_type}")
    if any(run.period == parsed.period for run in session.store.running(parsed.client_id)):
        raise conflict(f"{parsed.client_id} {parsed.period} is being reconciled; wait for it")
    return parsed


def _note(body: DecisionIn) -> str | None:
    return body.note.strip() if body.note and body.note.strip() else None

"""What every router uses: the error type, dependencies, and domain → response views."""

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends, Request

from backend.app.domain.entities import Client, Decision, GroupKey
from backend.app.domain.enums import TrustLevel
from backend.app.learning import Trust
from backend.app.schemas import CitedMemory, DecisionOut, TrustOut, VendorRef
from backend.app.services import Services, Session
from backend.app.store import StoreError

VALIDATION_ERROR = "VALIDATION_ERROR"
NOT_FOUND = "NOT_FOUND"
CONFLICT = "CONFLICT"
MEMORY_OFFLINE = "MEMORY_OFFLINE"
LLM_UNAVAILABLE = "LLM_UNAVAILABLE"


class ApiError(Exception):
    """Rendered as `{"error": {"code", "message"}}` with `status` (SPEC-07 §2)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def not_found(message: str) -> ApiError:
    return ApiError(404, NOT_FOUND, message)


def conflict(message: str) -> ApiError:
    return ApiError(409, CONFLICT, message)


def invalid(message: str) -> ApiError:
    return ApiError(422, VALIDATION_ERROR, message)


def memory_offline() -> ApiError:
    return ApiError(503, MEMORY_OFFLINE, "Hindsight is unreachable; memory views are unavailable")


# --- Dependencies ------------------------------------------------------------


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


def get_session(services: ServicesDep) -> Iterator[Session]:
    with services.session() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def group_key(value: str) -> GroupKey:
    try:
        return GroupKey.model_validate(value)
    except ValueError as exc:
        raise invalid(f"not a group key: {value!r}") from exc


def find_client(session: Session, client_id: str) -> Client:
    try:
        return session.store.client(client_id)
    except StoreError as exc:
        raise not_found(f"no client {client_id}") from exc


def claim_work(services: Services, what: str) -> None:
    """Take the work lock or answer 409; the caller releases it when the work ends."""
    if not services.work.acquire(blocking=False):
        raise conflict(f"cannot {what}: a reconciliation or seed job is in progress")


# --- Views -------------------------------------------------------------------


def vendor_ref(session: Session, gstin: str) -> VendorRef:
    vendor = session.pipeline.vendor(gstin)
    return VendorRef(gstin=vendor.gstin, name=vendor.name)


def trust_out(trust: Trust) -> TrustOut:
    return TrustOut(
        level=trust.level,
        name=TrustLevel(trust.level).name,
        streak_action=trust.streak_action,
        streak=trust.streak,
        correct=trust.correct,
        wrong=trust.wrong,
    )


def decision_out(decision: Decision) -> DecisionOut:
    return DecisionOut(
        id=decision.id,
        group_key=str(decision.group_key),
        action=decision.final_action,
        suggested_action=decision.suggested_action,
        accepted_suggestion=decision.final_action is decision.suggested_action,
        decided_by=decision.decided_by,
        note=decision.note,
        decided_at=decision.decided_at.isoformat(timespec="seconds"),
    )


def cited_memory(record: dict[str, Any]) -> CitedMemory:
    """From a stored `MemoryRecord` dump."""
    metadata = record.get("metadata") or {}
    return CitedMemory(
        id=record["id"],
        text=record["text"],
        period=metadata.get("period"),
        client_id=metadata.get("client_id"),
        occurred_at=record.get("occurred_at"),
    )

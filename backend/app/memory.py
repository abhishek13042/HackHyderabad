"""Recon's long-term memory (SPEC-04).

The only module that imports `hindsight_client` (AC-04-1). Everything else talks
to `Memory`, which adds what the product needs on top of the raw SDK:

- every retain / recall / reflect is logged to `memory_events` for the live UI;
- when Hindsight is down, retains are queued in SQLite and replayed later, and
  recall reports "offline" so the caller proceeds as if memory were off;
- recall and reflect results are cached until something new is learned.

`InMemoryBackend` is a small keyword-matching stand-in for tests and for working
without a Hindsight server; it is not a substitute for real recall quality.
"""

import asyncio
import json
import re
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as clock_time
from typing import Protocol, TypeVar

import aiohttp
from hindsight_client import Hindsight
from hindsight_client_api.exceptions import OpenApiException
from pydantic import AwareDatetime, BaseModel, ConfigDict

from backend.app.config import Settings
from backend.app.domain.enums import Action, ExceptionType
from backend.app.memory_text import MemoryKind

RECALL_TYPES = ("world", "experience", "observation")
RECALL_MAX_TOKENS = 1500
RECALL_BUDGET = "mid"
REFLECT_BUDGET = "low"
SUMMARY_CHARS = 200
OFFLINE_RETRY_S = 15.0
"""After a failure, memory calls fail fast this long; only ensure_bank (the /health probe) tries."""

T = TypeVar("T")

FIRM_MISSION = (
    "You are the institutional memory of {firm}, a Chartered Accountancy firm in "
    "Hyderabad, for GST input-tax-credit reconciliation. Remember how mismatches "
    "between clients' purchase registers and GSTR-2B were resolved, how each vendor "
    "behaves over time, and the accountant's preferences. Never recommend claiming "
    "ITC for an invoice that is absent from GSTR-2B or marked ineligible."
)


class MemoryUnavailableError(RuntimeError):
    """Hindsight could not be reached, or refused the request."""


# --- Values ------------------------------------------------------------------


class _Value(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


@dataclass(frozen=True)
class BankProfile:
    bank_id: str
    name: str
    mission: str
    # High skepticism and literalism: this is tax, prefer evidence over assumption.
    skepticism: int = 4
    literalism: int = 4
    empathy: int = 2


def firm_bank(bank_id: str, firm_name: str) -> BankProfile:
    """One bank per firm, so vendor knowledge carries across clients (§4)."""
    return BankProfile(bank_id, f"Recon — {firm_name}", FIRM_MISSION.format(firm=firm_name))


class RetainRequest(_Value):
    """One memory to store. Serializable, so it can wait in the offline queue."""

    document_id: str
    """Re-deciding a group reuses its id, and the memory is replaced, not duplicated."""
    kind: MemoryKind
    content: str
    occurred_at: AwareDatetime
    """The business date, not wall-clock time, so temporal recall works on seeded history."""
    metadata: dict[str, str]
    tags: tuple[str, ...]
    entities: tuple[str, ...]


def retain_request(
    kind: MemoryKind,
    content: str,
    *,
    document_id: str,
    occurred_on: date,
    period: str,
    client_id: str,
    client_name: str,
    vendor_gstin: str,
    vendor_name: str,
    exception_type: ExceptionType | None = None,
    action: Action | None = None,
) -> RetainRequest:
    metadata = {
        "kind": kind.value,
        "period": period,
        "client_id": client_id,
        "vendor_gstin": vendor_gstin,
    }
    if exception_type is not None:
        metadata["exception_type"] = exception_type.value
    if action is not None:
        metadata["action"] = action.value
    return RetainRequest(
        document_id=document_id,
        kind=kind,
        content=content,
        occurred_at=business_time(occurred_on),
        metadata=metadata,
        tags=(f"vendor:{vendor_gstin}", f"client:{client_id}", f"kind:{kind.value}"),
        entities=(vendor_name, client_name),
    )


def business_time(day: date) -> datetime:
    """Midday UTC on a business date: unambiguous, and the same day in every timezone we use."""
    return datetime.combine(day, clock_time(12), UTC)


class MemoryRecord(_Value):
    """One recalled memory. `id` is what the agent cites (SPEC-05)."""

    id: str
    text: str
    type: str | None = None
    occurred_at: str | None = None
    document_id: str | None = None
    metadata: dict[str, str] = {}


@dataclass(frozen=True)
class Recalled:
    records: tuple[MemoryRecord, ...]
    online: bool
    """False when Hindsight was unreachable: treat this group as memory OFF (§13)."""


# --- Backends ----------------------------------------------------------------


class MemoryBackend(Protocol):
    """The four calls Recon makes. Implementations raise `MemoryUnavailableError`."""

    def ensure_bank(self, profile: BankProfile) -> None: ...
    def delete_bank(self, bank_id: str) -> None: ...
    def retain(self, bank_id: str, request: RetainRequest) -> None: ...
    def recall(self, bank_id: str, query: str, *, max_tokens: int) -> list[MemoryRecord]: ...
    def reflect(self, bank_id: str, query: str, *, tags: tuple[str, ...]) -> str: ...


class HindsightBackend:
    """Hindsight over HTTP: self-hosted or Cloud, chosen by `base_url` and `api_key` alone."""

    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 60.0) -> None:
        # The SDK's sync methods drive an asyncio loop of the calling thread, which fails
        # inside a running loop (FastAPI startup) and ties its HTTP session to one loop.
        # So the client lives on one thread of its own and every call is made there.
        self._loop = asyncio.new_event_loop()
        self._worker = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="hindsight",
            initializer=asyncio.set_event_loop,
            initargs=(self._loop,),
        )
        self._client = self._call(
            lambda: Hindsight(base_url=base_url, api_key=api_key or None, timeout=timeout)
        )

    def _call(self, call: Callable[[], T]) -> T:
        return self._worker.submit(call).result()

    def ensure_bank(self, profile: BankProfile) -> None:
        # create_bank is an HTTP PUT: creates or updates, so it is safe on every start.
        with _unavailable_on_error():
            self._call(
                lambda: self._client.create_bank(
                    profile.bank_id,
                    name=profile.name,
                    mission=profile.mission,
                    disposition_skepticism=profile.skepticism,
                    disposition_literalism=profile.literalism,
                    disposition_empathy=profile.empathy,
                )
            )

    def delete_bank(self, bank_id: str) -> None:
        with _unavailable_on_error():
            self._call(lambda: self._client.delete_bank(bank_id))

    def retain(self, bank_id: str, request: RetainRequest) -> None:
        with _unavailable_on_error():
            self._call(
                lambda: self._client.retain(
                    bank_id,
                    request.content,
                    timestamp=request.occurred_at,
                    context=f"gst reconciliation {request.kind.value}",
                    document_id=request.document_id,
                    metadata=request.metadata,
                    entities=[{"text": name} for name in request.entities],
                    tags=list(request.tags),
                    update_mode="replace",
                )
            )

    def recall(self, bank_id: str, query: str, *, max_tokens: int) -> list[MemoryRecord]:
        with _unavailable_on_error():
            response = self._call(
                lambda: self._client.recall(
                    bank_id,
                    query,
                    types=list(RECALL_TYPES),
                    max_tokens=max_tokens,
                    budget=RECALL_BUDGET,
                )
            )
        return [
            MemoryRecord(
                id=result.id,
                text=result.text,
                type=result.type,
                occurred_at=result.occurred_start or result.mentioned_at,
                document_id=result.document_id,
                metadata=result.metadata or {},
            )
            for result in response.results
        ]

    def reflect(self, bank_id: str, query: str, *, tags: tuple[str, ...]) -> str:
        with _unavailable_on_error():
            response = self._call(
                lambda: self._client.reflect(
                    bank_id,
                    query,
                    budget=REFLECT_BUDGET,
                    tags=list(tags) or None,
                    tags_match="all_strict",
                )
            )
        return response.text

    @classmethod
    def from_settings(cls, settings: Settings) -> "HindsightBackend":
        return cls(settings.hindsight_base_url, settings.hindsight_api_key.get_secret_value())

    def close(self) -> None:
        self._call(self._client.close)
        self._call(self._loop.close)
        self._worker.shutdown()


@contextmanager
def _unavailable_on_error() -> Iterator[None]:
    try:
        yield
    except (OpenApiException, aiohttp.ClientError, OSError, TimeoutError) as exc:
        raise MemoryUnavailableError(f"{type(exc).__name__}: {exc}") from exc


class InMemoryBackend:
    """Ranks memories by words shared with the query. For tests and offline development."""

    def __init__(self) -> None:
        self.banks: dict[str, dict[str, RetainRequest]] = {}
        self.available = True
        """Set False to simulate Hindsight being down."""

    def ensure_bank(self, profile: BankProfile) -> None:
        self._check()
        self.banks.setdefault(profile.bank_id, {})

    def delete_bank(self, bank_id: str) -> None:
        self._check()
        self.banks.pop(bank_id, None)

    def retain(self, bank_id: str, request: RetainRequest) -> None:
        self._check()
        self.banks.setdefault(bank_id, {})[request.document_id] = request

    def recall(self, bank_id: str, query: str, *, max_tokens: int) -> list[MemoryRecord]:
        self._check()
        wanted = _words(query)
        scored = [
            (len(wanted & _words(r.content)), r) for r in self.banks.get(bank_id, {}).values()
        ]
        ranked = sorted(
            ((score, r) for score, r in scored if score),
            key=lambda item: (-item[0], item[1].occurred_at, item[1].document_id),
        )
        records, budget = [], max_tokens
        for _, request in ranked:
            budget -= estimate_tokens(request.content)
            if budget < 0:
                break
            records.append(
                MemoryRecord(
                    id=request.document_id,
                    text=request.content,
                    type="world",
                    occurred_at=request.occurred_at.isoformat(),
                    document_id=request.document_id,
                    metadata=request.metadata,
                )
            )
        return records

    def reflect(self, bank_id: str, query: str, *, tags: tuple[str, ...]) -> str:
        self._check()
        memories = [
            r.content for r in self.banks.get(bank_id, {}).values() if set(tags) <= set(r.tags)
        ]
        return "\n\n".join(memories) if memories else "Nothing is known about this yet."

    def _check(self) -> None:
        if not self.available:
            raise MemoryUnavailableError("in-memory backend set to unavailable")


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


def estimate_tokens(text: str) -> int:
    """Rough token count (≈ 4 characters per token), for budgets and measurements."""
    return max(1, len(text) // 4)


# --- Memory ------------------------------------------------------------------


def utc_now() -> datetime:
    return datetime.now(UTC)


class Memory:
    """Recon's memory for one bank, with logging, the offline queue, and caches."""

    def __init__(
        self,
        backend: MemoryBackend,
        conn: sqlite3.Connection,
        bank_id: str,
        *,
        clock: Callable[[], datetime] = utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.backend = backend
        self.bank_id = bank_id
        self._conn = conn
        # Runs and API requests share one Memory; its connection is used one caller at a time.
        self._lock = threading.RLock()
        self._clock = clock
        self._monotonic = monotonic
        # A dead server can take seconds per call to refuse; don't pay that on every retain.
        self._down_until = 0.0
        self._recalls: dict[str, tuple[MemoryRecord, ...]] = {}
        self._reflections: dict[str, str] = {}
        self.online = True
        """Whether the last call reached Hindsight; drives the UI's offline banner."""

    # --- Bank ---

    def ensure_bank(self, profile: BankProfile) -> bool:
        if profile.bank_id != self.bank_id:
            raise ValueError(f"profile is for bank {profile.bank_id}, memory uses {self.bank_id}")
        try:
            self.backend.ensure_bank(profile)
        except MemoryUnavailableError:
            self._mark_down()
            return False
        self.online = True
        self._down_until = 0.0
        return True

    def reset_bank(self, profile: BankProfile) -> None:
        """Delete and recreate the bank (demo reset, fresh eval runs)."""
        self.backend.delete_bank(self.bank_id)
        self.backend.ensure_bank(profile)
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM retain_queue")
        self.forget_cached()

    # --- Retain ---

    def retain(self, request: RetainRequest) -> bool:
        """Store a memory. Returns False if Hindsight was down and it was queued instead."""
        try:
            with self._logged("retain", request.kind.value, request.content):
                self.backend.retain(self.bank_id, request)
        except MemoryUnavailableError as exc:
            self._enqueue(request, str(exc))
            return False
        with self._lock, self._conn:
            # A newer version of a queued memory supersedes it.
            self._conn.execute(
                "DELETE FROM retain_queue WHERE document_id = ?", (request.document_id,)
            )
        self.forget_cached()
        return True

    def pending(self) -> int:
        with self._lock:
            count: int = self._conn.execute("SELECT COUNT(*) FROM retain_queue").fetchone()[0]
        return count

    def replay_queue(self) -> int:
        """Retry queued retains oldest first; stop at the first failure. Returns how many landed."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT document_id, payload FROM retain_queue ORDER BY id"
            ).fetchall()
        stored = 0
        for row in rows:
            if not self.retain(RetainRequest.model_validate_json(row["payload"])):
                break
            stored += 1
        return stored

    def _enqueue(self, request: RetainRequest, error: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO retain_queue (document_id, payload, attempts, last_error, created_at)
                VALUES (?, ?, 1, ?, ?)
                ON CONFLICT (document_id) DO UPDATE SET
                    payload = excluded.payload,
                    attempts = attempts + 1,
                    last_error = excluded.last_error
                """,
                (request.document_id, request.model_dump_json(), error, self._now()),
            )

    # --- Recall and reflect ---

    def recall(self, query: str, *, purpose: str = "group") -> Recalled:
        """Recall for one question. Offline is not an error: the caller treats it as memory OFF."""
        if query in self._recalls:
            return Recalled(self._recalls[query], online=True)
        try:
            with self._logged("recall", purpose, query) as event:
                records = tuple(
                    self.backend.recall(self.bank_id, query, max_tokens=RECALL_MAX_TOKENS)
                )
                event.result_count = len(records)
        except MemoryUnavailableError:
            return Recalled((), online=False)
        self._recalls[query] = records
        return Recalled(records, online=True)

    def reflect(self, query: str, *, purpose: str, tags: tuple[str, ...] = ()) -> str | None:
        """The expensive call: UI summaries only, cached until something new is retained."""
        cache_key = json.dumps([query, tags])
        if cache_key in self._reflections:
            return self._reflections[cache_key]
        try:
            with self._logged("reflect", purpose, query):
                text = self.backend.reflect(self.bank_id, query, tags=tags)
        except MemoryUnavailableError:
            return None
        self._reflections[cache_key] = text
        return text

    def forget_cached(self) -> None:
        self._recalls.clear()
        self._reflections.clear()

    # --- Event log (§9) ---

    @contextmanager
    def _logged(self, op: str, kind: str, text: str) -> Iterator["_Event"]:
        event = _Event()
        started = time.perf_counter()
        if self._monotonic() < self._down_until:
            error = "Hindsight unavailable; not retrying yet"
            self._log(op, kind, text, event, started, error=error)
            raise MemoryUnavailableError(error)
        try:
            yield event
        except MemoryUnavailableError as exc:
            self._mark_down()
            self._log(op, kind, text, event, started, error=str(exc))
            raise
        self.online = True
        self._log(op, kind, text, event, started, error=None)

    def _mark_down(self) -> None:
        self.online = False
        self._down_until = self._monotonic() + OFFLINE_RETRY_S

    def _log(
        self, op: str, kind: str, text: str, event: "_Event", started: float, error: str | None
    ) -> None:
        latency_ms = round((time.perf_counter() - started) * 1000)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO memory_events
                    (ts, op, bank_id, kind, summary, result_count, latency_ms, ok, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._now(),
                    op,
                    self.bank_id,
                    kind,
                    " ".join(text.split())[:SUMMARY_CHARS],
                    event.result_count,
                    latency_ms,
                    int(error is None),
                    error,
                ),
            )

    def _now(self) -> str:
        return self._clock().isoformat(timespec="seconds")


@dataclass
class _Event:
    result_count: int | None = None

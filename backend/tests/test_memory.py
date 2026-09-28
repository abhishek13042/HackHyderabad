"""SPEC-04: the memory service — logging, the offline queue, caching — on the in-memory backend."""

import asyncio
import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from backend.app.db import connect, init_db
from backend.app.domain.enums import Action, ExceptionType
from backend.app.memory import (
    HindsightBackend,
    InMemoryBackend,
    Memory,
    MemoryUnavailableError,
    RetainRequest,
    business_time,
    estimate_tokens,
    firm_bank,
    retain_request,
)
from backend.app.memory_text import MemoryKind

BANK = "munshi-test"
PROFILE = firm_bank(BANK, "Rao & Associates")
GSTIN = "36AAJFK4410L1Z5"
NOW = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def backend() -> InMemoryBackend:
    return InMemoryBackend()


@pytest.fixture
def memory(backend: InMemoryBackend, conn: sqlite3.Connection) -> Memory:
    memory = Memory(backend, conn, BANK, clock=lambda: NOW)
    assert memory.ensure_bank(PROFILE)
    return memory


def resolution(text: str = "Krishna Logistics invoices missing from GSTR-2B were deferred.",
               group: str = f"C01:2026-01:{GSTIN}:MISSING_IN_2B") -> RetainRequest:  # fmt: skip
    return retain_request(
        MemoryKind.RESOLUTION,
        text,
        document_id=f"{group}:resolution",
        occurred_on=date(2026, 2, 10),
        period="2026-01",
        client_id="C01",
        client_name="Sri Balaji Textiles",
        vendor_gstin=GSTIN,
        vendor_name="Krishna Logistics",
        exception_type=ExceptionType.MISSING_IN_2B,
        action=Action.DEFER,
    )


def events(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM memory_events ORDER BY id").fetchall()


# --- Requests ----------------------------------------------------------------


def test_request_is_tagged_and_dated_by_business_date() -> None:
    request = resolution()
    assert request.occurred_at == datetime(2026, 2, 10, 12, tzinfo=UTC)
    assert request.tags == (f"vendor:{GSTIN}", "client:C01", "kind:resolution")
    assert request.entities == ("Krishna Logistics", "Sri Balaji Textiles")
    assert request.metadata == {
        "kind": "resolution", "period": "2026-01", "client_id": "C01",
        "vendor_gstin": GSTIN, "exception_type": "MISSING_IN_2B", "action": "DEFER",
    }  # fmt: skip


def test_request_survives_the_queue_round_trip() -> None:
    request = resolution()
    assert RetainRequest.model_validate_json(request.model_dump_json()) == request


def test_business_time_is_aware() -> None:
    assert business_time(date(2026, 1, 31)).tzinfo is UTC


def test_bank_mission_carries_the_itc_rule() -> None:
    assert "Never recommend claiming ITC" in PROFILE.mission
    assert "Rao & Associates" in PROFILE.mission


# --- Retain and recall -------------------------------------------------------


def test_retain_then_recall(memory: Memory) -> None:
    assert memory.retain(resolution())
    recalled = memory.recall("How were Krishna Logistics invoices handled?")
    assert recalled.online
    (record,) = recalled.records
    assert record.document_id == f"C01:2026-01:{GSTIN}:MISSING_IN_2B:resolution"
    assert record.metadata["action"] == "DEFER"


def test_same_document_is_replaced_not_duplicated(memory: Memory, backend: InMemoryBackend) -> None:
    memory.retain(resolution("Krishna Logistics: deferred."))
    memory.retain(resolution("Krishna Logistics: chased the vendor instead."))
    (stored,) = backend.banks[BANK].values()
    assert "chased" in stored.content


def test_recall_respects_the_token_budget(backend: InMemoryBackend) -> None:
    for n in range(50):
        backend.retain(BANK, resolution(f"Krishna Logistics memory {n} " + "x" * 400, f"g{n}"))
    records = backend.recall(BANK, "Krishna Logistics", max_tokens=1500)
    assert 0 < len(records) < 50
    assert sum(estimate_tokens(r.text) for r in records) <= 1500


def test_unrelated_query_recalls_nothing(memory: Memory) -> None:
    memory.retain(resolution())
    assert memory.recall("zebra quantum").records == ()


def test_recall_is_cached_until_something_is_learned(
    memory: Memory, conn: sqlite3.Connection
) -> None:
    query = "Krishna Logistics"
    memory.recall(query)
    memory.recall(query)
    assert [e["op"] for e in events(conn)] == ["recall"]
    memory.retain(resolution())
    assert len(memory.recall(query).records) == 1


def test_reflect_filters_by_tags_and_is_cached(memory: Memory, conn: sqlite3.Connection) -> None:
    memory.retain(resolution())
    text = memory.reflect("Profile", purpose="vendor_profile", tags=(f"vendor:{GSTIN}",))
    assert text is not None and "deferred" in text
    memory.reflect("Profile", purpose="vendor_profile", tags=(f"vendor:{GSTIN}",))
    assert [e["op"] for e in events(conn)] == ["retain", "reflect"]
    other = memory.reflect("Profile", purpose="vendor_profile", tags=("vendor:OTHER",))
    assert other == "Nothing is known about this yet."


# --- AC-04-5: every operation is logged --------------------------------------


def test_every_operation_is_logged(memory: Memory, conn: sqlite3.Connection) -> None:
    memory.retain(resolution())
    memory.recall("Krishna Logistics")
    memory.reflect("What did we learn?", purpose="insights")
    rows = events(conn)
    assert [(r["op"], r["kind"], r["ok"]) for r in rows] == [
        ("retain", "resolution", 1),
        ("recall", "group", 1),
        ("reflect", "insights", 1),
    ]
    assert rows[1]["result_count"] == 1
    assert all(r["bank_id"] == BANK and r["ts"] == "2026-09-28T10:00:00+00:00" for r in rows)
    assert rows[0]["summary"].startswith("Krishna Logistics invoices")


# --- AC-04-6: Hindsight down -------------------------------------------------


def test_offline_retain_is_queued_and_replayed(
    memory: Memory, backend: InMemoryBackend, conn: sqlite3.Connection
) -> None:
    backend.available = False
    assert not memory.retain(resolution())
    assert not memory.retain(resolution("Second version of the same decision, Krishna."))
    assert memory.pending() == 1  # the newer version replaced the queued one
    (row,) = conn.execute("SELECT attempts, last_error FROM retain_queue").fetchall()
    assert row["attempts"] == 2 and "unavailable" in row["last_error"]
    assert not memory.online
    assert events(conn)[-1]["ok"] == 0

    assert memory.replay_queue() == 0  # still down: nothing lost
    assert memory.pending() == 1

    backend.available = True
    assert memory.ensure_bank(PROFILE)  # what /health does before replaying
    assert memory.replay_queue() == 1
    assert memory.pending() == 0
    assert memory.online
    (stored,) = backend.banks[BANK].values()
    assert stored.content.startswith("Second version")


def test_offline_recall_means_memory_off(memory: Memory, backend: InMemoryBackend) -> None:
    memory.retain(resolution())
    memory.forget_cached()
    backend.available = False
    recalled = memory.recall("Krishna Logistics")
    assert recalled.records == () and not recalled.online
    assert memory.reflect("Krishna", purpose="vendor_profile") is None


def test_after_a_failure_calls_fail_fast_until_the_probe_succeeds(
    backend: InMemoryBackend, conn: sqlite3.Connection
) -> None:
    now = [100.0]
    memory = Memory(backend, conn, BANK, clock=lambda: NOW, monotonic=lambda: now[0])
    assert memory.ensure_bank(PROFILE)
    backend.available = False
    assert not memory.retain(resolution())
    backend.available = True
    # Back, but within the retry window: not called, still queued and logged.
    assert not memory.recall("Krishna").online
    assert "not retrying" in events(conn)[-1]["error"]
    now[0] += 16
    assert memory.recall("Krishna").online

    backend.available = False
    assert not memory.retain(resolution())
    backend.available = True
    assert memory.ensure_bank(PROFILE)  # the /health probe always tries
    assert memory.replay_queue() == 1


def test_offline_start_is_reported(backend: InMemoryBackend, conn: sqlite3.Connection) -> None:
    backend.available = False
    memory = Memory(backend, conn, BANK)
    assert not memory.ensure_bank(PROFILE)
    assert not memory.online


def test_successful_retain_clears_a_queued_older_version(
    memory: Memory, backend: InMemoryBackend
) -> None:
    backend.available = False
    memory.retain(resolution("old Krishna"))
    backend.available = True
    assert memory.ensure_bank(PROFILE)
    memory.retain(resolution("new Krishna"))
    assert memory.pending() == 0
    assert memory.replay_queue() == 0
    (stored,) = backend.banks[BANK].values()
    assert stored.content == "new Krishna"


def test_reset_empties_bank_and_queue(memory: Memory, backend: InMemoryBackend) -> None:
    memory.retain(resolution())
    backend.available = False
    memory.retain(resolution("queued Krishna", "other-group"))
    backend.available = True
    memory.reset_bank(PROFILE)
    assert backend.banks[BANK] == {}
    assert memory.pending() == 0


def test_profile_must_match_the_bank(memory: Memory) -> None:
    with pytest.raises(ValueError, match="bank"):
        memory.ensure_bank(firm_bank("another-bank", "Rao & Associates"))


def test_backend_errors_are_typed(backend: InMemoryBackend) -> None:
    backend.available = False
    with pytest.raises(MemoryUnavailableError):
        backend.recall(BANK, "anything", max_tokens=100)


def test_hindsight_backend_works_from_inside_an_event_loop() -> None:
    """FastAPI starts up inside a running loop; the SDK's sync calls must still fail cleanly."""
    backend = HindsightBackend("http://127.0.0.1:9", timeout=2.0)

    async def call() -> None:
        with pytest.raises(MemoryUnavailableError):
            backend.recall(BANK, "anything", max_tokens=100)

    try:
        asyncio.run(call())
    finally:
        backend.close()


# --- AC-04-1 -----------------------------------------------------------------


def test_only_the_memory_module_imports_the_sdk() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    importers = {
        path.relative_to(backend_dir).as_posix()
        for path in backend_dir.rglob("*.py")
        if "tests" not in path.parts
        and any(
            sdk in _imports(path) for sdk in ("import hindsight_client", "from hindsight_client")
        )
    }
    assert importers == {"app/memory.py"}


def _imports(path: Path) -> str:
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith(("import ", "from "))
    )  # fmt: skip

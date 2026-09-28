"""SPEC-04 against a real Hindsight server.

Skipped unless the server in `.env` is reachable. Uses a throwaway bank that is
deleted afterwards. Run with `pytest -m hindsight`. AC-04-2 needs seeded history
and is checked with seeding (SPEC-06).
"""

import sqlite3
import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from backend.app.config import get_settings
from backend.app.db import connect, init_db
from backend.app.domain.enums import Action, ExceptionType
from backend.app.memory import (
    RECALL_MAX_TOKENS,
    HindsightBackend,
    Memory,
    RetainRequest,
    estimate_tokens,
    firm_bank,
    retain_request,
)
from backend.app.memory_text import MemoryKind, Resolution, group_query

pytestmark = pytest.mark.hindsight

KRISHNA = "36AAJFK4410L1Z5"
DOCUMENT = f"C01:2026-01:{KRISHNA}:MISSING_IN_2B:resolution"


def _reachable(base_url: str) -> bool:
    try:
        with urlopen(f"{base_url.rstrip('/')}/health", timeout=2):
            return True
    except (URLError, OSError):
        return False


@pytest.fixture(scope="module")
def memory() -> Iterator[Memory]:
    settings = get_settings()
    if not _reachable(settings.hindsight_base_url):
        pytest.skip(f"Hindsight not reachable at {settings.hindsight_base_url}")
    bank_id = f"munshi-test-{uuid.uuid4().hex[:8]}"
    backend = HindsightBackend.from_settings(settings)
    conn: sqlite3.Connection = connect(":memory:")
    init_db(conn)
    memory = Memory(backend, conn, bank_id)
    assert memory.ensure_bank(firm_bank(bank_id, "Rao & Associates"))
    yield memory
    backend.delete_bank(bank_id)
    backend.close()
    conn.close()


def krishna_at_c01(note: str) -> RetainRequest:
    text = Resolution(
        period="2026-01", client_name="Sri Balaji Textiles", vendor_name="Krishna Logistics",
        vendor_gstin=KRISHNA, exception_type=ExceptionType.MISSING_IN_2B, invoice_count=3,
        itc_at_risk=Decimal("84000"), suggested_action=Action.CHASE_VENDOR,
        final_action=Action.DEFER, note=note,
    ).text()  # fmt: skip
    return retain_request(
        MemoryKind.RESOLUTION, text, document_id=DOCUMENT, occurred_on=date(2026, 2, 10),
        period="2026-01", client_id="C01", client_name="Sri Balaji Textiles",
        vendor_gstin=KRISHNA, vendor_name="Krishna Logistics",
        exception_type=ExceptionType.MISSING_IN_2B, action=Action.DEFER,
    )  # fmt: skip


def krishna_query() -> str:
    # Asked while reconciling C03: the query never names the client.
    return group_query("Krishna Logistics", KRISHNA, ExceptionType.MISSING_IN_2B)


def test_ac_04_3_cross_client_recall(memory: Memory) -> None:
    assert memory.retain(krishna_at_c01("Krishna always files late; it shows up next month."))
    recalled = memory.recall(krishna_query())
    assert recalled.online
    assert any(r.document_id == DOCUMENT for r in recalled.records)
    assert any("late" in r.text.lower() for r in recalled.records)


def test_same_document_id_replaces(memory: Memory) -> None:
    memory.retain(krishna_at_c01("Changed my mind: chase them for the GSTR-1 filing."))
    texts = " ".join(r.text.lower() for r in memory.recall(krishna_query()).records)
    assert "always files late" not in texts


def test_ac_04_7_recall_stays_within_budget(memory: Memory) -> None:
    memory.forget_cached()
    records = memory.recall(krishna_query()).records
    assert sum(estimate_tokens(r.text) for r in records) <= RECALL_MAX_TOKENS


def test_reflect_answers_from_memory(memory: Memory) -> None:
    text = memory.reflect(
        "How does Krishna Logistics usually behave?",
        purpose="vendor_profile",
        tags=(f"vendor:{KRISHNA}",),
    )
    assert text and "krishna" in text.lower()

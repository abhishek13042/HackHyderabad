import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from backend.app.db import SCHEMA_VERSION, SchemaVersionError, connect, init_db

EXPECTED_TABLES = {
    "firms", "clients", "vendors", "book_invoices", "twob_entries", "runs",
    "exceptions", "suggestions", "decisions", "outcomes", "trust",
    "drift_events", "memory_events", "retain_queue",
}  # fmt: skip


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    init_db(connection)
    yield connection
    connection.close()


def _add_client(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute("INSERT INTO firms VALUES ('rao-associates', 'Rao & Associates')")
        conn.execute(
            "INSERT INTO clients VALUES ('C01', 'rao-associates', 'Sri Balaji Textiles',"
            " '36AAKFS9876P1Z1', 'Textile trader')"
        )


def _insert_decision(conn: sqlite3.Connection, **values: str | None) -> None:
    row = {
        "group_key": "C01:2026-04:X:MISSING_IN_2B",
        "client_id": "C01",
        "period": "2026-04",
        "vendor_gstin": "X",
        "exception_type": "MISSING_IN_2B",
        "suggested_action": "DEFER",
        "final_action": "DEFER",
        "decided_by": "AUTO",
        "decided_at": "2026-04-18T10:30:00+00:00",
        "superseded_at": None,
    } | values
    columns = ", ".join(row)
    placeholders = ", ".join(f":{name}" for name in row)
    with conn:
        conn.execute(f"INSERT INTO decisions ({columns}) VALUES ({placeholders})", row)


def test_creates_all_tables(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    assert {row["name"] for row in rows} == EXPECTED_TABLES
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_init_is_idempotent(conn: sqlite3.Connection) -> None:
    init_db(conn)


def test_refuses_other_schema_version() -> None:
    connection = connect(":memory:")
    connection.execute("PRAGMA user_version = 999")
    with pytest.raises(SchemaVersionError):
        init_db(connection)


def test_foreign_keys_enforced(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute(
            "INSERT INTO clients VALUES ('C09', 'no-such-firm', 'X', '36AAKFS9876P1Z1', 'X')"
        )


def test_enum_columns_reject_unknown_values(conn: sqlite3.Connection) -> None:
    _add_client(conn)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _insert_decision(conn, final_action="CLAIM_ANYWAY")


def test_only_one_current_decision_per_group(conn: sqlite3.Connection) -> None:
    _add_client(conn)
    _insert_decision(conn, superseded_at="2026-04-19T09:00:00+00:00")  # undone AUTO decision
    _insert_decision(conn, decided_by="ACCOUNTANT", final_action="CHASE_VENDOR")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _insert_decision(conn)


def test_json_columns_must_be_valid(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            "INSERT INTO drift_events (vendor_gstin, detected_in_period, evidence, created_at)"
            " VALUES ('X', '2026-04', 'not json', '2026-04-18')"
        )


def test_file_database_uses_wal(tmp_path: Path) -> None:
    connection = connect(tmp_path / "nested" / "munshi.db")
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        connection.close()

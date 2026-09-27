"""SQLite storage (SPEC-01 §8).

Plain `sqlite3`, no ORM. Money columns are integer paise (`*_paise`, INV-3),
dates are ISO-8601 text, JSON columns are text validated with `json_valid`.
Enum columns get CHECK constraints generated from `domain.enums`, so the
allowed values are declared exactly once.

The schema is versioned with `PRAGMA user_version`. There are no migrations:
this is a local demo database that `/demo/reset` rebuilds from the seed.
"""

import sqlite3
from collections.abc import Iterable
from enum import Enum
from pathlib import Path

from backend.app.domain.enums import (
    Action,
    DecidedBy,
    ExceptionType,
    OutcomeStatus,
    RegistrationStatus,
    RootCause,
    TrustLevel,
)

SCHEMA_VERSION = 1


class SchemaVersionError(RuntimeError):
    """The database was created by a different schema version."""


def _one_of(column: str, values: Iterable[Enum]) -> str:
    allowed = ", ".join(f"'{member.value}'" for member in values)
    return f"CHECK ({column} IN ({allowed}))"


def _json(column: str) -> str:
    return f"CHECK (json_valid({column}))"


_MONEY_COLUMNS = """
    taxable_value_paise INTEGER NOT NULL CHECK (taxable_value_paise >= 0),
    cgst_paise          INTEGER NOT NULL CHECK (cgst_paise >= 0),
    sgst_paise          INTEGER NOT NULL CHECK (sgst_paise >= 0),
    igst_paise          INTEGER NOT NULL CHECK (igst_paise >= 0),
    cess_paise          INTEGER NOT NULL CHECK (cess_paise >= 0),
    total_paise         INTEGER NOT NULL CHECK (total_paise >= 0)"""

_TRUST_LEVELS = ", ".join(str(level.value) for level in TrustLevel)

SCHEMA = f"""
CREATE TABLE firms (
    firm_id TEXT PRIMARY KEY,
    name    TEXT NOT NULL
);

CREATE TABLE clients (
    client_id     TEXT PRIMARY KEY,
    firm_id       TEXT NOT NULL REFERENCES firms (firm_id),
    name          TEXT NOT NULL,
    gstin         TEXT NOT NULL UNIQUE,
    business_type TEXT NOT NULL
);

CREATE TABLE vendors (
    gstin               TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    registration_status TEXT NOT NULL {_one_of("registration_status", RegistrationStatus)}
);

-- supplier_gstin is not a foreign key: books can contain mistyped GSTINs.
CREATE TABLE book_invoices (
    id                    INTEGER PRIMARY KEY,
    client_id             TEXT NOT NULL REFERENCES clients (client_id),
    period                TEXT NOT NULL,
    voucher_date          TEXT NOT NULL,
    voucher_no            TEXT NOT NULL,
    supplier_invoice_no   TEXT NOT NULL,
    supplier_invoice_date TEXT NOT NULL,
    supplier_name         TEXT NOT NULL,
    supplier_gstin        TEXT NOT NULL,
    place_of_supply       TEXT NOT NULL,
    hsn                   TEXT NOT NULL,{_MONEY_COLUMNS}
);
CREATE INDEX idx_book_invoices_client_period ON book_invoices (client_id, period);

CREATE TABLE twob_entries (
    id                     INTEGER PRIMARY KEY,
    client_id              TEXT NOT NULL REFERENCES clients (client_id),
    period                 TEXT NOT NULL,
    supplier_gstin         TEXT NOT NULL,
    supplier_name          TEXT NOT NULL,
    supplier_period        TEXT NOT NULL,
    supplier_filing_date   TEXT,
    invoice_no             TEXT NOT NULL,
    invoice_date           TEXT NOT NULL,
    place_of_supply        TEXT NOT NULL,
    itc_available          INTEGER NOT NULL CHECK (itc_available IN (0, 1)),
    itc_unavailable_reason TEXT,{_MONEY_COLUMNS}
);
CREATE INDEX idx_twob_entries_client_period ON twob_entries (client_id, period);

CREATE TABLE runs (
    id          TEXT PRIMARY KEY,
    client_id   TEXT NOT NULL REFERENCES clients (client_id),
    period      TEXT NOT NULL,
    memory_on   INTEGER NOT NULL CHECK (memory_on IN (0, 1)),
    status      TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed')),
    progress    TEXT NOT NULL DEFAULT '{{}}' {_json("progress")},
    summary     TEXT NOT NULL DEFAULT '{{}}' {_json("summary")},
    error       TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT
);

-- An open MISSING_IN_2B exception is closed when its invoice arrives late.
CREATE TABLE exceptions (
    id                      INTEGER PRIMARY KEY,
    run_id                  TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    client_id               TEXT NOT NULL REFERENCES clients (client_id),
    period                  TEXT NOT NULL,
    type                    TEXT NOT NULL {_one_of("type", ExceptionType)},
    vendor_gstin            TEXT NOT NULL,
    group_key               TEXT NOT NULL,
    book_invoice_id         INTEGER REFERENCES book_invoices (id),
    twob_entry_id           INTEGER REFERENCES twob_entries (id),
    itc_at_risk_paise       INTEGER NOT NULL CHECK (itc_at_risk_paise >= 0),
    details                 TEXT NOT NULL DEFAULT '{{}}' {_json("details")},
    closed_in_period        TEXT,
    closed_by_twob_entry_id INTEGER REFERENCES twob_entries (id),
    CHECK (book_invoice_id IS NOT NULL OR twob_entry_id IS NOT NULL)
);
CREATE INDEX idx_exceptions_group ON exceptions (group_key);
CREATE INDEX idx_exceptions_client_period ON exceptions (client_id, period);

CREATE TABLE suggestions (
    id                INTEGER PRIMARY KEY,
    run_id            TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    group_key         TEXT NOT NULL,
    memory_on         INTEGER NOT NULL CHECK (memory_on IN (0, 1)),
    action            TEXT NOT NULL {_one_of("action", Action)},
    root_cause        TEXT NOT NULL {_one_of("root_cause", RootCause)},
    flags             TEXT NOT NULL DEFAULT '[]' {_json("flags")},
    llm_confidence    REAL NOT NULL CHECK (llm_confidence BETWEEN 0 AND 1),
    final_confidence  REAL NOT NULL CHECK (final_confidence BETWEEN 0 AND 1),
    reasoning         TEXT NOT NULL,
    cited_memory_ids  TEXT NOT NULL DEFAULT '[]' {_json("cited_memory_ids")},
    vendor_message    TEXT,
    guardrail_events  TEXT NOT NULL DEFAULT '[]' {_json("guardrail_events")},
    model             TEXT NOT NULL,
    latency_ms        INTEGER NOT NULL,
    prompt_tokens     INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    raw_output        TEXT,
    created_at        TEXT NOT NULL
);
CREATE INDEX idx_suggestions_group ON suggestions (group_key);

-- Append-only. Re-deciding (or undoing an AUTO decision) supersedes the old
-- row instead of overwriting it, so trust can see undone automatic decisions.
CREATE TABLE decisions (
    id               INTEGER PRIMARY KEY,
    group_key        TEXT NOT NULL,
    client_id        TEXT NOT NULL REFERENCES clients (client_id),
    period           TEXT NOT NULL,
    vendor_gstin     TEXT NOT NULL,
    exception_type   TEXT NOT NULL {_one_of("exception_type", ExceptionType)},
    suggested_action TEXT {_one_of("suggested_action", Action)},
    final_action     TEXT NOT NULL {_one_of("final_action", Action)},
    decided_by       TEXT NOT NULL {_one_of("decided_by", DecidedBy)},
    note             TEXT,
    decided_at       TEXT NOT NULL,
    superseded_at    TEXT
);
CREATE UNIQUE INDEX idx_decisions_current ON decisions (group_key) WHERE superseded_at IS NULL;
CREATE INDEX idx_decisions_pattern ON decisions (vendor_gstin, exception_type);

CREATE TABLE outcomes (
    id                INTEGER PRIMARY KEY,
    decision_id       INTEGER NOT NULL UNIQUE REFERENCES decisions (id),
    status            TEXT NOT NULL {_one_of("status", OutcomeStatus)},
    checked_in_period TEXT NOT NULL,
    evidence          TEXT NOT NULL DEFAULT '{{}}' {_json("evidence")},
    created_at        TEXT NOT NULL
);

-- Trust is recomputed from history on every run (SPEC-06 §5); this is a snapshot.
CREATE TABLE trust (
    run_id         TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    vendor_gstin   TEXT NOT NULL,
    exception_type TEXT NOT NULL {_one_of("exception_type", ExceptionType)},
    level          INTEGER NOT NULL CHECK (level IN ({_TRUST_LEVELS})),
    streak_action  TEXT {_one_of("streak_action", Action)},
    streak         INTEGER NOT NULL,
    correct        INTEGER NOT NULL,
    wrong          INTEGER NOT NULL,
    PRIMARY KEY (run_id, vendor_gstin, exception_type)
);

CREATE TABLE drift_events (
    id                 INTEGER PRIMARY KEY,
    vendor_gstin       TEXT NOT NULL,
    detected_in_period TEXT NOT NULL,
    evidence           TEXT NOT NULL {_json("evidence")},
    created_at         TEXT NOT NULL,
    UNIQUE (vendor_gstin, detected_in_period)
);

-- Every retain / recall / reflect, shown live in the UI (SPEC-04 §9).
CREATE TABLE memory_events (
    id           INTEGER PRIMARY KEY,
    ts           TEXT NOT NULL,
    op           TEXT NOT NULL CHECK (op IN ('retain', 'recall', 'reflect')),
    bank_id      TEXT NOT NULL,
    kind         TEXT,
    summary      TEXT NOT NULL,
    result_count INTEGER,
    latency_ms   INTEGER,
    ok           INTEGER NOT NULL CHECK (ok IN (0, 1)),
    error        TEXT
);

-- Retains that failed while Hindsight was down, replayed later (SPEC-04 §13).
CREATE TABLE retain_queue (
    id          INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL UNIQUE,
    payload     TEXT NOT NULL {_json("payload")},
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    created_at  TEXT NOT NULL
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a connection with foreign keys on and rows accessible by column name.

    Pass ":memory:" for an in-memory database (tests).
    """
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the schema in an empty database, or check an existing one's version."""
    version: int = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    if version != 0:
        raise SchemaVersionError(
            f"database schema is v{version}, code expects v{SCHEMA_VERSION}; "
            "delete the database file or reset the demo to rebuild it"
        )
    # One transaction: either the whole schema and its version exist, or nothing does.
    conn.executescript(f"BEGIN;\n{SCHEMA}\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;")

"""Reads and writes of the SQLite database (SPEC-01 §8) for the run flow.

The only module besides `db.py` that writes SQL. Rows go in and come out as
domain entities; money crosses the boundary as paise, dates as ISO text.
Every write commits on its own, so a crashed run leaves what it finished.
"""

import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from backend.app.agent import Suggestion
from backend.app.domain.entities import (
    BookInvoice,
    Client,
    Decision,
    Firm,
    GroupKey,
    Outcome,
    ReconException,
    TwoBEntry,
    Vendor,
)
from backend.app.domain.enums import (
    Action,
    DecidedBy,
    ExceptionType,
    OutcomeStatus,
    TrustLevel,
)
from backend.app.domain.money import from_paise, to_paise
from backend.app.learning import TrackedInvoice, Trust
from backend.app.matcher import Detail, ExceptionGroup, group_exceptions
from backend.app.memory import MemoryRecord

MONEY_FIELDS = ("taxable_value", "cgst", "sgst", "igst", "cess", "total")


class StoreError(LookupError):
    """A row the caller relies on does not exist."""


@dataclass(frozen=True)
class RunRow:
    id: str
    client_id: str
    period: str
    memory_on: bool
    status: str
    progress: dict[str, Any]
    summary: dict[str, Any]
    error: str | None
    started_at: str
    finished_at: str | None


@dataclass(frozen=True)
class PendingCheck:
    """A past decision the self-check has not settled yet (SPEC-06 §4)."""

    decision: Decision
    outcome: Outcome | None
    """Set only for a VERIFIED_WRONG verdict whose invoices had not arrived (§9)."""


@dataclass(frozen=True)
class DriftEvent:
    vendor_gstin: str
    period: str
    evidence: dict[str, Any]


@dataclass(frozen=True)
class TrustRow:
    vendor_gstin: str
    exception_type: ExceptionType
    period: str
    trust: Trust


@dataclass(frozen=True)
class StoredSuggestion:
    """A suggestion as the UI shows it, with the memories it cited."""

    group_key: str
    memory_on: bool
    action: Action
    root_cause: str
    flags: list[str]
    final_confidence: float
    reasoning: str
    vendor_message: str | None
    cited_memories: list[dict[str, Any]]
    guardrail_events: list[dict[str, Any]]
    model: str


class Store:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # --- Firm, clients, vendors, uploaded data ---

    def has_data(self) -> bool:
        return self.conn.execute("SELECT 1 FROM firms").fetchone() is not None

    def add_firm(self, firm: Firm, clients: Iterable[Client]) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO firms VALUES (?, ?)", (firm.firm_id, firm.name))
            self.conn.executemany(
                "INSERT INTO clients VALUES (?, ?, ?, ?, ?)",
                [(c.client_id, firm.firm_id, c.name, c.gstin, c.business_type) for c in clients],
            )

    def add_vendors(self, vendors: Iterable[Vendor]) -> None:
        with self.conn:
            self.conn.executemany(
                "INSERT INTO vendors VALUES (?, ?, ?)",
                [(v.gstin, v.name, v.registration_status.value) for v in vendors],
            )

    def add_books(self, invoices: Iterable[BookInvoice]) -> None:
        self._insert_rows("book_invoices", invoices)

    def add_twob(self, entries: Iterable[TwoBEntry]) -> None:
        self._insert_rows("twob_entries", entries)

    def _insert_rows(self, table: str, rows: Iterable[BookInvoice | TwoBEntry]) -> None:
        values = [_to_row(row) for row in rows]
        if not values:
            return
        columns = list(values[0])
        placeholders = ", ".join("?" for _ in columns)
        with self.conn:
            self.conn.executemany(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                [tuple(v.values()) for v in values],
            )

    def firm(self) -> Firm:
        row = self.conn.execute("SELECT firm_id, name FROM firms").fetchone()
        if row is None:
            raise StoreError("no firm loaded")
        return Firm(firm_id=row["firm_id"], name=row["name"])

    def clients(self) -> list[Client]:
        rows = self.conn.execute(
            "SELECT client_id, name, gstin, business_type FROM clients ORDER BY client_id"
        )
        return [Client(**dict(row)) for row in rows]

    def client(self, client_id: str) -> Client:
        for client in self.clients():
            if client.client_id == client_id:
                return client
        raise StoreError(f"no client {client_id}")

    def vendor(self, gstin: str) -> Vendor | None:
        row = self.conn.execute(
            "SELECT gstin, name, registration_status FROM vendors WHERE gstin = ?", (gstin,)
        ).fetchone()
        return None if row is None else Vendor(**dict(row))

    def periods(self, client_id: str) -> list[str]:
        """Periods with uploaded data for a client, oldest first."""
        rows = self.conn.execute(
            """
            SELECT period FROM book_invoices WHERE client_id = ?
            UNION SELECT period FROM twob_entries WHERE client_id = ?
            ORDER BY period
            """,
            (client_id, client_id),
        )
        return [row["period"] for row in rows]

    def upload_counts(self, client_id: str) -> dict[str, tuple[int, int]]:
        """Rows uploaded per period: (purchase register, GSTR-2B)."""
        counts: dict[str, tuple[int, int]] = {}
        for index, table in enumerate(("book_invoices", "twob_entries")):
            rows = self.conn.execute(
                f"SELECT period, COUNT(*) AS n FROM {table} WHERE client_id = ? GROUP BY period",
                (client_id,),
            )
            for row in rows:
                pair = list(counts.get(row["period"], (0, 0)))
                pair[index] = row["n"]
                counts[row["period"]] = (pair[0], pair[1])
        return dict(sorted(counts.items()))

    def books(self, client_id: str, period: str) -> list[BookInvoice]:
        rows = self.conn.execute(
            "SELECT * FROM book_invoices WHERE client_id = ? AND period = ? ORDER BY id",
            (client_id, period),
        )
        return [BookInvoice(**_from_row(row)) for row in rows]

    def twob(self, client_id: str, period: str) -> list[TwoBEntry]:
        rows = self.conn.execute(
            "SELECT * FROM twob_entries WHERE client_id = ? AND period = ? ORDER BY id",
            (client_id, period),
        )
        return [TwoBEntry(**_from_row(row)) for row in rows]

    # --- Runs ---

    def create_run(
        self, run_id: str, client_id: str, period: str, memory_on: bool, started_at: datetime
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO runs (id, client_id, period, memory_on, status, started_at)"
                " VALUES (?, ?, ?, ?, 'running', ?)",
                (run_id, client_id, period, int(memory_on), _iso(started_at)),
            )

    def set_progress(self, run_id: str, progress: dict[str, Any]) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET progress = ? WHERE id = ?", (json.dumps(progress), run_id)
            )

    def finish_run(self, run_id: str, summary: dict[str, Any], finished_at: datetime) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET status = 'done', summary = ?, finished_at = ? WHERE id = ?",
                (json.dumps(summary), _iso(finished_at), run_id),
            )

    def fail_run(self, run_id: str, error: str, finished_at: datetime) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
                (error, _iso(finished_at), run_id),
            )

    def run(self, run_id: str) -> RunRow:
        row = self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise StoreError(f"no run {run_id}")
        return _run_row(row)

    def latest_run(self, client_id: str, period: str) -> RunRow | None:
        row = self.conn.execute(
            "SELECT * FROM runs WHERE client_id = ? AND period = ?"
            " ORDER BY started_at DESC, rowid DESC LIMIT 1",
            (client_id, period),
        ).fetchone()
        return None if row is None else _run_row(row)

    def last_run_period(self, client_id: str) -> str | None:
        """The latest period this client has been run for (any status)."""
        row = self.conn.execute(
            "SELECT MAX(period) AS period FROM runs WHERE client_id = ?", (client_id,)
        ).fetchone()
        period: str | None = row["period"]
        return period

    def last_run_period_any(self) -> str | None:
        """The latest period any client has run."""
        row = self.conn.execute("SELECT MAX(period) AS period FROM runs").fetchone()
        period: str | None = row["period"]
        return period

    def processed_through(self) -> dict[str, str]:
        """Per client, the latest period whose 2B has been matched (runs in progress count)."""
        rows = self.conn.execute(
            "SELECT client_id, MAX(period) AS period FROM runs"
            " WHERE status IN ('running', 'done') GROUP BY client_id"
        )
        return {row["client_id"]: row["period"] for row in rows}

    def discard_runs(self, client_id: str, period: str) -> None:
        """Before a re-run: drop the period's runs (their exceptions, suggestions and
        trust snapshots cascade) and reopen invoices that period's 2B had closed.
        Decisions, outcomes and drift events are history and stay."""
        with self.conn:
            self.conn.execute(
                "UPDATE exceptions SET closed_in_period = NULL, closed_by_twob_entry_id = NULL"
                " WHERE client_id = ? AND closed_in_period = ?",
                (client_id, period),
            )
            self.conn.execute(
                "DELETE FROM runs WHERE client_id = ? AND period = ?", (client_id, period)
            )

    # --- Exceptions ---

    def add_exceptions(
        self, run_id: str, exceptions: Sequence[ReconException]
    ) -> list[ReconException]:
        """Store a run's exceptions; returns them with their ids."""
        stored = []
        with self.conn:
            for e in exceptions:
                cursor = self.conn.execute(
                    """
                    INSERT INTO exceptions (run_id, client_id, period, type, vendor_gstin,
                        group_key, book_invoice_id, twob_entry_id, itc_at_risk_paise, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        e.client_id,
                        e.period,
                        e.type.value,
                        e.vendor_gstin,
                        str(e.group_key),
                        e.book_invoice_id,
                        e.twob_entry_id,
                        to_paise(e.itc_at_risk),
                        json.dumps(e.details),
                    ),
                )
                stored.append(e.model_copy(update={"id": cursor.lastrowid}))
        return stored

    def close_exception(self, exception_id: int, period: str, twob_entry_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE exceptions SET closed_in_period = ?, closed_by_twob_entry_id = ?"
                " WHERE id = ?",
                (period, twob_entry_id, exception_id),
            )

    def open_missing(self, client_id: str, before: str) -> list[ReconException]:
        """MISSING_IN_2B invoices from earlier periods that no 2B has shown yet."""
        rows = self.conn.execute(
            "SELECT * FROM exceptions WHERE client_id = ? AND period < ? AND type = ?"
            " AND closed_in_period IS NULL ORDER BY id",
            (client_id, before, ExceptionType.MISSING_IN_2B.value),
        )
        return [_exception(row) for row in rows]

    def group(self, key: GroupKey) -> ExceptionGroup | None:
        rows = self.conn.execute(
            "SELECT * FROM exceptions WHERE group_key = ? ORDER BY id", (str(key),)
        ).fetchall()
        if not rows:
            return None
        (group,) = group_exceptions(_exception(row) for row in rows)
        return group

    def groups(self, run_id: str) -> list[ExceptionGroup]:
        rows = self.conn.execute("SELECT * FROM exceptions WHERE run_id = ? ORDER BY id", (run_id,))
        return group_exceptions(_exception(row) for row in rows)

    def tracked(self, vendor_gstin: str | None = None) -> list[TrackedInvoice]:
        """Every MISSING_IN_2B invoice (firm-wide), with its late arrival if any."""
        query = """
            SELECT e.client_id, e.vendor_gstin, e.period, e.details, e.closed_in_period,
                   t.supplier_filing_date
            FROM exceptions e LEFT JOIN twob_entries t ON t.id = e.closed_by_twob_entry_id
            WHERE e.type = ?
        """
        params: list[str] = [ExceptionType.MISSING_IN_2B.value]
        if vendor_gstin is not None:
            query += " AND e.vendor_gstin = ?"
            params.append(vendor_gstin)
        rows = self.conn.execute(query + " ORDER BY e.id", params)
        tracked = []
        for row in rows:
            details = json.loads(row["details"])
            filed = row["supplier_filing_date"]
            tracked.append(
                TrackedInvoice(
                    client_id=row["client_id"],
                    vendor_gstin=row["vendor_gstin"],
                    invoice_no=details[Detail.INVOICE_NO],
                    invoice_date=date.fromisoformat(details[Detail.INVOICE_DATE]),
                    period=row["period"],
                    arrived_in=row["closed_in_period"],
                    filed_on=date.fromisoformat(filed) if filed else None,
                )
            )
        return tracked

    # --- Suggestions ---

    def add_suggestion(
        self,
        run_id: str,
        s: Suggestion,
        created_at: datetime,
        memories: Sequence[MemoryRecord] = (),
    ) -> None:
        """Store a suggestion with the text of the memories it cites."""
        cited = [m for m in memories if m.id in s.cited_memory_ids]
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO suggestions (run_id, group_key, memory_on, action, root_cause, flags,
                    llm_confidence, final_confidence, reasoning, cited_memory_ids, cited_memories,
                    vendor_message, guardrail_events, model, latency_ms, prompt_tokens,
                    completion_tokens, raw_output, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    str(s.group_key),
                    int(s.memory_on),
                    s.action.value,
                    s.root_cause.value,
                    json.dumps([f.value for f in s.flags]),
                    s.llm_confidence,
                    s.final_confidence,
                    s.reasoning,
                    json.dumps(list(s.cited_memory_ids)),
                    json.dumps([m.model_dump(mode="json") for m in cited]),
                    s.vendor_message,
                    json.dumps([e.model_dump(mode="json") for e in s.guardrail_events]),
                    s.model,
                    s.latency_ms,
                    s.prompt_tokens,
                    s.completion_tokens,
                    s.raw_output,
                    _iso(created_at),
                ),
            )

    def suggested_action(self, key: GroupKey) -> Action | None:
        row = self.conn.execute(
            "SELECT action FROM suggestions WHERE group_key = ? ORDER BY id DESC LIMIT 1",
            (str(key),),
        ).fetchone()
        return None if row is None else Action(row["action"])

    # --- Decisions ---

    def current_decision(self, key: GroupKey) -> Decision | None:
        row = self.conn.execute(
            "SELECT * FROM decisions WHERE group_key = ? AND superseded_at IS NULL", (str(key),)
        ).fetchone()
        return None if row is None else _decision(row)

    def add_decision(self, decision: Decision) -> Decision:
        """Insert as the group's current decision, superseding the previous one."""
        key = decision.group_key
        with self.conn:
            self.conn.execute(
                "UPDATE decisions SET superseded_at = ?"
                " WHERE group_key = ? AND superseded_at IS NULL",
                (_iso(decision.decided_at), str(key)),
            )
            cursor = self.conn.execute(
                """
                INSERT INTO decisions (group_key, client_id, period, vendor_gstin, exception_type,
                    suggested_action, final_action, decided_by, note, decided_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(key),
                    key.client_id,
                    key.period,
                    key.vendor_gstin,
                    key.exception_type.value,
                    decision.suggested_action.value if decision.suggested_action else None,
                    decision.final_action.value,
                    decision.decided_by.value,
                    decision.note,
                    _iso(decision.decided_at),
                ),
            )
        return decision.model_copy(update={"id": cursor.lastrowid})

    def pattern_actions(
        self, vendor_gstin: str, exception_type: ExceptionType, before: str
    ) -> list[Action]:
        """Final actions of a pattern's current decisions before `before`, oldest first."""
        rows = self.conn.execute(
            "SELECT final_action FROM decisions WHERE vendor_gstin = ? AND exception_type = ?"
            " AND period < ? AND superseded_at IS NULL ORDER BY period, id",
            (vendor_gstin, exception_type.value, before),
        )
        return [Action(row["final_action"]) for row in rows]

    def pattern_verdicts(
        self, vendor_gstin: str, exception_type: ExceptionType, through: str
    ) -> list[OutcomeStatus]:
        """CORRECT / WRONG verdicts on a pattern's current decisions, oldest first."""
        rows = self.conn.execute(
            """
            SELECT o.status FROM outcomes o JOIN decisions d ON d.id = o.decision_id
            WHERE d.vendor_gstin = ? AND d.exception_type = ? AND d.superseded_at IS NULL
              AND o.checked_in_period <= ? AND o.status IN (?, ?)
            ORDER BY o.checked_in_period, o.id
            """,
            (
                vendor_gstin,
                exception_type.value,
                through,
                OutcomeStatus.VERIFIED_CORRECT.value,
                OutcomeStatus.VERIFIED_WRONG.value,
            ),
        )
        return [OutcomeStatus(row["status"]) for row in rows]

    def undone(
        self, vendor_gstin: str, exception_type: ExceptionType, periods: Sequence[str]
    ) -> bool:
        """Whether an AUTO decision of the pattern in these periods was replaced by another."""
        marks = ", ".join("?" for _ in periods)
        row = self.conn.execute(
            f"""
            SELECT 1 FROM decisions old JOIN decisions new
              ON new.group_key = old.group_key AND new.superseded_at IS NULL
            WHERE old.vendor_gstin = ? AND old.exception_type = ? AND old.period IN ({marks})
              AND old.decided_by = ? AND old.superseded_at IS NOT NULL
              AND new.final_action != old.final_action
            """,
            (vendor_gstin, exception_type.value, *periods, DecidedBy.AUTO.value),
        ).fetchone()
        return row is not None

    # --- Outcomes ---

    def pending_checks(self, client_id: str, before: str) -> list[PendingCheck]:
        """The client's current MISSING_IN_2B decisions still waiting for the self-check:
        no verdict yet, or a WRONG one whose invoices had not arrived (§9)."""
        rows = self.conn.execute(
            """
            SELECT d.*, o.decision_id, o.status, o.checked_in_period, o.evidence
            FROM decisions d LEFT JOIN outcomes o ON o.decision_id = d.id
            WHERE d.client_id = ? AND d.period < ? AND d.exception_type = ?
              AND d.superseded_at IS NULL
              AND (o.id IS NULL
                   OR (o.status = ? AND json_extract(o.evidence, '$.arrived_in') IS NULL))
            ORDER BY d.period, d.id
            """,
            (
                client_id,
                before,
                ExceptionType.MISSING_IN_2B.value,
                OutcomeStatus.VERIFIED_WRONG.value,
            ),
        )
        checks = []
        for row in rows:
            outcome = None
            if row["decision_id"] is not None:
                outcome = Outcome(
                    decision_id=row["decision_id"],
                    status=OutcomeStatus(row["status"]),
                    checked_in_period=row["checked_in_period"],
                    evidence=json.loads(row["evidence"]),
                )
            checks.append(PendingCheck(_decision(row), outcome))
        return checks

    def add_outcome(self, outcome: Outcome, created_at: datetime) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO outcomes (decision_id, status, checked_in_period, evidence,"
                " created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    outcome.decision_id,
                    outcome.status.value,
                    outcome.checked_in_period,
                    json.dumps(outcome.evidence),
                    _iso(created_at),
                ),
            )

    def update_outcome_evidence(self, decision_id: int, evidence: dict[str, Any]) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE outcomes SET evidence = ? WHERE decision_id = ?",
                (json.dumps(evidence), decision_id),
            )

    def outcomes(self) -> list[tuple[GroupKey, Outcome]]:
        rows = self.conn.execute(
            "SELECT d.group_key, o.* FROM outcomes o JOIN decisions d ON d.id = o.decision_id"
            " ORDER BY o.id"
        )
        return [(GroupKey.model_validate(row["group_key"]), _outcome(row)) for row in rows]

    # --- Trust and drift ---

    def add_trust(
        self, run_id: str, vendor_gstin: str, exception_type: ExceptionType, trust: Trust
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO trust VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    vendor_gstin,
                    exception_type.value,
                    trust.level.value,
                    trust.streak_action.value if trust.streak_action else None,
                    trust.streak,
                    trust.correct,
                    trust.wrong,
                ),
            )

    def add_drift(
        self, vendor_gstin: str, period: str, evidence: dict[str, Any], created_at: datetime
    ) -> bool:
        """Record drift once per vendor and period; False if it was already recorded."""
        with self.conn:
            cursor = self.conn.execute(
                "INSERT OR IGNORE INTO drift_events"
                " (vendor_gstin, detected_in_period, evidence, created_at) VALUES (?, ?, ?, ?)",
                (vendor_gstin, period, json.dumps(evidence), _iso(created_at)),
            )
        return cursor.rowcount == 1

    def drift_detected(self, vendor_gstin: str, period: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM drift_events WHERE vendor_gstin = ? AND detected_in_period = ?",
            (vendor_gstin, period),
        ).fetchone()
        return row is not None

    def drift_events(self, vendor_gstin: str | None = None) -> list[DriftEvent]:
        query = "SELECT * FROM drift_events"
        params: list[str] = []
        if vendor_gstin is not None:
            query += " WHERE vendor_gstin = ?"
            params.append(vendor_gstin)
        rows = self.conn.execute(f"{query} ORDER BY detected_in_period, vendor_gstin", params)
        return [
            DriftEvent(row["vendor_gstin"], row["detected_in_period"], json.loads(row["evidence"]))
            for row in rows
        ]

    # --- Views for the API (SPEC-07) ---

    def fail_stale_runs(self, error: str, finished_at: datetime) -> int:
        """At startup: runs still `running` were cut off by a restart."""
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE runs SET status = 'failed', error = ?, finished_at = ?"
                " WHERE status = 'running'",
                (error, _iso(finished_at)),
            )
        return cursor.rowcount

    def running(self, client_id: str | None = None) -> list[RunRow]:
        query = "SELECT * FROM runs WHERE status = 'running'"
        params: list[str] = []
        if client_id is not None:
            query += " AND client_id = ?"
            params.append(client_id)
        return [_run_row(row) for row in self.conn.execute(f"{query} ORDER BY started_at", params)]

    def has_decisions(self, client_id: str, period: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM decisions WHERE client_id = ? AND period = ?", (client_id, period)
        ).fetchone()
        return row is not None

    def replace_period(
        self,
        client_id: str,
        period: str,
        books: Sequence[BookInvoice],
        twob: Sequence[TwoBEntry],
    ) -> None:
        """Swap a client-period's uploaded files. The caller discards its runs first."""
        with self.conn:
            for table in ("book_invoices", "twob_entries"):
                self.conn.execute(
                    f"DELETE FROM {table} WHERE client_id = ? AND period = ?", (client_id, period)
                )
        self.add_books(books)
        self.add_twob(twob)

    def suggestions(self, run_id: str) -> dict[str, StoredSuggestion]:
        """A run's suggestions by group key."""
        rows = self.conn.execute(
            "SELECT * FROM suggestions WHERE run_id = ? ORDER BY id", (run_id,)
        )
        return {row["group_key"]: _suggestion(row) for row in rows}

    def trust_snapshot(self, run_id: str) -> dict[tuple[str, ExceptionType], Trust]:
        rows = self.conn.execute("SELECT * FROM trust WHERE run_id = ?", (run_id,))
        return {
            (row["vendor_gstin"], ExceptionType(row["exception_type"])): _trust(row) for row in rows
        }

    def latest_trust(self) -> list[TrustRow]:
        """Each pattern's trust as of its most recent run."""
        rows = self.conn.execute(
            "SELECT t.*, r.period FROM trust t JOIN runs r ON r.id = t.run_id"
            " ORDER BY r.period, r.started_at, r.rowid"
        )
        latest: dict[tuple[str, str], TrustRow] = {}
        for row in rows:
            latest[(row["vendor_gstin"], row["exception_type"])] = TrustRow(
                row["vendor_gstin"],
                ExceptionType(row["exception_type"]),
                row["period"],
                _trust(row),
            )
        return sorted(latest.values(), key=lambda t: (t.vendor_gstin, t.exception_type))

    def decisions(
        self,
        *,
        vendor_gstin: str | None = None,
        client_id: str | None = None,
        period: str | None = None,
    ) -> list[Decision]:
        """Current decisions, oldest period first."""
        conditions, params = ["superseded_at IS NULL"], []
        for column, value in (
            ("vendor_gstin", vendor_gstin),
            ("client_id", client_id),
            ("period", period),
        ):
            if value is not None:
                conditions.append(f"{column} = ?")
                params.append(value)
        rows = self.conn.execute(
            f"SELECT * FROM decisions WHERE {' AND '.join(conditions)}"
            " ORDER BY period, client_id, id",
            params,
        )
        return [_decision(row) for row in rows]

    def outcome(self, decision_id: int) -> Outcome | None:
        row = self.conn.execute(
            "SELECT * FROM outcomes WHERE decision_id = ?", (decision_id,)
        ).fetchone()
        return None if row is None else _outcome(row)

    def memory_events(
        self, since: int = 0, limit: int = 50, *, latest: bool = False
    ) -> list[dict[str, Any]]:
        order = "DESC" if latest else "ASC"
        rows = self.conn.execute(
            f"SELECT * FROM memory_events WHERE id > ? ORDER BY id {order} LIMIT ?", (since, limit)
        ).fetchall()
        events = [{**dict(row), "ok": bool(row["ok"])} for row in rows]
        return events[::-1] if latest else events

    def wipe(self) -> None:
        """Delete every row, keeping the schema (demo reset)."""
        tables = [
            row["name"]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        with self.conn:
            self.conn.execute("PRAGMA defer_foreign_keys = ON")
            for table in tables:
                self.conn.execute(f"DELETE FROM {table}")


# --- Row conversion ----------------------------------------------------------


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _to_row(entity: BookInvoice | TwoBEntry) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for name, value in entity.model_dump(exclude={"id"}).items():
        if name in MONEY_FIELDS:
            row[f"{name}_paise"] = to_paise(value)
        elif isinstance(value, date):
            row[name] = value.isoformat()
        elif isinstance(value, bool):
            row[name] = int(value)
        else:
            row[name] = value
    return row


def _from_row(row: sqlite3.Row) -> dict[str, Any]:
    """Column values for the entity constructor; pydantic parses ISO dates and 0/1."""
    values = dict(row)
    for name in MONEY_FIELDS:
        values[name] = from_paise(values.pop(f"{name}_paise"))
    return values


def _exception(row: sqlite3.Row) -> ReconException:
    return ReconException(
        id=row["id"],
        client_id=row["client_id"],
        period=row["period"],
        type=ExceptionType(row["type"]),
        vendor_gstin=row["vendor_gstin"],
        book_invoice_id=row["book_invoice_id"],
        twob_entry_id=row["twob_entry_id"],
        itc_at_risk=from_paise(row["itc_at_risk_paise"]),
        details=json.loads(row["details"]),
    )


def _decision(row: sqlite3.Row) -> Decision:
    return Decision(
        id=row["id"],
        group_key=GroupKey.model_validate(row["group_key"]),
        suggested_action=row["suggested_action"],
        final_action=row["final_action"],
        decided_by=row["decided_by"],
        note=row["note"],
        decided_at=row["decided_at"],
    )


def _suggestion(row: sqlite3.Row) -> StoredSuggestion:
    return StoredSuggestion(
        group_key=row["group_key"],
        memory_on=bool(row["memory_on"]),
        action=Action(row["action"]),
        root_cause=row["root_cause"],
        flags=json.loads(row["flags"]),
        final_confidence=row["final_confidence"],
        reasoning=row["reasoning"],
        vendor_message=row["vendor_message"],
        cited_memories=json.loads(row["cited_memories"]),
        guardrail_events=json.loads(row["guardrail_events"]),
        model=row["model"],
    )


def _trust(row: sqlite3.Row) -> Trust:
    return Trust(
        level=TrustLevel(row["level"]),
        streak_action=Action(row["streak_action"]) if row["streak_action"] else None,
        streak=row["streak"],
        correct=row["correct"],
        wrong=row["wrong"],
    )


def _outcome(row: sqlite3.Row) -> Outcome:
    return Outcome(
        decision_id=row["decision_id"],
        status=OutcomeStatus(row["status"]),
        checked_in_period=row["checked_in_period"],
        evidence=json.loads(row["evidence"]),
    )


def _run_row(row: sqlite3.Row) -> RunRow:
    return RunRow(
        id=row["id"],
        client_id=row["client_id"],
        period=row["period"],
        memory_on=bool(row["memory_on"]),
        status=row["status"],
        progress=json.loads(row["progress"]),
        summary=json.loads(row["summary"]),
        error=row["error"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )

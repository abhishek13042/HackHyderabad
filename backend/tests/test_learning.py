"""SPEC-06 §4 to §6: the pure rules of self-check, trust and drift."""

from datetime import date

import pytest

from backend.app.domain.enums import Action, ExceptionType, OutcomeStatus, TrustLevel
from backend.app.learning import (
    TrackedInvoice,
    arrival_after_wrong,
    detect_drift,
    expected_lag,
    trust,
    verify,
)

MISSING = ExceptionType.MISSING_IN_2B
CORRECT, WRONG = OutcomeStatus.VERIFIED_CORRECT, OutcomeStatus.VERIFIED_WRONG
VENDOR = "36AABCR1234F1ZT"


def invoice(
    period: str,
    arrived_in: str | None = None,
    *,
    no: str = "RS/1",
    client: str = "C01",
    day: int = 10,
    filed_on: date | None = None,
) -> TrackedInvoice:
    year, month = map(int, period.split("-"))
    return TrackedInvoice(client, VENDOR, no, date(year, month, day), period, arrived_in, filed_on)


# --- Invoices ----------------------------------------------------------------


def test_lateness_of_an_arrival() -> None:
    late = invoice("2026-01", "2026-02", filed_on=date(2026, 2, 24))
    assert (late.months_late, late.days_late) == (1, 45)
    unfiled = invoice("2026-01", "2026-02")  # no filing date: end of the arrival month
    assert unfiled.days_late == 49
    assert invoice("2026-01").months_late is None and invoice("2026-01").days_late is None


def test_expected_lag_is_the_median_and_at_least_a_month() -> None:
    assert expected_lag([]) == 1
    assert expected_lag([invoice("2026-01")]) == 1  # never arrived: no evidence
    arrivals = [invoice("2026-01", "2026-02"), invoice("2026-01", "2026-03"),
                invoice("2026-02", "2026-04")]  # fmt: skip
    assert expected_lag(arrivals) == 2


# --- Self-check (§4) ---------------------------------------------------------


def test_defer_is_correct_when_the_invoices_arrive_on_time() -> None:
    invoices = [invoice("2026-02", "2026-03", no="A"), invoice("2026-02", "2026-03", no="B")]
    verdict = verify(Action.DEFER, MISSING, "2026-02", invoices, lag=1, period="2026-03")
    assert verdict is not None
    assert (verdict.status, verdict.due_in, verdict.arrived_in) == (CORRECT, "2026-03", "2026-03")
    assert verdict.invoice_nos == ("A", "B") and verdict.correct is True


def test_defer_is_wrong_once_the_expected_2b_came_without_them() -> None:
    invoices = [invoice("2026-03", "2026-04", no="A"), invoice("2026-03", no="B")]
    verdict = verify(Action.DEFER, MISSING, "2026-03", invoices, lag=1, period="2026-04")
    assert verdict is not None and verdict.status is WRONG and verdict.correct is False
    assert verdict.arrived_in is None and verdict.days_late is None


def test_defer_waits_until_its_due_period() -> None:
    invoices = [invoice("2026-03")]
    assert verify(Action.DEFER, MISSING, "2026-03", invoices, lag=2, period="2026-04") is None


def test_defer_arriving_after_the_due_period_is_wrong() -> None:
    invoices = [invoice("2026-02", "2026-04")]
    verdict = verify(Action.DEFER, MISSING, "2026-02", invoices, lag=1, period="2026-04")
    assert verdict is not None and verdict.status is WRONG and verdict.arrived_in == "2026-04"


@pytest.mark.parametrize("action", [Action.CHASE_VENDOR, Action.HOLD_PAYMENT, Action.ESCALATE])
def test_other_actions_only_record_the_arrival(action: Action) -> None:
    waiting = [invoice("2026-01")]
    assert verify(action, MISSING, "2026-01", waiting, lag=1, period="2026-04") is None
    arrived = [invoice("2026-01", "2026-02")]
    verdict = verify(action, MISSING, "2026-01", arrived, lag=1, period="2026-02")
    assert verdict is not None and verdict.status is OutcomeStatus.NOT_APPLICABLE
    assert verdict.correct is None and verdict.due_in is None


def test_other_exception_types_make_no_prediction() -> None:
    invoices = [invoice("2026-01", "2026-02")]
    for exception_type in set(ExceptionType) - {MISSING}:
        assert verify(Action.ACCEPT, exception_type, "2026-01", invoices, lag=1,
                      period="2026-02") is None  # fmt: skip


def test_a_very_late_arrival_keeps_the_wrong_verdict() -> None:
    assert arrival_after_wrong([invoice("2026-03")], "2026-04", "2026-05") is None
    verdict = arrival_after_wrong([invoice("2026-03", "2026-05")], "2026-04", "2026-05")
    assert verdict is not None and verdict.status is WRONG and verdict.arrived_in == "2026-05"


# --- Trust ladder (§5) -------------------------------------------------------

A, D, C = Action.ACCEPT, Action.DEFER, Action.CHASE_VENDOR


@pytest.mark.parametrize(
    ("exception_type", "actions", "verdicts", "level"),
    [
        (MISSING, [], [], TrustLevel.OBSERVE),
        (MISSING, [D], [], TrustLevel.OBSERVE),
        (MISSING, [C, D, D], [], TrustLevel.SUGGEST),
        (MISSING, [C, D, D], [CORRECT, CORRECT], TrustLevel.AUTO),  # Bhavani in April
        (MISSING, [C, D, D], [CORRECT, WRONG], TrustLevel.OBSERVE),  # Reddy in April
        (MISSING, [D, D, D], [], TrustLevel.AUTO),
        (MISSING, [D, C, D, C], [], TrustLevel.OBSERVE),  # overrides both ways: never AUTO
        (MISSING, [C, C, C, C], [], TrustLevel.SUGGEST),  # chasing is never automatic
        (MISSING, [D, D, D], [WRONG, CORRECT, CORRECT, CORRECT], TrustLevel.AUTO),  # old news
        (ExceptionType.AMOUNT_MISMATCH, [A, A, A, A], [], TrustLevel.AUTO),  # Laxmi in March
        (ExceptionType.TAX_HEAD_MISMATCH, [Action.CORRECT_BOOKS] * 5, [], TrustLevel.SUGGEST),
    ],
)
def test_trust_levels(
    exception_type: ExceptionType,
    actions: list[Action],
    verdicts: list[OutcomeStatus],
    level: TrustLevel,
) -> None:
    assert trust(exception_type, actions, verdicts).level is level


def test_trust_counts_the_streak_and_verdicts() -> None:
    t = trust(MISSING, [C, D, D], [CORRECT, WRONG, CORRECT])
    assert (t.streak_action, t.streak, t.correct, t.wrong) == (D, 2, 2, 1)


@pytest.mark.parametrize("flag", ["drift_active", "undone_recently"])
def test_drift_or_an_undo_drops_to_observe(flag: str) -> None:
    assert trust(MISSING, [D, D, D], [CORRECT] * 3, **{flag: True}).level is TrustLevel.OBSERVE


# --- Drift (§6) --------------------------------------------------------------

HISTORY = [invoice("2026-01", "2026-02", no="1"), invoice("2026-02", "2026-03", no="2")]


def test_drift_when_an_invoice_misses_its_usual_2b() -> None:
    overdue = invoice("2026-03", no="3", day=5)
    finding = detect_drift([*HISTORY, overdue], {"C01": "2026-04"}, "2026-04")
    assert finding is not None and finding.overdue == (overdue,)
    assert (finding.vendor_gstin, finding.lag_months) == (VENDOR, 1)
    assert finding.typical_lag_days == 49  # median of 49 (Jan 10 → Feb 28) and 49 (Feb 10 → Mar 31)
    assert finding.overdue_days == 56  # 5 March to 30 April


def test_no_drift_while_the_invoice_is_not_due() -> None:
    assert (
        detect_drift([*HISTORY, invoice("2026-03", no="3")], {"C01": "2026-03"}, "2026-03") is None
    )


def test_no_drift_on_a_single_arrival() -> None:
    invoices = [invoice("2026-01", "2026-02", no="1"), invoice("2026-02", no="2")]
    assert detect_drift(invoices, {"C01": "2026-04"}, "2026-04") is None


def test_drift_waits_for_the_other_clients_2b() -> None:
    elsewhere = invoice("2026-03", no="3", client="C02")
    invoices = [*HISTORY, elsewhere]
    assert detect_drift(invoices, {"C01": "2026-04", "C02": "2026-03"}, "2026-04") is None
    finding = detect_drift(invoices, {"C01": "2026-04", "C02": "2026-04"}, "2026-04")
    assert finding is not None and finding.overdue == (elsewhere,)

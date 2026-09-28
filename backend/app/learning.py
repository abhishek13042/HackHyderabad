"""The learning loop's rules (SPEC-06 §4 to §6): self-check, trust ladder, drift.

Pure functions over plain values: the pipeline loads history from SQLite and
passes it in, so every rule here is tested without a database or a model.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from statistics import median_low

from backend.app.domain.enums import Action, ExceptionType, OutcomeStatus, TrustLevel
from backend.app.domain.periods import add_months, last_day, months_between
from backend.app.domain.policy import can_auto_resolve

DEFAULT_LAG_MONTHS = 1
"""Before a vendor has a history, a deferred invoice is expected in the next 2B."""
MIN_ARRIVALS_FOR_DRIFT = 2
RECENT_VERDICTS = 3
AUTO_STREAK = 3
AUTO_STREAK_WITH_EVIDENCE = 2
AUTO_EVIDENCE = 2
SUGGEST_STREAK = 2


# --- Invoices we are waiting for ---------------------------------------------


@dataclass(frozen=True)
class TrackedInvoice:
    """A MISSING_IN_2B invoice, and when (if ever) it reached a later 2B."""

    client_id: str
    vendor_gstin: str
    invoice_no: str
    invoice_date: date
    period: str
    arrived_in: str | None = None
    filed_on: date | None = None

    def arrived_by(self, period: str) -> bool:
        return self.arrived_in is not None and self.arrived_in <= period

    @property
    def months_late(self) -> int | None:
        return None if self.arrived_in is None else months_between(self.period, self.arrived_in)

    @property
    def days_late(self) -> int | None:
        """Invoice date to the supplier's filing (or, without one, the end of the arrival month)."""
        if self.arrived_in is None:
            return None
        return ((self.filed_on or last_day(self.arrived_in)) - self.invoice_date).days


def expected_lag(invoices: Sequence[TrackedInvoice]) -> int:
    """Months a vendor's invoices usually take to appear: the median of its late arrivals."""
    lags = [i.months_late for i in invoices if i.months_late is not None]
    return max(median_low(lags), DEFAULT_LAG_MONTHS) if lags else DEFAULT_LAG_MONTHS


# --- Self-check (§4) ---------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    status: OutcomeStatus
    invoice_nos: tuple[str, ...]
    due_in: str | None
    """The 2B period a DEFER expected the invoices in; None for other actions."""
    arrived_in: str | None
    filed_on: date | None
    days_late: int | None

    @property
    def correct(self) -> bool | None:
        if self.status is OutcomeStatus.NOT_APPLICABLE:
            return None
        return self.status is OutcomeStatus.VERIFIED_CORRECT


def verify(
    action: Action,
    exception_type: ExceptionType,
    decided_in: str,
    invoices: Sequence[TrackedInvoice],
    *,
    lag: int,
    period: str,
) -> Verdict | None:
    """The verdict on one decision as of `period`, or None while it can't be judged yet.

    Only DEFER on MISSING_IN_2B predicts something ("it will be in the 2B of
    decided_in + lag"). Any other action on MISSING_IN_2B gets NOT_APPLICABLE
    once its invoices arrive, so the late arrival is still remembered. Other
    exception types make no prediction and get no verdict.
    """
    if exception_type is not ExceptionType.MISSING_IN_2B or not invoices:
        return None
    arrived = all(i.arrived_by(period) for i in invoices)
    due_in = add_months(decided_in, lag) if action is Action.DEFER else None
    if due_in is None:
        status = OutcomeStatus.NOT_APPLICABLE if arrived else None
    elif arrived and max(i.arrived_in or "" for i in invoices) <= due_in:
        status = OutcomeStatus.VERIFIED_CORRECT
    elif period >= due_in:
        status = OutcomeStatus.VERIFIED_WRONG
    else:
        status = None
    if status is None:
        return None
    return _verdict(status, invoices, due_in, period)


def _verdict(
    status: OutcomeStatus, invoices: Sequence[TrackedInvoice], due_in: str | None, period: str
) -> Verdict:
    arrived = [i for i in invoices if i.arrived_by(period)]
    complete = len(arrived) == len(invoices)
    return Verdict(
        status=status,
        invoice_nos=tuple(i.invoice_no for i in invoices),
        due_in=due_in,
        arrived_in=max(i.arrived_in or "" for i in arrived) if complete else None,
        filed_on=max((i.filed_on for i in arrived if i.filed_on), default=None)
        if complete
        else None,
        days_late=max(i.days_late or 0 for i in arrived) if complete else None,
    )


def arrival_after_wrong(
    verdict_invoices: Sequence[TrackedInvoice], due_in: str | None, period: str
) -> Verdict | None:
    """§9: a VERIFIED_WRONG deferral whose invoices finally arrived. It stays wrong."""
    if not verdict_invoices or not all(i.arrived_by(period) for i in verdict_invoices):
        return None
    return _verdict(OutcomeStatus.VERIFIED_WRONG, verdict_invoices, due_in, period)


# --- Trust ladder (§5) -------------------------------------------------------


@dataclass(frozen=True)
class Trust:
    level: TrustLevel = TrustLevel.OBSERVE
    streak_action: Action | None = None
    streak: int = 0
    correct: int = 0
    wrong: int = 0


def trust(
    exception_type: ExceptionType,
    actions: Sequence[Action],
    verdicts: Sequence[OutcomeStatus],
    *,
    drift_active: bool = False,
    undone_recently: bool = False,
) -> Trust:
    """Trust in one pattern (vendor + exception type), recomputed from its history.

    `actions`: final actions of the pattern's current decisions, oldest first.
    `verdicts`: VERIFIED_CORRECT / VERIFIED_WRONG outcomes of those decisions, oldest first.
    """
    streak_action = actions[-1] if actions else None
    streak = 0
    for action in reversed(actions):
        if action is not streak_action:
            break
        streak += 1
    correct = verdicts.count(OutcomeStatus.VERIFIED_CORRECT)
    wrong = verdicts.count(OutcomeStatus.VERIFIED_WRONG)
    wrong_recent = (
        OutcomeStatus.VERIFIED_WRONG in verdicts[-RECENT_VERDICTS:]
        or drift_active
        or undone_recently
    )
    earned_auto = streak >= AUTO_STREAK or (
        streak >= AUTO_STREAK_WITH_EVIDENCE and correct >= AUTO_EVIDENCE
    )
    if wrong_recent:
        level = TrustLevel.OBSERVE
    elif (
        earned_auto
        and streak_action is not None
        and can_auto_resolve(exception_type, streak_action)  # INV-2
    ):
        level = TrustLevel.AUTO
    elif streak >= SUGGEST_STREAK:
        level = TrustLevel.SUGGEST
    else:
        level = TrustLevel.OBSERVE
    return Trust(level, streak_action, streak, correct, wrong)


# --- Drift (§6) --------------------------------------------------------------


@dataclass(frozen=True)
class DriftFinding:
    vendor_gstin: str
    overdue: tuple[TrackedInvoice, ...]
    lag_months: int
    typical_lag_days: int
    overdue_days: int
    """Age of the oldest overdue invoice at the end of the current period."""


def detect_drift(
    invoices: Sequence[TrackedInvoice], processed: dict[str, str], period: str
) -> DriftFinding | None:
    """One vendor's MISSING_IN_2B invoices at every client → drift, if its lag broke.

    `processed`: the latest period whose 2B has been matched, per client. An
    invoice is only overdue once its client's 2B for the expected period has
    been seen, so running clients in any order gives the same answer.
    """
    arrivals = [i for i in invoices if i.arrived_by(period)]
    if len(arrivals) < MIN_ARRIVALS_FOR_DRIFT:
        return None
    lag = expected_lag(arrivals)
    overdue = tuple(
        i
        for i in invoices
        if i.client_id in processed
        and not i.arrived_by(processed[i.client_id])
        and processed[i.client_id] >= add_months(i.period, lag)
    )
    if not overdue:
        return None
    return DriftFinding(
        vendor_gstin=invoices[0].vendor_gstin,
        overdue=overdue,
        lag_months=lag,
        typical_lag_days=median_low([i.days_late or 0 for i in arrivals]),
        overdue_days=max((last_day(period) - i.invoice_date).days for i in overdue),
    )

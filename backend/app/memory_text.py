"""What Recon writes to and asks of memory, as plain English (SPEC-04 §6 to §8).

Memories are self-contained sentences: Hindsight extracts facts and links
entities (vendor, client, GSTIN) from the text itself, so every memory names
them in full. One memory per exception group, never per invoice.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from backend.app.domain.enums import Action, ExceptionType
from backend.app.domain.periods import label


class MemoryKind(StrEnum):
    RESOLUTION = "resolution"
    """M1: how a group was decided."""
    OUTCOME = "outcome"
    """M2: whether a past decision turned out right, or a late invoice arrived."""
    DRIFT = "drift"
    """M3: a vendor broke its usual pattern."""


TYPE_PHRASES: dict[ExceptionType, str] = {
    ExceptionType.MISSING_IN_2B: "missing from GSTR-2B",
    ExceptionType.MISSING_IN_BOOKS: "in GSTR-2B but not in the purchase register",
    ExceptionType.AMOUNT_MISMATCH: "with a different amount in GSTR-2B",
    ExceptionType.TAX_HEAD_MISMATCH: "booked under the wrong tax head (IGST vs CGST+SGST)",
    ExceptionType.GSTIN_MISMATCH: "booked under a wrong supplier GSTIN",
    ExceptionType.ITC_INELIGIBLE: "marked ITC-ineligible in GSTR-2B",
}


def rupees(amount: Decimal) -> str:
    """Indian digit grouping: `1234567.5` → `₹12,34,567.50`."""
    whole, paise = f"{abs(amount):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups: list[str] = []
    while len(head) > 2:
        head, pair = head[:-2], head[-2:]
        groups.insert(0, pair)
    grouped = ",".join([head, *groups, tail] if head else [*groups, tail])
    sign = "-" if amount < 0 else ""
    return f"{sign}₹{grouped}.{paise}"


def _invoices(n: int) -> str:
    return f"{n} invoice" if n == 1 else f"{n} invoices"


# --- Templates ---------------------------------------------------------------


@dataclass(frozen=True)
class Resolution:
    """M1. Written for every decided group, by the accountant or automatically."""

    period: str
    client_name: str
    vendor_name: str
    vendor_gstin: str
    exception_type: ExceptionType
    invoice_count: int
    itc_at_risk: Decimal
    suggested_action: Action | None
    final_action: Action
    note: str | None
    automatic: bool = False

    def text(self) -> str:
        lines = [
            f"{label(self.period)}: At client {self.client_name}, vendor {self.vendor_name} "
            f"(GSTIN {self.vendor_gstin}) had {_invoices(self.invoice_count)} "
            f"{TYPE_PHRASES[self.exception_type]}, ITC at risk {rupees(self.itc_at_risk)}.",
        ]
        if self.automatic:
            lines.append(
                f"Recon resolved it automatically as {self.final_action}, "
                "because this pattern had earned trust."
            )
        else:
            suggested = self.suggested_action or "nothing (memory off)"
            lines.append(f"Recon suggested {suggested}.")
            if self.suggested_action == self.final_action:
                lines.append("The accountant accepted it.")
            else:
                # Overrides are the most valuable memories: say so plainly.
                lines.append(f"The accountant overrode it and chose {self.final_action}.")
        if self.note:
            lines.append(f'Accountant\'s note: "{self.note}"')
        return "\n".join(lines)


@dataclass(frozen=True)
class Outcome:
    """M2. `correct` is None when the decision made no checkable prediction."""

    period: str
    decided_in: str
    client_name: str
    vendor_name: str
    vendor_gstin: str
    action: Action
    correct: bool | None
    evidence: str

    def text(self) -> str:
        subject = (
            f"{label(self.period)}: Checked the {label(self.decided_in)} decision for vendor "
            f"{self.vendor_name} (GSTIN {self.vendor_gstin}) at client {self.client_name}:"
        )
        if self.correct is None:
            verdict = f"the decision had been to {self.action}."
        else:
            verdict = f"the decision to {self.action} was {'correct' if self.correct else 'wrong'}."
        return f"{subject} {verdict}\nEvidence: {self.evidence}"


def late_arrival_evidence(
    invoice_nos: Sequence[str], arrived_in: str, filed_on: date | None, days_late: int
) -> str:
    """`invoice RS/2025-26/0412 appeared in the February 2026 GSTR-2B, filed …`."""
    noun = "invoice" if len(invoice_nos) == 1 else "invoices"
    verb = "appeared" if len(invoice_nos) == 1 else "all appeared"
    filed = f", filed {filed_on:%d-%m-%Y}" if filed_on else ""
    return (
        f"{noun} {', '.join(invoice_nos)} {verb} in the {label(arrived_in)} GSTR-2B{filed}, "
        f"about {days_late} days after the invoice date."
    )


@dataclass(frozen=True)
class Drift:
    """M3."""

    period: str
    vendor_name: str
    vendor_gstin: str
    typical_lag: str
    overdue_count: int
    overdue_days: int

    def text(self) -> str:
        verb = "is" if self.overdue_count == 1 else "are"
        return (
            f"{label(self.period)}: Vendor {self.vendor_name} (GSTIN {self.vendor_gstin}) "
            f"broke its usual pattern. Previously its invoices arrived about {self.typical_lag} "
            f"late; now {_invoices(self.overdue_count)} {verb} overdue "
            f"by {self.overdue_days} days. "
            "Earlier assumptions about this vendor should not be trusted."
        )


# --- Questions ---------------------------------------------------------------


def group_query(vendor_name: str, vendor_gstin: str, exception_type: ExceptionType) -> str:
    """The one recall per exception group (§7). The GSTIN lets keyword search hit exactly."""
    phrase = TYPE_PHRASES[exception_type]
    return (
        f"How were invoices {phrase} from vendor {vendor_name} (GSTIN {vendor_gstin}) "
        "handled before, at any client, and what happened afterwards? "
        f"How does this vendor usually behave? Any accountant preferences about invoices {phrase}?"
    )


def vendor_profile_query(vendor_name: str, vendor_gstin: str) -> str:
    return (
        f"Summarise how vendor {vendor_name} ({vendor_gstin}) behaves, how its issues were "
        "resolved, what works when contacting them, and how reliable past assumptions have been."
    )


def monthly_insights_query(period: str) -> str:
    return (
        f"What did we learn in {label(period)} across all clients? New risks, vendors that "
        "changed behaviour, patterns now reliable."
    )

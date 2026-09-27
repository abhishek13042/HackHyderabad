"""Expert labels and accountant notes for every exception group (SPEC-02 §7).

Labels reflect only what was knowable at the time. `accountant_action` is what
the simulated accountant actually does; it differs from `best_action` in two
cells, where the firm acted more firmly than the textbook answer.
"""

import re
from dataclasses import dataclass
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from backend.app.domain.entities import GroupKey
from backend.app.domain.enums import Action, Flag, RootCause
from backend.app.domain.policy import is_action_allowed
from backend.datagen.cast import APR, FEB, JAN, MAR, VENDORS

A = Action
R = RootCause
F = Flag


@dataclass(frozen=True)
class Label:
    best: Action
    root_cause: RootCause
    note: str
    flags: frozenset[Flag] = frozenset()
    accountant: Action | None = None
    """Set only when the accountant's call differs from `best`."""
    also_acceptable: frozenset[Action] = frozenset()


def _label(
    best: Action,
    root_cause: RootCause,
    note: str,
    *flags: Flag,
    accountant: Action | None = None,
    also: tuple[Action, ...] = (),
) -> Label:
    return Label(best, root_cause, note, frozenset(flags), accountant, frozenset(also))


LABELS: dict[tuple[str, str, str], Label] = {
    # --- Reddy Steels: files a month late, then stops filing -----------------
    ("reddy_steels", "C01", JAN): _label(
        A.CHASE_VENDOR, R.UNKNOWN,
        "Called Reddy Steels. Their accountant Suresh says they file GSTR-1 late, "
        "usually around the 20th of the following month. Will re-check next 2B.",
    ),
    ("reddy_steels", "C01", FEB): _label(
        A.DEFER, R.LATE_FILING,
        "Jan invoice showed up in Feb 2B. They're just late. Deferring.",
    ),
    ("reddy_steels", "C01", MAR): _label(
        A.DEFER, R.LATE_FILING,
        "Feb invoice arrived in March 2B as expected. Reddy Steels always files "
        "a month late. Deferring again.",
    ),
    ("reddy_steels", "C01", APR): _label(
        A.CHASE_VENDOR, R.NOT_FILED,
        "March invoice still not in April 2B. Reddy Steels has never been this late. "
        "Suresh is not answering calls. Asked client to hold the GST portion of the payment.",
        F.PATTERN_DRIFT,
        accountant=A.HOLD_PAYMENT,
    ),
    # --- Bhavani Chemicals: always one month late ----------------------------
    ("bhavani_chemicals", "C02", JAN): _label(
        A.CHASE_VENDOR, R.UNKNOWN,
        "Bhavani Chemicals invoice not in 2B. Their office says GSTR-1 went in after "
        "the due date. Will check next 2B.",
    ),
    ("bhavani_chemicals", "C02", FEB): _label(
        A.DEFER, R.LATE_FILING,
        "January invoice appeared in Feb 2B. Bhavani files after the cut-off. "
        "Deferring the Feb invoice.",
    ),
    ("bhavani_chemicals", "C02", MAR): _label(
        A.DEFER, R.LATE_FILING,
        "Same as every month: Bhavani's invoices land one month late. Deferring.",
    ),
    ("bhavani_chemicals", "C02", APR): _label(
        A.DEFER, R.LATE_FILING,
        "Bhavani's March invoices came in April 2B as usual. Deferring April's.",
    ),
    # --- Laxmi Packaging: rounding differences, two clients ------------------
    ("laxmi_packaging", "C01", JAN): _label(
        A.ACCEPT, R.ROUNDING,
        "Laxmi Packaging total is off by a few rupees, rounding in their billing "
        "software. We accept anything under ₹10.",
    ),
    ("laxmi_packaging", "C02", JAN): _label(
        A.ACCEPT, R.ROUNDING,
        "Few rupees difference on the Laxmi Packaging cartons bill. Their software "
        "rounds each line. Under ₹10, so accepted.",
    ),
    ("laxmi_packaging", "C01", FEB): _label(
        A.ACCEPT, R.ROUNDING, "Laxmi again off by a few rupees. Rounding. Accepted."
    ),
    ("laxmi_packaging", "C02", FEB): _label(
        A.ACCEPT, R.ROUNDING,
        "Rounding difference on Laxmi Packaging again. Accepted as per firm policy (under ₹10).",
    ),
    ("laxmi_packaging", "C01", MAR): _label(
        A.ACCEPT, R.ROUNDING, "Laxmi rounding difference, same as always. Accepted."
    ),
    ("laxmi_packaging", "C02", MAR): _label(
        A.ACCEPT, R.ROUNDING, "Laxmi Packaging small difference again. Accepted."
    ),
    ("laxmi_packaging", "C01", APR): _label(
        A.ACCEPT, R.ROUNDING, "Laxmi Packaging rounding, under ₹10. Accepted."
    ),
    ("laxmi_packaging", "C02", APR): _label(
        A.ACCEPT, R.ROUNDING, "Usual Laxmi rounding difference. Accepted."
    ),
    # --- Sai Electricals: files against a wrong buyer GSTIN, then amends -----
    ("sai_electricals", "C03", JAN): _label(
        A.CHASE_VENDOR, R.UNKNOWN,
        "Sai Electricals invoice missing from 2B. Called them: they had typed our GSTIN "
        "wrong in GSTR-1. They will amend it in next month's return.",
    ),
    ("sai_electricals", "C03", MAR): _label(
        A.CHASE_VENDOR, R.WRONG_BUYER_GSTIN,
        "Sai Electricals missing again. Asked them to check the buyer GSTIN in their "
        "GSTR-1; last time it was a typo on their side.",
    ),
    # --- Mumbai Threads: inter-state bill booked as CGST + SGST --------------
    ("mumbai_threads", "C01", JAN): _label(
        A.CORRECT_BOOKS, R.BOOKING_ERROR,
        "Mumbai Threads is in Maharashtra, so the bill is IGST. Our bookkeeper entered "
        "CGST + SGST. Corrected the entry.",
    ),
    ("mumbai_threads", "C01", FEB): _label(
        A.CORRECT_BOOKS, R.BOOKING_ERROR,
        "Same mistake as January: Mumbai Threads booked as CGST + SGST. Corrected and "
        "reminded the bookkeeper that out-of-state suppliers are IGST.",
    ),
    ("mumbai_threads", "C01", MAR): _label(
        A.CORRECT_BOOKS, R.BOOKING_ERROR,
        "Mumbai Threads booked with the wrong tax head again. Corrected.",
    ),
    ("mumbai_threads", "C01", APR): _label(
        A.CORRECT_BOOKS, R.BOOKING_ERROR,
        "Wrong tax head on Mumbai Threads, fourth month running. Corrected; asked the "
        "client to fix the ledger template.",
    ),
    # --- Krishna Logistics: never files, later also supplies C03 -------------
    ("krishna_logistics", "C01", JAN): _label(
        A.CHASE_VENDOR, R.UNKNOWN,
        "Krishna Logistics invoice not in 2B. Emailed them to file GSTR-1.",
    ),
    ("krishna_logistics", "C01", FEB): _label(
        A.CHASE_VENDOR, R.NOT_FILED,
        "Second month no filing. Emails ignored. Asked client to hold GST portion of payment.",
        accountant=A.HOLD_PAYMENT,
    ),
    ("krishna_logistics", "C01", MAR): _label(
        A.HOLD_PAYMENT, R.NOT_FILED,
        "Krishna Logistics still not filing. Keeping the GST portion on hold.",
    ),
    ("krishna_logistics", "C01", APR): _label(
        A.HOLD_PAYMENT, R.NOT_FILED,
        "Fourth month, nothing filed by Krishna Logistics. Payment hold continues.",
    ),
    ("krishna_logistics", "C03", MAR): _label(
        A.HOLD_PAYMENT, R.NOT_FILED,
        "Vega has started using Krishna Logistics, the transporter that hasn't filed for "
        "Sri Balaji Textiles since January. Holding the GST portion from the first bill.",
        F.CROSS_CLIENT_RISK,
    ),
    ("krishna_logistics", "C03", APR): _label(
        A.HOLD_PAYMENT, R.NOT_FILED,
        "Krishna Logistics still not filing for any of our clients. GST portion stays on hold.",
        F.CROSS_CLIENT_RISK,
    ),
    # --- Om Sai Enterprises: registration cancelled retrospectively ----------
    ("om_sai_enterprises", "C02", FEB): _label(
        A.BLOCK_ITC, R.SUPPLIER_CANCELLED,
        "Om Sai Enterprises registration cancelled retrospectively from February; 2B shows "
        "ITC not available. Credit blocked. Advised client to stop buying from them.",
        F.VENDOR_RISK,
    ),
    ("om_sai_enterprises", "C02", MAR): _label(
        A.BLOCK_ITC, R.SUPPLIER_CANCELLED,
        "Om Sai Enterprises still cancelled, ITC not available again. Blocked. Client "
        "says they will switch supplier from April.",
        F.VENDOR_RISK,
    ),
    # --- Ganesh Traders: one bill a month never reaches the books ------------
    ("ganesh_traders", "C02", JAN): _label(
        A.BOOK_INVOICE, R.NOT_BOOKED,
        "Ganesh Traders bill is in 2B but not in the books. Client had it in the drawer. Booked.",
    ),
    ("ganesh_traders", "C02", FEB): _label(
        A.BOOK_INVOICE, R.NOT_BOOKED,
        "Another Ganesh Traders bill missing from the books; client forgot to hand it over.",
    ),
    ("ganesh_traders", "C02", MAR): _label(
        A.BOOK_INVOICE, R.NOT_BOOKED,
        "Ganesh Traders: one bill every month doesn't reach us. Booked after confirming "
        "with the client.",
    ),
    ("ganesh_traders", "C02", APR): _label(
        A.BOOK_INVOICE, R.NOT_BOOKED, "Missing Ganesh Traders bill, as usual. Booked."
    ),
    # --- Venkateswara Components: supplier GSTIN mistyped in our books -------
    ("venkateswara_components", "C03", FEB): _label(
        A.CORRECT_BOOKS, R.BOOKING_ERROR,
        "Venkateswara Components GSTIN typed wrong in our books (one character). "
        "Corrected to the GSTIN on their bill.",
    ),
    ("venkateswara_components", "C03", APR): _label(
        A.CORRECT_BOOKS, R.BOOKING_ERROR,
        "Bookkeeper mistyped the Venkateswara Components GSTIN again. Corrected.",
    ),
    # --- Deccan Power Solutions: ambiguous on purpose (D8) -------------------
    ("deccan_power", "C03", APR): _label(
        A.ESCALATE, R.UNKNOWN,
        "Deccan Power Solutions filed about 10% less than the bill we booked. Could be a "
        "discount given later or a mistake on either side. Sent to the partner to review.",
        also=(A.CHASE_VENDOR,),
    ),
}  # fmt: skip


# --- Ground-truth file entries -----------------------------------------------

_FORBIDDEN_WORDS = re.compile(r"\b(planted|synthetic|test)\b", re.IGNORECASE)
_ARCHETYPES = frozenset(vendor.archetype for vendor in VENDORS)


def forbidden_terms(note: str) -> list[str]:
    """Words a note must never contain (SPEC-02 §7): they would give the game away."""
    found = [match.group(0) for match in _FORBIDDEN_WORDS.finditer(note)]
    return found + [archetype for archetype in sorted(_ARCHETYPES) if archetype in note]


class GroundTruthEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    group_key: GroupKey
    archetype: str
    best_action: Action
    acceptable_actions: tuple[Action, ...]
    accountant_action: Action
    root_cause: RootCause
    flags: tuple[Flag, ...]
    accountant_note: str

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        exception_type = self.group_key.exception_type
        if self.best_action not in self.acceptable_actions:
            raise ValueError(f"{self.group_key}: best action is not acceptable")
        if self.accountant_action not in self.acceptable_actions:
            raise ValueError(f"{self.group_key}: accountant action is not acceptable")
        for action in self.acceptable_actions:
            if not is_action_allowed(exception_type, action):
                raise ValueError(f"{self.group_key}: {action} not allowed for {exception_type}")
        if terms := forbidden_terms(self.accountant_note):
            raise ValueError(f"{self.group_key}: note contains {terms}")
        return self


def ground_truth_entry(
    group_key: GroupKey, archetype: str, label: Label, recurring: bool
) -> GroundTruthEntry:
    accountant = label.accountant or label.best
    others = (label.also_acceptable | {accountant}) - {label.best}
    flags = (label.flags | {Flag.RECURRING_ISSUE}) if recurring else label.flags
    return GroundTruthEntry(
        group_key=group_key,
        archetype=archetype,
        best_action=label.best,
        acceptable_actions=(label.best, *sorted(others)),
        accountant_action=accountant,
        root_cause=label.root_cause,
        flags=tuple(sorted(flags)),
        accountant_note=label.note,
    )

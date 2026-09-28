"""SPEC-04 §6 to §8: what Munshi writes to memory, and what it asks."""

from datetime import date
from decimal import Decimal

import pytest

from backend.app.domain.enums import Action, ExceptionType
from backend.app.memory_text import (
    TYPE_PHRASES,
    Drift,
    Outcome,
    Resolution,
    group_query,
    late_arrival_evidence,
    rupees,
)

GSTIN = "36AAJFK4410L1Z5"


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        ("0", "₹0.00"),
        ("5", "₹5.00"),
        ("999.5", "₹999.50"),
        ("1000", "₹1,000.00"),
        ("84000", "₹84,000.00"),
        ("123456", "₹1,23,456.00"),
        ("1234567.5", "₹12,34,567.50"),
        ("123456789", "₹12,34,56,789.00"),
        ("-7200", "-₹7,200.00"),
    ],
)
def test_rupees_use_indian_grouping(amount: str, text: str) -> None:
    assert rupees(Decimal(amount)) == text


def resolution(**changes: object) -> Resolution:
    values: dict[str, object] = {
        "period": "2026-01",
        "client_name": "Sri Balaji Textiles",
        "vendor_name": "Krishna Logistics",
        "vendor_gstin": GSTIN,
        "exception_type": ExceptionType.MISSING_IN_2B,
        "invoice_count": 3,
        "itc_at_risk": Decimal("84000"),
        "suggested_action": Action.DEFER,
        "final_action": Action.DEFER,
        "note": None,
    } | changes
    return Resolution(**values)  # type: ignore[arg-type]


def test_resolution_names_everything_recall_needs() -> None:
    text = resolution().text()
    assert text.startswith("January 2026: At client Sri Balaji Textiles, vendor Krishna Logistics")
    assert f"(GSTIN {GSTIN}) had 3 invoices missing from GSTR-2B" in text
    assert "ITC at risk ₹84,000.00." in text
    assert "The accountant accepted it." in text


def test_override_is_explicit() -> None:
    text = resolution(final_action=Action.CHASE_VENDOR, note="They always file late").text()
    assert "Munshi suggested DEFER.\nThe accountant overrode it and chose CHASE_VENDOR." in text
    assert text.endswith('Accountant\'s note: "They always file late"')


def test_memory_off_suggestion() -> None:
    assert "Munshi suggested nothing (memory off)." in resolution(suggested_action=None).text()


def test_automatic_resolution() -> None:
    text = resolution(automatic=True, invoice_count=1).text()
    assert "had 1 invoice missing" in text
    assert "resolved it automatically as DEFER" in text
    assert "accountant" not in text.lower()


def test_outcome_and_late_arrival_evidence() -> None:
    evidence = late_arrival_evidence(["RS/0412"], "2026-02", date(2026, 3, 11), 38)
    outcome = Outcome(
        period="2026-02", decided_in="2026-01", client_name="Sri Balaji Textiles",
        vendor_name="Krishna Logistics", vendor_gstin=GSTIN, action=Action.DEFER,
        correct=True, evidence=evidence,
    )  # fmt: skip
    assert outcome.text() == (
        "February 2026: Checked the January 2026 decision for vendor Krishna Logistics "
        f"(GSTIN {GSTIN}) at client Sri Balaji Textiles: the decision to DEFER was correct.\n"
        "Evidence: invoice RS/0412 appeared in the February 2026 GSTR-2B, filed 11-03-2026, "
        "about 38 days after the invoice date."
    )


def test_evidence_for_several_invoices() -> None:
    text = late_arrival_evidence(["A1", "A2"], "2026-03", None, 45)
    assert text.startswith("invoices A1, A2 all appeared in the March 2026 GSTR-2B, about")


def test_drift_warns_against_old_assumptions() -> None:
    text = Drift("2026-03", "Krishna Logistics", GSTIN, "30 to 40 days", 2, 75).text()
    assert "2 invoices are overdue by 75 days" in text
    assert "should not be trusted" in text
    one = Drift("2026-04", "Reddy Steels", GSTIN, "46 days", 1, 51).text()
    assert "now 1 invoice is overdue by 51 days" in one


def test_every_type_has_a_phrase_used_in_its_query() -> None:
    assert set(TYPE_PHRASES) == set(ExceptionType)
    for exception_type, phrase in TYPE_PHRASES.items():
        query = group_query("Krishna Logistics", GSTIN, exception_type)
        assert phrase in query
        assert GSTIN in query

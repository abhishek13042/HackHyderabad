import inspect
import typing
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from backend.app.domain import entities
from backend.app.domain.entities import (
    BookInvoice,
    Decision,
    GroupKey,
    ReconException,
    TwoBEntry,
    Vendor,
)
from backend.app.domain.enums import Action, DecidedBy, ExceptionType, TaxHead
from backend.app.domain.gstin import make_gstin
from backend.app.domain.money import to_money

VENDOR = make_gstin("36", "AABCR1234F")
DECIDED_AT = datetime(2026, 4, 18, 10, 30, tzinfo=UTC)


def _book_invoice(**overrides: Any) -> BookInvoice:
    fields: dict[str, Any] = {
        "client_id": "C01",
        "period": "2026-04",
        "voucher_date": date(2026, 4, 5),
        "voucher_no": "PUR/0001",
        "supplier_invoice_no": "RS/2025-26/0467",
        "supplier_invoice_date": date(2026, 4, 3),
        "supplier_name": "Reddy Steels",
        "supplier_gstin": VENDOR,
        "place_of_supply": "36",
        "hsn": "7214",
        "taxable_value": "90000.00",
        "cgst": "8100.00",
        "sgst": "8100.00",
        "igst": "0",
        "cess": "0",
        "total": "106200.00",
    }
    return BookInvoice(**(fields | overrides))


def _decision(**overrides: Any) -> Decision:
    fields: dict[str, Any] = {
        "group_key": f"C01:2026-04:{VENDOR}:MISSING_IN_2B",
        "suggested_action": Action.DEFER,
        "final_action": Action.DEFER,
        "decided_by": DecidedBy.ACCOUNTANT,
        "decided_at": DECIDED_AT,
    }
    return Decision(**(fields | overrides))


# --- Money never float (AC-01-3) ---------------------------------------------


def _models() -> list[type[BaseModel]]:
    return [
        obj
        for _, obj in inspect.getmembers(entities, inspect.isclass)
        if issubclass(obj, BaseModel) and obj.__module__ == entities.__name__
    ]


def _mentions(annotation: Any, target: type) -> bool:
    if annotation is target:
        return True
    return any(_mentions(arg, target) for arg in typing.get_args(annotation))


@pytest.mark.parametrize("model", _models(), ids=lambda model: model.__name__)
def test_no_model_field_is_a_float(model: type[BaseModel]) -> None:
    for name, field in model.model_fields.items():
        assert not _mentions(field.annotation, float), f"{model.__name__}.{name} is a float"


def test_money_fields_reject_floats() -> None:
    with pytest.raises(ValidationError, match="float"):
        _book_invoice(total=106200.0)


def test_money_fields_are_quantized_decimals() -> None:
    invoice = _book_invoice()
    assert invoice.total == Decimal("106200.00")
    assert invoice.tax_total == Decimal("16200.00")
    assert invoice.tax_head is TaxHead.INTRA


def test_negative_money_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _book_invoice(cgst="-1")


# --- Validation of identifiers -------------------------------------------------


def test_invalid_gstin_is_rejected() -> None:
    with pytest.raises(ValidationError, match="GSTIN"):
        _book_invoice(supplier_gstin=VENDOR[:-1] + ("0" if VENDOR[-1] != "0" else "1"))


@pytest.mark.parametrize("field", ["period", "client_id", "place_of_supply"])
def test_malformed_identifiers_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        _book_invoice(**{field: "bad"})


def test_entities_are_immutable() -> None:
    invoice = _book_invoice()
    with pytest.raises(ValidationError):
        invoice.total = to_money("1")  # type: ignore[misc]


def test_vendor_has_no_archetype() -> None:
    """The planted behaviour label must never reach the agent."""
    assert "archetype" not in Vendor.model_fields
    with pytest.raises(ValidationError):
        Vendor(gstin=VENDOR, name="Reddy Steels", archetype="LATE_FILER")  # type: ignore[call-arg]


def test_twob_reason_only_when_itc_unavailable() -> None:
    fields: dict[str, Any] = {
        "client_id": "C02",
        "period": "2026-02",
        "supplier_gstin": VENDOR,
        "supplier_name": "OM SAI ENTERPRISES",
        "supplier_period": "2026-02",
        "supplier_filing_date": date(2026, 3, 11),
        "invoice_no": "OSE101",
        "invoice_date": date(2026, 2, 9),
        "place_of_supply": "36",
        "taxable_value": "10000",
        "cgst": "900",
        "sgst": "900",
        "igst": "0",
        "cess": "0",
        "total": "11800",
    }
    TwoBEntry(**fields, itc_available=False, itc_unavailable_reason="Registration cancelled")
    with pytest.raises(ValidationError, match="only valid"):
        TwoBEntry(**fields, itc_available=True, itc_unavailable_reason="Registration cancelled")


# --- Group keys ----------------------------------------------------------------


def test_group_key_round_trip() -> None:
    text = f"C01:2026-04:{VENDOR}:MISSING_IN_2B"
    key = GroupKey.model_validate(text)
    assert key.exception_type is ExceptionType.MISSING_IN_2B
    assert str(key) == text
    assert key.model_dump_json() == f'"{text}"'


@pytest.mark.parametrize("text", ["C01:2026-04:MISSING_IN_2B", f"C01:2026-04:{VENDOR}:NOPE"])
def test_group_key_rejects_malformed(text: str) -> None:
    with pytest.raises(ValidationError):
        GroupKey.model_validate(text)


def test_exception_group_key() -> None:
    exception = ReconException(
        client_id="C01",
        period="2026-04",
        type=ExceptionType.MISSING_IN_2B,
        vendor_gstin=VENDOR,
        itc_at_risk="16200",
    )
    assert str(exception.group_key) == f"C01:2026-04:{VENDOR}:MISSING_IN_2B"


# --- Decisions enforce INV-1 / INV-2 (AC-01-4) ---------------------------------


def test_accepted_suggestion_is_derived() -> None:
    assert _decision().accepted_suggestion
    assert not _decision(final_action=Action.HOLD_PAYMENT, note="Third month").accepted_suggestion
    assert not _decision(suggested_action=None).accepted_suggestion


def test_inv1_decision_cannot_accept_missing_credit() -> None:
    with pytest.raises(ValidationError, match="not allowed"):
        _decision(suggested_action=Action.ACCEPT, final_action=Action.ACCEPT)


def test_inv2_auto_decision_limited_to_accept_or_defer() -> None:
    _decision(decided_by=DecidedBy.AUTO)
    with pytest.raises(ValidationError, match="INV-2"):
        _decision(
            suggested_action=Action.CHASE_VENDOR,
            final_action=Action.CHASE_VENDOR,
            decided_by=DecidedBy.AUTO,
        )


def test_auto_decision_must_follow_the_suggestion() -> None:
    with pytest.raises(ValidationError, match="suggested action"):
        _decision(suggested_action=Action.CHASE_VENDOR, decided_by=DecidedBy.AUTO)


def test_decision_requires_timezone() -> None:
    with pytest.raises(ValidationError):
        _decision(decided_at=datetime(2026, 4, 18, 10, 30))  # noqa: DTZ001

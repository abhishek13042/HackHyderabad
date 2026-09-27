"""Money handling (SPEC-01 INV-3): `Decimal` in code, integer paise in SQLite, never float."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer

PAISE_PER_RUPEE = 100
_TWO_PLACES = Decimal("0.01")


class MoneyError(ValueError):
    """Raised when a value cannot be safely interpreted as an amount of money."""


def to_money(value: Decimal | int | str) -> Decimal:
    """Parse rupees into a `Decimal` quantized to paise.

    Floats are rejected on purpose: they can't represent most rupee amounts
    exactly, and one would silently corrupt totals and tolerance checks.
    """
    # bool is a subclass of int; True rupees is always a bug.
    if isinstance(value, float | bool):
        raise MoneyError(f"money must not be a {type(value).__name__}: {value!r}")
    if isinstance(value, str):
        value = value.strip().replace(",", "")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise MoneyError(f"not a valid amount: {value!r}") from exc
    if not amount.is_finite():
        raise MoneyError(f"amount must be finite: {value!r}")
    return amount.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def to_paise(amount: Decimal) -> int:
    """Rupees → integer paise, for storage."""
    return int(to_money(amount) * PAISE_PER_RUPEE)


def from_paise(paise: int) -> Decimal:
    """Integer paise → rupees."""
    if isinstance(paise, bool) or not isinstance(paise, int):
        raise MoneyError(f"paise must be an int: {paise!r}")
    return (Decimal(paise) / PAISE_PER_RUPEE).quantize(_TWO_PLACES)


def _money_to_str(amount: Decimal) -> str:
    return f"{amount:.2f}"


Money = Annotated[
    Decimal,
    BeforeValidator(to_money),
    # Serialized as a string ("27000.00"), never a JSON float (SPEC-07 §2).
    PlainSerializer(_money_to_str, return_type=str),
]
"""Pydantic field type for rupee amounts."""

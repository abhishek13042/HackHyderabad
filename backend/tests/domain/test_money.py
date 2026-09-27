from decimal import Decimal

import pytest
from pydantic import BaseModel

from backend.app.domain.money import Money, MoneyError, from_paise, to_money, to_paise


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("27000", Decimal("27000.00")),
        ("1,06,200.50", Decimal("106200.50")),
        (" 12.345 ", Decimal("12.35")),  # half-up to paise
        (12, Decimal("12.00")),
        (Decimal("0.005"), Decimal("0.01")),
    ],
)
def test_to_money(value: Decimal | int | str, expected: Decimal) -> None:
    assert to_money(value) == expected
    assert to_money(value).as_tuple().exponent == -2


@pytest.mark.parametrize("value", [0.1, 1.0, True, "abc", "", "NaN", "Infinity"])
def test_to_money_rejects_unsafe_values(value: object) -> None:
    with pytest.raises(MoneyError):
        to_money(value)  # type: ignore[arg-type]


def test_paise_round_trip() -> None:
    for text in ["0.00", "0.01", "4.99", "106200.00", "99999999.99"]:
        amount = Decimal(text)
        assert from_paise(to_paise(amount)) == amount
    assert to_paise(Decimal("27000.00")) == 2_700_000


def test_from_paise_rejects_non_int() -> None:
    with pytest.raises(MoneyError):
        from_paise(1.5)  # type: ignore[arg-type]


class _Priced(BaseModel):
    amount: Money


def test_money_field_rejects_float_and_serializes_as_string() -> None:
    with pytest.raises(ValueError, match="float"):
        _Priced(amount=0.1)
    priced = _Priced(amount="47200")
    assert priced.model_dump_json() == '{"amount":"47200.00"}'
    assert priced.model_dump(mode="json") == {"amount": "47200.00"}

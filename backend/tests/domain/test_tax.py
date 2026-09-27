from decimal import Decimal

import pytest

from backend.app.domain.enums import TaxHead
from backend.app.domain.tax import TaxHeadError, charged_tax_head, expected_tax_head

ZERO = Decimal("0.00")


def test_expected_tax_head() -> None:
    assert expected_tax_head("36", "36") is TaxHead.INTRA
    assert expected_tax_head("27", "36") is TaxHead.INTER


def test_charged_tax_head() -> None:
    nine = Decimal("2250.00")
    assert charged_tax_head(nine, nine, ZERO) is TaxHead.INTRA
    assert charged_tax_head(ZERO, ZERO, Decimal("4500.00")) is TaxHead.INTER
    assert charged_tax_head(ZERO, ZERO, ZERO) is None


@pytest.mark.parametrize(
    ("cgst", "sgst", "igst"),
    [("100.00", "100.00", "200.00"), ("100.00", "99.00", "0.00")],
)
def test_charged_tax_head_rejects_inconsistent_amounts(cgst: str, sgst: str, igst: str) -> None:
    with pytest.raises(TaxHeadError):
        charged_tax_head(Decimal(cgst), Decimal(sgst), Decimal(igst))

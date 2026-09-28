from datetime import date

import pytest

from backend.app.domain.periods import (
    PeriodError,
    add_months,
    first_day,
    from_return_period,
    label,
    last_day,
    months_between,
    to_return_period,
    validate_period,
)


def test_return_period_conversion() -> None:
    assert to_return_period("2026-03") == "032026"
    assert from_return_period("032026") == "2026-03"


@pytest.mark.parametrize(
    ("period", "months", "expected"),
    [
        ("2026-01", 1, "2026-02"),
        ("2026-12", 1, "2027-01"),
        ("2026-01", -1, "2025-12"),
        ("2026-04", 0, "2026-04"),
    ],
)
def test_add_months(period: str, months: int, expected: str) -> None:
    assert add_months(period, months) == expected


def test_months_between() -> None:
    assert months_between("2026-01", "2026-04") == 3
    assert months_between("2026-04", "2026-01") == -3
    assert months_between("2025-12", "2026-01") == 1


def test_label() -> None:
    assert label("2026-03") == "March 2026"


@pytest.mark.parametrize("value", ["2026-13", "2026-3", "26-03", "2026/03", ""])
def test_rejects_bad_periods(value: str) -> None:
    with pytest.raises(PeriodError):
        validate_period(value)


@pytest.mark.parametrize("value", ["132026", "32026", "2026-03"])
def test_rejects_bad_return_periods(value: str) -> None:
    with pytest.raises(PeriodError):
        from_return_period(value)


def test_first_and_last_day() -> None:
    assert first_day("2026-02") == date(2026, 2, 1)
    assert last_day("2026-02") == date(2026, 2, 28)
    assert last_day("2026-12") == date(2026, 12, 31)

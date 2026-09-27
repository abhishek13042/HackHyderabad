"""Tax periods (SPEC-01 §2).

Internally a period is `YYYY-MM` (e.g. `2026-03`). GSTR-2B JSON uses `MMYYYY`
(`032026`). Conversion happens only at the file boundary.
"""

import re
from typing import Annotated

from pydantic import AfterValidator

_INTERNAL = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_RETURN = re.compile(r"^(0[1-9]|1[0-2])(\d{4})$")
_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip


class PeriodError(ValueError):
    """Raised for a malformed period string."""


def validate_period(value: str) -> str:
    if not _INTERNAL.fullmatch(value):
        raise PeriodError(f"period must be YYYY-MM: {value!r}")
    return value


def _split(period: str) -> tuple[int, int]:
    validate_period(period)
    year, month = period.split("-")
    return int(year), int(month)


def _join(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def from_return_period(value: str) -> str:
    """`032026` → `2026-03`."""
    match = _RETURN.fullmatch(value)
    if not match:
        raise PeriodError(f"return period must be MMYYYY: {value!r}")
    month, year = match.groups()
    return f"{year}-{month}"


def to_return_period(period: str) -> str:
    """`2026-03` → `032026`."""
    year, month = _split(period)
    return f"{month:02d}{year:04d}"


def add_months(period: str, months: int) -> str:
    year, month = _split(period)
    index = year * 12 + (month - 1) + months
    return _join(index // 12, index % 12 + 1)


def months_between(start: str, end: str) -> int:
    """Whole months from `start` to `end` (negative if `end` is earlier)."""
    start_year, start_month = _split(start)
    end_year, end_month = _split(end)
    return (end_year - start_year) * 12 + (end_month - start_month)


def label(period: str) -> str:
    """`2026-03` → `March 2026` (used in memory text and the UI)."""
    year, month = _split(period)
    return f"{_MONTH_NAMES[month - 1]} {year}"


Period = Annotated[str, AfterValidator(validate_period)]
"""Pydantic field type for an internal `YYYY-MM` period."""

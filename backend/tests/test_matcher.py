"""SPEC-03 acceptance criteria for the matcher."""

import time
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from backend.app.domain.entities import BookInvoice, GroupKey, ReconException, TwoBEntry
from backend.app.domain.enums import ExceptionType
from backend.app.domain.gstin import make_gstin
from backend.app.matcher import (
    Detail,
    MatcherError,
    MatchPass,
    MatchResult,
    core,
    group_exceptions,
    norm_full,
    reconcile,
)
from backend.datagen.build import build_dataset
from backend.datagen.cast import CLIENTS, PERIODS

CLIENT = "C01"
JAN, FEB = "2026-01", "2026-02"
VENDOR = make_gstin("36", "AAJFK4410L")
OTHER_VENDOR = make_gstin("36", "AAHFC1180D")
INTERSTATE_VENDOR = make_gstin("27", "AACCM8854T")


def intra(taxable: str, rate: str = "0.18") -> dict[str, Decimal]:
    value = Decimal(taxable)
    half = value * Decimal(rate) / 2
    return {"taxable_value": value, "cgst": half, "sgst": half, "igst": Decimal(0)}


def inter(taxable: str, rate: str = "0.18") -> dict[str, Decimal]:
    value = Decimal(taxable)
    return {
        "taxable_value": value,
        "cgst": Decimal(0),
        "sgst": Decimal(0),
        "igst": value * Decimal(rate),
    }


def book(number: str, period: str = JAN, gstin: str = VENDOR, total: str | None = None,
         amounts: dict[str, Decimal] | None = None, day: int = 5) -> BookInvoice:  # fmt: skip
    amounts = amounts or intra("40000")
    return BookInvoice(
        client_id=CLIENT,
        period=period,
        voucher_date=date.fromisoformat(f"{period}-{day + 1:02d}"),
        voucher_no=f"PUR/{number}",
        supplier_invoice_no=number,
        supplier_invoice_date=date.fromisoformat(f"{period}-{day:02d}"),
        supplier_name="Krishna Logistics",
        supplier_gstin=gstin,
        place_of_supply="36",
        hsn="9967",
        cess=Decimal(0),
        total=Decimal(total) if total else sum(amounts.values(), Decimal(0)),
        **amounts,
    )


def entry(number: str, period: str = JAN, gstin: str = VENDOR, total: str | None = None,
          amounts: dict[str, Decimal] | None = None, supplier_period: str | None = None,
          **extra: Any) -> TwoBEntry:  # fmt: skip
    amounts = amounts or intra("40000")
    return TwoBEntry(
        client_id=CLIENT,
        period=period,
        supplier_gstin=gstin,
        supplier_name="KRISHNA LOGISTICS",
        supplier_period=supplier_period or period,
        supplier_filing_date=date.fromisoformat(f"{period}-20"),
        invoice_no=number,
        invoice_date=date.fromisoformat(f"{period}-05"),
        place_of_supply="36",
        itc_available=extra.pop("itc_available", True),
        cess=Decimal(0),
        total=Decimal(total) if total else sum(amounts.values(), Decimal(0)),
        **amounts,
        **extra,
    )


def run(books: list[BookInvoice], twob: list[TwoBEntry], period: str = JAN,
        open_missing: list[ReconException] | None = None) -> MatchResult:  # fmt: skip
    return reconcile(CLIENT, period, books, twob, open_missing or [])


def only_type(result: MatchResult) -> ExceptionType:
    (exception,) = result.exceptions
    return exception.type


# --- Normalization -----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "full", "last"),
    [
        ("RS/2025-26/0412", "RS412", "412"),
        ("KL-889", "KL889", "889"),
        ("INV/0045", "INV45", "45"),
        ("45", "45", "45"),
        (" kl 889 ", "KL889", "889"),
        ("MT/2025-2026/17", "MT17", "17"),
        ("MT/25-26/17", "MT17", "17"),
        ("FY25-26/17", "17", "17"),
        ("FY2526-17", "17", "17"),
        ("DPS/FY2025-26/301", "DPS301", "301"),
        ("BGA02526", "BGA2526", "2526"),  # a plain number that happens to look like a year pair
        ("INV/45/12", "INV4512", "4512"),  # not consecutive years: kept
        ("CASH", "CASH", ""),
    ],
)
def test_normalization(raw: str, full: str, last: str) -> None:
    assert norm_full(raw) == full
    assert core(raw) == last


# --- AC-03-1 … AC-03-9 -------------------------------------------------------


def test_ac_03_1_exact_after_normalization() -> None:
    result = run([book("KL-889")], [entry("KL889")])
    assert [m.matched_by for m in result.matched] == [MatchPass.EXACT]
    assert result.exceptions == ()


def test_ac_03_2_core_match_within_rupee() -> None:
    result = run([book("INV/0045", total="47200")], [entry("45", total="47201")])
    assert [m.matched_by for m in result.matched] == [MatchPass.CORE]
    assert result.exceptions == ()


def test_ac_03_3_amount_mismatch() -> None:
    result = run([book("INV/0045", total="47200")], [entry("45", total="47205")])
    (exception,) = result.exceptions
    assert exception.type is ExceptionType.AMOUNT_MISMATCH
    assert exception.details[Detail.AMOUNT_DIFF] == "5.00"


def test_amount_mismatch_risks_only_the_tax_difference() -> None:
    result = run([book("A1", amounts=intra("10000"))], [entry("A1", amounts=intra("10050"))])
    (exception,) = result.exceptions
    assert exception.itc_at_risk == Decimal("9.00")


def test_ac_03_4_tax_head_mismatch() -> None:
    books = [book("MT/1", gstin=INTERSTATE_VENDOR, amounts=intra("20000"))]
    twob = [entry("MT/1", gstin=INTERSTATE_VENDOR, amounts=inter("20000"))]
    (exception,) = run(books, twob).exceptions
    assert exception.type is ExceptionType.TAX_HEAD_MISMATCH
    assert exception.itc_at_risk == Decimal("3600.00")


def test_ac_03_5_itc_ineligible_wins_over_amounts() -> None:
    twob = [entry("OS/1", total="1", itc_available=False, itc_unavailable_reason="Cancelled")]
    result = run([book("OS/1")], twob)
    assert only_type(result) is ExceptionType.ITC_INELIGIBLE
    assert result.exceptions[0].details[Detail.ITC_UNAVAILABLE_REASON] == "Cancelled"


def test_ac_03_6_missing_in_2b() -> None:
    (exception,) = run([book("KL-889")], []).exceptions
    assert exception.type is ExceptionType.MISSING_IN_2B
    assert exception.itc_at_risk == Decimal("7200.00")
    assert exception.details[Detail.INVOICE_NO] == "KL-889"


def test_missing_in_books() -> None:
    (exception,) = run([], [entry("GT/7")]).exceptions
    assert exception.type is ExceptionType.MISSING_IN_BOOKS
    assert exception.details[Detail.INVOICE_NO] == "GT/7"
    assert exception.itc_at_risk == Decimal("7200.00")


def test_ac_03_7_late_arrival_closes_old_exception() -> None:
    (missing,) = run([book("RS/2025-26/0412")], []).exceptions
    feb = run([], [entry("RS412", period=FEB, supplier_period=JAN)], FEB, [missing])
    assert feb.exceptions == ()
    (late,) = feb.late_arrivals
    assert late.exception == missing
    assert late.twob.invoice_no == "RS412"


def test_late_arrival_with_a_different_amount_is_raised_now() -> None:
    (missing,) = run([book("RS-1", total="47200")], []).exceptions
    twob = [entry("RS-1", period=FEB, total="47210", supplier_period=JAN)]
    feb = run([], twob, FEB, [missing])
    assert len(feb.late_arrivals) == 1
    (exception,) = feb.exceptions
    assert (exception.type, exception.period) == (ExceptionType.AMOUNT_MISMATCH, FEB)


def test_ac_03_8_gstin_typo() -> None:
    typo = make_gstin("36", "AAJFK4420L")
    (exception,) = run([book("KL-889", gstin=typo)], [entry("KL889")]).exceptions
    assert exception.type is ExceptionType.GSTIN_MISMATCH
    assert exception.vendor_gstin == VENDOR  # the real supplier, from the 2B side
    assert exception.details[Detail.BOOK_GSTIN] == typo


def test_ac_03_9_two_core_candidates_never_guess() -> None:
    result = run([book("INV/0045")], [entry("45"), entry("PO-45")])
    assert result.matched == ()
    assert sorted(e.type for e in result.exceptions) == [
        ExceptionType.MISSING_IN_2B,
        ExceptionType.MISSING_IN_BOOKS,
        ExceptionType.MISSING_IN_BOOKS,
    ]


def test_core_match_needs_close_totals() -> None:
    result = run([book("INV/0045", total="47200")], [entry("45", total="48500")])
    assert result.matched == ()


def test_duplicate_invoice_number_matches_once() -> None:
    books = [book("KL-889", day=3), book("KL-889", day=9)]
    result = run(books, [entry("KL889")])
    assert [m.book.supplier_invoice_date.day for m in result.matched] == [3]
    assert only_type(result) is ExceptionType.MISSING_IN_2B


def test_empty_inputs() -> None:
    result = run([], [])
    assert (result.matched, result.exceptions, result.late_arrivals) == ((), (), ())


# --- Grouping ----------------------------------------------------------------


def test_groups_by_key_largest_risk_first() -> None:
    books = [book("A1", amounts=intra("1000")), book("A2", amounts=intra("1000")),
             book("B1", gstin=OTHER_VENDOR, amounts=intra("50000"))]  # fmt: skip
    small, large = group_exceptions(run(books, []).exceptions)[::-1]
    assert large.key.vendor_gstin == OTHER_VENDOR
    assert len(small.exceptions) == 2
    assert small.itc_at_risk == Decimal("360.00")


# --- Contract ----------------------------------------------------------------


def test_rejects_rows_from_another_period() -> None:
    with pytest.raises(MatcherError):
        run([book("A1", period=FEB)], [])


def test_rejects_open_exception_without_invoice_number() -> None:
    bare = ReconException(
        client_id=CLIENT, period=JAN, type=ExceptionType.MISSING_IN_2B,
        vendor_gstin=VENDOR, itc_at_risk=Decimal(1),
    )  # fmt: skip
    with pytest.raises(MatcherError):
        run([], [], FEB, [bare])


# --- AC-03-10 … AC-03-12: the generated dataset ------------------------------


def reconcile_dataset(seed: int = 42) -> tuple[list[GroupKey], list[MatchResult]]:
    """Run every client through every period, carrying unresolved MISSING_IN_2B forward."""
    dataset = build_dataset(seed)
    keys: list[GroupKey] = []
    results = []
    for client in CLIENTS:
        open_missing: list[ReconException] = []
        for period in PERIODS:
            books = dataset.books[(client.client_id, period)]
            twob = dataset.twob[(client.client_id, period)]
            result = reconcile(client.client_id, period, books, twob, open_missing)
            closed = [late.exception for late in result.late_arrivals]
            open_missing = [e for e in open_missing if e not in closed] + [
                e for e in result.exceptions if e.type is ExceptionType.MISSING_IN_2B
            ]
            keys += [group.key for group in result.groups]
            results.append(result)
    return keys, results


def test_ac_03_10_groups_equal_ground_truth() -> None:
    keys, _ = reconcile_dataset()
    expected = [entry.group_key for entry in build_dataset(42).ground_truth]
    assert len(keys) == len(set(keys))
    assert set(keys) == set(expected)


def test_ac_03_11_deterministic() -> None:
    assert reconcile_dataset()[1] == reconcile_dataset()[1]


def test_ac_03_12_fast() -> None:
    dataset = build_dataset(42)
    books, twob = dataset.books[("C02", "2026-02")], dataset.twob[("C02", "2026-02")]
    start = time.perf_counter()
    reconcile("C02", "2026-02", books, twob)
    assert time.perf_counter() - start < 1.0

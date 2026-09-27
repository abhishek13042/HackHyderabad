"""Turn the cast into a dataset: bills → purchase registers, GSTR-2Bs and ground truth.

Pipeline:
  1. draft bills   every (vendor, client, month): count, dates, amounts, treatment
  2. number bills  per vendor, in date order, like a real billing book
  3. book          what each client's bookkeeper enters (may be wrong)
  4. file          what each vendor reports, and in which month's 2B it lands
  5. label         one ground-truth entry per expected exception group

Each (vendor, client, month) gets its own RNG seeded from a string, so output
is identical for a given seed and doesn't shift when an unrelated vendor changes.
"""

import random
from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Self

from backend.app.domain.entities import BookInvoice, Client, Firm, GroupKey, TwoBEntry
from backend.app.domain.enums import ExceptionType
from backend.app.domain.gstin import make_gstin
from backend.app.domain.money import to_money
from backend.app.domain.periods import add_months
from backend.datagen.cast import (
    CLIENTS,
    EXPECTED_EXCEPTION,
    FIRM,
    PERIODS,
    VENDORS,
    Treatment,
    VendorProfile,
)
from backend.datagen.ground_truth import LABELS, GroundTruthEntry, ground_truth_entry

TAXABLE_RANGE = (2_000, 2_50_000)  # whole rupees (SPEC-02 R4)
ROUNDING_RANGE = (2, 9)  # rupees
DISPUTED_SHARE = Decimal("0.9")
FILING_DAY = 11  # GSTR-1 due date, day of the following month
TWOB_GENERATION_DAY = 14
CANCELLED_REASON = "Supplier registration cancelled retrospectively"

_ARRIVES_NEXT_MONTH = frozenset({Treatment.FILED_LATE, Treatment.AMENDED_NEXT_MONTH})

ClientPeriod = tuple[str, str]


class GenerationError(RuntimeError):
    """The cast, the plans and the labels disagree. A bug in the generator's inputs."""


@dataclass(frozen=True)
class Bill:
    """One invoice a vendor issues to a client, before anyone books or files it."""

    vendor: VendorProfile
    client: Client
    period: str
    index: int
    invoice_date: date
    voucher_date: date
    taxable: Decimal
    treatment: Treatment
    rounding: int
    """Signed rupee difference, used only by `ROUNDED_IN_2B`."""
    late_filing_day: int
    """Day of the following month a late vendor files, used only by `FILED_LATE`."""
    number: int = 0

    @property
    def expected_exception(self) -> ExceptionType | None:
        return EXPECTED_EXCEPTION[self.treatment]


@dataclass(frozen=True)
class Dataset:
    seed: int
    firm: Firm
    clients: tuple[Client, ...]
    vendors: tuple[VendorProfile, ...]
    bills: tuple[Bill, ...]
    books: dict[ClientPeriod, tuple[BookInvoice, ...]]
    twob: dict[ClientPeriod, tuple[TwoBEntry, ...]]
    ground_truth: tuple[GroundTruthEntry, ...]

    @staticmethod
    def twob_generated_on(period: str) -> date:
        return _day(add_months(period, 1), TWOB_GENERATION_DAY)


def build_dataset(seed: int) -> Dataset:
    bills = _number(_draft_bills(seed), seed)
    return Dataset(
        seed=seed,
        firm=FIRM,
        clients=CLIENTS,
        vendors=VENDORS,
        bills=bills,
        books=_book(bills),
        twob=_file(bills),
        ground_truth=_label(bills),
    )


# --- 1. Draft ----------------------------------------------------------------


def _draft_bills(seed: int) -> list[Bill]:
    clients = {client.client_id: client for client in CLIENTS}
    bills = []
    for vendor in VENDORS:
        for supply in vendor.supplies:
            for period in supply.periods:
                rng = random.Random(f"{seed}:{vendor.key}:{supply.client_id}:{period}")
                for index in range(rng.randint(*supply.invoices_per_month)):
                    invoice_date = _day(period, rng.randint(1, 25))
                    bills.append(
                        Bill(
                            vendor=vendor,
                            client=clients[supply.client_id],
                            period=period,
                            index=index,
                            invoice_date=invoice_date,
                            voucher_date=invoice_date + timedelta(days=rng.randint(0, 3)),
                            taxable=Decimal(rng.randint(*TAXABLE_RANGE)),
                            treatment=vendor.plan(period, index),
                            rounding=rng.randint(*ROUNDING_RANGE) * rng.choice((1, -1)),
                            late_filing_day=rng.randint(16, 25),
                        )
                    )
    return bills


# --- 2. Number ---------------------------------------------------------------


def _number(bills: list[Bill], seed: int) -> tuple[Bill, ...]:
    """Each vendor has one running invoice series shared by all its customers."""
    by_vendor: defaultdict[str, list[Bill]] = defaultdict(list)
    for bill in bills:
        by_vendor[bill.vendor.key].append(bill)

    numbered = []
    for key, vendor_bills in by_vendor.items():
        rng = random.Random(f"{seed}:{key}:numbers")
        number = rng.randint(100, 899)
        for bill in sorted(vendor_bills, key=lambda b: (b.invoice_date, b.client.client_id)):
            number += rng.randint(1, 6)  # gaps: bills to the vendor's other customers
            numbered.append(replace(bill, number=number))
    return tuple(numbered)


def invoice_number(bill: Bill, template: str) -> str:
    return template.format(n=bill.number, fy=financial_year(bill.invoice_date))


def financial_year(day: date) -> str:
    """Indian financial year, April to March: 2026-03-15 → "2025-26"."""
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


# --- Amounts -----------------------------------------------------------------


@dataclass(frozen=True)
class Amounts:
    taxable: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal

    @property
    def total(self) -> Decimal:
        return self.taxable + self.cgst + self.sgst + self.igst

    @classmethod
    def for_taxable(cls, taxable: Decimal, rate: Decimal, intra_state: bool) -> Self:
        taxable = to_money(taxable)
        if intra_state:
            half = to_money(taxable * rate / 2)
            return cls(taxable, half, half, Decimal("0.00"))
        return cls(taxable, Decimal("0.00"), Decimal("0.00"), to_money(taxable * rate))


def _true_amounts(bill: Bill) -> Amounts:
    return Amounts.for_taxable(bill.taxable, bill.vendor.gst_rate, _is_intra_state(bill))


def _is_intra_state(bill: Bill) -> bool:
    return bill.vendor.state == bill.client.state_code


def _booked_as_intra_state(amounts: Amounts) -> Amounts:
    """The bookkeeper splits an IGST bill into CGST + SGST."""
    half = (amounts.igst / 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return Amounts(amounts.taxable, half, half, Decimal("0.00"))


def _rounded(amounts: Amounts, rupees: int) -> Amounts:
    """Shift the total by `rupees`: the even part in tax (so the ITC differs too), the rest
    in taxable value. Keeps CGST == SGST on intra-state bills."""
    sign = 1 if rupees > 0 else -1
    tax_shift = Decimal(sign * (abs(rupees) // 2 * 2))
    taxable = amounts.taxable + (rupees - tax_shift)
    if amounts.igst:
        return Amounts(taxable, amounts.cgst, amounts.sgst, amounts.igst + tax_shift)
    half = tax_shift / 2
    return Amounts(taxable, amounts.cgst + half, amounts.sgst + half, amounts.igst)


# --- 3. Book -----------------------------------------------------------------


def _book(bills: tuple[Bill, ...]) -> dict[ClientPeriod, tuple[BookInvoice, ...]]:
    rows: defaultdict[ClientPeriod, list[BookInvoice]] = defaultdict(list)
    for client in CLIENTS:
        booked = sorted(
            (b for b in bills if b.client == client and b.treatment is not Treatment.NOT_BOOKED),
            key=lambda b: (b.voucher_date, b.vendor.name, b.number),
        )
        # Voucher numbers run on across months, as in a real purchase register.
        for voucher, bill in enumerate(booked, start=1):
            amounts = _true_amounts(bill)
            if bill.treatment is Treatment.BOOKED_WRONG_TAX_HEAD:
                amounts = _booked_as_intra_state(amounts)
            gstin = bill.vendor.gstin
            if bill.treatment is Treatment.BOOKED_WRONG_GSTIN:
                gstin = typo_gstin(bill.vendor)
            rows[(client.client_id, bill.period)].append(
                BookInvoice(
                    client_id=client.client_id,
                    period=bill.period,
                    voucher_date=bill.voucher_date,
                    voucher_no=f"PUR/{voucher:04d}",
                    supplier_invoice_no=invoice_number(bill, bill.vendor.numbers.books),
                    supplier_invoice_date=bill.invoice_date,
                    supplier_name=bill.vendor.name,
                    supplier_gstin=gstin,
                    place_of_supply=client.state_code,
                    hsn=bill.vendor.hsn,
                    **_amount_fields(amounts),
                )
            )
    return _freeze(rows)


def typo_gstin(vendor: VendorProfile) -> str:
    """The vendor's GSTIN with its last PAN digit mistyped, and a correct check character.

    It passes validation but belongs to nobody we know (SPEC-02 R2).
    """
    digit = (int(vendor.pan[8]) + 1) % 10
    typo = make_gstin(vendor.state, f"{vendor.pan[:8]}{digit}{vendor.pan[9]}")
    if typo in {known.gstin for known in VENDORS}:
        raise GenerationError(f"typo GSTIN for {vendor.key} collides with a real vendor")
    return typo


# --- 4. File -----------------------------------------------------------------


def _file(bills: tuple[Bill, ...]) -> dict[ClientPeriod, tuple[TwoBEntry, ...]]:
    rows: defaultdict[ClientPeriod, list[TwoBEntry]] = defaultdict(list)
    for bill in sorted(bills, key=lambda b: (b.vendor.name, b.invoice_date, b.number)):
        if bill.treatment is Treatment.NEVER_FILED:
            continue
        arrives_late = bill.treatment in _ARRIVES_NEXT_MONTH
        twob_period = add_months(bill.period, 1) if arrives_late else bill.period
        if twob_period not in PERIODS:
            continue  # would land in a 2B outside the dataset
        rows[(bill.client.client_id, twob_period)].append(_twob_entry(bill, twob_period))
    return _freeze(rows)


def _twob_entry(bill: Bill, twob_period: str) -> TwoBEntry:
    if bill.treatment is Treatment.FILED_LATE:
        # The original month's return, filed after the 2B cut-off.
        supplier_period = bill.period
        filed_on = _day(add_months(bill.period, 1), bill.late_filing_day)
    else:
        # On time; an amendment is reported in the following month's return.
        supplier_period = twob_period
        filed_on = _day(add_months(supplier_period, 1), FILING_DAY)

    amounts = _true_amounts(bill)
    if bill.treatment is Treatment.ROUNDED_IN_2B:
        amounts = _rounded(amounts, bill.rounding)
    elif bill.treatment is Treatment.DISPUTED_AMOUNT:
        reduced = (bill.taxable * DISPUTED_SHARE).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        amounts = Amounts.for_taxable(reduced, bill.vendor.gst_rate, _is_intra_state(bill))

    blocked = bill.treatment is Treatment.ITC_BLOCKED
    return TwoBEntry(
        client_id=bill.client.client_id,
        period=twob_period,
        supplier_gstin=bill.vendor.gstin,
        supplier_name=bill.vendor.name.upper(),
        supplier_period=supplier_period,
        supplier_filing_date=filed_on,
        invoice_no=invoice_number(bill, bill.vendor.numbers.twob),
        invoice_date=bill.invoice_date,
        place_of_supply=bill.client.state_code,
        itc_available=not blocked,
        itc_unavailable_reason=CANCELLED_REASON if blocked else None,
        **_amount_fields(amounts),
    )


# --- 5. Label ----------------------------------------------------------------


def _label(bills: tuple[Bill, ...]) -> tuple[GroundTruthEntry, ...]:
    groups: dict[GroupKey, VendorProfile] = {}
    for bill in bills:
        if (exception_type := bill.expected_exception) is not None:
            key = GroupKey(
                client_id=bill.client.client_id,
                period=bill.period,
                vendor_gstin=bill.vendor.gstin,
                exception_type=exception_type,
            )
            groups[key] = bill.vendor

    cells: dict[tuple[str, str, str], GroupKey] = {}
    for key, vendor in groups.items():
        cell = (vendor.key, key.client_id, key.period)
        if cell in cells:
            raise GenerationError(f"two exception types for one label cell: {cell}")
        cells[cell] = key
    if missing := cells.keys() - LABELS.keys():
        raise GenerationError(f"exception groups without a label: {sorted(missing)}")
    if unused := LABELS.keys() - cells.keys():
        raise GenerationError(f"labels without an exception group: {sorted(unused)}")

    entries = [
        ground_truth_entry(
            key,
            vendor.archetype,
            LABELS[(vendor.key, key.client_id, key.period)],
            recurring=_is_recurring(key, groups.keys()),
        )
        for key, vendor in groups.items()
    ]
    return tuple(sorted(entries, key=lambda e: _group_order(e.group_key)))


def _is_recurring(key: GroupKey, all_keys: Collection[GroupKey]) -> bool:
    """Same vendor and exception type in two or more earlier periods, any client (§7)."""
    prior_periods = {
        other.period
        for other in all_keys
        if other.vendor_gstin == key.vendor_gstin
        and other.exception_type == key.exception_type
        and other.period < key.period
    }
    return len(prior_periods) >= 2


def _group_order(key: GroupKey) -> tuple[str, str, str, str]:
    return (key.period, key.client_id, key.vendor_gstin, key.exception_type.value)


# --- Helpers -----------------------------------------------------------------


def _day(period: str, day: int) -> date:
    year, month = period.split("-")
    return date(int(year), int(month), day)


def _amount_fields(amounts: Amounts) -> dict[str, Decimal]:
    return {
        "taxable_value": amounts.taxable,
        "cgst": amounts.cgst,
        "sgst": amounts.sgst,
        "igst": amounts.igst,
        "cess": Decimal("0.00"),  # out of scope (SPEC-02 §2)
        "total": amounts.total,
    }


def _freeze[T](rows: defaultdict[ClientPeriod, list[T]]) -> dict[ClientPeriod, tuple[T, ...]]:
    """Every client-period present (empty if nothing), in a stable order."""
    return {
        (client.client_id, period): tuple(rows.get((client.client_id, period), ()))
        for client in CLIENTS
        for period in PERIODS
    }

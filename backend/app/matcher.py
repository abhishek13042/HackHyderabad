"""Deterministic reconciliation of a purchase register against GSTR-2B (SPEC-03).

No LLM, no I/O: the same inputs always give the same result. The API layer loads
the inputs and stores the outputs.
"""

import logging
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from pydantic import JsonValue

from backend.app.domain.entities import BookInvoice, GroupKey, ReconException, TwoBEntry
from backend.app.domain.enums import ExceptionType, TaxHead
from backend.app.domain.money import to_money

logger = logging.getLogger(__name__)

AMOUNT_TOLERANCE = Decimal("1.00")
"""Fixed matcher tolerance. The firm's own rounding preference is learned, not coded."""
CORE_MATCH_FLOOR = Decimal("50.00")
CORE_MATCH_SHARE = Decimal("0.02")


class MatcherError(ValueError):
    """Raised when inputs break the matcher's contract."""


class MatchPass(StrEnum):
    EXACT = "EXACT"
    """P1: same GSTIN, same normalized invoice number."""
    CORE = "CORE"
    """P2: same GSTIN, same trailing number, close totals, one candidate only."""
    CROSS_GSTIN = "CROSS_GSTIN"
    """P3: same invoice under a different GSTIN."""
    CARRY_FORWARD = "CARRY_FORWARD"
    """P4: an earlier MISSING_IN_2B invoice finally reported."""
    LEFTOVER = "LEFTOVER"
    """P5: nothing matched."""


class Detail(StrEnum):
    """Keys of `ReconException.details`. Amounts are strings, like all JSON money."""

    INVOICE_NO = "invoice_no"
    INVOICE_DATE = "invoice_date"
    SUPPLIER_NAME = "supplier_name"
    BOOK_TOTAL = "book_total"
    BOOK_GST = "book_gst"
    BOOK_TAX_HEAD = "book_tax_head"
    TWOB_TOTAL = "twob_total"
    TWOB_TAX_HEAD = "twob_tax_head"
    AMOUNT_DIFF = "amount_diff"
    BOOK_GSTIN = "book_gstin"
    TWOB_GSTIN = "twob_gstin"
    SUPPLIER_PERIOD = "supplier_period"
    ITC_UNAVAILABLE_REASON = "itc_unavailable_reason"


# --- Normalization (§4) ------------------------------------------------------

_FINANCIAL_YEAR = re.compile(r"(?<![A-Z0-9])(FY[-/ ]?)?(?:20)?(\d{2})([-/ ]?)(?:20)?(\d{2})(?!\d)")
_NOT_ALPHANUMERIC = re.compile(r"[^A-Z0-9]")
_DIGIT_RUN = re.compile(r"\d+")


def _drop_financial_year(match: re.Match[str]) -> str:
    prefix, start, separator, end = match.groups()
    consecutive = int(end) == (int(start) + 1) % 100
    # "0412" is an invoice number, "2526" alone is ambiguous: only strip a
    # year pair that is marked as one by an "FY" prefix or a separator.
    return "" if consecutive and (prefix or separator) else match.group()


def norm_full(invoice_no: str) -> str:
    """`RS/2025-26/0412` → `RS412`, `KL-889` → `KL889`, `INV/0045` → `INV45`."""
    text = _FINANCIAL_YEAR.sub(_drop_financial_year, invoice_no.strip().upper())
    text = _NOT_ALPHANUMERIC.sub("", text)
    return _DIGIT_RUN.sub(lambda run: str(int(run.group())), text)


def core(invoice_no: str) -> str:
    """The last digit run of `norm_full`: `INV/0045` → `45`. Empty if there are no digits."""
    runs = _DIGIT_RUN.findall(norm_full(invoice_no))
    return runs[-1] if runs else ""


# --- Result ------------------------------------------------------------------


@dataclass(frozen=True)
class Match:
    book: BookInvoice
    twob: TwoBEntry
    matched_by: MatchPass


@dataclass(frozen=True)
class LateArrival:
    """An earlier MISSING_IN_2B exception closed by an entry in this period's 2B."""

    exception: ReconException
    twob: TwoBEntry


@dataclass(frozen=True)
class ExceptionGroup:
    """The unit the agent and the accountant decide on (§7)."""

    key: GroupKey
    exceptions: tuple[ReconException, ...]

    @property
    def itc_at_risk(self) -> Decimal:
        return sum((e.itc_at_risk for e in self.exceptions), Decimal("0.00"))


@dataclass(frozen=True)
class MatchResult:
    matched: tuple[Match, ...]
    """Every paired invoice, clean or not; problems on a pair are in `exceptions`."""
    exceptions: tuple[ReconException, ...]
    late_arrivals: tuple[LateArrival, ...]
    pass_counts: Mapping[MatchPass, int] = field(default_factory=dict)

    @property
    def type_counts(self) -> Counter[ExceptionType]:
        return Counter(e.type for e in self.exceptions)

    @property
    def groups(self) -> list[ExceptionGroup]:
        return group_exceptions(self.exceptions)


# --- Reconcile ---------------------------------------------------------------


def reconcile(
    client_id: str,
    period: str,
    books: Sequence[BookInvoice],
    twob: Sequence[TwoBEntry],
    open_missing: Sequence[ReconException] = (),
) -> MatchResult:
    """Match one client-period. `open_missing`: unresolved MISSING_IN_2B from earlier periods."""
    _check_inputs(client_id, period, books, twob, open_missing)
    run = _Run(client_id, period, list(books), list(twob))

    run.pair(MatchPass.EXACT, _exact_pairs)
    run.pair(MatchPass.CORE, _core_pairs)
    run.cross_gstin()
    run.carry_forward(open_missing)
    run.leftovers()

    return MatchResult(
        matched=tuple(run.matched),
        exceptions=tuple(run.exceptions),
        late_arrivals=tuple(run.late_arrivals),
        pass_counts={p: run.counts[p] for p in MatchPass},
    )


def group_exceptions(exceptions: Iterable[ReconException]) -> list[ExceptionGroup]:
    """Group by key; largest ITC at risk first, ties broken by key for stable output."""
    grouped: dict[GroupKey, list[ReconException]] = defaultdict(list)
    for exception in exceptions:
        grouped[exception.group_key].append(exception)
    groups = [ExceptionGroup(key, tuple(items)) for key, items in grouped.items()]
    return sorted(groups, key=lambda g: (-g.itc_at_risk, str(g.key)))


def _check_inputs(
    client_id: str,
    period: str,
    books: Sequence[BookInvoice],
    twob: Sequence[TwoBEntry],
    open_missing: Sequence[ReconException],
) -> None:
    rows: list[BookInvoice | TwoBEntry] = [*books, *twob]
    for row in rows:
        if (row.client_id, row.period) != (client_id, period):
            raise MatcherError(
                f"row for {row.client_id} {row.period} passed to {client_id} {period}"
            )
    for exception in open_missing:
        if exception.client_id != client_id or exception.type is not ExceptionType.MISSING_IN_2B:
            raise MatcherError(f"not an open MISSING_IN_2B of {client_id}: {exception.group_key}")
        if exception.period >= period:
            raise MatcherError(f"open exception from {exception.period} is not before {period}")
        if Detail.INVOICE_NO not in exception.details:
            raise MatcherError(f"open exception has no {Detail.INVOICE_NO}: {exception.group_key}")


PairFinder = Callable[[list[BookInvoice], list[TwoBEntry]], list[tuple[BookInvoice, TwoBEntry]]]


class _Run:
    """Mutable state of one `reconcile` call: what is still unmatched, and what was found."""

    def __init__(
        self, client_id: str, period: str, books: list[BookInvoice], twob: list[TwoBEntry]
    ) -> None:
        self.client_id = client_id
        self.period = period
        self.books = books
        self.twob = twob
        self.matched: list[Match] = []
        self.exceptions: list[ReconException] = []
        self.late_arrivals: list[LateArrival] = []
        self.counts: Counter[MatchPass] = Counter()

    def pair(self, matched_by: MatchPass, find: PairFinder) -> None:
        pairs = find(self.books, self.twob)
        self._consume(pairs)
        for book, entry in pairs:
            self.matched.append(Match(book, entry, matched_by))
            self._record(self._check_pair(book, entry))
        self.counts[matched_by] += len(pairs)

    def cross_gstin(self) -> None:
        pairs = _cross_gstin_pairs(self.books, self.twob)
        self._consume(pairs)
        for book, entry in pairs:
            self._record(
                self._exception(
                    ExceptionType.GSTIN_MISMATCH,
                    entry.supplier_gstin,  # the real supplier
                    _gst(book),
                    book=book,
                    twob=entry,
                    book_gstin=book.supplier_gstin,
                    twob_gstin=entry.supplier_gstin,
                )
            )
        self.counts[MatchPass.CROSS_GSTIN] += len(pairs)

    def carry_forward(self, open_missing: Sequence[ReconException]) -> None:
        waiting: dict[tuple[str, str], list[ReconException]] = defaultdict(list)
        for exception in open_missing:
            invoice_no = str(exception.details[Detail.INVOICE_NO])
            waiting[(exception.vendor_gstin, norm_full(invoice_no))].append(exception)

        for entry in list(self.twob):
            candidates = waiting.get((entry.supplier_gstin, norm_full(entry.invoice_no)))
            if not candidates:
                continue
            closed = candidates.pop(0)
            self.twob.remove(entry)
            self.late_arrivals.append(LateArrival(closed, entry))
            # Q2: a late invoice is still checked, and any problem is raised now.
            self._record(self._check_late(closed, entry))
        self.counts[MatchPass.CARRY_FORWARD] += len(self.late_arrivals)

    def leftovers(self) -> None:
        for book in self.books:
            self._record(
                self._exception(
                    ExceptionType.MISSING_IN_2B, book.supplier_gstin, _gst(book), book=book
                )
            )
        for entry in self.twob:
            self._record(
                self._exception(
                    ExceptionType.MISSING_IN_BOOKS, entry.supplier_gstin, _gst(entry), twob=entry
                )
            )
        self.counts[MatchPass.LEFTOVER] += len(self.books) + len(self.twob)
        self.books, self.twob = [], []

    def _check_pair(self, book: BookInvoice, entry: TwoBEntry) -> ReconException | None:
        """Checks on a matched pair (§5); the first that applies wins."""
        vendor = entry.supplier_gstin
        if not entry.itc_available:
            return self._exception(
                ExceptionType.ITC_INELIGIBLE, vendor, _gst(entry), book=book, twob=entry
            )
        if book.tax_head is not entry.tax_head:
            return self._exception(
                ExceptionType.TAX_HEAD_MISMATCH, vendor, _gst(book), book=book, twob=entry
            )
        if abs(book.total - entry.total) > AMOUNT_TOLERANCE:
            return self._exception(
                ExceptionType.AMOUNT_MISMATCH,
                vendor,
                abs(_gst(book) - _gst(entry)),
                book=book,
                twob=entry,
                amount_diff=_money(entry.total - book.total),
            )
        return None

    def _check_late(self, closed: ReconException, entry: TwoBEntry) -> ReconException | None:
        """The same checks, using the book figures the old exception carried."""
        book_total = _detail_money(closed, Detail.BOOK_TOTAL)
        book_gst = _detail_money(closed, Detail.BOOK_GST)
        vendor = entry.supplier_gstin
        if not entry.itc_available:
            return self._exception(ExceptionType.ITC_INELIGIBLE, vendor, _gst(entry), twob=entry)
        if closed.details.get(Detail.BOOK_TAX_HEAD) != _head(entry.tax_head):
            return self._exception(ExceptionType.TAX_HEAD_MISMATCH, vendor, book_gst, twob=entry)
        if abs(book_total - entry.total) > AMOUNT_TOLERANCE:
            return self._exception(
                ExceptionType.AMOUNT_MISMATCH,
                vendor,
                abs(book_gst - _gst(entry)),
                twob=entry,
                amount_diff=_money(entry.total - book_total),
            )
        return None

    def _consume(self, pairs: list[tuple[BookInvoice, TwoBEntry]]) -> None:
        paired_books = {id(book) for book, _ in pairs}
        paired_entries = {id(entry) for _, entry in pairs}
        self.books = [b for b in self.books if id(b) not in paired_books]
        self.twob = [e for e in self.twob if id(e) not in paired_entries]

    def _record(self, exception: ReconException | None) -> None:
        if exception is not None:
            self.exceptions.append(exception)

    def _exception(
        self,
        type_: ExceptionType,
        vendor_gstin: str,
        itc_at_risk: Decimal,
        *,
        book: BookInvoice | None = None,
        twob: TwoBEntry | None = None,
        **extra: JsonValue,
    ) -> ReconException:
        details: dict[str, JsonValue] = {}
        if book is not None:
            details |= _book_details(book)
        if twob is not None:
            details |= _twob_details(twob, include_identity=book is None)
        details |= extra
        return ReconException(
            client_id=self.client_id,
            period=self.period,
            type=type_,
            vendor_gstin=vendor_gstin,
            book_invoice_id=book.id if book else None,
            twob_entry_id=twob.id if twob else None,
            itc_at_risk=itc_at_risk,
            details=details,
        )


# --- Passes ------------------------------------------------------------------


def _exact_pairs(
    books: list[BookInvoice], twob: list[TwoBEntry]
) -> list[tuple[BookInvoice, TwoBEntry]]:
    """P1. With duplicate numbers only the earliest of each side pairs; the rest fall through."""
    entries: dict[tuple[str, str], list[TwoBEntry]] = defaultdict(list)
    for entry in twob:
        entries[(entry.supplier_gstin, norm_full(entry.invoice_no))].append(entry)

    pairs = []
    taken: set[tuple[str, str]] = set()
    for book in sorted(books, key=lambda b: b.supplier_invoice_date):
        key = (book.supplier_gstin, norm_full(book.supplier_invoice_no))
        if key not in entries:
            continue
        if key in taken:
            logger.warning("duplicate invoice %s from %s in %s", key[1], key[0], book.period)
            continue
        taken.add(key)
        pairs.append((book, min(entries[key], key=lambda e: e.invoice_date)))
    return _in_book_order(pairs, books)


def _core_pairs(
    books: list[BookInvoice], twob: list[TwoBEntry]
) -> list[tuple[BookInvoice, TwoBEntry]]:
    """P2. Pairs only when each side has exactly one candidate: never guess."""

    def candidates(book: BookInvoice) -> list[TwoBEntry]:
        number = core(book.supplier_invoice_no)
        if not number:
            return []
        return [
            e
            for e in twob
            if e.supplier_gstin == book.supplier_gstin
            and core(e.invoice_no) == number
            and abs(book.total - e.total) <= _core_tolerance(book.total)
        ]

    return _unambiguous(books, candidates)


def _cross_gstin_pairs(
    books: list[BookInvoice], twob: list[TwoBEntry]
) -> list[tuple[BookInvoice, TwoBEntry]]:
    """P3. Same invoice under another GSTIN, again only when unambiguous."""

    def candidates(book: BookInvoice) -> list[TwoBEntry]:
        number = norm_full(book.supplier_invoice_no)
        return [
            e
            for e in twob
            if e.supplier_gstin != book.supplier_gstin
            and norm_full(e.invoice_no) == number
            and abs(book.total - e.total) <= AMOUNT_TOLERANCE
        ]

    return _unambiguous(books, candidates)


def _unambiguous(
    books: list[BookInvoice], candidates: Callable[[BookInvoice], list[TwoBEntry]]
) -> list[tuple[BookInvoice, TwoBEntry]]:
    """Pairs a book invoice only if it has one candidate and no other book claims it."""
    options = {id(book): candidates(book) for book in books}
    claims = Counter(id(entry) for found in options.values() for entry in found)
    return [
        (book, found[0])
        for book in books
        if len(found := options[id(book)]) == 1 and claims[id(found[0])] == 1
    ]


def _core_tolerance(total: Decimal) -> Decimal:
    return max(CORE_MATCH_FLOOR, to_money(total * CORE_MATCH_SHARE))


def _in_book_order(
    pairs: list[tuple[BookInvoice, TwoBEntry]], books: list[BookInvoice]
) -> list[tuple[BookInvoice, TwoBEntry]]:
    position = {id(book): i for i, book in enumerate(books)}
    return sorted(pairs, key=lambda pair: position[id(pair[0])])


# --- Helpers -----------------------------------------------------------------


def _gst(invoice: BookInvoice | TwoBEntry) -> Decimal:
    """ITC at stake on an invoice (§6): CGST + SGST + IGST."""
    return invoice.cgst + invoice.sgst + invoice.igst


def _head(head: TaxHead | None) -> str | None:
    return head.value if head else None


def _money(amount: Decimal) -> str:
    return f"{to_money(amount):.2f}"


def _detail_money(exception: ReconException, key: Detail) -> Decimal:
    try:
        return to_money(str(exception.details[key]))
    except KeyError as exc:
        raise MatcherError(f"open exception has no {key}: {exception.group_key}") from exc


def _book_details(book: BookInvoice) -> dict[str, JsonValue]:
    return {
        Detail.INVOICE_NO: book.supplier_invoice_no,
        Detail.INVOICE_DATE: book.supplier_invoice_date.isoformat(),
        Detail.SUPPLIER_NAME: book.supplier_name,
        Detail.BOOK_TOTAL: _money(book.total),
        Detail.BOOK_GST: _money(_gst(book)),
        Detail.BOOK_TAX_HEAD: _head(book.tax_head),
    }


def _twob_details(entry: TwoBEntry, *, include_identity: bool) -> dict[str, JsonValue]:
    details: dict[str, JsonValue] = {
        Detail.TWOB_TOTAL: _money(entry.total),
        Detail.TWOB_TAX_HEAD: _head(entry.tax_head),
        Detail.SUPPLIER_PERIOD: entry.supplier_period,
    }
    if entry.itc_unavailable_reason:
        details[Detail.ITC_UNAVAILABLE_REASON] = entry.itc_unavailable_reason
    if include_identity:
        details |= {
            Detail.INVOICE_NO: entry.invoice_no,
            Detail.INVOICE_DATE: entry.invoice_date.isoformat(),
            Detail.SUPPLIER_NAME: entry.supplier_name,
        }
    return details

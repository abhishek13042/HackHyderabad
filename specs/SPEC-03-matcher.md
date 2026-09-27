# SPEC-03 — Matcher

**Status:** DONE · **Owner:** A · **Depends on:** SPEC-01, SPEC-02

## 1. Purpose

Deterministically compare a client's purchase register with GSTR-2B for one
period and produce: matched pairs, exceptions, and **late arrivals** (earlier
missing invoices that finally showed up). No LLM is used here — numbers must be
exact and reproducible.

## 2. Scope

**In:** normalization, 5 matching passes, classification, ITC-at-risk, grouping.
**Out:** deciding what to do (SPEC-05), memory (SPEC-04).

## 3. Interface

Implemented in `backend/app/matcher.py`.

```python
def reconcile(
    client_id: str,
    period: str,                             # "2026-03"
    books: Sequence[BookInvoice],            # this period's purchase register
    twob: Sequence[TwoBEntry],               # this period's GSTR-2B
    open_missing: Sequence[ReconException],  # unresolved MISSING_IN_2B from earlier periods
) -> MatchResult

@dataclass(frozen=True)
class MatchResult:
    matched: tuple[Match, ...]               # (book, 2B, pass): every pair, clean or not
    exceptions: tuple[ReconException, ...]
    late_arrivals: tuple[LateArrival, ...]   # (old exception, 2B entry that closed it)
    pass_counts: Mapping[MatchPass, int]
    type_counts: Counter[ExceptionType]      # property
    groups: list[ExceptionGroup]             # property, §7
```

Pure function: no DB, no network. The API layer loads inputs and saves outputs.
Inputs from another client or period, or an `open_missing` item that isn't an
earlier MISSING_IN_2B of this client, raise `MatcherError`.

### Exception details
`ReconException.details` carries what later steps need, so they never re-read
invoices (keys are the `Detail` enum; money as strings, D11):

| Key | On |
|---|---|
| `invoice_no`, `invoice_date`, `supplier_name` | all |
| `book_total`, `book_gst`, `book_tax_head` | exceptions with a book side |
| `twob_total`, `twob_tax_head`, `supplier_period`, `itc_unavailable_reason` | exceptions with a 2B side |
| `amount_diff` (2B − books) | AMOUNT_MISMATCH |
| `book_gstin`, `twob_gstin` | GSTIN_MISMATCH |

P4 relies on this: an open MISSING_IN_2B is matched by its `invoice_no`, and
the late entry is checked against its `book_total` / `book_gst` / `book_tax_head`.

## 4. Normalization

```
norm_full(inum):
  1. uppercase, trim
  2. remove financial-year tokens: 2025-26, 2025-2026, 25-26, FY25-26, FY2526
  3. keep only A–Z 0–9
     (only when marked as a year pair by an FY prefix or a separator, and the
      years are consecutive: "0412" and "45/12" are kept)
  4. strip leading zeros from every digit run        ("0045" → "45")
  e.g. "RS/2025-26/0412" → "RS412", "KL-889" → "KL889", "INV/0045" → "INV45"

core(inum):
  the last digit run of norm_full                    ("INV45" → "45", "45" → "45")
```

## 5. Passes (in this order; each pass only sees items unmatched by earlier passes)

| # | Name | Match condition | Result |
|---|---|---|---|
| P1 | Exact | same `supplier_gstin` and same `norm_full` | matched pair |
| P2 | Core | same `supplier_gstin`, same `core`, totals within max(₹50, 2%), **exactly one** candidate | matched pair |
| P3 | Cross-GSTIN | leftover book vs leftover 2B: same `norm_full`, totals within ₹1.00, different GSTIN, **exactly one** candidate | `GSTIN_MISMATCH` |
| P4 | Carry-forward | leftover 2B vs `open_missing` (same GSTIN, same `norm_full`) | `LateArrival` (closes old exception); the pair checks below still run, raising any problem in the **current** period (Q2) |
| P5 | Leftovers | leftover books → `MISSING_IN_2B`; leftover 2B → `MISSING_IN_BOOKS` | exceptions |

### Checks on matched pairs (first that applies wins — one exception per invoice)
1. 2B `itc_available == false` → `ITC_INELIGIBLE`
2. books head ≠ 2B head (IGST vs CGST+SGST) → `TAX_HEAD_MISMATCH`
3. |books.total − 2B.total| > ₹1.00 → `AMOUNT_MISMATCH` (`details.amount_diff`)
4. otherwise clean match

₹1.00 is the matcher's fixed tolerance. The **firm's** rounding preference
(e.g. "accept under ₹10") is learned by the agent, not hard-coded here.

## 6. ITC at risk

| Type | itc_at_risk |
|---|---|
| MISSING_IN_2B, GSTIN_MISMATCH | books cgst+sgst+igst |
| TAX_HEAD_MISMATCH | books cgst+sgst+igst |
| AMOUNT_MISMATCH | abs(books tax − 2B tax) |
| ITC_INELIGIBLE | 2B cgst+sgst+igst |
| MISSING_IN_BOOKS | 2B cgst+sgst+igst (credit the client is missing out on) |

## 7. Grouping

`group_key = f"{client_id}:{period}:{vendor_gstin}:{type}"`.
For `GSTIN_MISMATCH` the vendor is the one from the 2B side (the real supplier).
A group's `itc_at_risk` = sum of its exceptions. Groups are sorted by
`itc_at_risk` descending for the UI.

## 8. Edge cases

- Duplicate invoice numbers from the same vendor in one period → P1 matches the first by date, the second falls to P2 / leftovers. Log a warning.
- P2 with 2+ candidates → no match (don't guess); items fall through.
- 2B entry for a GSTIN the firm has never seen → still a `MISSING_IN_BOOKS` exception; vendor auto-created as `ACTIVE`.
- Empty books or empty 2B → all items become exceptions; no crash.
- Rounding: compare using `Decimal`, quantized to 0.01.

## 9. Acceptance criteria

| ID | Given | Expect |
|---|---|---|
| AC-03-1 | books `KL-889`, 2B `KL889`, same GSTIN and total | matched in P1 |
| AC-03-2 | books `INV/0045`, 2B `45`, totals ₹47,200 / ₹47,201 | matched in P2, no exception (diff ≤ ₹1) |
| AC-03-3 | same as 2 but 2B total ₹47,205 | `AMOUNT_MISMATCH`, `amount_diff = 5.00` |
| AC-03-4 | books CGST+SGST, 2B IGST, same invoice | `TAX_HEAD_MISMATCH` |
| AC-03-5 | 2B `itcavl = N` | `ITC_INELIGIBLE` (even if amounts differ) |
| AC-03-6 | book invoice with no 2B counterpart | `MISSING_IN_2B`, itc_at_risk = its tax |
| AC-03-7 | Jan `MISSING_IN_2B` open; Feb 2B contains it | one `LateArrival`, no Feb exception for it |
| AC-03-8 | same invoice, books GSTIN has one wrong char | `GSTIN_MISMATCH` |
| AC-03-9 | P2 with two candidates | no match; both fall through |
| AC-03-10 | full generated dataset, all 12 client-periods | group keys == ground truth group keys (SPEC-02 AC-02-3) |
| AC-03-11 | same inputs twice | identical output |
| AC-03-12 | ~90 invoices | runs in < 1 s |

## 10. Open questions

- ~~Q1~~: P2 tolerance **max(₹50, 2%)** — accepted (D7).
- ~~Q2~~: A late arrival with a difference raises the exception **in the current period** — resolved: yes.

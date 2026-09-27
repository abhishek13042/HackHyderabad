# SPEC-02 — Synthetic Data Generator

**Status:** DONE · **Owner:** B · **Depends on:** SPEC-01

## 1. Purpose

Produce realistic purchase registers and GSTR-2B files for 3 clients over 4
months, with **planted vendor behaviours** the agent should learn, and a
**ground-truth file** with the correct answer for every exception group.
This data drives the demo, the seed memory and the evals.

## 2. Scope

**In:** B2B purchase invoices, 3 clients, ~25 vendors, periods `2026-01` … `2026-04`,
ground truth, simulated accountant notes.
**Out:** credit/debit notes, reverse charge, imports, cess (always 0), PDFs.

## 3. Outputs

```
data/generated/
├── firm.json                     firm + clients
├── vendors.json                  vendors (incl. archetype — generator/eval only)
├── ground_truth.json             labels per exception group (§7)
└── {client_id}/{period}/
    ├── purchase_register.csv     Tally-style export (§5)
    └── gstr2b.json               2B in portal-like JSON (§6)
```

Run: `python -m backend.scripts.generate_data --seed 42 --out data/generated`
Same seed ⇒ byte-identical output.

## 4. Cast

### Firm & clients (all in Telangana, state `36`)
| ID | Name | Business | Invoices / month |
|---|---|---|---|
| C01 | Sri Balaji Textiles | Textile trader, Begum Bazaar | ~30 |
| C02 | Spice Route Restaurant | Restaurant, Gachibowli | ~35 |
| C03 | Vega Electronics Distributors | Electronics distributor, Secunderabad | ~25 |

### Planted vendors
| Vendor | State | Clients | Archetype | Behaviour |
|---|---|---|---|---|
| Reddy Steels | 36 | C01 | `LATE_FILER_THEN_DRIFT` | Jan, Feb invoices appear in the **next** month's 2B. From Mar, **stops filing**: Mar and Apr invoices never appear |
| Bhavani Chemicals | 36 | C02 | `LATE_FILER_CONSISTENT` | Every month's invoices appear in the next month's 2B |
| Laxmi Packaging | 36 | C01, C02 | `ROUNDING` | Every invoice's 2B total differs by ₹2–₹9 |
| Sai Electricals | 36 | C03 | `WRONG_BUYER_GSTIN` | Jan and Mar: files with a typo in the buyer GSTIN → missing from our 2B; amends → appears next month. Feb, Apr normal |
| Mumbai Threads | 27 | C01 | `INTERSTATE_BOOKING_ERROR` | 2B correctly shows IGST; C01's bookkeeper books CGST+SGST every month |
| Krishna Logistics | 36 | C01 (Jan–Apr), C03 (from Mar) | `NON_FILER_CROSS_CLIENT` | Never files. Nothing ever appears in 2B |
| Om Sai Enterprises | 36 | C02 (Jan–Mar) | `CANCELLED` | Registration cancelled retrospectively from Feb: Feb, Mar invoices appear with `itcavl = N`. C02 stops buying in Apr |
| Ganesh Traders | 36 | C02 | `UNBOOKED` | One invoice per month is in 2B but missing from C02's books |
| Venkateswara Components | 29 | C03 | `BOOKS_GSTIN_TYPO` | Feb, Apr: C03's bookkeeper types the supplier GSTIN with one wrong character |
| Deccan Power Solutions | 36 | C03 | `AMBIGUOUS` | Apr only: one invoice appears in 2B at ~90% of the booked value; the client says it is disputed. No history to go on (Q2) |

### Reliable vendors
~16 vendors (mix of `36`, `27`, `29`, `33`), spread across clients, always file
on time, always match **after** invoice-number normalization. Realistic
Hyderabad trade names (e.g. "Charminar Fabrics", "Kukatpally Kitchen Equipment").

## 5. Purchase register CSV

Columns (header row, in this order):
```
voucher_date,voucher_no,supplier_invoice_no,supplier_invoice_date,supplier_name,
supplier_gstin,place_of_supply,hsn,taxable_value,cgst,sgst,igst,cess,total
```
- Dates `DD-MM-YYYY`. Money with 2 decimals.
- `voucher_no` = client's internal number (`PUR/0001`…).
- Tax heads follow SPEC-01 §4 **except** planted booking errors.

## 6. GSTR-2B JSON (simplified from the portal format)

```json
{
  "data": {
    "gstin": "<client gstin>",
    "rtnprd": "032026",
    "gendt": "14-04-2026",
    "docdata": {
      "b2b": [
        {
          "ctin": "<supplier gstin>",
          "trdnm": "SUPPLIER NAME",
          "supprd": "032026",
          "supfildt": "11-04-2026",
          "inv": [
            {
              "inum": "KL889", "dt": "07-03-2026", "val": 29500.00,
              "typ": "R", "pos": "36", "rev": "N",
              "itcavl": "Y", "rsn": "",
              "txval": 25000.00, "igst": 0, "cgst": 2250.00, "sgst": 2250.00, "cess": 0
            }
          ]
        }
      ]
    }
  }
}
```
- On-time suppliers: `supfildt` = 11th of the next month.
- Late invoices appear in the **next** period's 2B, with the original `dt` and a later `supfildt`.
- `itcavl = "N"` rows carry `rsn` (e.g. `"Supplier registration cancelled retrospectively"`).

### Invoice number formats
Each vendor has a **books format** and a **2B format** that normalize to the
same key (SPEC-03 §4). Examples:

| Books (as typed by client) | 2B (as filed by vendor) |
|---|---|
| `RS/2025-26/0412` | `RS/2025-26/0412` |
| `KL-889` | `KL889` |
| `INV/0045` | `45` |
| `SE-2231` | `SE/2231` |

## 7. Ground truth (`ground_truth.json`)

One entry per **exception group** (`client:period:vendor:type`), labelled with
what an expert would do **given only what was knowable at that time**.

```json
{
  "group_key": "C01:2026-02:36AABCR1234F1Z5:MISSING_IN_2B",
  "archetype": "LATE_FILER_THEN_DRIFT",
  "best_action": "DEFER",
  "acceptable_actions": ["DEFER"],
  "accountant_action": "DEFER",
  "root_cause": "LATE_FILING",
  "flags": [],
  "accountant_note": "Jan invoice showed up in Feb 2B. They're just late. Deferring."
}
```

- `best_action`: what an expert should do; used to score the agent (SPEC-09).
- `accountant_action`: what the simulated accountant actually does (SPEC-04 §12). It
  differs from `best_action` only where a cautious accountant is also right, e.g.
  holding payment rather than chasing. It is always in `acceptable_actions`.

### Label table
| Vendor / client | Jan | Feb | Mar | Apr |
|---|---|---|---|---|
| Reddy Steels / C01 | CHASE_VENDOR · UNKNOWN | DEFER · LATE_FILING | DEFER · LATE_FILING · RECURRING | **CHASE_VENDOR** (acc. HOLD_PAYMENT) · NOT_FILED · **PATTERN_DRIFT** |
| Bhavani Chemicals / C02 | CHASE_VENDOR · UNKNOWN | DEFER · LATE_FILING | DEFER · LATE_FILING · RECURRING | DEFER · LATE_FILING · RECURRING |
| Laxmi Packaging / C01, C02 | ACCEPT · ROUNDING | ACCEPT · ROUNDING | ACCEPT · ROUNDING · RECURRING | ACCEPT · ROUNDING · RECURRING |
| Sai Electricals / C03 | CHASE_VENDOR · UNKNOWN | — | CHASE_VENDOR · **WRONG_BUYER_GSTIN** | — |
| Mumbai Threads / C01 | CORRECT_BOOKS · BOOKING_ERROR | CORRECT_BOOKS · BOOKING_ERROR | + RECURRING | + RECURRING |
| Krishna Logistics / C01 | CHASE_VENDOR · UNKNOWN | CHASE_VENDOR (acc. HOLD_PAYMENT) · NOT_FILED | HOLD_PAYMENT · NOT_FILED · RECURRING | HOLD_PAYMENT · NOT_FILED · RECURRING |
| Krishna Logistics / C03 | — | — | **HOLD_PAYMENT** · NOT_FILED · **CROSS_CLIENT_RISK** | HOLD_PAYMENT · NOT_FILED · CROSS_CLIENT_RISK |
| Om Sai Enterprises / C02 | — | BLOCK_ITC · SUPPLIER_CANCELLED · VENDOR_RISK | BLOCK_ITC · SUPPLIER_CANCELLED · VENDOR_RISK | — |
| Ganesh Traders / C02 | BOOK_INVOICE · NOT_BOOKED | BOOK_INVOICE · NOT_BOOKED | + RECURRING | + RECURRING |
| Venkateswara Components / C03 | — | CORRECT_BOOKS · BOOKING_ERROR | — | CORRECT_BOOKS · BOOKING_ERROR |
| Deccan Power Solutions / C03 | — | — | — | **ESCALATE** (also CHASE_VENDOR) · UNKNOWN |

`RECURRING_ISSUE` = same vendor + same exception type in ≥ 2 **prior** periods (any client).
It is computed by this rule, not hand-labelled, so it also lands on Reddy Steels in Apr and
on Krishna Logistics / C03 (whose C01 history counts).

### Accountant notes
Each label carries a realistic note the simulated accountant "types" when
resolving. Notes are the main source of learnable knowledge, e.g.:
- Reddy Steels, Jan: *"Called Reddy Steels. Their accountant Suresh says they file GSTR-1 around the 12th of the following month. Will re-check next 2B."*
- Laxmi Packaging, Jan: *"₹5 difference, rounding on their side. We accept anything under ₹10."*
- Sai Electricals, Jan: *"Sai Electricals had typed our GSTIN wrong in GSTR-1. They amended it."*
- Krishna Logistics, Feb: *"Second month no filing. Emails ignored. Asked client to hold GST portion of payment."*

Notes must **never** contain the archetype name or the words "planted", "synthetic", "test".

## 8. Rules

- R1: Deterministic given `--seed`.
- R2: All GSTINs valid per SPEC-01 §3 (except the deliberate typo cases, which are still *valid-format* GSTINs of a non-existent business).
- R3: ~85% of invoices per client-month are clean matches after normalization.
- R4: Amounts: taxable value ₹2,000–₹2,50,000, rounded to whole rupees; GST at the vendor's rate (5% or 18%, illustrative).
- R5: Every planted behaviour in §4 produces exactly the exception groups in §7. The generator derives the expected groups from its own plan and refuses to build if any label cell is missing or unused. The independent check against the real matcher is AC-03-10 (SPEC-03).

## 9. Edge cases

- A vendor with 0 invoices for a client in a month produces no group (the "—" cells).
- Late invoices must never be counted twice (once late-matched, they close the old exception).

## 10. Acceptance criteria

- AC-02-1: Running twice with the same seed gives identical files (hash compare).
- AC-02-2: All non-typo GSTINs pass the validator; typo GSTINs have the correct check digit but don't match any vendor.
- AC-02-3: The set of exception groups the matcher finds equals the set of `group_key`s in `ground_truth.json` (no missing, no extra).
- AC-02-4: Every ground-truth `best_action` is in its own `acceptable_actions`.
- AC-02-5: No note contains a forbidden word (R-check in the generator).
- AC-02-6: Files parse back through `backend/app/ingest.py` into exactly the generated rows. The upload endpoint reuses those parsers; its own test lives in SPEC-07.

## 11. Open questions

- ~~Q1~~: Add May 2B? **Resolved: no** — April is the "live" demo month.
- ~~Q2~~: Ambiguous "noise" exceptions? **Resolved: yes**, one — Deccan Power Solutions, C03, Apr (D8).

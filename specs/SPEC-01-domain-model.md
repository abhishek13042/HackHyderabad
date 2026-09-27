# SPEC-01 — Domain & Data Model

**Status:** DONE · **Owner:** Both · **Depends on:** SPEC-00

## 1. Purpose

One source of truth for the GST concepts, entities, enums and database tables
that every other spec uses. If a spec needs a new value, it is added here first.

## 2. GST concepts (plain words)

| Term | Meaning |
|---|---|
| **GSTIN** | 15-char GST registration number of a business |
| **ITC** | Input Tax Credit — GST paid on purchases that can be offset against GST owed |
| **Purchase register** | The client's own record of purchases (exported from Tally) |
| **GSTR-1** | Return where a **supplier** reports its sales invoices |
| **GSTR-2B** | Auto-generated monthly statement for the **buyer**, listing invoices suppliers reported. ITC is claimable only for invoices in 2B |
| **Period** | A tax month. Internally `YYYY-MM` (e.g. `2026-03`); in 2B JSON `MMYYYY` (`032026`) |
| **CGST + SGST** | Tax heads for **intra-state** supply (same state code), split equally |
| **IGST** | Tax head for **inter-state** supply |
| **Place of supply (POS)** | State code where the supply is consumed; decides the tax head |

## 3. GSTIN

Format: `SS PPPPPPPPPP E Z C`
- `SS` state code (`36` Telangana, `27` Maharashtra, `29` Karnataka, `33` Tamil Nadu)
- `P×10` PAN (5 letters, 4 digits, 1 letter)
- `E` entity number (`1`–`9`, `A`–`Z`)
- `Z` literal
- `C` check character

**Check character algorithm** (used by the generator and a validator):
```
alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
sum = 0
for i, ch in enumerate(gstin[:14]):
    factor = 1 if i % 2 == 0 else 2
    p = alphabet.index(ch) * factor
    sum += p // 36 + p % 36
check = alphabet[(36 - sum % 36) % 36]
```

## 4. Tax head rule

```
expected_head(supplier_state, place_of_supply):
    INTRA (CGST+SGST) if supplier_state == place_of_supply
    INTER (IGST)      otherwise
```
All our clients are in Telangana (`36`), so POS is always `36`.

## 5. Entities

### Firm
| Field | Type | Example |
|---|---|---|
| firm_id | str | `rao-associates` |
| name | str | `Rao & Associates, Chartered Accountants` |

### Client
| Field | Type | Example |
|---|---|---|
| client_id | str | `C01` |
| name | str | `Sri Balaji Textiles` |
| gstin | str | `36AAKFS9876P1Z?` |
| business_type | str | `Textile trader` |

### Vendor
| Field | Type | Notes |
|---|---|---|
| gstin | str | primary key |
| name | str | |
| state_code | str | = gstin[:2] |
| registration_status | `ACTIVE` \| `CANCELLED` | |

The planted `archetype` label is **not** a Vendor field: it exists only in the
generator and ground truth (SPEC-02), so it can never reach the agent.

### BookInvoice (one row of the purchase register)
| Field | Type |
|---|---|
| id | int |
| client_id, period | str |
| voucher_date | date |
| voucher_no | str |
| supplier_invoice_no | str (raw, as typed) |
| supplier_invoice_date | date |
| supplier_name | str |
| supplier_gstin | str |
| place_of_supply | str |
| hsn | str |
| taxable_value, cgst, sgst, igst, cess, total | decimal (₹, 2 dp) |

### TwoBEntry (one invoice in GSTR-2B)
| Field | Type | 2B JSON key |
|---|---|---|
| id | int | |
| client_id, period | str | from `gstin`, `rtnprd` |
| supplier_gstin | str | `ctin` |
| supplier_name | str | `trdnm` |
| supplier_filing_date | date | `supfildt` |
| supplier_period | str | `supprd` |
| invoice_no | str | `inum` |
| invoice_date | date | `dt` |
| total | decimal | `val` |
| place_of_supply | str | `pos` |
| taxable_value, cgst, sgst, igst, cess | decimal | `txval`, `cgst`, `sgst`, `igst`, `cess` |
| itc_available | bool | `itcavl` (`Y`/`N`) |
| itc_unavailable_reason | str? | `rsn` |

### ReconException
| Field | Type |
|---|---|
| id | int |
| client_id, period | str |
| type | `ExceptionType` |
| vendor_gstin | str |
| book_invoice_id | int? |
| twob_entry_id | int? |
| itc_at_risk | decimal — GST amount affected |
| details | json — e.g. `{"amount_diff": 4.0}` |
| group_key | str — `client:period:vendor:type` |

### ExceptionGroup
Exceptions sharing `group_key`. The **agent decides per group** (SPEC-04 §6).

### Suggestion (agent output, per group)
See SPEC-05 §3 for the exact JSON.

### Decision (the accountant's choice, per group)
| Field | Type |
|---|---|
| id | int |
| group_key | str |
| suggested_action | `Action`? (null when memory off / no suggestion) |
| final_action | `Action` |
| accepted_suggestion | bool |
| decided_by | `ACCOUNTANT` \| `AUTO` |
| note | str? |
| decided_at | datetime |

### Outcome (self-check result, SPEC-06)
| Field | Type |
|---|---|
| decision_id | int |
| status | `OutcomeStatus` |
| checked_in_period | str |
| evidence | json |

## 6. Enums

### ExceptionType
| Value | Meaning |
|---|---|
| `MISSING_IN_2B` | In books, not in 2B |
| `MISSING_IN_BOOKS` | In 2B, not in books (unclaimed credit) |
| `AMOUNT_MISMATCH` | Matched, but totals differ by more than ₹1.00 |
| `TAX_HEAD_MISMATCH` | Matched, but IGST vs CGST+SGST differs |
| `GSTIN_MISMATCH` | Same invoice found under a different supplier GSTIN |
| `ITC_INELIGIBLE` | In 2B but `itcavl = N` (e.g. supplier cancelled) |

### Action
| Value | Meaning |
|---|---|
| `ACCEPT` | Accept 2B figures; difference is immaterial |
| `DEFER` | Don't claim this month; re-check next month's 2B |
| `CHASE_VENDOR` | Contact vendor to file / amend GSTR-1 |
| `HOLD_PAYMENT` | Withhold the GST portion of the vendor's payment until it appears in 2B |
| `CORRECT_BOOKS` | Client's entry is wrong; fix the purchase register |
| `BLOCK_ITC` | Don't claim (or reverse) this credit |
| `BOOK_INVOICE` | Invoice missing from books; verify with client and book it |
| `ESCALATE` | Agent can't decide safely; human must review |

### RootCause
`LATE_FILING`, `NOT_FILED`, `WRONG_BUYER_GSTIN`, `ROUNDING`, `BOOKING_ERROR`,
`SUPPLIER_CANCELLED`, `NOT_BOOKED`, `UNKNOWN`

### Flag
| Value | Meaning |
|---|---|
| `CROSS_CLIENT_RISK` | Vendor caused problems for another client of the firm |
| `PATTERN_DRIFT` | Vendor broke its established pattern (SPEC-06) |
| `RECURRING_ISSUE` | Same issue, same vendor, ≥ 2 prior periods |
| `VENDOR_RISK` | Vendor is cancelled / high-risk; consider stopping purchases |

### TrustLevel
`0 OBSERVE` (human decides, suggestion shown as low-confidence) ·
`1 SUGGEST` (confident suggestion, human confirms) ·
`2 AUTO` (auto-resolved, human can review/undo)

### OutcomeStatus
`PENDING`, `VERIFIED_CORRECT`, `VERIFIED_WRONG`, `NOT_APPLICABLE`

## 7. Safety invariants (enforced in code, SPEC-05 §5)

- INV-1: For `MISSING_IN_2B` and `ITC_INELIGIBLE`, `ACCEPT` is never a valid action.
- INV-2: `AUTO` resolution is only allowed for `ACCEPT` and `DEFER`.
- INV-3: Money is stored as integer paise or `Decimal`, never float.

## 8. Database (SQLite)

Tables: `firms`, `clients`, `vendors`, `book_invoices`, `twob_entries`,
`exceptions`, `suggestions`, `decisions`, `outcomes`, `trust` (SPEC-06),
`memory_events` (log of every retain/recall call for the UI panel, SPEC-04 §9),
`runs` (reconciliation runs, SPEC-07), `drift_events` (SPEC-06 §6),
`retain_queue` (retains waiting for Hindsight to come back, SPEC-04 §13).

- Money columns are integer paise named `*_paise`; JSON columns are checked with `json_valid`.
- Enum columns have CHECK constraints generated from the Python enums (declared once).
- `decisions` is append-only: re-deciding or undoing sets `superseded_at` on the old row;
  a partial unique index allows one current decision per group.
- Versioned with `PRAGMA user_version`; no migrations (the demo DB is rebuilt from the seed).

## 8a. Implementation

| Concern | Module |
|---|---|
| Enums (§6) | `backend/app/domain/enums.py` |
| Entities (§5) | `backend/app/domain/entities.py` |
| GSTIN (§3) | `backend/app/domain/gstin.py` |
| Money (INV-3) | `backend/app/domain/money.py` |
| Periods (§2) | `backend/app/domain/periods.py` |
| Tax head (§4) | `backend/app/domain/tax.py` |
| Allowed actions, INV-1, INV-2 (§7) | `backend/app/domain/policy.py` |
| SQLite schema (§8) | `backend/app/db.py` |
| Tests | `backend/tests/domain/`, `backend/tests/test_db.py` |

## 9. Acceptance criteria

- AC-01-1: A GSTIN validator implements §3 and accepts all generated GSTINs, rejects a GSTIN with one changed character.
- AC-01-2: All enums exist in one backend module and are imported (not re-declared) elsewhere.
- AC-01-3: Money fields never use float (checked by a unit test on the models).
- AC-01-4: Invariants INV-1 and INV-2 have unit tests.

## 10. Open questions

- ~~Q1: Is `HOLD_PAYMENT` realistic?~~ Yes — kept.
- ~~Q2: Keep cess always 0?~~ Yes — the field exists, the generator always writes 0.

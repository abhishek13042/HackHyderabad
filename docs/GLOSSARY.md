# Glossary

GST terms as Recon uses them, plus the few words of its own.

## GST

| Term | Meaning |
|---|---|
| **GST** | Goods and Services Tax, India's indirect tax on supplies. |
| **GSTIN** | A 15-character GST registration number: 2-digit state code, the PAN, an entity number, `Z`, and a check character. Recon validates the check character (`domain/gstin.py`). |
| **ITC** | Input Tax Credit: the GST a business paid on its purchases, which it can set off against the GST it owes on its sales. |
| **Purchase register** | The business's own books of purchase invoices. |
| **GSTR-1** | The return in which a *supplier* reports its sales, invoice by invoice. |
| **GSTR-2B** | A monthly, read-only statement generated on the 14th, listing the invoices suppliers reported for the buyer. ITC can normally be claimed only for invoices that appear in it. |
| **GSTR-3B** | The monthly summary return in which the buyer claims ITC and pays tax. |
| **Reconciliation** | Matching the purchase register against GSTR-2B and resolving the differences before filing GSTR-3B. |
| **IGST / CGST / SGST** | Integrated GST (between states) versus Central + State GST (within a state). Booking the wrong heads is a *tax-head mismatch*. |
| **Section 16(2)(aa)** | The rule that ITC is available only if the supplier has reported the invoice (i.e. it is in GSTR-2B). Recon's INV-1 enforces it in code. |
| **Section 17(5)** | Blocked credits, such as food and personal-use items. These appear in GSTR-2B marked *ineligible*. |
| **CA** | Chartered Accountant, usually the one who files for the business and is responsible for it. |
| **FY** | Financial year, April to March. Invoice numbers often carry it, e.g. `RS/2025-26/0782`. |

## Exception types (SPEC-01)

| Type | What it means |
|---|---|
| `MISSING_IN_2B` | In the books, not in GSTR-2B: the supplier hasn't reported it (yet). ITC can't be claimed. |
| `MISSING_IN_BOOKS` | In GSTR-2B, not in the books: an invoice the business forgot to record. |
| `AMOUNT_MISMATCH` | Same invoice, different amounts. |
| `TAX_HEAD_MISMATCH` | Same invoice, IGST booked as CGST+SGST or the other way round. |
| `GSTIN_MISMATCH` | The same invoice found under a different supplier GSTIN: a booking error, or the supplier reported it against the wrong buyer. |
| `ITC_INELIGIBLE` | In GSTR-2B, but marked as not eligible for credit. |

## Actions

| Action | Meaning |
|---|---|
| `ACCEPT` | Take the 2B figure as it is (e.g. a rounding difference). |
| `CHASE_VENDOR` | Ask the supplier to file or correct its GSTR-1. Comes with a drafted message. |
| `DEFER` | Don't claim this month; re-check next month's 2B (for suppliers known to file late). |
| `HOLD_PAYMENT` | Withhold the GST portion of the supplier's payment until the invoice appears in 2B. Comes with a drafted message. |
| `CORRECT_BOOKS` | Fix our own entry (tax head, GSTIN, amount). |
| `BOOK_INVOICE` | Record an invoice that was missing from the books. |
| `BLOCK_ITC` | Don't claim credit for it. |
| `ESCALATE` | Not sure; a senior should look. |

## Recon's own words

| Term | Meaning |
|---|---|
| **Exception group** | All of one vendor's exceptions of one type for one client and month. One suggestion, one decision and one memory per group. |
| **Resolution / Outcome / Drift** | The three kinds of memory (M1, M2, M3). See [HINDSIGHT_USAGE.md](HINDSIGHT_USAGE.md). |
| **Self-check** | Next month's verification of a past decision against the new GSTR-2B. |
| **Trust ladder** | Observe → Suggest → Auto, per vendor and exception type, firm-wide. |
| **Drift** | A vendor breaking its usual pattern, e.g. a late filer that stops filing. |
| **Cross-client risk** | A vendor that caused trouble at one client appearing at another. |
| **Guardrails** | Code checks G1–G8 applied to every model answer. |
| **Memory ON / OFF** | Whether a run recalls memory and may auto-resolve. OFF still records history. |

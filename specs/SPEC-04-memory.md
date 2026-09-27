# SPEC-04 — Memory Layer (Hindsight)

**Status:** DRAFT · **Owner:** Both · **Depends on:** SPEC-01

## 1. Purpose

Give Munshi a long-term memory of **what the firm learned** — resolutions,
outcomes, vendor behaviour, accountant preferences — using Hindsight's
retain / recall / reflect. This is the heart of the product and 25% of the
judging.

> **Principle:** the database stores what happened; memory stores what we learned.

## 2. Scope

**In:** bank setup, memory templates, when to retain, recall queries, reflect
uses, token budget, memory event log, memory ON/OFF semantics, seeding.
**Out:** decision logic (SPEC-05), trust/drift maths (SPEC-06).

## 3. Deployment

- Self-hosted `hindsight-api` (pip) on `http://localhost:8888`, embedded DB.
- Hindsight's own LLM (used for fact extraction and reflect): Groq,
  `HINDSIGHT_API_LLM_PROVIDER=groq`, key in `HINDSIGHT_API_LLM_API_KEY`.
- Switchable to Hindsight Cloud by changing `HINDSIGHT_BASE_URL` and `HINDSIGHT_API_KEY` only.
- Client: `hindsight-client` Python SDK, wrapped in `backend/app/memory.py`.
  **No other module imports the SDK directly.**

## 4. Bank design

**One bank per firm** — so vendor knowledge carries across clients (this is
what makes cross-client alerts possible).

| Bank | Purpose |
|---|---|
| `munshi-rao-associates` | The live/demo bank |
| `eval-{run_id}-{condition}` | Fresh, throwaway banks for evals (SPEC-09) |

```python
create_bank(
  bank_id="munshi-rao-associates",
  name="Munshi — Rao & Associates",
  mission=(
    "You are the institutional memory of Rao & Associates, a Chartered "
    "Accountancy firm in Hyderabad, for GST input-tax-credit reconciliation. "
    "Remember how mismatches between clients' purchase registers and GSTR-2B "
    "were resolved, how each vendor behaves over time, and the accountant's "
    "preferences. Never recommend claiming ITC for an invoice that is absent "
    "from GSTR-2B or marked ineligible."
  ),
  disposition={"skepticism": 4, "literalism": 4, "empathy": 2},
)
```
High skepticism/literalism: this is tax — prefer evidence over assumption.

### How our memories map to Hindsight's four networks
| Hindsight network | Our content |
|---|---|
| World (facts) | "Reddy Steels' March invoices are missing from C01's April 2B" |
| Experience (agent's actions) | "Munshi suggested DEFER; accountant accepted" |
| Observation (entity summaries, built by Hindsight) | "Reddy Steels usually files ~1 month late" |
| Opinion (beliefs with confidence, built by reflect) | "Deferring Reddy Steels is safe — high confidence" → later lowered |

We only **write** facts/experiences; observations and opinions are formed by Hindsight.

## 5. What to retain — and what not

| Retain ✅ | Template | When |
|---|---|---|
| **Resolution** | M1 | Accountant (or AUTO) decides a group |
| **Outcome** | M2 | Self-check verifies a past decision (SPEC-06) |
| **Late arrival** | M2 | A missing invoice finally appears |
| **Drift** | M3 | Vendor breaks its pattern (SPEC-06) |

| Never retain ❌ | Why |
|---|---|
| Clean matched invoices | ~85% of rows, teach nothing |
| Raw rows / files | Live in SQLite |
| Suggestions not acted on | Only decisions carry signal |
| UI actions, chat | Noise |

Overrides are the most valuable memories — the template makes them explicit.

## 6. Templates

Written as plain, self-contained English so Hindsight extracts clean facts and
links entities (vendor, client, GSTIN). One memory per **group**, never per invoice.

**M1 — Resolution**
```
{Month YYYY}: At client {client_name}, vendor {vendor_name} (GSTIN {gstin})
had {n} invoice(s) {type_phrase}, ITC at risk ₹{amount}.
Munshi suggested {suggested_action|"nothing (memory off)"}.
The accountant {accepted it | overrode it and chose {final_action}}.
Accountant's note: "{note}".
```

**M2 — Outcome**
```
{Month YYYY}: Checked the {prev Month} decision for vendor {vendor_name}
(GSTIN {gstin}) at client {client_name}: the decision to {action} was
{correct | wrong}. Evidence: {evidence}.
```
e.g. evidence = `invoice RS/2025-26/0412 appeared in the Feb 2026 GSTR-2B, filed 12-02-2026, ~40 days after the invoice date.`

**M3 — Drift**
```
{Month YYYY}: Vendor {vendor_name} (GSTIN {gstin}) broke its usual pattern.
Previously its invoices arrived about {typical_lag} late; now {n} invoice(s)
are overdue by {days} days. Earlier assumptions about this vendor should not be trusted.
```

### Retain call
```python
retain(
  bank_id=bank,
  content=<template text>,
  context="gst reconciliation " + kind,          # resolution | outcome | drift
  timestamp=<decision date in the simulated month>,
  document_id=f"{group_key}:{kind}",
  metadata={"kind": kind, "client_id": ..., "period": ..., "vendor_gstin": ...,
            "exception_type": ..., "action": ...},
)
```
Timestamps are the **business date** (e.g. `2026-02-18`), not wall-clock, so
temporal recall ("last 3 months") works on seeded history.

## 7. Recall

**One recall per exception group** (not per invoice), cached per vendor within a run.

```
query = (
  f"How were {type_phrase} issues with vendor {vendor_name} (GSTIN {gstin}) "
  f"handled before, at any client, and what happened afterwards? "
  f"How does this vendor usually behave? Any accountant preferences about {type_phrase}?"
)
recall(bank_id, query, types=["world", "experience", "observation"],
       max_tokens=1500, budget="mid")
```
- The GSTIN in the query lets keyword search hit exact matches.
- Results are passed to the agent with **their IDs** so it can cite them (SPEC-05).
- Cross-client knowledge comes from here: one bank, so memories from other clients surface.

## 8. Reflect

Used sparingly (it's the expensive call):

| Use | Query | Cache key |
|---|---|---|
| Vendor profile (UI) | "Summarise how vendor {name} ({gstin}) behaves, how its issues were resolved, what works when contacting them, and how reliable past assumptions have been." | vendor + last memory event id |
| Monthly insights (UI) | "What did we learn in {Month} across all clients? New risks, vendors that changed behaviour, patterns now reliable." | period + last memory event id |

Never called per exception.

## 9. Memory event log

Every retain / recall / reflect is logged to `memory_events`:
`id, ts, op, bank_id, kind, summary (first 200 chars of content/query),
result_count, latency_ms`. The UI shows these live (SPEC-08) — the content guide
asks us to *"show retain/recall happening live"*.

## 10. Memory ON / OFF

| | ON | OFF |
|---|---|---|
| Recall before deciding | yes | **no** |
| Trust ladder / AUTO | yes | **no** (everything level 0) |
| Retain decisions | yes | yes (the firm still learns) |

In evals (SPEC-09), OFF uses a separate bank so nothing leaks between conditions.

## 11. Token budget (estimates, to be measured in SPEC-09)

| Call | Per client-month | Size |
|---|---|---|
| recall | ≈ number of groups (3–6) | ≤ 1,500 tokens returned |
| retain | ≈ number of groups + outcomes | ~100–150 tokens each (+ Hindsight's extraction cost) |
| reflect | 0 during reconciliation | on demand, cached |

Goal: prompt size per group stays **flat** as history grows (recall is capped).

## 12. Seeding

`seed(months=["2026-01","2026-02","2026-03"])` replays those months through the
real pipeline (matcher → agent → decision → retain → self-check) with a
**simulated accountant** that picks the ground-truth `accountant_action` and types the
ground-truth `accountant_note`. April is left for the live demo.

## 13. Edge cases

- Hindsight down → reconciliation still works with memory treated as OFF, UI shows a banner; retains are queued in SQLite and replayed later.
- Recall returns nothing → agent behaves as memory OFF for that group (not an error).
- Re-deciding a group → same `document_id` (overwrite, not duplicate) — *verify SDK behaviour*.

## 14. Acceptance criteria

- AC-04-1: `memory.py` is the only module importing `hindsight_client`.
- AC-04-2: After seeding, recall for Reddy Steels returns ≥ 1 memory mentioning late filing.
- AC-04-3: After seeding, recall for Krishna Logistics **from C03's context** returns memories from C01.
- AC-04-4: No clean-match invoice ever produces a retain (count check in a test run).
- AC-04-5: Every retain/recall/reflect creates a `memory_events` row.
- AC-04-6: With Hindsight stopped, a reconciliation completes and shows the offline banner.
- AC-04-7: Recall prompt size for a vendor does not grow beyond `max_tokens` after 4 months (measured).

## 15. Verify during implementation (unknowns about the SDK)

- Exact shape of recall results (IDs, text, type, score fields).
- Whether bank *directives* can be set via SDK (else mission text only).
- Whether retain with an existing `document_id` replaces or appends.
- Whether recall can filter by `metadata` (we don't depend on it).
- `delete_bank` availability for resets.

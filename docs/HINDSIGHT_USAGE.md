# How Munshi uses Hindsight

[Hindsight](https://github.com/vectorize-io/hindsight) is Munshi's long-term memory.
All of it goes through one module,
[`backend/app/memory.py`](../backend/app/memory.py). It is the only file that
imports `hindsight_client`, and the only place the four calls below are made.
The English we write and the questions we ask are in
[`backend/app/memory_text.py`](../backend/app/memory_text.py). The spec is
[SPEC-04](../specs/SPEC-04-memory.md).

| Call | When | Why |
|---|---|---|
| `create_bank` | App start, demo reset, each eval condition | One bank per firm, with a mission and a cautious disposition |
| `retain` | A decision, a verified outcome, a late arrival, a drift | Store what was *learned*, not what happened |
| `recall` | Once per exception group, before the model suggests | Ground the suggestion in the firm's own history |
| `reflect` | Vendor profile and monthly insights, on demand, cached | Summaries for people, never in the reconciliation path |

## 1. One bank per firm

```python
create_bank(
    "munshi-rao-associates",
    name="Munshi — Rao & Associates",
    mission="You are the institutional memory of Rao & Associates … Never recommend "
    "claiming ITC for an invoice that is absent from GSTR-2B or marked ineligible.",
    disposition_skepticism=4,
    disposition_literalism=4,
    disposition_empathy=2,
)
```

- **Per firm, not per client.** A vendor's behaviour at one client is evidence at
  another. That is how Munshi warns C03 about Krishna Logistics, a vendor that never
  filed for C01 (D5).
- **Skeptical and literal**, because this is tax: evidence beats assumption.
- The ITC rule is also in the mission, but it is *enforced* in code (INV-1 and
  guardrail G1), not left to memory (D20).
- `create_bank` is an HTTP PUT, so it is safe to call on every start.
- Evals get fresh banks, `eval-<run_id>-<on|off>-r<n>`, so nothing leaks between
  conditions (D41).

## 2. What we retain, and what we don't

Only three kinds of memory, one per exception **group** (vendor × type × month),
never one per invoice:

| Kind | Written when | Example |
|---|---|---|
| **Resolution** (M1) | The accountant decides, or Munshi auto-resolves | How the group was decided, and the accountant's note |
| **Outcome** (M2) | Next month's self-check has a verdict, or a late invoice shows up | Whether that decision turned out right, with the evidence |
| **Drift** (M3) | A vendor breaks its usual pattern | What changed, and a warning against old assumptions |

Reddy Steels at Sri Balaji Textiles, as the sample data actually retains it:

```text
February 2026: At client Sri Balaji Textiles, vendor Reddy Steels (GSTIN 36AABCR1234F1ZT)
had 2 invoices missing from GSTR-2B, ITC at risk ₹53,402.04.
Munshi suggested DEFER.
The accountant accepted it.
Accountant's note: "Jan invoice showed up in Feb 2B. They're just late. Deferring."

March 2026: Checked the February 2026 decision for vendor Reddy Steels (GSTIN 36AABCR1234F1ZT)
at client Sri Balaji Textiles: the decision to DEFER was correct.
Evidence: invoices RS/2025-26/0783, RS/2025-26/0786 all appeared in the March 2026 GSTR-2B,
filed 23-03-2026, about 46 days after the invoice date.

April 2026: Checked the March 2026 decision for vendor Reddy Steels (GSTIN 36AABCR1234F1ZT)
at client Sri Balaji Textiles: the decision to DEFER was wrong.
Evidence: invoice RS/2025-26/0792 expected in the April 2026 GSTR-2B had still not appeared
by the April 2026 GSTR-2B.

April 2026: Vendor Reddy Steels (GSTIN 36AABCR1234F1ZT) broke its usual pattern. Previously
its invoices arrived about 46 days late; now 1 invoice is overdue by 51 days. Earlier
assumptions about this vendor should not be trusted.
```

We **never** retain clean matches (about 85% of rows, which teach nothing), raw
files (SQLite has them), suggestions nobody acted on, or UI clicks (D3). That
keeps recall relevant and each month's writes small.

How each retain is built (`HindsightBackend.retain`):

```python
client.retain(
    bank_id,
    content,
    timestamp=occurred_at,  # the business date (15th of the next month), not wall clock (D29)
    context="gst reconciliation resolution",
    document_id="resolution:C01:2026-02:36AABCR1234F1ZT:MISSING_IN_2B",
    metadata={"kind": ..., "period": ..., "client_id": ..., "vendor_gstin": ..., "action": ...},
    entities=[{"text": "Reddy Steels"}, {"text": "Sri Balaji Textiles"}],
    tags=["vendor:36AABCR1234F1ZT", "client:C01", "kind:resolution"],
    update_mode="replace",
)
```

- **The text is self-contained English** that names the vendor, GSTIN and client
  in full, so Hindsight's fact extraction and entity links work from the text alone.
- **`document_id` is keyed by group** (D28). Re-deciding a group *replaces* its
  memory instead of piling up contradictions.
- **Overrides say so plainly** ("The accountant overrode it and chose …"). They
  are the most valuable memories.
- **The timestamp is the business date**, so seeded history has a real timeline
  and temporal recall works.
- **Tags** let reflect be scoped to one vendor (`vendor:<gstin>`). **Metadata** lets
  the UI show which client and month a cited memory came from.

## 3. Recall: one question per group

```python
client.recall(
    bank_id,
    group_query(vendor, gstin, exception_type),
    types=["world", "experience", "observation"],
    max_tokens=1500,
    budget="mid",
)
```

The question (`memory_text.group_query`):

> How were invoices missing from GSTR-2B from vendor Reddy Steels (GSTIN
> 36AABCR1234F1ZT) handled before, at any client, and what happened afterwards?
> How does this vendor usually behave? Any accountant preferences about invoices
> missing from GSTR-2B?

- **One recall per group**, not per invoice, and cached until something new is
  retained. A client-month makes about 3 to 6 recalls.
- **It covers all three kinds at once**: past resolutions (with the accountant's
  preferences), whether they turned out right, and how the vendor behaves.
- **The GSTIN in the question** lets keyword search hit exact matches; the names
  help semantic search.
- **"At any client"** plus one bank per firm gives cross-client knowledge.
- **`max_tokens=1500` caps the prompt**, so its size stays flat as history grows
  instead of growing with it (MemGPT, and Lost in the Middle; see
  [RESEARCH.md](RESEARCH.md)). E10 in the evals measures this.
- The memories go to the model as `M1`, `M2`, … (D22). It must cite the ones it
  used, and guardrails G2, G3 and G5 check the citations. In the UI every card shows
  the memories it cited, with the client and month each came from.
- Each memory line starts with where it came from, taken from its metadata:
  `[M1] (another client C01 · March 2026) …` (D51). Hindsight rewrites what we
  retain into extracted facts, and those often drop the client's name; without the
  tag the model can't tell another client's history from this one's, and the
  cross-client warning never fires.

## 4. Reflect: for people, not for the pipeline

| Use | Question | Scope |
|---|---|---|
| Vendor profile | "Summarise how vendor {name} ({gstin}) behaves, how its issues were resolved, what works when contacting them, and how reliable past assumptions have been." | `tags=["vendor:<gstin>"]`, `tags_match="all_strict"` |
| Monthly insights | "What did we learn in {Month} across all clients? New risks, vendors that changed behaviour, patterns now reliable." | whole bank |

Reflect is the expensive call, so it is **never** called per exception. It runs
with `budget="low"` and is cached until the next retain.

## 5. Memory ON / OFF

| | ON | OFF |
|---|---|---|
| Recall before suggesting | yes | no |
| Trust ladder / auto-resolve | yes | no |
| Retain decisions, outcomes, drift | yes | yes (D26) |

OFF is a switch on each run (`?memory=off`), shown in the UI, and one of the two
eval conditions. Memory OFF only changes what the agent *sees*; the firm keeps
learning.

## 6. When Hindsight is down

- **Retains queue** in SQLite (`retain_queue`) and replay oldest-first when
  `/api/health` finds the server again. A newer version of a queued memory replaces
  the old one.
- **Recall returns "offline"**, and that group is handled as memory OFF, with a
  banner in the UI. A missing memory never blocks the accountant.
- **Fail fast**: after a failure, calls are skipped for 15 s instead of waiting
  on a dead server each time (D39).
- **Demo reset deletes the bank first**; if that fails, nothing is wiped (D33).

## 7. Seeing it live

Every retain, recall and reflect is written to `memory_events` with its latency
and result count. The workbench's **memory panel** polls it, so you watch memories
being written as the accountant decides, and recalled as a run suggests. You can
also call `GET /api/memory/recall?q=…` to ask the bank directly.

## 8. Running Hindsight

Self-hosted, in its own virtual environment because of its heavy dependencies
(D14). The client is pinned to the same version as the server (`0.10.1`). For
Hindsight Cloud, set `HINDSIGHT_BASE_URL=https://api.hindsight.vectorize.io` and
`HINDSIGHT_API_KEY` in `.env`; no code changes, and no local server or model key.
The live tests (`pytest -m hindsight`) pass against both. `InMemoryBackend` is a keyword-matching stand-in, so the tests and
offline work need no server. It is not a substitute for real recall quality.

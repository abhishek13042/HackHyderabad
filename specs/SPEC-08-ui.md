# SPEC-08 — User Interface

**Status:** DONE · **Owner:** B · **Depends on:** SPEC-07

## 1. Purpose

A focused workbench where an accountant clears a month's mismatches fast, and
where **the memory is visible**: what Recon recalled, why it suggests something,
how much it trusts itself, and what it just learned. This is the UX 15% and it
carries most of the demo video.

## 2. Stack & style

- React + Vite + TypeScript + Tailwind. Charts: Recharts. Data fetching: TanStack Query (polling built in).
- Desktop-first (1280px+), usable at 768px. Light theme, neutral greys, one accent colour.
- Money in Indian format: `₹1,06,200.00` (`Intl.NumberFormat('en-IN')`).
- Plain language, no jargon in labels: "Missing from GSTR-2B", not `MISSING_IN_2B`.

## 3. Layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Recon · Rao & Associates   [Client ▾ C01] [Period ▾ Apr 2026]  Memory ●ON  │
├───────────┬────────────────────────────────────────────────┬─────────────────┤
│ Nav       │  Main screen                                   │ Memory activity │
│ Workbench │                                                │ (live panel)    │
│ Vendors   │                                                │ ↓ recall  Reddy │
│ Insights  │                                                │ ↑ retain  M1    │
│ Data      │                                                │ ✓ outcome ...   │
└───────────┴────────────────────────────────────────────────┴─────────────────┘
```
Top bar also shows status dots for Hindsight / LLM (from `/health`) and an offline banner when down.

## 4. Screens

### S1 — Data
- "Load sample data (3 clients × 4 months)" → `/demo/seed`, with progress.
- Or upload: client, period, CSV + JSON drop zones → `/uploads`, showing row counts and warnings.
- Table of client × period with status (not run / run / decided) and a Run button.
- "Reset demo" (typed confirmation).

### S2 — Workbench (main screen)
Header: `ITC at risk ₹84,500 · 7 groups · 2 auto-resolved · 5 need you` and a **Run reconciliation** button (progress bar from `/runs/{id}`).

**Exception card** (one per group, sorted by ITC at risk):
```
┌─────────────────────────────────────────────────────────────────────────┐
│ Reddy Steels  36AABCR1234F1Z5         Missing from GSTR-2B   ₹27,000    │
│ 2 invoices ▸                                        ⚠ Pattern changed   │
│─────────────────────────────────────────────────────────────────────────│
│ Recon suggests:  CHASE VENDOR            Confidence: Medium            │
│ "Reddy Steels usually files a month late, but its March invoice still   │
│  hasn't appeared in April's 2B. The pattern has broken — chase now."    │
│                                                                         │
│ Based on 3 memories ▸   Trust: ● Observe (was Suggest — reset by drift) │
│ Draft message to vendor ▸  [Copy]                                       │
│─────────────────────────────────────────────────────────────────────────│
│ [✓ Accept]   [Choose another ▾]  Note: [____________________________]   │
└─────────────────────────────────────────────────────────────────────────┘
```
- **Invoices ▸** expands a small table (no., date, total, tax, books vs 2B values for mismatches).
- **Based on N memories ▸** expands the cited memories: text, month, client. Memories from **another client** get a "from Vega Electronics" tag — makes cross-client learning obvious.
- **Flags** as coloured chips: Pattern changed (red), Seen at another client (orange), Recurring (grey), Vendor risk (red).
- **Trust chip:** Observe / Suggest / Auto, with a hover showing streak + correct/wrong counts.
- **Choose another** lists only allowed actions (SPEC-05 §4); the note box becomes required (red outline) when overriding.
- After deciding: card collapses to one line "✓ Held payment · note saved to memory", and the memory panel shows the retain.
- Guardrail events shown discreetly: "Safety rule applied: large difference → escalated".

**Auto-resolved section** (collapsed by default): one line per group, "Auto · Laxmi Packaging · ₹6 rounding · accepted (trusted pattern, 4 months)" + **Undo**.

**Memory toggle** (top bar): switching OFF shows a confirm "Re-run this month without memory?" → re-runs with `memory=off`. Cards then show "No memories used". The demo uses this for before/after.

### S3 — Vendor profile
Opened by clicking a vendor name.
- Header: name, GSTIN, state, status, clients buying from it.
- **What Recon knows** — reflect profile text (cached), with "last updated from N memories".
- **Timeline** — month rows × client: exception type, action taken, outcome (✓ correct / ✗ wrong / —), drift marker.
- **Trust per issue type** — small ladder graphic 0→1→2 with the current step highlighted.

### S4 — Insights
- **Learning curve** (line chart): accuracy per month, memory ON vs OFF, plus auto-resolved % as bars. From SPEC-09 results.
- **This month's lessons** — reflect monthly summary.
- **Trust board** — table of all patterns with level, sortable.
- Stat tiles: groups auto-resolved, overrides this month, drift events, cross-client warnings, safety rules applied.

### Memory activity panel (right, always visible, collapsible)
Polls `/memory/events` every 1 s while a run is active, else every 5 s.
Each row: icon (↓ recall, ↑ retain, ✓ outcome, ⚠ drift, ✦ reflect), vendor/kind, 1-line summary, latency.
Click → full text. New rows animate in briefly. This is how we "show retain/recall happening live".

## 5. States

Every screen has loading (skeletons), empty ("No data yet — load sample data"), and error states.
Offline Hindsight → yellow banner "Memory offline — suggestions made without memory" and toggle disabled.

## 6. Accessibility & polish

- All actions keyboard-reachable; `A` accepts the focused card, `J/K` move between cards.
- Colour is never the only signal (chips carry text).
- Numbers right-aligned with tabular figures.

## 7. Acceptance criteria

- AC-08-1: Fresh start → load sample → open C01 Apr → run → decide all cards, without touching the API manually.
- AC-08-2: Overriding without a note is blocked in the UI (and by the API).
- AC-08-3: Cited memories from another client show the other client's name.
- AC-08-4: Memory panel shows recall rows during a run and a retain row within 2 s of a decision.
- AC-08-5: Memory OFF re-run shows cards with "No memories used" and no Auto section.
- AC-08-6: Undo on an auto-resolved group moves it back to the main list as decided-by-accountant.
- AC-08-7: No layout break at 768px; no console errors in the demo flow.
- AC-08-8: Clicking a vendor name opens its profile with the reflect summary, per-client timeline with outcomes, and trust per issue type (US-8).
- AC-08-9: Insights shows ITC at risk, auto-resolved count, drift and cross-client counts for the selected period, plus the learning curve (US-9).

## 8. Open questions (resolved)

- Q1: Label, with the number on hover. Done.
- Q2: No chat box; only the debug "Ask memory" recall box on Insights. Done.

## 9. Implementation

| Path (`frontend/src/`) | Role |
|---|---|
| `api/types.ts`, `api/client.ts` | TypeScript mirrors of `schemas.py`; a fetch wrapper that turns the error envelope into `ApiError`. Money stays a string. |
| `api/hooks.ts` | One TanStack Query hook per endpoint, with the polling below; decisions refresh every view that shows them. |
| `lib/workspace.tsx` | Shared state: route, client, period, and the one background job (a run or the seed). |
| `lib/format.ts`, `lib/labels.ts`, `lib/route.ts` | ₹ with Indian grouping and no floats, plain-English labels for every enum, hash routes. |
| `components/` | `TopBar` (pickers, memory switch, status), `ExceptionCard`, `UndoForm`, `MemoryPanel`, badges and small UI parts. |
| `screens/` | `Workbench` (S2), `VendorProfile` (S3), `Insights` (S4, lazy-loaded with the chart library), `DataScreen` (S1). |

Run it (with the API on port 8000): `cd frontend`, `npm ci`, `npm run dev`, open `http://localhost:5173`.
Checks: `npm run typecheck`, `npm test`, `npm run build`.

Decisions made while building (DECISIONS.md D36–D40):
- **Hash routes** (`#/workbench`, `#/vendors/<gstin>`, `#/insights`, `#/data`): four screens need no router library, and links survive a reload.
- **Polling, no push**: runs and jobs every 1 s while running, health every 5 s, the memory panel every 1 s while busy and 5 s otherwise. A decision refreshes the panel at once, which is what makes AC-08-4's 2 s hold.
- **The Auto section is the run's `auto_resolved_keys`**, not every AUTO decision: a memory-off re-run keeps earlier automatic decisions (D27), but they were not resolved by that run, so AC-08-5 shows no Auto section.
- **The firm name comes from `/health`** (`firm`), and `/insights` counts cross-client warnings and safety rules applied.
- **Memory fails fast when Hindsight is down**: after one failure, memory calls are skipped for 15 s (logged as offline, retains queued) and only the `/health` probe tries. A refused connection costs about 2 s on Windows, so without this the offline seed took minutes.
- **The memory panel starts from the latest 40 events** (`/memory/events?latest=true`), then asks only for newer ids.

| AC | Verified by |
|---|---|
| AC-08-1 | Browser run on a fresh database: load sample → C01 Apr 2026 → Run → Accept; no API calls by hand. |
| AC-08-2 | `ExceptionCard.test.tsx` "blocks an override until a note is written"; API: `test_override_needs_a_note`. |
| AC-08-3 | `ExceptionCard.test.tsx` "names the other client a memory came from". |
| AC-08-4 | Browser: recall rows during the run, the decision's retain row within 1.5 s of Accept. |
| AC-08-5 | `ExceptionCard.test.tsx` "says no memories were used when memory is off"; the Auto section uses the run's `auto_resolved_keys`. |
| AC-08-6 | `ExceptionCard.test.tsx` "offers Undo on an automatic decision"; the move back is the API's (`test_undo_*`). |
| AC-08-7 | Browser at 768 px: no horizontal page scroll, the memory panel moves below the screen; no console errors in the flow. |
| AC-08-8 | Browser: vendor name → profile with header, profile text (or the offline notice), timeline and trust ladders. |
| AC-08-9 | Browser: Insights tiles (ITC at risk, auto-resolved, overrides, drift, cross-client, safety rules) and the learning curve (empty state until SPEC-09 has results); API: `test_insights`. |

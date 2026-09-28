# SPEC-06 — Learning Loop

**Status:** DONE · **Owner:** A · **Depends on:** SPEC-04, SPEC-05

## 1. Purpose

Make the agent's learning **real and checkable**, not just "it reads old notes":
1. **Self-check:** verify past decisions against what actually happened.
2. **Trust ladder:** earn (and lose) autonomy per pattern.
3. **Drift detection:** notice when a vendor's learned pattern breaks.
4. **Cross-client risk:** carry vendor knowledge across clients.

## 2. Scope

**In:** outcome verification, trust computation, drift detection, auto-resolution, undo, run order, and **seeding** (moved from SPEC-04 §12: it replays Jan–Mar through this loop).
**Out:** the LLM prompt (SPEC-05), storage templates (SPEC-04).

## 3. Run order (every reconciliation of client C, period P)

```
1. Matcher(books_P, 2B_P, open_missing)       → exceptions, late_arrivals      (SPEC-03)
2. Verify outcomes of past decisions          → outcomes + M2 retains           (§4)
3. Detect drift                               → drift events + M3 retains       (§6)
4. Compute trust per pattern                                                    (§5)
5. Per group: recall → suggest → guardrails                                     (SPEC-04/05)
6. Auto-resolve groups eligible at level 2    → decisions (AUTO) + M1 retains   (§7)
7. Remaining groups wait for the accountant   → decisions + M1 retains
```
Steps 2–4 are deterministic code over SQLite. Their **results are retained to
memory** so the agent can reason about them in natural language.

## 4. Outcome verification (self-check)

Only decisions that make a **checkable prediction** get a verdict.

| Decision | Prediction | Verdict |
|---|---|---|
| `DEFER` on MISSING_IN_2B | "will appear in the 2B of period `P + expected_lag`" (default lag 1 month; learned lag per vendor, §6) | appeared by then → `VERIFIED_CORRECT`; not appeared when that 2B is processed → `VERIFIED_WRONG` |
| `CHASE_VENDOR` / `HOLD_PAYMENT` on MISSING_IN_2B | none | `NOT_APPLICABLE`, but a late arrival is still retained as M2 ("after chasing, it appeared") |
| everything else | none | `NOT_APPLICABLE` |

Evidence stored and retained: invoice numbers, 2B period they arrived in,
supplier filing date, days late.

## 5. Trust ladder

**Pattern key:** `(vendor_gstin, exception_type)` — **firm-wide**, across clients.

Computed fresh at step 4 from history (not stored as a mutable counter):
```
history   = decisions for this pattern, oldest → newest
streak    = number of most-recent consecutive decisions with the same final_action
correct   = count of VERIFIED_CORRECT outcomes for this pattern
wrong_recent = any VERIFIED_WRONG among the last 3 outcomes, or drift active, or an
               AUTO decision was undone in the last 2 periods

if wrong_recent:                                     level 0  OBSERVE
elif (streak >= 3 or (streak >= 2 and correct >= 2))
     and streak_action in {ACCEPT, DEFER}:           level 2  AUTO
elif streak >= 2:                                    level 1  SUGGEST
else:                                                level 0  OBSERVE
```

| Level | UI | Confidence cap |
|---|---|---|
| 0 OBSERVE | suggestion shown as "low confidence", accountant decides | 0.6 |
| 1 SUGGEST | suggestion pre-selected, accountant confirms | 0.85 |
| 2 AUTO | resolved automatically, listed under "Auto-resolved" with Undo | 1.0 |

Only `ACCEPT` and `DEFER` can ever be AUTO (SPEC-01 INV-2). Memory OFF ⇒ everything level 0.

### Expected trajectories on our data
| Pattern | Jan | Feb | Mar | Apr |
|---|---|---|---|---|
| Laxmi Packaging · AMOUNT_MISMATCH (C01+C02 pooled) | 0 | 1 (streak 2) | **2 AUTO** (streak 4) | 2 AUTO |
| Bhavani Chemicals · MISSING_IN_2B | 0 | 0 | 0 (streak 1) | **2 AUTO** (streak 2, 2 correct) |
| Reddy Steels · MISSING_IN_2B | 0 | 0 | 0 (streak 1) | **0 — drift, Mar DEFER wrong** |
| Mumbai Threads · TAX_HEAD_MISMATCH | 0 | 0 | 1 | 1 (never AUTO: CORRECT_BOOKS) |

Bhavani and Reddy look **identical until April** — that contrast is the demo's key moment.

## 6. Drift detection

For vendor V with **≥ 2 prior late arrivals**:
```
expected_lag(V) = median over V's late arrivals of (arrival 2B period − invoice period), in months
for each open MISSING_IN_2B invoice of V (any client):
    if current period ≥ invoice period + expected_lag(V) and it has not arrived:
        → DRIFT(V): overdue invoice, days overdue, expected lag
```
Period-based (not day-based) so invoice dates within a month don't cause false alarms.

On drift:
- create a drift event; retain **M3**;
- mark the related `DEFER` decisions `VERIFIED_WRONG` (§4);
- trust for all V's patterns → level 0 (§5);
- pass `DriftInfo` to the agent; guardrail G6 enforces `PATTERN_DRIFT` + no `DEFER`.

Expected on our data: **Reddy Steels drifts in April** (March invoice expected in
April 2B, absent). Bhavani Chemicals never drifts.

## 7. Auto-resolution & undo

- A group is auto-resolved iff trust level 2 **and** the suggestion's action equals
  the pattern's `streak_action` **and** no guardrail fired **and** memory ON.
- Creates `Decision(decided_by=AUTO, accepted_suggestion=true)` and retains M1
  with "Munshi auto-resolved this (trust level 2)".
- **Undo** (UI): converts it to an accountant override → retains M1 as an override →
  counts toward `wrong_recent` (drops the pattern to level 0).

## 8. Cross-client risk

Comes from memory: one firm-wide bank, so a recall for Krishna Logistics from
C03 surfaces C01's resolutions. The agent may raise `CROSS_CLIENT_RISK` only
with a citation to another client's memory (SPEC-05 G5). Expected: raised for
**Krishna Logistics at C03 in March** — its first-ever invoice there.

## 9. Edge cases

- A late arrival for a decision that was `VERIFIED_WRONG` (arrives very late) → keep WRONG, retain an M2 noting the actual arrival; lag updates.
- Vendor with only 1 late arrival → no drift detection yet (not enough evidence).
- Accountant overrides the same pattern in opposite directions → streak stays low → never AUTO. Correct behaviour.

## 10. Acceptance criteria

- AC-06-1: After replaying Jan–Mar with the simulated accountant, trust levels match the table in §5 for Jan–Mar.
- AC-06-2: At the start of April: Reddy Steels drift detected; its March `DEFER` is `VERIFIED_WRONG`; its level is 0.
- AC-06-3: Bhavani Chemicals is AUTO in April and its groups are auto-resolved.
- AC-06-4: No action other than `ACCEPT`/`DEFER` is ever auto-resolved (property test).
- AC-06-5: Undoing an AUTO decision drops that pattern to level 0 on the next run.
- AC-06-6: Every outcome and drift event produces exactly one retain.
- AC-06-7: With memory OFF, no auto-resolution happens.

## 11. Implementation

| Module | Role |
|---|---|
| `backend/app/learning.py` | Pure rules: `verify` (§4), `trust` (§5), `detect_drift` (§6), `expected_lag`, `arrival_after_wrong` (§9). No I/O. |
| `backend/app/store.py` | All SQL: dataset, runs, exceptions, suggestions, decisions, outcomes, trust snapshots, drift events. |
| `backend/app/pipeline.py` | `Pipeline.run(client, period, memory_on)`, `decide(key, action, note)`, `undo(key, action, note)`. |
| `backend/app/seed.py` | `load_dataset(store, dir)`, `seed(pipeline, dir, periods=None)`: replays all periods but the last with the ground truth's `accountant_action`. |

Decisions made while building (see DECISIONS.md D23–D29):
- **History is strictly earlier periods.** Trust for period P uses decisions with period < P; verdicts checked ≤ P. So every client in P sees the same trust, whatever order clients run in.
- **Outcome rows only when there is something to learn**: a DEFER verdict, or an arrival after another action (`NOT_APPLICABLE` with evidence). One row ⇒ one M2 retain; a §9 late arrival updates the evidence and re-retains the same document.
- **Drift waits for every client's 2B.** An invoice is overdue only if its own client has processed the due period (`Store.processed_through`), so a client not yet run can't cause a false alarm.
- **Memory OFF still records.** It changes what the agent sees (`AgentContext.effective`) and forbids auto-resolution; decisions, outcomes and drift are still stored and retained.
- **Runs:** a client's periods run in order; only the latest can run again. A re-run discards that period's runs (exceptions, suggestions and trust cascade) and reopens invoices its 2B closed; decisions, outcomes and drift are history and stay.
- **Undo** = `undo(key, action)`: only for an AUTO decision, and only to a different action. `wrong_recent` looks for an undone AUTO decision in P−1 or P.
- **Memory documents:** `resolution:{group_key}`, `outcome:{group_key}`, `drift:{gstin}:{period}`, dated the review day (15th of the next month).

| AC | Test |
|---|---|
| AC-06-1 | `test_pipeline.py::test_trust_trajectories_match_the_spec`, `test_learning.py::test_trust_levels` |
| AC-06-2 | `test_pipeline.py::test_reddy_drifts_in_april_and_its_deferral_was_wrong` |
| AC-06-3 | `test_pipeline.py::test_bhavani_is_auto_resolved_in_april` |
| AC-06-4 | `test_pipeline.py::test_only_accept_or_defer_is_ever_automatic` (6 random policies) |
| AC-06-5 | `test_pipeline.py::test_undo_drops_the_pattern_to_observe`, `test_undo_in_the_same_period_holds_on_a_rerun` |
| AC-06-6 | `test_pipeline.py::test_every_outcome_and_drift_event_is_retained_once` |
| AC-06-7 | `test_pipeline.py::test_memory_off_never_auto_resolves_but_still_learns` |

## 12. Open questions (resolved)


- Q1: Should trust be per **client + vendor** instead of firm-wide? Firm-wide learns faster and enables cross-client; per-client is more conservative. **Resolved: firm-wide (D5).**
- Q2: Is "streak ≥ 3" too fast for AUTO in real life? For a 4-month demo it has to be; note it in DECISIONS.md as a tunable. **Resolved: tunable constants in `learning.py` (D6).**

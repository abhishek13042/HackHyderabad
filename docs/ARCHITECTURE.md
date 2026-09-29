# Architecture

Recon splits the work in two. **Code does the numbers**: matching, checking past
decisions, trust and drift are deterministic and tested. **The model does the
judgment**: one short, structured suggestion per exception group, grounded in
recalled memory and checked by guardrails before anyone sees it (D2).

```
 Purchase register (CSV) ─┐
                          ├─► Matcher ──► exception groups ─┐
 GSTR-2B (JSON) ──────────┘   (code)      (vendor × type)   │
                                                            ▼
 ┌──────────────────────────── one run: client × month ─────────────────────────────┐
 │ 1 match   2 verify past decisions   3 detect drift   4 trust ladder               │
 │   (all code over SQLite; what they learn is retained to Hindsight as English)     │
 │ 5 recall  ── one Hindsight recall per group, ≤ 1,500 tokens ──► memories M1, M2…  │
 │ 6 suggest ── Groq, JSON mode, one call per group ──► guardrails G1–G8             │
 │ 7 resolve ── patterns at AUTO trust are decided automatically (never unsafe ones) │
 └───────────────────────────────────────────────────────────────────────────────────┘
                                                            │
                        React workbench ◄── FastAPI ◄───────┘
                               │
            accountant accepts / overrides with a note ──► retain (M1) ──► next month
```

## The loop that makes it learn

1. **Decide.** The accountant accepts or overrides a suggestion. An override needs a
   note, because it is the most useful thing Recon can remember. The decision is
   retained as a plain-English *resolution* memory (M1).
2. **Check.** Next month, step 2 looks at what really happened. Did the deferred
   invoice arrive in GSTR-2B? The verdict is retained as an *outcome* memory (M2):
   "the decision to DEFER was correct".
3. **Trust.** A pattern (vendor × exception type, firm-wide) climbs Observe → Suggest
   → Auto after a streak of the same decision, faster when outcomes confirm it (D6).
   A wrong outcome, an undo or drift drops it back to Observe at once.
4. **Drift.** When a vendor that always filed a month late misses its usual window,
   step 3 retains a *drift* memory (M3), guardrail G6 stops deferral, and trust resets.
5. **Recall.** Every suggestion starts with one recall about that vendor, at any
   client. That single bank per firm is what makes cross-client warnings possible.

Nothing here changes the model's weights (D1). The model stays the same; the
memory grows.

## Components

| Layer | Where | Notes |
|---|---|---|
| Domain | `backend/app/domain/` | Enums, GSTIN, money (`Decimal`, never float), periods, the safety policy (INV-1: no ITC without 2B). |
| Ingest | `backend/app/ingest.py` | Purchase-register CSV and GSTR-2B JSON, validated at the boundary. |
| Matcher | `backend/app/matcher.py` | Exact, then fuzzy (max(₹50, 2%), single candidate only), then grouped per vendor and type. |
| Learning | `backend/app/learning.py` | Pure functions: verify, trust, drift. |
| Memory | `backend/app/memory.py`, `memory_text.py` | The only code that imports `hindsight_client`. Event log, offline queue, caches. See [HINDSIGHT_USAGE.md](HINDSIGHT_USAGE.md). |
| Agent | `backend/app/agent.py`, `prompts/system.md`, `llm.py` | Prompt with few-shot examples, JSON schema, retries, fallback model, guardrails. |
| Pipeline | `backend/app/pipeline.py`, `store.py` | The seven steps; all SQL in one place. |
| API | `backend/app/main.py`, `routers/` | FastAPI; background runs polled by the UI; one run at a time. |
| UI | `frontend/src/` | Workbench, memory panel, vendor profile, insights, data. |
| Evals | `evals/` | Memory ON vs OFF over the same months. See [EVALS.md](EVALS.md). |

## Guardrails

Every model answer passes through `apply_guardrails` (`backend/app/agent.py`), which
is pure and tested case by case:

| | Rule |
|---|---|
| G1 | An action the policy forbids for this exception type becomes ESCALATE. |
| G2 | Citations of memories that were not provided are dropped. |
| G3 | Claims about history with no citation get their confidence capped. |
| G4 | A large amount difference is never simply accepted. |
| G5 | A cross-client warning needs a cited memory about another client. |
| G6 | If the vendor's pattern broke, deferring becomes chasing, and the drift flag is added. |
| G7 | No valid JSON after all retries → a safe escalation. |
| G8 | Chase and hold always come with a vendor message, drafted from a template if needed. |

Automatic resolution is further limited in code (INV-2): only safe actions can
ever be automatic, whatever the trust.

## Failure modes

- **Hindsight down**: retains queue in SQLite and replay when it's back; recall
  reports offline, and that group is handled as memory OFF. The UI shows a banner.
- **Groq down or no key**: suggestions escalate with a clear reason; the rest of
  the app works (D35).
- **Re-running a month**: only the latest month can be re-run; decisions,
  outcomes and drift are history and stay (D27).

The full rationale for each choice is in [DECISIONS.md](DECISIONS.md), and the
specs in [specs/](../specs/README.md).

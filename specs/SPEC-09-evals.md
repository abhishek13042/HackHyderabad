# SPEC-09 — Evaluation Harness

**Status:** DRAFT · **Owner:** A · **Depends on:** SPEC-02, SPEC-05, SPEC-06

## 1. Purpose

Prove with numbers that **memory makes Munshi better over time**, and that it
stays safe. Output feeds the Insights chart, `docs/EVALS.md`, the README, the
video and the articles.

## 2. Design

Two conditions, same data, same model, same prompt, same guardrails:

| Condition | Bank | Recall | Trust/AUTO |
|---|---|---|---|
| `on` | fresh `eval-{run_id}-on` | yes | yes |
| `off` | fresh `eval-{run_id}-off` | no | no |

For each condition, replay months **in order** Jan → Apr, all 3 clients, through the
real pipeline (SPEC-06 §3). After the agent suggests, the **simulated accountant**
decides with the ground-truth `accountant_action` + `accountant_note` (so both conditions
receive identical feedback). The **suggestion** (before the accountant) is what we score.

```
python -m evals.run --conditions on,off --seed 42 --repeats 1 --out evals/results/
python -m evals.report evals/results/<run_id>   # → EVALS.md tables + chart PNG + JSON
```

Fresh banks per run ⇒ no leakage between conditions or runs. `--repeats 3` for final numbers (LLM variance).

## 3. Metrics

| # | Metric | Definition | Target (SPEC-00) |
|---|---|---|---|
| E1 | Action accuracy | suggestion.action ∈ acceptable_actions, per month | Apr ON ≥ 80% |
| E2 | Memory gap | accuracy ON − OFF, months 2–4 | ≥ 25 pp by Apr |
| E3 | Learning curve | E1 per month for each condition | ON rises, OFF flat |
| E4 | Safety | suggestions reaching the user that violate INV-1 / allowed-actions | **0** (raw LLM violations also reported) |
| E5 | Root-cause accuracy | root_cause == label | report |
| E6 | Flag recall / precision | per flag, esp. PATTERN_DRIFT, CROSS_CLIENT_RISK, RECURRING_ISSUE | drift & cross-client both caught |
| E7 | Grounding | % of suggestions with history claims that cite ≥ 1 valid memory; G3 fire rate | report |
| E8 | JSON validity | % valid first try; retries; G7 fallbacks | ≥ 95% first try |
| E9 | Autonomy | % of groups auto-resolved per month; % of auto that were correct | Apr ≥ 40%, 100% correct |
| E10 | Cost | prompt + completion tokens per group; recall tokens; latency p50/p95 | tokens per group flat over months |

### Named scenario checks (pass/fail)
- S1 Drift: Reddy Steels Apr → PATTERN_DRIFT flag, action ≠ DEFER (ON).
- S2 Consistency: Bhavani Chemicals Apr → DEFER, auto-resolved (ON).
- S3 Cross-client: Krishna Logistics C03 Mar → CROSS_CLIENT_RISK with a C01 citation (ON); OFF can't.
- S4 Preference: Laxmi Packaging diff ₹2–9 → ACCEPT from Feb (ON), with the "under ₹10" note cited.
- S5 Root cause: Sai Electricals C03 Mar → WRONG_BUYER_GSTIN (ON), learnt from the Jan note.

## 4. Also run (cheap, deterministic, no LLM)

- Matcher vs ground truth (SPEC-03 AC-03-10): group-key precision/recall = 100%.
- Guardrail unit suite (SPEC-05 AC-05-1…4).
- **Baseline "rules only"**: a fixed rule table (MISSING_IN_2B → CHASE_VENDOR, AMOUNT ≤ ₹10 → ACCEPT, …) scored on the same labels — shows what memory adds beyond hard-coding.

## 5. Rate limits & runtime

- Groq free tier: throttle to ≤ 3 concurrent, backoff on 429 (SPEC-05 §7); `--rpm` flag.
- Estimated volume: 12 client-months × ~6 groups × 2 conditions ≈ 150 agent calls + Hindsight's own extraction calls. Budget ~15–30 min per repeat.
- Checkpoint after each client-month so a crash resumes (`--resume <run_id>`).
- Log the exact model IDs and Hindsight version in results.

## 6. Output

```
evals/results/<run_id>/
├── config.json          seed, models, versions, git sha
├── suggestions.jsonl    every suggestion + label + condition
├── metrics.json         E1–E10 + scenarios
├── learning_curve.png
└── report.md            copied/merged into docs/EVALS.md
```

## 7. Honesty rules

- Data is synthetic and the patterns are planted — say so plainly in EVALS.md and the articles.
- Report failures and the scenarios we missed, not only wins.
- Never tune the prompt against April labels; tune on Jan–Mar only (April = held-out).

## 8. Acceptance criteria

- AC-09-1: One command produces `metrics.json` and `report.md` for both conditions.
- AC-09-2: ON and OFF banks are different and freshly created (checked in config.json).
- AC-09-3: Re-running `report` on saved results is deterministic.
- AC-09-4: `/insights` learning curve reads the latest `metrics.json`.
- AC-09-5: S1–S5 each reported as pass/fail with the suggestion text.

## 9. Open questions

- Q1: Should the simulated accountant sometimes be wrong / skip notes to test robustness? Proposed: stretch goal (`--noisy-accountant`).
- Q2: Does Hindsight's fact extraction add enough latency that a full run exceeds 30 min? Measure on day 1.

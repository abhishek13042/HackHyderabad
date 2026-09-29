# Recon — Specifications

Recon is a GST reconciliation agent for small CA firms. It matches purchase
registers against GSTR-2B, remembers how every mismatch was resolved (via
Hindsight), checks whether its own past advice was right, and earns autonomy
only where it has proven itself.

We build **spec-first**: a spec is reviewed and agreed before any code for it
is written. "Done" means every acceptance criterion in the spec passes.

## Workflow

```
Write spec → Both review (comment / edit) → Status: APPROVED → Build → Verify acceptance → Status: DONE
```

## Index

| Spec | Title | Owner | Depends on | Status |
|---|---|---|---|---|
| [SPEC-00](SPEC-00-product.md) | Product Requirements | Both | — | DONE |
| [SPEC-01](SPEC-01-domain-model.md) | Domain & Data Model | Both | 00 | DONE |
| [SPEC-02](SPEC-02-synthetic-data.md) | Synthetic Data Generator | B | 01 | DONE |
| [SPEC-03](SPEC-03-matcher.md) | Matcher | A | 01, 02 | DONE |
| [SPEC-04](SPEC-04-memory.md) | Memory Layer (Hindsight) | Both | 01 | DONE |
| [SPEC-05](SPEC-05-agent.md) | Agent / Decision Engine | A | 03, 04 | DONE |
| [SPEC-06](SPEC-06-learning-loop.md) | Learning Loop | A | 04, 05 | DONE |
| [SPEC-07](SPEC-07-api.md) | Backend API | B | 03–06 | DONE |
| [SPEC-08](SPEC-08-ui.md) | Frontend UI | B | 07 | DONE |
| [SPEC-09](SPEC-09-evals.md) | Evals | A | 02, 05, 06 | DONE |
| [SPEC-10](SPEC-10-demo.md) | Demo, Video & Submission | Both | all | DONE |

Owner A = backend person, Owner B = frontend + content person.

## Build order

```
00 → 01 → 02 → 03 ─┐
          04 ──────┼→ 05 → 06 → 07 → 08 → 10
                   └────────→ 09
```

## Spec template

Every spec uses these sections (omit one only if it truly doesn't apply):

1. **Purpose** — why this part exists
2. **Scope** — in / explicitly out
3. **Inputs / Outputs** — exact data shapes
4. **Rules** — the behaviour, precisely
5. **Edge cases**
6. **Acceptance criteria** — testable; numbered `AC-xx-n`
7. **Dependencies**
8. **Open questions** — to settle during review

## Shared vocabulary

Defined once in [SPEC-01](SPEC-01-domain-model.md) and used everywhere:
`ExceptionType`, `Action`, `RootCause`, `Flag`, `TrustLevel`, `OutcomeStatus`.
If a spec needs a new value, add it to SPEC-01 first.

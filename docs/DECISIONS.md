# Decisions

Short records of choices that shaped the design. Newest last.

| # | Decision | Why | Alternatives rejected |
|---|---|---|---|
| D1 | **No fine-tuning.** Specialise with prompt + few-shot + JSON schema + memory + code guardrails. | The firm-specific knowledge changes monthly; memory adapts instantly, a fine-tune doesn't. No labelled public dataset exists for this task. | LoRA fine-tune on synthetic data (would just memorise our planted patterns). |
| D2 | **Code for numbers, AI for judgment.** Matching is deterministic (SPEC-03). | Tax amounts must be exact and reproducible. | LLM-based matching. |
| D3 | **DB stores what happened; memory stores what was learned.** Only resolutions, outcomes and drift are retained (SPEC-04 §5). | Keeps recall relevant and token cost flat; clean matches teach nothing. | Retaining every invoice or conversation. |
| D4 | **Groq JSON mode, no tool calling.** | Tool calling is fragile on Groq-hosted models; one structured call per group is enough. | Agent loop with tools. |
| D5 | **Trust is firm-wide** per (vendor, exception type). | Learns faster and enables cross-client warnings. | Per client + vendor (more conservative). |
| D6 | **AUTO after streak ≥ 3, or streak ≥ 2 with ≥ 2 verified-correct outcomes.** A tunable. | Must be reachable within a 4-month demo; real deployments would raise it. | Fixed high thresholds. |
| D7 | Matcher fuzzy tolerance **max(₹50, 2%)**, only with a single candidate. | Tolerates typing differences without guessing between invoices. | — |
| D8 | One ambiguous April case labelled `ESCALATE`. | Tests that the agent escalates when unsure. | — |
| D9 | Confidence shown as **High / Medium / Low**, number on hover. | LLM confidence is rough; labels are honest. | Raw percentages. |
| D10 | Memory panel **polls** every 1 s. | Simpler than SSE, good enough locally. | Server-sent events. |
| D11 | **Money is `Decimal` in code, integer paise in SQLite, strings in JSON.** Floats rejected at the boundary. | Floats can't represent rupee amounts exactly. | Floats; `REAL` columns. |
| D12 | **Vendor archetype is not a domain field.** | The planted label must never be able to leak into prompts. | Field excluded from serialisation. |
| D13 | **Decisions are append-only** (`superseded_at`). | Undone AUTO decisions must count against trust; keeps an audit trail. | Overwriting the row. |
| D14 | **Hindsight server in its own venv** (`.venv-hindsight`); app depends only on `hindsight-client`, pinned to the same version. | The server pulls ~200 packages (PyTorch, transformers); the app stays small and fast to install. | One shared venv; Docker (not installed). |
| D15 | **Plain `sqlite3`, no ORM**; enum CHECK constraints generated from Python enums. | Small schema, explicit SQL, values declared once. | SQLAlchemy. |
| D16 | Dependencies: ranges in `pyproject.toml`, exact pins in pip-tools lock files. | Reproducible installs without losing readable intent. | Unpinned requirements; Poetry/uv (not installed). |
| D17 | GSTR-2B amounts are **JSON numbers**, read with `parse_float=Decimal`. | Matches the portal format; values have ≤ 15 significant digits, so they round-trip exactly. | Strings (not what the portal emits). |
| D18 | Ground truth has **`accountant_action`** beside `best_action`. | The simulated accountant can be cautious (HOLD_PAYMENT) where the expert chases; the agent is scored on `best_action`, but learns from what the accountant really did. | One action for both (hides a realistic disagreement). |

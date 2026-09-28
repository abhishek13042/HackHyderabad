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
| D19 | Memory behind a **`MemoryBackend` protocol**, with an in-memory stand-in. | Unit tests and offline work need no server; only `memory.py` knows the SDK. | Mocking the SDK client. |
| D20 | **No Hindsight directives**; the ITC rule is in the bank mission and enforced in code (INV-1). | One source of truth for a safety rule; a directive would be a second copy that can drift. | Directive plus code check. |
| D21 | **`openai` SDK against Groq's OpenAI-compatible API**, SDK retries off, our own backoff and fallback behind a `ChatModel` protocol. | One small, well-typed client; retries we can test; the agent is tested with a scripted fake. | Groq SDK; raw HTTP; SDK retries (can't fall back to another model). |
| D22 | **Memories are shown to the model as `M1`, `M2`**; a missing vendor message is filled from a code template. | Aliases are short and hard to mistype; a template is exact about invoices and amounts and costs no extra call. | Raw Hindsight ids; retrying the model for a message. |
| D23 | **Trust for period P uses only periods before P.** | Same answer for every client in P, whatever order they run in; a period can't vouch for itself. | Everything decided so far (order-dependent). |
| D24 | **Outcome rows only where there is a verdict or an arrival.** | Memory holds what was learned (D3); "still waiting" teaches nothing. | A row for every decision. |
| D25 | **Drift waits for each client's own 2B** of the due period. | Clients are reconciled one by one; an unrun client isn't evidence. | Current period for every client. |
| D26 | **Memory OFF still records history.** | The comparison view must not cost the firm its learning. | Skipping writes when OFF. |
| D27 | **Only the latest period re-runs;** a re-run keeps decisions, outcomes and drift. | Earlier results feed later ones; rewriting them would silently change the past. | Free re-runs with recomputation. |
| D28 | **Memory document ids are keyed by group** (`resolution:`, `outcome:`, `drift:`). | Re-deciding replaces the memory instead of piling up contradictions. | Random ids. |
| D29 | **Memories are dated the 15th of the next month** (review day). | That's when the firm learns it, after GSTR-2B on the 14th. | Run wall-clock time (meaningless for seeded history). |
| D30 | **A SQLite connection per request and per background task; one shared `Memory`** with its own connection and a lock. | sqlite3 connections aren't shared across threads; memory caches must outlive a request. | One global connection with `check_same_thread=False`. |
| D31 | **One run or seed at a time**, behind a process-wide lock; busy → 409. | Every run updates firm-wide trust and memory; concurrent runs would race. A CA firm reconciles one client at a time anyway. | Per-client locks; a job queue. |
| D32 | **The Hindsight SDK is called from one dedicated thread** with its own event loop. | Its sync methods run the calling thread's asyncio loop, which fails inside FastAPI's running loop. | The async SDK methods (would make every layer async). |
| D33 | **Reset deletes the memory bank before the database.** | If Hindsight is down, nothing is wiped and the two stay consistent. | Database first (could leave old memories behind). |
| D34 | **Memory-backed parts of a page degrade to null**, not 503, when the rest comes from SQLite. | The vendor page and insights stay useful offline; the UI shows a banner. | 503 for the whole page. |
| D35 | **A missing Groq key is not a startup error.** | The demo, the UI and the tests work offline; suggestions fall back to ESCALATE (SPEC-05 §8). | Refusing to start. |
| D36 | **React + Vite + TanStack Query + Tailwind, hash routes, no router or state library.** | Four screens and server state only; the query cache is the state. | React Router, Redux/Zustand, Next.js. |
| D37 | **Polling, not push**, and a decision refreshes the memory panel at once. | A run lasts seconds and one accountant uses the app; polling is simple and testable. | WebSockets or server-sent events. |
| D38 | **The Auto section lists the run's `auto_resolved_keys`.** | A memory-off re-run keeps earlier automatic decisions (D27) but didn't make them. | Every AUTO decision in the period. |
| D39 | **Memory fails fast for 15 s after a failure**; only `ensure_bank` (the `/health` probe) retries. | A dead server can take ~2 s per call to refuse; runs and the seed stay fast offline, and recovery is still noticed within 5 s. | Trying every call; a full circuit-breaker library. |
| D40 | **Insights (and the chart library) load lazily.** | Keeps the first screen's bundle to about 95 kB gzipped. | One bundle. |
| D41 | **Evals regenerate the dataset from `--seed`, with one database and one bank per condition and repeat.** | No leakage between conditions or runs, and the app's own data is never touched. | Re-using `data/generated` and the app database. |
| D42 | **Suggestions are recorded raw and joined with the labels at report time.** | `evals.report` needs only the run folder and is byte-reproducible (AC-09-3). | Scoring inside the run loop. |
| D43 | **The learning curve is an SVG written by hand, not a matplotlib PNG.** | No plotting dependency and deterministic bytes; GitHub renders it. | matplotlib. |
| D44 | **Eval checkpoints are per client-month.** | Periods must run in order; the interrupted month is the latest, so the pipeline re-runs it cleanly. | Per-group checkpoints; no resume. |
| D45 | **Eval results are committable; only `work/` is ignored.** | The report is the evidence for the claims in the README, video and articles. | Ignoring all results. |
| D46 | **The demo rehearsal is a standard-library script against the running API, and needs `--yes`.** | It checks exactly what the video shows, runs on any machine with the stack up, and can't wipe data by accident. The tests drive it in-process. | Browser automation (Playwright); a pytest-only check. |
| D47 | **The memory-OFF comparison runs on C03 April before its ON run.** | Decisions survive a re-run (D27), so an OFF re-run of a decided month would still show earlier automatic decisions. | Re-running C01 OFF after ON. |
| D48 | **Article and post drafts carry placeholders, not numbers.** | Every number published must come from a real eval report; the drafts are written before the live run. | Illustrative numbers to be "updated later". |
| D49 | **Memory texts agree in number** ("1 invoice is overdue"). | Hindsight extracts facts from the text, and the text is shown to the accountant. | Leaving the template fixed-plural. |
| D50 | **Fallback model is `openai/gpt-oss-20b`; a 429 waits for its `retry-after`, capped at 20 s.** | Groq retired `qwen/qwen3-32b` (HTTP 404). The free tier allows 8,000 tokens per minute per model, so 1-2-4 s backoff gave up before the window reset. | Another retired or preview model; waiting indefinitely. |
| D51 | **Each memory in the prompt is tagged with its client and month from metadata** (`(another client C01 · March 2026)`). | Hindsight's extracted facts often drop the client's name, so in the first live rehearsal the model cited Krishna's history at C01 but couldn't tell it was another client, and never flagged the risk. G5 still checks the flag in code. | Relying on the text naming the client; setting the flag in code (the model should say why it matters). |

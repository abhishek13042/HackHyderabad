# Munshi

**A GST reconciliation agent that remembers how your firm resolves mismatches — and checks whether its own advice was right.**

Built on [Hindsight](https://github.com/vectorize-io/hindsight) agent memory.

**Video:** [VIDEO_URL] · **Design:** [specs/](specs/README.md) · **How memory is used:** [docs/HINDSIGHT_USAGE.md](docs/HINDSIGHT_USAGE.md)

<!-- Screenshots go in docs/images/ after recording (docs/DEMO.md §3):
![Workbench with cited memories](docs/images/workbench.png)
![Reddy Steels drift card](docs/images/drift.png)
-->

## Quickstart (about a minute, once installed)

With the environments from [Development setup](#development-setup-windows-powershell)
and your keys in `.env`, start three terminals from the repo root. With Hindsight
Cloud (`HINDSIGHT_BASE_URL=https://api.hindsight.vectorize.io` and `HINDSIGHT_API_KEY`
in `.env`), skip the first one:

```powershell
.venv-hindsight\Scripts\hindsight-api                      # 1. memory on :8888
.venv\Scripts\uvicorn backend.app.main:app --port 8000     # 2. API on :8000
cd frontend; npm run dev                                   # 3. UI on http://localhost:5173
```

Open the UI, go to **Data → Load sample data**, and wait for January to March to
replay. Then pick a client, choose **April** and click **Run reconciliation**.
The story to look for is in [docs/DEMO.md](docs/DEMO.md).

## The problem

Every month, about 1.3 crore regular GST taxpayers reconcile their purchase
register against **GSTR-2B**. Input Tax Credit (ITC) can be claimed only for
invoices the supplier has reported, so every mismatch is money at risk.

Existing tools already *match* invoices. What they don't do is **remember how
exceptions were resolved**: which vendor files late but reliably, which one
always has a ₹5 rounding difference, which one never files at all, and which
vendor caused trouble for another client. That knowledge lives in a senior
accountant's head, and it's lost when they're busy or leave.

## Who it's for

**CA Priya Rao**, a sole practitioner in Hyderabad with 40 small-business
clients. She spends the first ten days of every month reconciling and chasing
vendors. She is legally responsible for what she files, so she won't hand
decisions to a black box.

## What Munshi does

> Big GST tools match invoices. Munshi remembers how your firm resolves them,
> checks whether its advice was right, and handles next month's exceptions the
> way your best accountant would.

- **Remembers** every resolution and the accountant's note (Hindsight `retain`).
- **Recalls** how a vendor behaved before, at any client, before suggesting an action.
- **Checks itself**: next month, it verifies whether "defer, they're just late" was actually right.
- **Earns autonomy** per pattern (Observe → Suggest → Auto), and loses it when wrong.
- **Notices drift** when a vendor breaks its usual pattern.
- **Warns across clients** when a vendor that failed one client shows up at another.
- **Never unsafe**: code-level rules stop it from ever claiming credit that isn't in GSTR-2B.

The agent suggests; the CA decides.

## Results

The evaluation replays the same four months with memory ON and OFF (same model,
prompt and simulated accountant) and reports accuracy per month, the held-out
April, unsafe suggestions and tokens per group. Method: [docs/EVALS.md](docs/EVALS.md).
Numbers: the newest `evals/results/<run_id>/report.md` ([RESULTS_LINK]).

## Documentation

| Document | What's in it |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, the monthly learning loop, guardrails, failure modes |
| [docs/HINDSIGHT_USAGE.md](docs/HINDSIGHT_USAGE.md) | Exactly what is retained, recalled and reflected, and why |
| [docs/EVALS.md](docs/EVALS.md) | Evaluation method and metrics |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Design decisions log |
| [docs/RESEARCH.md](docs/RESEARCH.md) | Papers behind the design, and what we chose not to do |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | GST terms and Munshi's own vocabulary |
| [docs/DEMO.md](docs/DEMO.md) | Demo runbook and video script |
| [specs/](specs/README.md) | The specs SPEC-00 … SPEC-10 |

## Repository layout

```
backend/app/domain/    GST domain: enums, entities, GSTIN, money, periods, safety rules
backend/app/db.py      SQLite schema
backend/app/config.py  settings from .env
backend/app/ingest.py  purchase-register CSV and GSTR-2B JSON readers/writers
backend/app/matcher.py deterministic books-vs-2B reconciliation
backend/app/memory.py  Hindsight wrapper: event log, offline queue, caches
backend/app/memory_text.py  what is retained and asked, as plain English
backend/app/agent.py   one suggestion per exception group: prompt, guardrails, retries
backend/app/llm.py     Groq chat client: JSON mode, backoff, fallback model
backend/app/learning.py  self-check, trust ladder and drift rules (pure)
backend/app/store.py   all SQL for runs, exceptions, decisions, outcomes, drift
backend/app/pipeline.py  one reconciliation run, decisions and undo
backend/app/seed.py    loads the dataset and replays history
backend/app/services.py  what API requests share: memory, agent, work lock, jobs
backend/app/schemas.py API request and response models
backend/app/routers/   API endpoints (data, runs, decisions, insights, demo)
backend/app/main.py    FastAPI app: routers, CORS, error envelope
backend/app/prompts/   system prompt with few-shot examples
backend/datagen/       synthetic dataset generator (never imported by the app)
backend/scripts/       command-line entry points (generate_data, demo_check)
backend/tests/         pytest suite
frontend/src/api/      typed API client and TanStack Query hooks
frontend/src/lib/      shared state, formatting, labels, hash routes
frontend/src/components/  exception card, memory panel, top bar, UI parts
frontend/src/screens/  workbench, vendor profile, insights, data
evals/                 evaluation harness: memory ON vs OFF, metrics, report
specs/                 spec-driven design documents (SPEC-00 … SPEC-10)
```

## Development setup (Windows, PowerShell)

Requires **Python 3.12** (see `.python-version`) and git.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install pip-tools
.venv\Scripts\pip-sync requirements-dev.lock
.venv\Scripts\python -m pip install --no-deps -e .
copy .env.example .env   # then fill in your keys; never commit .env
```

On macOS/Linux use `python3.12 -m venv .venv` and `.venv/bin/...`.

### Hindsight memory server

The server has heavy dependencies (PyTorch, transformers), so it runs in its own
virtual environment, like a separate database service:

```powershell
py -3.12 -m venv .venv-hindsight
.venv-hindsight\Scripts\python -m pip install -r requirements-hindsight.lock
.venv-hindsight\Scripts\hindsight-api          # serves on http://localhost:8888
```

It reads `HINDSIGHT_API_LLM_PROVIDER` and `HINDSIGHT_API_LLM_API_KEY` from the environment.

### Checks

```powershell
.venv\Scripts\pytest
.venv\Scripts\ruff check .
.venv\Scripts\ruff format --check .
.venv\Scripts\mypy
```

### Dependencies

Direct dependencies are declared in `pyproject.toml` with compatible ranges.
Exact, reproducible versions are in the lock files, generated with pip-tools:

```powershell
.venv\Scripts\pip-compile --strip-extras -o requirements.lock pyproject.toml
.venv\Scripts\pip-compile --strip-extras --extra dev -o requirements-dev.lock pyproject.toml
```

### API server

```powershell
.venv\Scripts\uvicorn backend.app.main:app --port 8000   # docs at http://localhost:8000/docs
```

It runs without Hindsight or a Groq key (memory off, suggestions escalate); `/api/health` says what is up.

### Frontend

Requires **Node 20+**. With the API running on port 8000:

```powershell
cd frontend
npm ci
npm run dev          # http://localhost:5173, /api is proxied to :8000
```

Checks: `npm run typecheck`, `npm test`, `npm run build`.

### Demo rehearsal

With all three processes running, this resets the demo, seeds, runs April and
checks every beat of the video script. It deletes the demo data, so it asks for `--yes`:

```powershell
.venv\Scripts\python -m backend.scripts.demo_check --yes --strict
```

### Evaluation

Needs Hindsight and `GROQ_API_KEY`. It replays January to April with memory ON and
OFF and writes `evals/results/<run_id>/report.md`; the Insights screen charts the
newest run. The method and metrics are in [docs/EVALS.md](docs/EVALS.md).

```powershell
.venv\Scripts\python -m evals.run --conditions on,off --seed 42 --repeats 1
```

## Data

All data is **synthetic**: three fictional clients of a fictional firm over four
months, with vendor behaviours planted on purpose so learning can be measured
against a ground truth (see [SPEC-02](specs/SPEC-02-synthetic-data.md)).

Generate it (same seed, byte-identical files on every machine):

```powershell
.venv\Scripts\python -m backend.scripts.generate_data --seed 42
```

Output goes to `data/generated/` (gitignored): `firm.json`, `vendors.json`,
`ground_truth.json`, and a `purchase_register.csv` + `gstr2b.json` per client-month.

## License

MIT

# Munshi

**A GST reconciliation agent that remembers how your firm resolves mismatches — and checks whether its own advice was right.**

Built on [Hindsight](https://github.com/vectorize-io/hindsight) agent memory.

> Status: early build. Specs are approved; the domain model (SPEC-01) is implemented.
> See [specs/](specs/README.md) for the full design.

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

## Repository layout

```
backend/app/domain/    GST domain: enums, entities, GSTIN, money, periods, safety rules
backend/app/db.py      SQLite schema
backend/app/config.py  settings from .env
backend/app/ingest.py  purchase-register CSV and GSTR-2B JSON readers/writers
backend/app/matcher.py deterministic books-vs-2B reconciliation
backend/datagen/       synthetic dataset generator (never imported by the app)
backend/scripts/       command-line entry points
backend/tests/         pytest suite
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

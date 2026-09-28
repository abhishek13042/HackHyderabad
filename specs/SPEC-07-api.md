# SPEC-07 — Backend API

**Status:** DONE · **Owner:** B · **Depends on:** SPEC-01, SPEC-03, SPEC-05, SPEC-06

## 1. Purpose

A small FastAPI service that loads data, runs reconciliations, records decisions,
and exposes memory/trust/insight views to the UI. No auth (single-firm local demo).

## 2. Conventions

- Base URL `http://localhost:8000/api`. JSON everywhere except uploads (multipart).
- Money is serialized as **strings** with 2 decimals (`"27000.00"`) — never floats (INV-3).
- Errors: `{"error": {"code": "NOT_FOUND", "message": "..."}}` with a proper HTTP status.
- Codes: `VALIDATION_ERROR` 422, `NOT_FOUND` 404, `CONFLICT` 409, `MEMORY_OFFLINE` 503 (only for memory-only endpoints), `LLM_UNAVAILABLE` 503.
- OpenAPI docs at `/docs` (free with FastAPI; useful for judges).
- CORS allows `http://localhost:5173` (Vite).

## 3. Endpoints

### System
| Method | Path | Returns |
|---|---|---|
| GET | `/health` | `{ok, db, hindsight: "up"|"down", llm: "up"|"down", bank_id}` |

### Reference data
| Method | Path | Returns |
|---|---|---|
| GET | `/clients` | `[{id, name, gstin, business}]` |
| GET | `/periods?client_id=C01` | `[{period, has_books, has_2b, run_status, open_groups, auto_resolved}]` |

### Uploads
`POST /uploads` — multipart: `client_id`, `period`, `purchase_register` (CSV), `gstr2b` (JSON).
- Validates columns (SPEC-02 §5), 2B shape (§6), GSTINs (SPEC-01 §3), and that `rtnprd` matches `period`.
- Replaces that client-period's data if no decisions exist yet; else `409 CONFLICT`.
- Returns `{rows_books, rows_2b, warnings[]}`.

### Reconciliation runs
`POST /reconciliations/{client_id}/{period}/run?memory=on|off`
- Starts a **background task** running SPEC-06 §3 steps 1–6. Returns `202 {run_id}`.
- If a run for the same client-period is already running → `409`.

`GET /runs/{run_id}`
```json
{
  "run_id": "r_01", "status": "running|done|failed",
  "progress": {"step": "suggest", "done": 3, "total": 7},
  "memory_on": true,
  "summary": {"groups": 7, "auto_resolved": 2, "itc_at_risk": "84500.00",
              "flags": {"PATTERN_DRIFT": 1, "CROSS_CLIENT_RISK": 0}},
  "error": null
}
```
UI polls every 1 s.

### Exceptions & decisions
`GET /reconciliations/{client_id}/{period}/groups` — sorted by `itc_at_risk` desc:
```json
[{
  "group_key": "C01:2026-04:36AABCR1234F1Z5:MISSING_IN_2B",
  "vendor": {"gstin": "...", "name": "Reddy Steels"},
  "type": "MISSING_IN_2B",
  "invoices": [{"invoice_no": "RS/2025-26/0467", "date": "2026-04-03", "total": "106200.00", "tax": "16200.00"}],
  "itc_at_risk": "27000.00",
  "suggestion": {
    "action": "CHASE_VENDOR", "root_cause": "NOT_FILED",
    "flags": ["PATTERN_DRIFT"], "confidence_label": "MEDIUM", "final_confidence": 0.6,
    "reasoning": "...", "vendor_message": "...",
    "cited_memories": [{"id": "m_1a2b", "text": "...", "period": "2026-03", "client_id": "C01"}],
    "guardrail_events": ["DRIFT_OVERRIDE"]
  },
  "trust": {"level": 0, "name": "OBSERVE", "streak": 2, "correct": 1, "wrong": 1},
  "decision": null
}]
```
`confidence_label`: HIGH ≥ 0.8, MEDIUM ≥ 0.5, else LOW.

`POST /exceptions/{group_key}/decision`
```json
{"action": "HOLD_PAYMENT", "note": "Third month no filing. Holding GST portion."}
```
- `action` must be allowed for the type (SPEC-05 §4) → else 422.
- `accepted_suggestion` = (action == suggestion.action), computed server-side.
- Note is **required when overriding** (it's the most valuable memory) → else 422.
- Writes decision, triggers M1 retain (async; failure queues it, SPEC-04 §13).
- Re-deciding the same group replaces the decision (same `document_id`).

`POST /exceptions/{group_key}/undo` — only for `decided_by=AUTO`; body `{action, note}`; behaves as an override (SPEC-06 §7).

### Memory, trust, insights
| Method | Path | Returns |
|---|---|---|
| GET | `/vendors/{gstin}` | vendor facts, per-client history table (period, type, action, outcome), trust per exception type, `profile` (reflect, cached), drift events |
| GET | `/trust` | all patterns: `[{vendor, type, level, streak_action, streak, correct, wrong}]` |
| GET | `/insights?period=2026-04` | `{summary (reflect, cached), learning_curve: [{period, accuracy_on, accuracy_off, auto_rate}], stats}` — curve from latest eval results (SPEC-09) |
| GET | `/memory/events?since={id}&limit=50` | memory_events rows newer than `since` (UI polls every 1 s during runs) |
| GET | `/memory/recall?q=...` | raw recall for the "Ask memory" box (debug/demo) |

### Demo controls
| Method | Path | Effect |
|---|---|---|
| POST | `/demo/seed` | Load generated data for all clients/periods; replay Jan–Mar with the simulated accountant (SPEC-04 §12). Background task → `{run_id}` |
| POST | `/demo/reset` | Wipe SQLite runtime tables and delete/recreate the bank. Requires body `{"confirm": "RESET"}` |

## 4. Module layout

```
backend/app/
├── main.py            FastAPI app, routers, CORS
├── config.py          settings from .env (pydantic-settings)
├── db.py              SQLite + schema (SPEC-01 §8)
├── domain/            enums, entities, GSTIN, money, periods, policy (SPEC-01)
├── schemas.py         API request/response models
├── matcher.py         SPEC-03
├── memory.py          SPEC-04 (only SDK importer)
├── agent.py           SPEC-05
├── learning.py        SPEC-06 (outcomes, trust, drift)
├── pipeline.py        run orchestration (SPEC-06 §3)
├── routers/           health, data, runs, decisions, insights, demo
└── prompts/system.md
backend/scripts/generate_data.py   SPEC-02
backend/tests/
```

## 5. Configuration (`.env`, never committed; `.env.example` is)

```
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-120b
GROQ_FALLBACK_MODEL=openai/gpt-oss-20b
HINDSIGHT_BASE_URL=http://localhost:8888
HINDSIGHT_API_KEY=            # empty for self-hosted
HINDSIGHT_BANK_ID=munshi-rao-associates
DB_PATH=data/munshi.db
DATA_DIR=data/generated
```

## 6. Edge cases

- Hindsight down: `/health` shows `down`; runs proceed as memory OFF with `summary.memory_degraded=true`; reflect endpoints return `503 MEMORY_OFFLINE`; UI banner.
- Groq down: suggestions become ESCALATE "AI unavailable" (SPEC-05 §8); decisions still work.
- Server restarted mid-run: runs left `running` are marked `failed` on startup.

## 7. Acceptance criteria

- AC-07-1: `pytest` API tests with a mocked LLM and a fake memory client cover every endpoint's happy path + one error.
- AC-07-2: No endpoint response contains a JSON float for money.
- AC-07-3: Override without a note → 422.
- AC-07-4: Disallowed action (e.g. ACCEPT on MISSING_IN_2B) → 422.
- AC-07-5: Seed → run April C01 → groups endpoint shows Reddy Steels with `PATTERN_DRIFT`.
- AC-07-6: `/demo/reset` without the confirm body → 422.
- AC-07-7: API keys never appear in logs or responses.

## 8. Implementation

| Module | Role |
|---|---|
| `backend/app/main.py` | `create_app(services=None)`: lifespan, CORS, routers under `/api`, the error envelope. `app` for uvicorn. |
| `backend/app/services.py` | What requests share: settings, one `Memory`, the agent, the work lock, seed jobs. A SQLite connection per request and per background task. |
| `backend/app/schemas.py` | Request and response models. Money fields are `Money` (2-decimal strings). |
| `backend/app/routers/common.py` | `ApiError`, dependencies, lookups that 404, shared views. |
| `backend/app/routers/{data,runs,decisions,insights,demo}.py` | The endpoints of §3, grouped as in the tables. |

Run it: `.venv\Scripts\uvicorn backend.app.main:app --port 8000`, docs at `http://localhost:8000/docs`.

Decisions made while building (DECISIONS.md D30–D35):
- **One job at a time.** A run or seed takes a process-wide work lock in the request (busy → `409`) and releases it when the background task ends. Runs change trust and memory for every client, so two at once would race.
- **Seed is a job**, not a run: `POST /demo/seed` returns `202 {job_id, status, done, total}`; poll `GET /demo/jobs/{job_id}`.
- **Summary**: `auto_resolved` is a count and `auto_resolved_keys` lists the groups; `memory_degraded` is true when memory was on but Hindsight was offline; also `exceptions`, `matched`, `drift`, `late_arrivals`, `outcomes`.
- **Groups** also carry `allowed_actions` (for the UI's buttons) and `guardrail_details` (rule + detail) beside the rule names.
- **Undo** always needs a note: it says why an automatic decision was wrong.
- **Vendor page with memory offline** returns `profile: null` instead of `503`, since the rest of the page comes from SQLite. `/insights` does the same with `memory_offline: true`; only `/memory/recall` is memory-only.
- **Reset deletes the memory bank first**; if Hindsight is down it answers `503` and wipes nothing, so the database and the bank never disagree.
- **Uploads** also refuse (`409`) a period earlier than one already run, and warn about empty files and unknown suppliers.
- **The Hindsight SDK runs on one thread of its own** with its own event loop: its sync calls drive the calling thread's loop, which fails during FastAPI's startup.
- **No Groq key** is not a startup error: `/health` says `llm: down` and suggestions fall back to ESCALATE.

| AC | Test (`backend/tests/test_api.py`) |
|---|---|
| AC-07-1 | every endpoint: `test_health_*`, `test_clients_and_periods`, `test_run_*`, `test_groups_*`, `test_*decision*`, `test_undo_*`, `test_vendor_page`, `test_trust_table`, `test_insights`, `test_memory_events_and_recall`, `test_upload_*`, `test_seed_*`, `test_reset_*` (in-memory backend, scripted chat) |
| AC-07-2 | `test_no_money_is_ever_a_float` (every body the module received) |
| AC-07-3 | `test_override_needs_a_note` |
| AC-07-4 | `test_disallowed_action_is_rejected` |
| AC-07-5 | `test_reddy_shows_pattern_drift_in_april` |
| AC-07-6 | `test_reset_needs_confirmation` |
| AC-07-7 | `test_api_keys_never_leak` |

## 9. Open questions (resolved)

- Q1: Polling vs server-sent events for the memory panel? **Resolved: polling (D10).**

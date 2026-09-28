# Demo runbook and video script

How to set up, rehearse and record the 2–5 minute video (SPEC-10). Everything the
video shows comes from the sample data in [SPEC-02](../specs/SPEC-02-synthetic-data.md):
three clients of *Rao & Associates* over January to April 2026, with vendor
behaviours planted on purpose.

## 1. Before recording

**Start the three processes** (three terminals, from the repo root):

```powershell
.venv-hindsight\Scripts\hindsight-api                          # memory, :8888
.venv\Scripts\uvicorn backend.app.main:app --port 8000         # API, :8000
cd frontend; npm run dev                                       # UI, :5173
```

**Rehearse** (AC-10-1). This resets the demo twice, seeds January to March, runs
April, and checks every story beat the video relies on:

```powershell
.venv\Scripts\python -m backend.scripts.demo_check --yes --strict
```

It prints ✓ or ✗ per beat and exits non-zero on any error. A ✗ with a live model
means that beat can't be filmed as scripted: see §4.

**Then set up the demo state** (in the UI, *Data* screen):

1. *Reset demo* → type `RESET`.
2. *Load sample data* and wait for January to March to finish (the memory panel
   fills as it goes).
3. Run April for **C01** and **C02** only. Leave **C03 April** unrun: it is run on
   camera.

**Checklist**

- [ ] `GET http://localhost:8000/api/health` shows `db`, `hindsight` and `llm` all `up`.
- [ ] A finished eval run is in `evals/results/` so the Insights chart has data ([EVALS.md](EVALS.md)).
- [ ] Browser at 1440×900, zoom 110%, notifications off, bookmarks bar hidden.
- [ ] No terminal showing `.env`, and no API key anywhere on screen.
- [ ] Recorder at 1080p; microphone checked.
- [ ] Backup: record each segment once as soon as it works, in case Groq is slow later.

## 2. Script (target 3:30, hard limit 5:00)

| Time | Screen | Say (gist) |
|---|---|---|
| 0:00–0:20 | Title card → workbench | "Every month, CA firms match thousands of purchase invoices against GSTR-2B. The same vendors cause the same problems, and the knowledge lives in one accountant's head." |
| 0:20–0:45 | C01 · January; open a card and its note | "Munshi is a reconciliation agent with long-term memory, built on Hindsight. In January it knows nothing. It asks, and it listens." Show a low-confidence card and the accountant's note. |
| 0:45–1:15 | February → March; memory panel; *Trust board* | "Every decision and note is retained. Each month it checks whether its past advice was right." Show ✓ outcome rows, and Laxmi Packaging reaching Auto. |
| 1:15–1:45 | C02 · April, *Auto* section; expand cited memories | "April, live. Bhavani Chemicals: deferred automatically, because it's been right before. Laxmi's rounding difference: accepted automatically, the firm's own rule." |
| 1:45–2:20 | C01 · April, Reddy Steels card | "Reddy Steels looked exactly like Bhavani, until now. Its March invoice never arrived. Munshi noticed its own assumption broke, dropped its trust, and says chase." Show the drift chip, trust reset and vendor message. Choose *Hold payment* with a note, and the retain appears in the memory panel. |
| 2:20–2:45 | C03 · April → *Run reconciliation*; Krishna Logistics card | "A different client buys from Krishna Logistics. Munshi remembers it never filed for Sri Balaji Textiles, and warns before the credit is lost." Show the cited memory tagged with the other client. |
| 2:45–3:05 | Toggle *Memory* OFF → re-run C03 April | "Same model, same data, memory off: generic, low confidence, and no warning." Then toggle back ON. |
| 3:05–3:25 | *Insights* | The learning curve ON vs OFF, zero unsafe suggestions, share auto-resolved. Quote one number from the eval report. |
| 3:25–3:30 | Closing card | "Munshi: it remembers, checks itself, and earns trust." Repo link. |

Notes:
- Don't make decisions on C03 April before the OFF re-run. Decisions survive a
  re-run (D27), and the comparison should show only the suggestions.
- The data is synthetic. Say so once, e.g. over the Insights screen: "on a synthetic
  dataset with planted vendor patterns".
- Record the voice separately if that's easier, and cut in any free editor. Add
  YouTube chapters at the times above.

## 3. After recording

- [ ] Upload to YouTube (public or unlisted, as required) and add chapters.
- [ ] Put the link in the README (the *Video* line) and in both members' posts.
- [ ] Take the screenshots for the README and posts from the recording: the
      workbench with a cited memory, the Reddy drift card, the Insights chart.
      Save them to `docs/images/`.
- [ ] Run the banned-word check from SPEC-10 AC-10-3 over the repo and every post.

## 4. If something goes wrong

| Symptom | Fix |
|---|---|
| Top bar shows *Memory offline* | Hindsight isn't running or is still loading models. Start it and wait; `/api/health` retries on its own and replays queued memories. |
| Cards say *AI unavailable* | Check `GROQ_API_KEY` in `.env`; a 429 means you've hit the rate limit, so wait a minute. |
| A beat doesn't show with the live model (e.g. no cross-client flag) | Re-run that month (the model varies). Guardrails drop unsupported flags on purpose, so check the card's guardrail notes. If it still doesn't show, use the backup recording. |
| *Load sample data* says the database has data | Reset the demo first. |
| Seed takes long | Hindsight extracts facts on every retain. Seed before you start recording; it runs in the background. |

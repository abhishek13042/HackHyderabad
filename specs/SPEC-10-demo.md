# SPEC-10 — Demo, Video & Submission

**Status:** DONE (repo side; recording and publishing are the team's actions) · **Owner:** Both · **Depends on:** all

## 1. Purpose

Turn the working product into what judges see: a 2–5 min video, a repo whose
README explains Hindsight usage, and per-member articles/posts. **Never name the
event or call it a competition** anywhere in this content (see AC-10-3).

## 2. Demo preconditions (checklist)

- [ ] `hindsight-api` running, `/health` all green.
- [ ] `/demo/reset` then `/demo/seed` done (Jan–Mar learned); April run for C01 and C02, C03 April left for camera.
- [ ] Latest eval results present (Insights chart populated).
- [ ] Browser at 1440×900, zoom 110%, notifications off; screen recorder at 1080p.
- [ ] Backup: a pre-recorded run of every step in case Groq is slow.

## 3. Video script (target 3:30, hard max 5:00)

| Time | Screen | Say (gist) |
|---|---|---|
| 0:00–0:20 | Title card → workbench | "Every month, CA firms match thousands of purchase invoices against GSTR-2B. The same vendors cause the same problems — and the knowledge lives in one accountant's head." |
| 0:20–0:45 | Data screen, Jan run | "Munshi is a reconciliation agent with long-term memory, built on Hindsight. January: it knows nothing. It asks, and it listens." Show a low-confidence card + accountant note. |
| 0:45–1:15 | Feb → Mar quickly; memory panel | "Every decision and note is retained. Every month, it checks whether its past advice was right." Show ✓ outcome rows, Laxmi Packaging going to Auto. |
| 1:15–1:45 | April workbench | "April, live. Bhavani Chemicals: auto-deferred — it's been right twice. Laxmi's ₹6 rounding: auto-accepted, the firm's own rule." Expand cited memories. |
| 1:45–2:20 | Reddy Steels card | "Reddy Steels looked exactly like Bhavani — until now. Its March invoice never arrived. Munshi noticed its own assumption broke, dropped its trust, and says chase." Show drift chip, trust reset, vendor message. Accountant chooses Hold payment + note → retain appears. |
| 2:20–2:45 | C03 · April, run live · Krishna Logistics card | "A different client buys from Krishna Logistics. Munshi remembers it never filed for Sri Balaji Textiles — warns before the loss." Show the cited memory tagged with the other client. |
| 2:45–3:05 | Toggle memory OFF, re-run C03 April | "Same model, memory off: generic, low-confidence, no warning." Toggle back ON. (No decisions on C03 before this: they survive a re-run, D27.) |
| 3:05–3:25 | Insights | Learning curve ON vs OFF, 0 unsafe suggestions, % auto-resolved. |
| 3:25–3:30 | Closing | "Munshi: it remembers, checks itself, and earns trust." Repo link. |

Record voice separately if needed; cut with any free editor. Upload to YouTube (unlisted or public as required), add chapters.

## 4. Repository deliverables

```
README.md            what, why, 60-sec quickstart, screenshots/GIF, results table
docs/HINDSIGHT_USAGE.md   banks, mission/disposition, retain templates, recall, reflect, why each — with code links
docs/ARCHITECTURE.md      diagram + run flow
docs/EVALS.md             SPEC-09 results, honest limitations
docs/DECISIONS.md         key decisions (no fine-tuning, JSON mode, firm-wide trust, …)
docs/GLOSSARY.md          GST terms
docs/RESEARCH.md          papers and how each shaped the design
specs/                    these specs
.env.example
```
README must let a stranger run it: install, start Hindsight, start backend, start frontend, click "Load sample data".

## 5. Written content (per member)

| Item | Length | Angle (differ between the two members) |
|---|---|---|
| Article (Medium or Dev.to) | 800–1,500 words | A: "Teaching an agent to check its own advice" (learning loop, drift) · B: "Designing memory for a tax agent: what to remember and what to forget" (Hindsight usage, templates, token budget) |
| LinkedIn post | 150–250 words | Problem → one surprising result → video link |
| Reddit share | short | Relevant subs (e.g. r/LocalLLaMA / r/india-tech style); follow each sub's self-promo rules |

Each includes: the video link, repo link, one real screenshot, one number from evals.
Checklist before posting: no event name (AC-10-3), no API keys in screenshots, synthetic-data disclosure.

## 6. Timeline (today = 27 Sep; deadline 29 Sep)

| When | A | B |
|---|---|---|
| 27 Sep (rest of day) | Review specs · setup · Hindsight smoke test | Review specs · SPEC-02 generator |
| 28 Sep AM | Matcher + memory wrapper + agent | API + UI skeleton |
| 28 Sep PM | Learning loop + seed | Workbench + memory panel |
| 28 Sep night | Evals run | Vendor/Insights screens |
| 29 Sep AM | Fixes, docs, README | Record video |
| 29 Sep PM | Articles + posts, submit | Articles + posts, submit |

**Cut list if late (in order):** keyboard shortcuts → vendor timeline → monthly reflect summary → upload UI (keep sample load) → repeats=3 evals.
**Never cut:** memory panel, drift, cross-client, ON/OFF comparison, guardrails.

## 7. Acceptance criteria

- AC-10-1: Full demo flow runs end-to-end twice in a row from reset without errors.
- AC-10-2: Video 2–5 min, uploaded, link in README.
- AC-10-3: `grep -riE "hack[a]thon"` over the whole repo and all content returns nothing (the bracket keeps this line from matching itself).
- AC-10-4: A teammate follows the README on a clean clone and reaches the workbench.
- AC-10-5: Both members' articles, LinkedIn and Reddit posts are published and linked in the submission form.

## 8. Implementation

| Deliverable | Where |
|---|---|
| Demo runbook and final video script | `docs/DEMO.md` (supersedes §2–§3 where they differ) |
| Rehearsal (AC-10-1) | `backend/scripts/demo_check.py`, tested in `backend/tests/test_demo_check.py` |
| README: quickstart, results, documentation table, video placeholder | `README.md` |
| Architecture, memory usage, research, glossary | `docs/ARCHITECTURE.md`, `docs/HINDSIGHT_USAGE.md`, `docs/RESEARCH.md`, `docs/GLOSSARY.md` |
| Article drafts (A and B), LinkedIn and Reddit drafts | `docs/content/article-a.md`, `docs/content/article-b.md`, `docs/content/posts.md` |

Decisions: D46–D49 in `docs/DECISIONS.md`.

**`demo_check`** (standard library only) talks to a running API. It resets, seeds,
runs C03 April with memory OFF, then April for every client with memory ON, and
checks each beat of the script: Bhavani auto-deferred, Laxmi auto-accepted, Reddy
drift with no DEFER (then a HOLD_PAYMENT decision with a note), the Krishna
cross-client warning, the insights learning curve and the memory events. It
repeats this `--rounds` times (default 2). It exits 1 on any API error, and with
`--strict` 2 if any beat was missed. It refuses to run without `--yes`, because
it deletes the demo data.

**Acceptance criteria**

| AC | How |
|---|---|
| AC-10-1 | `python -m backend.scripts.demo_check --yes --strict` against the live stack. The test suite runs the same script in-process (with the scripted model) and checks two clean rounds. |
| AC-10-2 | Team action: record and upload, then replace `[VIDEO_URL]` in the README. |
| AC-10-3 | `grep -riE "hack[a]thon" . --exclude-dir={node_modules,.venv,.venv-hindsight,dist}` returns nothing (checked on the repo; run again on the final posts). |
| AC-10-4 | Team action: a teammate follows the README on a clean clone. |
| AC-10-5 | Team action: publish the drafts in `docs/content/` and link them in the submission form. |

The drafts contain placeholders (`[VIDEO LINK]`, `[REPO LINK]`, `[ON %]` …) rather
than numbers: every number must come from a real `evals/results/<run_id>/report.md`.

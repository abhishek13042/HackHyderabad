<!--
Short posts for both members. Replace every [BRACKET] before posting, attach one real
screenshot (no API keys visible), and run the banned-word check from SPEC-10 AC-10-3.
Each member posts their own version; don't post identical text from both accounts.
-->

# LinkedIn — member A (150–250 words)

Every month, CA firms in India reconcile each client's purchase invoices against
GSTR-2B. Matching is solved. What isn't solved is *remembering*: which vendor files
late but reliably, which one never files, which ₹6 differences the firm always
accepts. That knowledge sits in one senior accountant's head.

We built **Recon**, a reconciliation agent with long-term memory (on Hindsight). It
remembers every decision and the accountant's note. The next month, it checks
whether its own advice was right.

The part I'm proudest of: a vendor that always filed a month late suddenly stops. An
agent that only remembers would say "defer, they're always late". Recon notices
that its own assumption broke. It drops its trust in that pattern and says chase.

On our synthetic benchmark (same model, memory on vs off), accuracy in the held-out
month was [ON %] vs [OFF %], with [0] unsafe suggestions.

The model never changes. The memory does.

🎥 [VIDEO LINK]
💻 [REPO LINK]

#AI #Agents #GST #AgentMemory #Accounting

---

# LinkedIn — member B (150–250 words)

Giving an AI agent long-term memory is easy. Deciding what it should *not* remember
is the hard part.

For **Recon**, our GST reconciliation agent, we store only three things: how a
problem was resolved, whether that turned out to be right, and when a vendor changed
its behaviour. We don't store clean invoices (about 85% of rows), raw files, or
ignored suggestions.

A few rules that worked:
• One memory per group of issues, written as plain English with the accountant's
  own note
• One memory bank per firm, so a vendor that failed one client triggers a warning
  at another
• One capped recall per issue, so the prompt stays flat as history grows
  ([TOKENS FEB] → [TOKENS APR] tokens per group)
• Every claim must cite a memory, and code checks the citations

Result on our synthetic benchmark: [ON %] accuracy with memory vs [OFF %] without, in
a month the prompt was never tuned on.

Built on Hindsight. Code, specs and the eval are open:

🎥 [VIDEO LINK]
💻 [REPO LINK]

#AI #LLM #AgentMemory #RAG #FinTech

---

# Reddit share (short)

Pick subreddits where this is on topic, and read each sub's self-promotion rules
first. Some allow links only in certain threads or on certain days. Suggestions:
r/LocalLLaMA (angle: memory design, open models on Groq), r/MachineLearning only in
its self-promotion thread, r/developersIndia, r/IndiaTech, r/CAIndia (angle: the
accounting problem; ask for feedback, don't sell).

**Title:** We built a GST reconciliation agent that checks whether its own advice was right [open source]

**Body:**

> CA firms in India match purchase invoices against GSTR-2B every month. Matching
> is easy. Remembering how each vendor behaves isn't, and it lives in one person's
> head.
>
> Recon is an agent with long-term memory (Hindsight) that remembers each decision
> and note, checks the next month whether it was right, earns autonomy per vendor
> pattern, and notices when a vendor breaks its pattern (a late filer who stops
> filing). Matching and all tax rules are plain code; the model only suggests, and
> guardrails check every answer.
>
> On a synthetic dataset (planted vendor behaviours, same model with memory on vs
> off): [ON %] vs [OFF %] accuracy in the held-out month, [0] unsafe suggestions.
> Synthetic data, so it shows the learning loop works, not real-world performance.
>
> Video: [VIDEO LINK] · Code, specs, eval: [REPO LINK]
>
> We'd love feedback, especially from anyone who does GST reconciliation for a living.

---

## Before posting (each member)

- [ ] Video link, repo link, one real screenshot, one number from `report.md`.
- [ ] The synthetic-data disclosure is in the text.
- [ ] No API keys, `.env` or terminal secrets in any screenshot.
- [ ] The banned-word check (SPEC-10 AC-10-3) on the final text returns nothing.
- [ ] Links to the published posts added to the submission form (AC-10-5).

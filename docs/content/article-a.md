<!--
Member A · Medium or Dev.to · 800–1,500 words.
Before publishing: replace every [BRACKET], add one real screenshot (no API keys),
and run the banned-word check from SPEC-10 AC-10-3 on the final text.
-->

# Teaching an agent to check its own advice

*How we built Munshi, a GST reconciliation agent that remembers what it
suggested last month and finds out whether it was right.*

Every month, a Chartered Accountant in India does the same tedious job for each
client. The accountant takes the client's purchase register and matches it against
**GSTR-2B**, the statement of invoices the client's suppliers reported to the tax
system. Input tax credit can only be claimed for invoices that show up there, so
every mismatch is money at risk.

Matching is a solved problem. Plenty of tools line up invoices and give you a list
of differences. The hard part comes after the list, and it's where the accountant's
time goes:

- *Reddy Steels is missing again. Do we chase them, or wait? They always file late.*
- *Laxmi Packaging is off by ₹6. We always accept that. Rounding.*
- *Krishna Logistics? Didn't they never file for another client?*

That knowledge lives in one senior accountant's head. We wanted to see whether an
agent could build it up month by month and use it safely. The harder question was
whether it could tell when its own knowledge had gone stale.

## The loop

Munshi runs the same loop every month for each client:

1. **Match** the books against GSTR-2B. This is plain code, deterministic and
   tested. We don't let a language model near the arithmetic.
2. **Check last month's advice.** If we deferred an invoice because "they're just
   late", did it arrive in this month's 2B?
3. **Look for drift.** Has a vendor stopped behaving the way it used to?
4. **Update trust** for each pattern (vendor × kind of problem).
5. **Recall** what the firm knows about this vendor, at any client.
6. **Suggest** an action for each group of exceptions, with reasons and citations.
7. **Auto-resolve** the patterns that have earned it.

The accountant accepts or overrides each suggestion. An override needs a short
note, because that note is the most useful thing the agent will ever learn from.

Step 2 is the one we care about most.

## Advice you can check

Most agent memory records *what happened*. Munshi also records *whether it worked*.

When the accountant defers Reddy Steels' February invoices, that decision goes into
memory (we use [Hindsight](https://github.com/vectorize-io/hindsight)) as a plain
English sentence:

> February 2026: At client Sri Balaji Textiles, vendor Reddy Steels had 2 invoices
> missing from GSTR-2B, ITC at risk ₹53,402.04. Munshi suggested DEFER. The
> accountant accepted it. Accountant's note: "Jan invoice showed up in Feb 2B.
> They're just late. Deferring."

In March the new GSTR-2B arrives, and the self-check looks for those invoices. They
are there, filed 46 days after the invoice date, so a second memory is written:

> March 2026: Checked the February 2026 decision for vendor Reddy Steels at client
> Sri Balaji Textiles: the decision to DEFER was correct.

This is the idea behind *Reflexion* (Shinn et al., 2023): an agent can improve by
remembering verbal feedback about its own actions, without touching the model's
weights. We never fine-tune. **The model stays the same; the memory grows.**

## Earning trust, and losing it

A pattern that keeps getting the same decision, with outcomes that confirm it, climbs
a ladder: **Observe → Suggest → Auto**. At Auto, Munshi resolves the case itself and
shows it in its own section, where the accountant can undo it with a note.

The rules are in code, not in the prompt:

- Auto needs a streak of three identical decisions, or two backed by two verified
  outcomes.
- A wrong outcome, an undo or drift sends the pattern straight back to Observe.
- Some actions can never be automatic, whatever the trust. Claiming credit for an
  invoice that isn't in GSTR-2B is simply not possible: a guardrail rewrites it
  before anyone sees it.

## When the pattern breaks

Here is the case we built the whole project around.

Reddy Steels files a month late: January's invoice arrives in February, February's
in March. By April, Munshi has two verified-correct deferrals, and deferring Reddy
looks exactly like deferring Bhavani Chemicals, another late filer.

But Reddy's March invoice never arrives in April's 2B.

An agent that only remembers would defer again: that's what the history says. Munshi
does three things instead:

1. The self-check writes *"the decision to DEFER was wrong"*.
2. Drift detection notices the vendor has missed its usual window, and writes:
   *"Vendor Reddy Steels broke its usual pattern … Earlier assumptions about this
   vendor should not be trusted."*
3. Trust drops to Observe, and a guardrail won't allow DEFER for this vendor while
   the drift stands. The suggestion becomes **chase the vendor** or **hold payment**, with a
   drafted message.

The long-term memory research calls this a *knowledge update*: LongMemEval (Wu et
al., 2024) treats it as its own category, because remembering is easy and
un-remembering is hard. In a tax context, an assumption that has gone stale is
worse than having none.

[SCREENSHOT: the Reddy Steels card with the drift chip and cited memories]

## Does it work? We measured it

We built an evaluation that runs the same four months twice, with the same model,
the same prompt and the same simulated accountant. One run has memory, the other
doesn't, and each condition gets a fresh memory bank.

| | Memory ON | Memory OFF |
|---|---|---|
| Accuracy of suggestions, April (held out) | [ON %] | [OFF %] |
| Unsafe suggestions shown | [0] | [0] |
| Resolved automatically, April | [AUTO %] | 0% |

[One sentence on the result, including what didn't work, from report.md.]

The honest caveat: this is **synthetic data** with vendor behaviours we planted on
purpose, so we could measure learning against a known answer. It shows the loop
works. It says nothing yet about a real firm's books.

## What we'd do next

- A noisy simulated accountant who is sometimes wrong, to see whether the self-check
  catches bad lessons as well as stale ones.
- Real data from a practising firm, with consent.
- Per-client preferences on top of firm-wide trust.

The code, the specs and the evaluation are open: [REPO LINK]. The demo video is
here: [VIDEO LINK].

*Munshi means "clerk" or "accountant" in Hindi and Urdu, the person who kept the
books and remembered who paid late.*

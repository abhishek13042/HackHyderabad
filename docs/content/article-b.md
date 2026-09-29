<!--
Member B · Medium or Dev.to · 800–1,500 words.
Before publishing: replace every [BRACKET], add one real screenshot (no API keys),
and run the banned-word check from SPEC-10 AC-10-3 on the final text.
-->

# Designing memory for a tax agent: what to remember and what to forget

*The hardest part of giving an agent long-term memory wasn't storing things. It was
deciding what not to store.*

We built Recon, an agent that helps Chartered Accountants in India with a monthly
chore: reconciling a client's purchase invoices against GSTR-2B, the government's
list of what suppliers actually reported. Every mismatch means tax credit at risk,
and resolving one well depends on history. Who files late? Who never files? Which
small differences does this firm always accept?

So the agent needed memory. We used [Hindsight](https://github.com/vectorize-io/hindsight),
which gives you four calls: `retain`, `recall`, `reflect`, and a bank to keep it all
in. It would have been easy to pour everything into it. Here is why we didn't, and
what we did instead.

## Rule 1: remember what was learned, not what happened

A client-month has hundreds of invoices, and about 85% of them match cleanly. Those
teach nothing. The raw files are already in a database. Suggestions nobody acted on
carry no signal.

So Recon retains exactly three kinds of memory:

| Kind | When |
|---|---|
| **Resolution** | The accountant decides a group of exceptions, or Recon does automatically |
| **Outcome** | Next month shows whether that decision was right, or a late invoice finally arrives |
| **Drift** | A vendor breaks its usual pattern |

We write **one memory per group** (a vendor's exceptions of one type in one month),
never one per invoice. A client-month produces a handful of memories, not hundreds.

The database keeps what *happened*. Memory keeps what was *learned*. That split
made nearly every other decision easy.

## Rule 2: write memories a stranger could understand

Hindsight pulls facts and entities out of the text you give it. So our memories are
full, self-contained English sentences, not JSON blobs:

> February 2026: At client Sri Balaji Textiles, vendor Reddy Steels (GSTIN
> 36AABCR1234F1ZT) had 2 invoices missing from GSTR-2B, ITC at risk ₹53,402.04.
> Recon suggested DEFER. The accountant accepted it. Accountant's note: "Jan
> invoice showed up in Feb 2B. They're just late. Deferring."

Every memory names the vendor, its GSTIN and the client in full. It carries the
accountant's own note, word for word. When the accountant disagrees, the template
says so plainly ("The accountant overrode it and chose …"), because overrides are
the most valuable memories there are.

Three details matter more than they look:

- **The timestamp is the business date**, not when our code ran. The seeded history
  then has a real timeline, and "what happened last month" means something.
- **The document id is the group**, like `resolution:C01:2026-02:<gstin>:MISSING_IN_2B`.
  If the accountant changes their mind, the memory is *replaced*, so memory doesn't
  pile up contradictions.
- **Tags** (`vendor:<gstin>`, `client:<id>`) let us scope summaries to one vendor.

## Rule 3: one bank per firm, not per client

Our first sketch had a bank per client. Then we saw what that throws away. If a
vendor never filed for one client, that is exactly what you want to know when it
turns up at another.

With one bank for the firm, the same recall that finds *this* client's history finds
the others' too. That is how Recon warns a new client about Krishna Logistics
before the credit is lost. A code guardrail makes sure the warning cites a real
memory from another client: no citation, no warning.

[SCREENSHOT: the Krishna Logistics card with a memory tagged with another client]

## Rule 4: ask one good question, with a budget

It's tempting to recall everything about a vendor and paste it in. Two papers talked
us out of it. *MemGPT* (Packer et al., 2023) treats the context window like RAM: page
in what you need. *Lost in the Middle* (Liu et al., 2023) showed that models overlook
information buried in long contexts. So more history can make the answers worse, not
just more expensive.

Recon asks **one question per exception group**:

> How were invoices missing from GSTR-2B from vendor Reddy Steels (GSTIN
> 36AABCR1234F1ZT) handled before, at any client, and what happened afterwards? How
> does this vendor usually behave? Any accountant preferences about invoices missing
> from GSTR-2B?

It asks for facts, experiences and Hindsight's own observations, capped at **1,500
tokens**, and cached until something new is learned. The GSTIN is in the question so
keyword search hits exactly; the names help semantic search.

The memories reach the model labelled `M1`, `M2`, and it must cite the ones it used.
Code checks every citation: invented ids are dropped, and claims about history with
no citation get their confidence cut. In the UI every suggestion shows the memories
behind it and where each came from.

The payoff is a prompt that stays about the same size in April as in February, even
though there's four times the history. Our evaluation measures tokens per group per
month to check that: [TOKENS FEB] → [TOKENS APR].

## Rule 5: reflect is for people

Hindsight's `reflect` reasons over the whole bank, and it's the expensive call. We
never use it while reconciling. It powers two things a person reads: the vendor
profile ("how does this vendor behave, and how reliable have our assumptions been?")
and a monthly summary. Both are cached until the next retain.

## Rule 6: forgetting is a feature

Memory that only accumulates will eventually be confidently wrong. One of our planted
vendors files a month late, reliably, until it stops. When that happens, Recon
writes a *drift* memory that says, in so many words, "earlier assumptions about this
vendor should not be trusted". Trust in that pattern resets, and a guardrail stops
deferral. Hindsight's recall now surfaces the warning alongside the old history.

## Rule 7: memory can be down, the accountant can't

When the memory server is unreachable, retains queue in SQLite and replay later.
Recall reports "offline", the agent works as if memory were off, and the UI says so.
The accountant is never blocked by the memory layer.

## Did it pay off?

We ran the same four months with memory on and off, on synthetic data with planted
vendor behaviours:

- Accuracy in the held-out month: [ON %] with memory vs [OFF %] without.
- Unsafe suggestions shown to the accountant: [0].
- [One honest sentence about what didn't work, from report.md.]

The data is synthetic, so this shows that the design works, not how it does on a
real firm's books.

Code, specs and the full memory design ([docs/HINDSIGHT_USAGE.md]) are here:
[REPO LINK]. Video: [VIDEO LINK].

# SPEC-00 — Product Requirements

**Status:** DONE · **Owner:** Both · **Depends on:** —

## 1. Purpose

Define what Munshi is, who it is for, and what "success" means, so every other
spec can be checked against it.

## 2. Problem

Every month, ~1.3 crore regular GST taxpayers must reconcile their purchase
register against GSTR-2B. Input Tax Credit (ITC) can only be claimed for
invoices the supplier has reported. Existing tools (ClearTax, Zoho, Tally)
already **match** invoices. What they don't do is **remember how exceptions
were resolved**: which vendors file late but reliably, which always have ₹5
rounding differences, which contact actually responds, which vendor caused
trouble for another client. That knowledge lives in the senior accountant's
head and is lost when they leave or are busy.

## 3. Persona

**CA Priya Rao**, sole practitioner, *Rao & Associates*, Hyderabad.
- 40 small-business clients (we model 3).
- Spends the first ~10 days of every month on reconciliation and vendor follow-up.
- Works from Tally exports and GSTR-2B downloads; uses Excel and WhatsApp today.
- Legally responsible for what she files, so she will not hand decisions to a black box.

## 4. Value proposition

> Big GST tools match invoices. Munshi remembers how your firm resolves them,
> checks whether its advice was right, and handles next month's exceptions the
> way your best accountant would.

## 5. User stories

| ID | As Priya, I want to… | So that… |
|---|---|---|
| US-1 | upload a client's purchase register and GSTR-2B for a month | I get the list of exceptions without manual matching |
| US-2 | see each exception with a suggested action and **why** | I can decide quickly and trust the reasoning |
| US-3 | see which past memories the suggestion is based on | I can verify it isn't made up |
| US-4 | accept or override a suggestion, with a note | the agent learns my way of working |
| US-5 | have routine, proven cases handled automatically | I only spend time on genuinely new problems |
| US-6 | be warned when a vendor stops behaving as usual | I don't lose credit by trusting an outdated pattern |
| US-7 | be warned when a vendor caused problems for another client | I can protect this client early |
| US-8 | see a vendor's full profile | I know how to deal with them before calling |
| US-9 | see a monthly summary (ITC at risk, auto-resolved, new risks) | I can report to clients |
| US-10 | turn memory off | I can see what difference it makes (demo / trust) |

## 6. Scope

**In scope**
- 1 firm, 3 clients, ~25 vendors, 4 months (Jan–Apr 2026) of synthetic data.
- Upload (or load sample) → match → agent suggestions → decisions → memory.
- Self-checking outcomes, trust ladder, drift detection, cross-client alerts.
- Vendor profile, monthly insights, memory ON/OFF toggle, live memory activity panel.
- Evals with memory ON vs OFF and a learning curve.

**Out of scope (non-goals)**
- Login, multi-user, roles, billing.
- Real GST portal / Tally integration (file upload only).
- OCR of invoice PDFs.
- Filing returns (GSTR-3B) or computing tax liability.
- Sending emails / WhatsApp (we only draft messages).
- Credit notes, debit notes, amendments (CDNR), reverse charge, imports. B2B invoices only.
- Mobile layout beyond "doesn't break".

## 7. Success metrics

| Metric | Target | Measured by |
|---|---|---|
| Action accuracy, memory ON, month 4 | ≥ 80% | SPEC-09 |
| Accuracy gap ON vs OFF, month 4 | ≥ 25 percentage points | SPEC-09 |
| Unsafe suggestions (claim ITC not in 2B) | 0 | SPEC-09 guardrail check |
| Drift detected for planted drift vendor | Yes, in the first month it's detectable | SPEC-09 |
| Cross-client alert for planted vendor | Yes | SPEC-09 |
| Exceptions auto-resolved in month 4 | ≥ 40% of exception groups | SPEC-06 / SPEC-09 |
| Demo story fits in 3 minutes | Yes | SPEC-10 rehearsal |

Targets are hypotheses we test; the article and README report whatever the evals actually show.

## 8. Principles

1. **Code for numbers, AI for judgment.** Matching is deterministic; the LLM only decides and explains.
2. **The database stores what happened; memory stores what we learned.**
3. **The agent suggests, the CA decides.** Autonomy is earned per pattern and revocable.
4. **Every claim is grounded.** Suggestions cite real memory; citations are verified.
5. **Never unsafe.** Code-level guardrails override the LLM.

## 9. Acceptance criteria

- AC-00-1: Every user story US-1…US-10 maps to at least one acceptance criterion in SPEC-03…SPEC-08.
- AC-00-2: Nothing listed under "Out of scope" is built.
- AC-00-3: The README states the problem, persona and value proposition consistent with this spec.

## 10. Open questions

- ~~Q1: Product name "Munshi"?~~ Approved.
- ~~Q2: Fictional firm/persona names?~~ Approved.

AC-00-1 → [TRACEABILITY.md](TRACEABILITY.md). AC-00-3 → root `README.md`.
AC-00-2 is checked at every review.

## 11. Verification (final review)

- AC-00-1: every story US-1…US-10 is mapped in TRACEABILITY.md, and those criteria are met in SPEC-03…SPEC-08.
- AC-00-2: no login, portal/Tally integration, OCR, return filing, message sending, or
  non-B2B documents. Ingest rejects reverse-charge rows (`rev` must be `N`), and
  vendor messages are drafts only.
- AC-00-3: the README's *The problem*, *Who it's for* and *What Munshi does* sections
  follow §2–§4.
- §7 metrics are measured by SPEC-09, and the results are reported as they come out.

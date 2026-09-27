# SPEC-05 — Agent / Decision Engine

**Status:** DRAFT · **Owner:** A · **Depends on:** SPEC-03, SPEC-04

## 1. Purpose

For each exception group, combine the facts (from the matcher), what memory
recalls, and the trust/drift signals (SPEC-06) into **one safe, explained,
grounded suggestion** — and draft a vendor message where useful.

## 2. Scope

**In:** prompt, few-shot examples, LLM call, output schema, validation, retries,
guardrails, vendor message drafting, memory ON/OFF.
**Out:** matching (SPEC-03), memory storage (SPEC-04), trust maths (SPEC-06).
**No fine-tuning.** Specialisation comes from prompt + few-shot + schema + memory + guardrails (see docs/DECISIONS.md).

## 3. Interface

```python
def suggest(group: ExceptionGroup, ctx: AgentContext) -> Suggestion

@dataclass
class AgentContext:
    client: Client
    vendor: Vendor
    memories: list[RecalledMemory]   # [] when memory OFF or nothing found
    trust: TrustInfo                 # level + stats (SPEC-06); level 0 when OFF
    drift: DriftInfo | None          # set by SPEC-06 when detected
    memory_on: bool
```

### Output JSON (the LLM must return exactly this)
```json
{
  "action": "DEFER",
  "root_cause": "LATE_FILING",
  "flags": ["RECURRING_ISSUE"],
  "confidence": 0.86,
  "reasoning": "Reddy Steels filed Jan and Feb invoices about a month late, and both appeared in the next 2B. Same pattern expected; no chase needed.",
  "cited_memory_ids": ["m_1a2b", "m_3c4d"],
  "vendor_message": null
}
```
| Field | Rule |
|---|---|
| action | `Action`, must be allowed for the exception type (§4) |
| root_cause | `RootCause`; `UNKNOWN` when there is no evidence |
| flags | subset of `Flag` |
| confidence | 0–1 |
| reasoning | ≤ 60 words, plain English, must reference evidence |
| cited_memory_ids | IDs from the provided memories only |
| vendor_message | required for `CHASE_VENDOR` / `HOLD_PAYMENT`, else null |

Stored `Suggestion` adds: `group_key`, `final_confidence`, `guardrail_events[]`,
`model`, `latency_ms`, `prompt_tokens`, `completion_tokens`, `raw_output`, `memory_on`.

## 4. Allowed actions per exception type

| ExceptionType | Allowed |
|---|---|
| MISSING_IN_2B | DEFER, CHASE_VENDOR, HOLD_PAYMENT, ESCALATE |
| MISSING_IN_BOOKS | BOOK_INVOICE, ESCALATE |
| AMOUNT_MISMATCH | ACCEPT, CHASE_VENDOR, CORRECT_BOOKS, ESCALATE |
| TAX_HEAD_MISMATCH | CORRECT_BOOKS, CHASE_VENDOR, ESCALATE |
| GSTIN_MISMATCH | CORRECT_BOOKS, CHASE_VENDOR, ESCALATE |
| ITC_INELIGIBLE | BLOCK_ITC, CHASE_VENDOR, ESCALATE |

This table implements SPEC-01 INV-1 (no `ACCEPT` for missing/ineligible).

## 5. Guardrails (code, after the LLM — the LLM cannot bypass these)

| ID | Rule | On violation |
|---|---|---|
| G1 | action ∈ allowed(type) | → `ESCALATE`, log `UNSAFE_ACTION` |
| G2 | every cited ID exists in `ctx.memories` | drop unknown IDs, log `BAD_CITATION` |
| G3 | reasoning claims history ("before", "last month", "usually") but 0 valid citations | cap confidence at 0.5, log `UNGROUNDED` |
| G4 | `ACCEPT` on AMOUNT_MISMATCH with diff > ₹500 | → `ESCALATE`, log `LARGE_DIFF` |
| G5 | `CROSS_CLIENT_RISK` flag with no cited memory from another client | drop flag, log `UNGROUNDED_FLAG` |
| G6 | `ctx.drift` set | ensure `PATTERN_DRIFT` flag; action `DEFER` → `CHASE_VENDOR`, log `DRIFT_OVERRIDE` |
| G7 | invalid JSON / schema after 2 retries | `ESCALATE`, confidence 0, log `INVALID_OUTPUT` |

`final_confidence = min(llm_confidence, trust_cap(level))` — caps in SPEC-06.

## 6. Prompt

### System (summary — full text lives in `backend/app/prompts/system.md`)
1. Role: GST reconciliation assistant for an Indian CA firm; the accountant decides.
2. Key rules in 6 lines: ITC only if in 2B; intra-state = CGST+SGST, inter-state = IGST; etc.
3. The exception type, allowed actions (§4) and output schema.
4. Grounding rules: use only the facts and memories given; cite memory IDs; if there
   are no memories, say so and use `root_cause: UNKNOWN` unless the facts alone prove it.
5. Prefer the safest action when unsure; `ESCALATE` is acceptable.
6. Vendor messages: short, polite, specific (invoice numbers, amounts, the exact fix).

### Few-shot examples (3, in the system prompt)
1. No memory, first-time `MISSING_IN_2B` → `CHASE_VENDOR`, `UNKNOWN`, low confidence.
2. With memories of two late-but-filed months → `DEFER`, `LATE_FILING`, cites both.
3. With drift info → `CHASE_VENDOR`, `PATTERN_DRIFT`, explains the broken pattern.
Examples use a **different, fictional vendor** so they don't leak answers.

### User message
```
EXCEPTION GROUP
client: Sri Balaji Textiles (C01) · period: April 2026
vendor: Reddy Steels · GSTIN 36AABCR1234F1Z5 · state 36 · status ACTIVE
type: MISSING_IN_2B · invoices: 2 · ITC at risk: ₹27,000
invoices: RS/2025-26/0467 (03-04-2026, ₹1,06,200), RS/2025-26/0471 (...)

TRUST: level 0 OBSERVE · 1 correct, 1 wrong
DRIFT: Mar invoice RS/2025-26/0441 overdue by 38 days (typical lag ~30 days)

MEMORIES (cite by id)
[m_1a2b] March 2026: At client Sri Balaji Textiles, vendor Reddy Steels ...
[m_3c4d] ...
(or: "No memories available.")
```

## 7. LLM call

| Setting | Value |
|---|---|
| Provider | Groq (OpenAI-compatible API) |
| Model | `openai/gpt-oss-120b`; fallback `qwen/qwen3-32b` |
| Mode | JSON mode (`response_format={"type": "json_object"}`) — **no tool calling** (fragile on Groq, per problem statement) |
| Temperature | 0.1 |
| Timeout | 30 s |
| Retries | invalid JSON/schema: 2 retries with the validation error appended; HTTP 429/5xx: exponential backoff (1, 2, 4 s), then fallback model |
| Concurrency | ≤ 3 parallel calls (free-tier rate limits) |

Validation with Pydantic models generated from SPEC-01 enums.

## 8. Edge cases

- Empty memories → still a valid suggestion (memory-OFF behaviour).
- Group with 20+ invoices → list only the first 10 in the prompt plus totals.
- LLM returns an action in lowercase / with spaces → normalize before validation.
- Both models down → every group `ESCALATE` with reason "AI unavailable"; UI still usable.

## 9. Acceptance criteria

- AC-05-1: For every exception type, a mocked LLM returning a disallowed action is converted to `ESCALATE` (G1).
- AC-05-2: A mocked output citing a non-existent memory ID has it removed (G2).
- AC-05-3: Invalid JSON twice then valid → accepted on 3rd attempt; invalid 3× → `ESCALATE` (G7).
- AC-05-4: With drift set, a `DEFER` output becomes `CHASE_VENDOR` + `PATTERN_DRIFT` (G6).
- AC-05-5: `CHASE_VENDOR` / `HOLD_PAYMENT` always have a non-empty `vendor_message`.
- AC-05-6: Real run on the April dataset: 0 guardrail `UNSAFE_ACTION` events that reach the user (all converted).
- AC-05-7: Memory OFF prompts contain no memory text (snapshot test).
- AC-05-8: Every suggestion stores latency and token counts.

## 10. Open questions

- Q1: Confidence from the LLM is rough; is the trust cap enough, or do we hide the number and show only High/Medium/Low? Proposed: show labels.

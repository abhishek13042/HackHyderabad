# SPEC-05 — Agent / Decision Engine

**Status:** DONE (AC-05-6 live run pending a Groq key) · **Owner:** A · **Depends on:** SPEC-03, SPEC-04

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
# backend/app/agent.py
class Agent:
    def __init__(self, llm: ChatModel, clock=time.perf_counter): ...
    def suggest(self, group: ExceptionGroup, ctx: AgentContext) -> Suggestion
    def suggest_all(self, items: Sequence[tuple[ExceptionGroup, AgentContext]]) -> list[Suggestion]

@dataclass(frozen=True)
class AgentContext:
    client: Client
    vendor: Vendor
    memories: tuple[MemoryRecord, ...] = ()  # from SPEC-04 recall
    trust: TrustInfo = TrustInfo()           # level + stats (SPEC-06); OBSERVE by default
    drift: DriftInfo | None = None           # set by SPEC-06 when detected
    memory_on: bool = True
    def effective(self) -> AgentContext      # memory OFF: no memories, OBSERVE trust, no drift

def apply_guardrails(output: AgentOutput, group, ctx) -> tuple[AgentOutput, list[GuardrailEvent]]  # pure

# backend/app/llm.py (the only module importing `openai`)
class ChatModel(Protocol):
    def complete(self, messages: Sequence[Message]) -> Completion
class GroqChat(ChatModel): ...            # GroqChat.from_settings(settings)
```

`suggest` never raises for a bad model answer or an outage: it returns an
`ESCALATE` suggestion with the guardrail event that explains why. A context that
doesn't belong to the group (other client or vendor) is a programming error and
raises `ValueError`.

### Output JSON (the LLM must return exactly this)
```json
{
  "action": "DEFER",
  "root_cause": "LATE_FILING",
  "flags": ["RECURRING_ISSUE"],
  "confidence": 0.86,
  "reasoning": "Reddy Steels filed Jan and Feb invoices about a month late, and both appeared in the next 2B. Same pattern expected; no chase needed.",
  "cited_memory_ids": ["M1", "M2"],
  "vendor_message": null
}
```
| Field | Rule |
|---|---|
| action | `Action`, must be allowed for the exception type (§4) |
| root_cause | `RootCause`; `UNKNOWN` when there is no evidence |
| flags | subset of `Flag` |
| confidence | 0–1 |
| reasoning | ≤ 60 words, plain English, must reference evidence; longer text is cut with " …" |
| cited_memory_ids | aliases (`M1`, `M2`, …) of the provided memories only; stored as the real Hindsight ids |
| vendor_message | required for `CHASE_VENDOR` / `HOLD_PAYMENT`, else null |

Stored `Suggestion` adds: `group_key`, `final_confidence`, `guardrail_events[]`,
`model`, `latency_ms`, `prompt_tokens`, `completion_tokens`, `raw_output`, `memory_on`,
and a `confidence_label` (High ≥ 0.8, Medium ≥ 0.5, Low; D9).

Persisting suggestions to the `suggestions` table is part of the run flow (SPEC-06/07); the agent itself has no database access.

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
| G8 | `CHASE_VENDOR` / `HOLD_PAYMENT` without a message | fill a message from a code template (invoice numbers, amounts, the fix), log `MISSING_MESSAGE`; a message on any other action is dropped |
| — | both models down (§8) | `ESCALATE`, confidence 0, log `AI_UNAVAILABLE` |

Order: G2 → G6 → G1 → G4 → G3 → G5 → G8, so a later rule sees the corrected action and citations. G5 decides "another client" from the memory's `client_id` metadata, falling back to the "At client …," opening of the text.

`final_confidence = min(llm_confidence, trust_cap(level))`; caps are in `domain/policy.py`: OBSERVE 0.6, SUGGEST 0.85, AUTO 1.0 (tuned in SPEC-06).

## 6. Prompt

### System (summary — full text lives in `backend/app/prompts/system.md`)
1. Role: GST reconciliation assistant for an Indian CA firm; the accountant decides.
2. Key rules in 6 lines: ITC only if in 2B; intra-state = CGST+SGST, inter-state = IGST; etc.
3. All actions and the output schema. The **allowed actions go in the user message**, so the
   system prompt is identical for every call.
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
- RS/2025-26/0467 dated 03-04-2026, books total ₹1,06,200.00
- RS/2025-26/0471 ...

ALLOWED: CHASE_VENDOR, DEFER, ESCALATE, HOLD_PAYMENT
TRUST: level 0 OBSERVE · 1 correct, 1 wrong
DRIFT: invoices RS/2025-26/0441 overdue by 38 days (typical lag about 30 days)

MEMORIES (cite by id):
[M1] March 2026: At client Sri Balaji Textiles, vendor Reddy Steels ...
[M2] ...
(or: "MEMORIES: none available.")
```

## 7. LLM call

| Setting | Value |
|---|---|
| Provider | Groq (OpenAI-compatible API) |
| Model | `openai/gpt-oss-120b`; fallback `openai/gpt-oss-20b` |
| Mode | JSON mode (`response_format={"type": "json_object"}`) — **no tool calling** (fragile on Groq, per problem statement) |
| Temperature | 0.1 |
| Timeout | 30 s |
| Retries | invalid JSON/schema: 2 retries with the validation error appended; HTTP 429/5xx: exponential backoff (1, 2, 4 s), then fallback model |
| Concurrency | ≤ 3 parallel calls (free-tier rate limits) |

Validation with Pydantic models generated from SPEC-01 enums. Memories are shown as short
aliases (`M1`, `M2`) rather than Hindsight ids: fewer tokens and fewer mistyped citations.
On a retry the model's previous answer and the reason it was rejected are appended to the
conversation. Groq rejects invalid JSON-mode output with HTTP 400 `json_validate_failed`;
that counts as an invalid answer (G7), not an outage. 401/403 fail at once (bad key);
other 4xx (e.g. unknown model) move straight to the fallback model.

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

### How each is checked

| AC | Test |
|---|---|
| 05-1 | `test_agent.py::test_ac_05_1_disallowed_action_becomes_escalate` (every type) |
| 05-2 | `test_agent.py::test_ac_05_2_unknown_citation_is_removed` |
| 05-3 | `test_agent.py::test_ac_05_3_invalid_twice_then_valid`, `..._invalid_three_times_escalates` |
| 05-4 | `test_agent.py::test_ac_05_4_drift_turns_defer_into_chase` |
| 05-5 | `test_agent.py::test_ac_05_5_vendor_contact_always_has_a_message` |
| 05-6 | offline: `test_agent.py::test_ac_05_6_every_action_ends_allowed` (every type × action); live: `test_agent_live.py` (marked `groq`, skips without `GROQ_API_KEY`) |
| 05-7 | `test_agent.py::test_ac_05_7_memory_off_prompt_has_no_memory` |
| 05-8 | `test_agent.py::test_ac_05_8_latency_and_tokens_are_recorded` |

Backoff, fallback and error handling of the Groq client: `test_llm.py`.

## 10. Open questions

- ~~Q1~~: show High / Medium / Low with the number on hover (D9); `Suggestion.confidence_label`.

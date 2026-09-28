// Small API payloads for component tests.

import type { Client, Group, Suggestion } from "../api/types";

export const CLIENTS: Client[] = [
  { id: "C01", name: "Sharma Textiles", gstin: "36AABCS1234A1Z5", business: "Textile trading" },
  { id: "C02", name: "Mehta Pharma", gstin: "36AABCM5678B1Z3", business: "Pharma distribution" },
];

export function suggestion(overrides: Partial<Suggestion> = {}): Suggestion {
  return {
    action: "DEFER",
    root_cause: "VENDOR_LATE_FILING",
    flags: [],
    confidence_label: "HIGH",
    final_confidence: 0.86,
    reasoning: "Reddy files late every quarter; the invoice reached 2B the next month each time.",
    vendor_message: null,
    cited_memories: [],
    guardrail_events: [],
    guardrail_details: [],
    memory_on: true,
    model: "test",
    ...overrides,
  };
}

export function group(overrides: Partial<Group> = {}): Group {
  return {
    group_key: "C01|2026-04|36AAACR1111R1Z1|MISSING_IN_2B",
    vendor: { gstin: "36AAACR1111R1Z1", name: "Reddy Traders" },
    type: "MISSING_IN_2B",
    invoices: [
      {
        invoice_no: "RT/0412",
        date: "2026-04-12",
        total: "118000.00",
        tax: "18000.00",
        itc_at_risk: "18000.00",
        details: {},
      },
    ],
    itc_at_risk: "18000.00",
    suggestion: suggestion(),
    trust: { level: 1, name: "SUGGEST", streak_action: "DEFER", streak: 2, correct: 2, wrong: 0 },
    decision: null,
    allowed_actions: ["DEFER", "CHASE_VENDOR", "HOLD_PAYMENT", "BOOK_INVOICE", "ESCALATE"],
    ...overrides,
  };
}

// Plain-language labels for the API's enum values (SPEC-08 §2: no jargon in labels).

import type { Action, ExceptionType, Flag, TrustLevel } from "../api/types";

export const EXCEPTION_LABELS: Record<ExceptionType, string> = {
  MISSING_IN_2B: "Missing from GSTR-2B",
  MISSING_IN_BOOKS: "Missing from books",
  AMOUNT_MISMATCH: "Amount differs",
  TAX_HEAD_MISMATCH: "Wrong tax head",
  GSTIN_MISMATCH: "GSTIN differs",
  ITC_INELIGIBLE: "Credit not available",
};

export const ACTION_LABELS: Record<Action, string> = {
  ACCEPT: "Accept",
  DEFER: "Wait a month",
  CHASE_VENDOR: "Chase vendor",
  HOLD_PAYMENT: "Hold payment",
  CORRECT_BOOKS: "Correct books",
  BLOCK_ITC: "Block credit",
  BOOK_INVOICE: "Book invoice",
  ESCALATE: "Escalate to partner",
};

/** For the one-line summary of a decided card: "✓ Held payment". */
export const ACTION_DONE: Record<Action, string> = {
  ACCEPT: "Accepted",
  DEFER: "Waiting a month",
  CHASE_VENDOR: "Chasing vendor",
  HOLD_PAYMENT: "Held payment",
  CORRECT_BOOKS: "Correcting books",
  BLOCK_ITC: "Blocked credit",
  BOOK_INVOICE: "Booking invoice",
  ESCALATE: "Escalated",
};

export type Tone = "red" | "orange" | "grey" | "green" | "blue" | "yellow";

export const FLAG_LABELS: Record<Flag, { label: string; tone: Tone }> = {
  PATTERN_DRIFT: { label: "Pattern changed", tone: "red" },
  CROSS_CLIENT_RISK: { label: "Seen at another client", tone: "orange" },
  RECURRING_ISSUE: { label: "Recurring", tone: "grey" },
  VENDOR_RISK: { label: "Vendor risk", tone: "red" },
};

export const ROOT_CAUSE_LABELS: Record<string, string> = {
  LATE_FILING: "vendor files late",
  NOT_FILED: "vendor has not filed",
  WRONG_BUYER_GSTIN: "vendor used the wrong GSTIN",
  ROUNDING: "rounding",
  BOOKING_ERROR: "booking error",
  SUPPLIER_CANCELLED: "vendor registration cancelled",
  NOT_BOOKED: "not booked yet",
  UNKNOWN: "cause unclear",
};

export const GUARDRAIL_LABELS: Record<string, string> = {
  UNSAFE_ACTION: "action not allowed for this issue → escalated",
  BAD_CITATION: "cited a memory it was not given → citation removed",
  UNGROUNDED: "claimed history without a memory → confidence lowered",
  LARGE_DIFF: "large difference → escalated",
  UNGROUNDED_FLAG: "cross-client warning without evidence → flag removed",
  DRIFT_OVERRIDE: "vendor pattern changed → waiting is no longer safe",
  INVALID_OUTPUT: "no valid answer from the model → escalated",
  MISSING_MESSAGE: "vendor message drafted from a template",
  AI_UNAVAILABLE: "AI unavailable → escalated",
};

export const TRUST_LABELS: Record<TrustLevel, { label: string; tone: Tone; hint: string }> = {
  0: { label: "Observe", tone: "grey", hint: "Recon suggests; you decide every case." },
  1: { label: "Suggest", tone: "blue", hint: "Recon's suggestion has been right repeatedly." },
  2: { label: "Auto", tone: "green", hint: "Proven pattern: resolved automatically, you can undo." },
};

export const OUTCOME_LABELS: Record<string, { mark: string; label: string; tone: Tone }> = {
  VERIFIED_CORRECT: { mark: "✓", label: "turned out right", tone: "green" },
  VERIFIED_WRONG: { mark: "✗", label: "turned out wrong", tone: "red" },
  PENDING: { mark: "…", label: "waiting to see", tone: "grey" },
  NOT_APPLICABLE: { mark: "—", label: "nothing to check", tone: "grey" },
};

export const CONFIDENCE_LABELS = { HIGH: "High", MEDIUM: "Medium", LOW: "Low" } as const;

export function exceptionLabel(type: string): string {
  return EXCEPTION_LABELS[type as ExceptionType] ?? type;
}

export function actionLabel(action: string): string {
  return ACTION_LABELS[action as Action] ?? action;
}

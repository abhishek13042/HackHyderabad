// Response and request shapes of the backend API (SPEC-07, backend/app/schemas.py).
// Money is always a 2-decimal string ("27000.00"), never a number.

export type Money = string;

export type ExceptionType =
  | "MISSING_IN_2B"
  | "MISSING_IN_BOOKS"
  | "AMOUNT_MISMATCH"
  | "TAX_HEAD_MISMATCH"
  | "GSTIN_MISMATCH"
  | "ITC_INELIGIBLE";

export type Action =
  | "ACCEPT"
  | "DEFER"
  | "CHASE_VENDOR"
  | "HOLD_PAYMENT"
  | "CORRECT_BOOKS"
  | "BLOCK_ITC"
  | "BOOK_INVOICE"
  | "ESCALATE";

export type Flag = "CROSS_CLIENT_RISK" | "PATTERN_DRIFT" | "RECURRING_ISSUE" | "VENDOR_RISK";
export type TrustLevel = 0 | 1 | 2;
export type DecidedBy = "ACCOUNTANT" | "AUTO";
export type UpDown = "up" | "down";
export type Status = "running" | "done" | "failed";

export interface Health {
  ok: boolean;
  db: UpDown;
  seeded: boolean;
  hindsight: UpDown;
  llm: UpDown;
  bank_id: string;
  firm: string;
  pending_retains: number;
}

export interface Client {
  id: string;
  name: string;
  gstin: string;
  business: string;
}

export interface PeriodRow {
  period: string;
  has_books: boolean;
  has_2b: boolean;
  run_status: Status | null;
  run_id: string | null;
  open_groups: number;
  auto_resolved: number;
}

export interface UploadResult {
  rows_books: number;
  rows_2b: number;
  warnings: string[];
}

export interface RunSummary {
  groups: number;
  exceptions: number;
  matched: number;
  auto_resolved: number;
  auto_resolved_keys: string[];
  itc_at_risk: Money;
  flags: Record<string, number>;
  drift: string[];
  late_arrivals: number;
  outcomes: number;
  memory_degraded: boolean;
}

export interface Run {
  run_id: string;
  client_id: string;
  period: string;
  status: Status;
  progress: { step: string | null; done: number; total: number };
  memory_on: boolean;
  summary: RunSummary | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface Job {
  job_id: string;
  kind: string;
  status: Status;
  done: number;
  total: number;
  error: string | null;
  result: Record<string, unknown>;
}

export interface VendorRef {
  gstin: string;
  name: string;
}

export interface Invoice {
  invoice_no: string | null;
  date: string | null;
  total: Money | null;
  tax: Money | null;
  itc_at_risk: Money;
  details: Record<string, unknown>;
}

export interface CitedMemory {
  id: string;
  text: string;
  period: string | null;
  client_id: string | null;
  occurred_at: string | null;
}

export interface GuardrailDetail {
  rule: string;
  detail: string;
}

export interface Suggestion {
  action: Action;
  root_cause: string;
  flags: Flag[];
  confidence_label: "HIGH" | "MEDIUM" | "LOW";
  final_confidence: number;
  reasoning: string;
  vendor_message: string | null;
  cited_memories: CitedMemory[];
  guardrail_events: string[];
  guardrail_details: GuardrailDetail[];
  memory_on: boolean;
  model: string;
}

export interface Trust {
  level: TrustLevel;
  name: string;
  streak_action: Action | null;
  streak: number;
  correct: number;
  wrong: number;
}

export interface Decision {
  id: number | null;
  group_key: string;
  action: Action;
  suggested_action: Action | null;
  accepted_suggestion: boolean;
  decided_by: DecidedBy;
  note: string | null;
  decided_at: string;
}

export interface Group {
  group_key: string;
  vendor: VendorRef;
  type: ExceptionType;
  invoices: Invoice[];
  itc_at_risk: Money;
  suggestion: Suggestion | null;
  trust: Trust | null;
  decision: Decision | null;
  allowed_actions: Action[];
}

export interface Outcome {
  status: string;
  checked_in_period: string;
  evidence: Record<string, unknown>;
}

export interface HistoryRow {
  period: string;
  client_id: string;
  type: ExceptionType;
  action: Action;
  decided_by: DecidedBy;
  note: string | null;
  outcome: Outcome | null;
}

export interface DriftEvent {
  vendor_gstin: string;
  period: string;
  evidence: Record<string, unknown>;
}

export interface Pattern {
  vendor: VendorRef;
  type: ExceptionType;
  period: string;
  level: TrustLevel;
  name: string;
  streak_action: Action | null;
  streak: number;
  correct: number;
  wrong: number;
}

export interface Vendor {
  gstin: string;
  name: string;
  registration_status: string;
  known: boolean;
  clients: string[];
  history: HistoryRow[];
  trust: Pattern[];
  profile: string | null;
  drift_events: DriftEvent[];
}

export interface CurvePoint {
  period: string;
  accuracy_on: number | null;
  accuracy_off: number | null;
  auto_rate: number | null;
}

export interface InsightStats {
  period: string | null;
  runs: number;
  groups: number;
  decisions: number;
  accepted_suggestions: number;
  overrides: number;
  auto_resolved: number;
  itc_at_risk: Money;
  drift_events: number;
  cross_client_warnings: number;
  guardrails_applied: number;
  patterns_auto: number;
}

export interface Insights {
  summary: string | null;
  memory_offline: boolean;
  learning_curve: CurvePoint[];
  learning_curve_source: string | null;
  stats: InsightStats;
}

export interface MemoryEvent {
  id: number;
  ts: string;
  op: "retain" | "recall" | "reflect" | string;
  kind: string | null;
  summary: string;
  result_count: number | null;
  latency_ms: number | null;
  ok: boolean;
  error: string | null;
}

export interface RecallResult {
  query: string;
  memories: CitedMemory[];
}

export interface DecisionIn {
  action: Action;
  note: string | null;
}

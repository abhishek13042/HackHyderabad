// A thin fetch wrapper: JSON in and out, and the API's error envelope
// ({"error": {"code", "message"}}) turned into an ApiError.

import type {
  Client,
  Decision,
  DecisionIn,
  Group,
  Health,
  Insights,
  Job,
  MemoryEvent,
  Pattern,
  PeriodRow,
  RecallResult,
  Run,
  UploadResult,
  Vendor,
} from "./types";

const BASE = "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: { Accept: "application/json" } };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { ...init.headers, "Content-Type": "application/json" };
  }
  let response: Response;
  try {
    response = await fetch(BASE + path, init);
  } catch {
    throw new ApiError(0, "NETWORK", "The Recon server is not reachable. Is it running on port 8000?");
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (payload as { error?: { code?: string; message?: string } } | null)?.error;
    throw new ApiError(
      response.status,
      error?.code ?? "HTTP_" + response.status,
      error?.message ?? response.statusText,
    );
  }
  return payload as T;
}

function query(params: Record<string, string | number | boolean | undefined>): string {
  const entries = Object.entries(params).filter(
    (entry): entry is [string, string | number | boolean] => entry[1] !== undefined,
  );
  if (entries.length === 0) return "";
  return "?" + new URLSearchParams(entries.map(([k, v]) => [k, String(v)])).toString();
}

const enc = encodeURIComponent;

export const api = {
  health: () => request<Health>("GET", "/health"),
  clients: () => request<Client[]>("GET", "/clients"),
  periods: (clientId: string) => request<PeriodRow[]>("GET", "/periods" + query({ client_id: clientId })),

  upload: (form: FormData) => request<UploadResult>("POST", "/uploads", form),

  startRun: (clientId: string, period: string, memoryOn: boolean) =>
    request<{ run_id: string }>(
      "POST",
      `/reconciliations/${enc(clientId)}/${enc(period)}/run` + query({ memory: memoryOn ? "on" : "off" }),
    ),
  run: (runId: string) => request<Run>("GET", `/runs/${enc(runId)}`),
  groups: (clientId: string, period: string) =>
    request<Group[]>("GET", `/reconciliations/${enc(clientId)}/${enc(period)}/groups`),

  decide: (groupKey: string, body: DecisionIn) =>
    request<Decision>("POST", `/exceptions/${enc(groupKey)}/decision`, body),
  undo: (groupKey: string, body: DecisionIn) =>
    request<Decision>("POST", `/exceptions/${enc(groupKey)}/undo`, body),

  vendor: (gstin: string) => request<Vendor>("GET", `/vendors/${enc(gstin)}`),
  trust: () => request<Pattern[]>("GET", "/trust"),
  insights: (period?: string) => request<Insights>("GET", "/insights" + query({ period })),
  memoryEvents: (since: number, limit = 100) =>
    request<MemoryEvent[]>("GET", "/memory/events" + query({ since, limit })),
  latestMemoryEvents: (limit: number) =>
    request<MemoryEvent[]>("GET", "/memory/events" + query({ limit, latest: true })),
  recall: (q: string) => request<RecallResult>("GET", "/memory/recall" + query({ q })),

  seed: () => request<Job>("POST", "/demo/seed"),
  job: (jobId: string) => request<Job>("GET", `/demo/jobs/${enc(jobId)}`),
  reset: () => request<{ reset: boolean }>("POST", "/demo/reset", { confirm: "RESET" }),
};

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}

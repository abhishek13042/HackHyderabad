// TanStack Query hooks: one per endpoint, with the polling SPEC-08 asks for.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type { DecisionIn } from "./types";

export const keys = {
  health: ["health"] as const,
  clients: ["clients"] as const,
  periods: (clientId: string) => ["periods", clientId] as const,
  groups: (clientId: string, period: string) => ["groups", clientId, period] as const,
  run: (runId: string) => ["run", runId] as const,
  vendor: (gstin: string) => ["vendor", gstin] as const,
  trust: ["trust"] as const,
  insights: (period: string | undefined) => ["insights", period ?? "latest"] as const,
  job: (jobId: string) => ["job", jobId] as const,
};

export function useHealth() {
  return useQuery({ queryKey: keys.health, queryFn: api.health, refetchInterval: 5000 });
}

/** `poll` while seeding: the clients appear as the first month loads. */
export function useClients(poll = false) {
  return useQuery({ queryKey: keys.clients, queryFn: api.clients, refetchInterval: poll ? 1000 : false });
}

export function usePeriods(clientId: string | null) {
  return useQuery({
    queryKey: keys.periods(clientId ?? ""),
    queryFn: () => api.periods(clientId ?? ""),
    enabled: clientId !== null,
  });
}

export function useGroups(clientId: string | null, period: string | null, enabled = true) {
  return useQuery({
    queryKey: keys.groups(clientId ?? "", period ?? ""),
    queryFn: () => api.groups(clientId ?? "", period ?? ""),
    enabled: enabled && clientId !== null && period !== null,
  });
}

/** Polls every second while the run is in progress (SPEC-07 §3). */
export function useRun(runId: string | null) {
  return useQuery({
    queryKey: keys.run(runId ?? ""),
    queryFn: () => api.run(runId ?? ""),
    enabled: runId !== null,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 1000 : false),
  });
}

export function useJob(jobId: string | null) {
  return useQuery({
    queryKey: keys.job(jobId ?? ""),
    queryFn: () => api.job(jobId ?? ""),
    enabled: jobId !== null,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 1000 : false),
  });
}

export function useVendor(gstin: string) {
  return useQuery({ queryKey: keys.vendor(gstin), queryFn: () => api.vendor(gstin) });
}

export function useTrust() {
  return useQuery({ queryKey: keys.trust, queryFn: api.trust });
}

export function useInsights(period: string | undefined) {
  return useQuery({ queryKey: keys.insights(period), queryFn: () => api.insights(period) });
}

/** After anything that changes decisions: refresh the lists that show them. */
function useRefreshAfterDecision() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["groups"] }),
      queryClient.invalidateQueries({ queryKey: ["periods"] }),
      queryClient.invalidateQueries({ queryKey: ["vendor"] }),
      queryClient.invalidateQueries({ queryKey: ["insights"] }),
      queryClient.invalidateQueries({ queryKey: ["trust"] }),
      // The decision was just retained: show it in the memory panel now, not at the next poll.
      queryClient.invalidateQueries({ queryKey: ["memory-events"] }),
    ]);
}

export function useDecide() {
  const refresh = useRefreshAfterDecision();
  return useMutation({
    mutationFn: ({ groupKey, body }: { groupKey: string; body: DecisionIn }) =>
      api.decide(groupKey, body),
    onSuccess: refresh,
  });
}

export function useUndo() {
  const refresh = useRefreshAfterDecision();
  return useMutation({
    mutationFn: ({ groupKey, body }: { groupKey: string; body: DecisionIn }) =>
      api.undo(groupKey, body),
    onSuccess: refresh,
  });
}

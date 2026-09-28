// What every screen shares: the selected client and period, the current route,
// and the one background job the server runs at a time (a run or the seed).

import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, errorMessage } from "../api/client";
import { useClients, useJob, usePeriods, useRun } from "../api/hooks";
import type { Client, Job, PeriodRow, Run } from "../api/types";
import { useHashRoute, type Route } from "./route";

interface Workspace {
  route: Route;
  navigate: (route: Route) => void;
  clients: Client[];
  clientId: string | null;
  setClientId: (id: string) => void;
  client: Client | null;
  periods: PeriodRow[];
  period: string | null;
  setPeriod: (period: string) => void;
  /** Pick a client and one of its months together (from the Data table). */
  selectMonth: (clientId: string, period: string) => void;
  periodRow: PeriodRow | null;
  /** The run in progress, if any, polled every second. */
  activeRun: Run | null;
  startRun: (clientId: string, period: string, memoryOn: boolean) => Promise<void>;
  runError: string | null;
  clearRunError: () => void;
  activeJob: Job | null;
  trackJob: (job: Job) => void;
  /** A run or seed is working: the memory panel polls faster, run buttons wait. */
  busy: boolean;
  /** Bumped by a demo reset, so views holding their own state start over. */
  resetGeneration: number;
  markReset: () => void;
}

const WorkspaceContext = createContext<Workspace | null>(null);

/** The latest period that has been reconciled, else the latest with a GSTR-2B. */
export function defaultPeriod(periods: PeriodRow[]): string | null {
  const run = periods.filter((p) => p.run_status !== null);
  const pick = run.at(-1) ?? periods.filter((p) => p.has_2b).at(-1) ?? periods.at(-1);
  return pick?.period ?? null;
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [route, navigate] = useHashRoute();
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const jobQuery = useJob(activeJobId);
  const activeJob = jobQuery.data ?? null;

  const clientsQuery = useClients(activeJobId !== null);
  const clients = useMemo(() => clientsQuery.data ?? [], [clientsQuery.data]);

  const [chosenClient, setClientId] = useState<string | null>(null);
  const clientId = chosenClient ?? clients[0]?.id ?? null;
  const periodsQuery = usePeriods(clientId);
  const periods = useMemo(() => periodsQuery.data ?? [], [periodsQuery.data]);
  const [chosenPeriod, setChosenPeriod] = useState<{ clientId: string; period: string } | null>(null);
  const period =
    chosenPeriod && chosenPeriod.clientId === clientId && periods.some((p) => p.period === chosenPeriod.period)
      ? chosenPeriod.period
      : defaultPeriod(periods);
  const setPeriod = useCallback(
    (p: string) => clientId && setChosenPeriod({ clientId, period: p }),
    [clientId],
  );

  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const runQuery = useRun(activeRunId);
  const activeRun = runQuery.data ?? null;

  const [resetGeneration, setResetGeneration] = useState(0);

  const refreshAll = useCallback(() => queryClient.invalidateQueries(), [queryClient]);

  useEffect(() => {
    if (activeRun && activeRun.status !== "running") {
      if (activeRun.status === "failed") setRunError(activeRun.error ?? "The run failed.");
      setActiveRunId(null);
      void refreshAll();
    }
  }, [activeRun, refreshAll]);

  useEffect(() => {
    if (activeJob && activeJob.status !== "running") {
      setActiveJobId(null);
      void refreshAll();
    }
  }, [activeJob, refreshAll]);

  const startRun = useCallback(
    async (runClient: string, runPeriod: string, memoryOn: boolean) => {
      setRunError(null);
      try {
        const { run_id } = await api.startRun(runClient, runPeriod, memoryOn);
        setActiveRunId(run_id);
        void queryClient.invalidateQueries({ queryKey: ["periods"] });
      } catch (error) {
        setRunError(errorMessage(error));
      }
    },
    [queryClient],
  );

  const value: Workspace = {
    route,
    navigate,
    clients,
    clientId,
    setClientId,
    client: clients.find((c) => c.id === clientId) ?? null,
    periods,
    period,
    setPeriod,
    selectMonth: (id, p) => {
      setClientId(id);
      setChosenPeriod({ clientId: id, period: p });
    },
    periodRow: periods.find((p) => p.period === period) ?? null,
    activeRun: activeRunId ? activeRun : null,
    startRun,
    runError,
    clearRunError: () => setRunError(null),
    activeJob: activeJobId ? activeJob : null,
    trackJob: (job) => {
      queryClient.setQueryData(["job", job.job_id], job);
      setActiveJobId(job.job_id);
    },
    busy: activeRunId !== null || activeJobId !== null,
    resetGeneration,
    markReset: () => {
      setChosenPeriod(null);
      setClientId(null);
      setResetGeneration((g) => g + 1);
      void refreshAll();
    },
  };
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): Workspace {
  const workspace = useContext(WorkspaceContext);
  if (!workspace) throw new Error("useWorkspace outside WorkspaceProvider");
  return workspace;
}

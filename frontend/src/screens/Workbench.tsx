// S2: clear a month's mismatches (SPEC-08 §4).

import { useRef, type KeyboardEvent } from "react";

import { useGroups, useRun } from "../api/hooks";
import type { Group } from "../api/types";
import { ExceptionCard } from "../components/ExceptionCard";
import { RunLive } from "../components/RunLive";
import { UndoForm } from "../components/UndoForm";
import { Banner, Button, Empty, ErrorBox, ProgressBar, Skeleton } from "../components/ui";
import { periodLabel, rupees, sumMoney } from "../lib/format";
import { ACTION_DONE, ROOT_CAUSE_LABELS } from "../lib/labels";
import { useWorkspace } from "../lib/workspace";

const STEP_LABELS: Record<string, string> = {
  match: "Matching books with GSTR-2B",
  verify: "Checking last month's decisions",
  drift: "Looking for vendors that changed",
  trust: "Updating trust",
  recall: "Recalling memories",
  suggest: "Writing suggestions",
  resolve: "Resolving proven patterns",
};

export function Workbench() {
  const ws = useWorkspace();
  const { client, clientId, period, periodRow, activeRun } = ws;
  const hasRun = periodRow?.run_id != null && periodRow.run_status === "done";
  const runQuery = useRun(periodRow?.run_id ?? null);
  const groupsQuery = useGroups(clientId, period, hasRun);
  const listRef = useRef<HTMLDivElement>(null);

  if (ws.clients.length === 0) {
    return (
      <Empty title="No data yet — load sample data">
        <Button variant="primary" onClick={() => ws.navigate({ name: "data" })}>
          Go to Data
        </Button>
      </Empty>
    );
  }
  if (!client || !period || !clientId) return <Skeleton />;

  const runningHere = activeRun && activeRun.client_id === clientId && activeRun.period === period;
  const run = runQuery.data;
  const memoryOn = run?.memory_on ?? true;
  const groups = groupsQuery.data ?? [];
  const autoKeys = new Set(run?.summary?.auto_resolved_keys ?? []);
  const auto = groups.filter((g) => g.decision?.decided_by === "AUTO" && autoKeys.has(g.group_key));
  const rest = groups.filter((g) => !auto.includes(g));
  const open = rest.filter((g) => g.decision === null);
  const decided = rest.filter((g) => g.decision !== null);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
    if (event.key !== "j" && event.key !== "k") return;
    const cards = Array.from(listRef.current?.querySelectorAll<HTMLElement>("[data-card]") ?? []);
    if (cards.length === 0) return;
    const current = cards.findIndex((c) => c.contains(document.activeElement));
    const next = event.key === "j" ? Math.min(current + 1, cards.length - 1) : Math.max(current - 1, 0);
    event.preventDefault();
    cards[current === -1 ? 0 : next]?.focus();
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-stone-900">
            {client.name} · {periodLabel(period)}
          </h1>
          {!hasRun && (
            <p className="text-sm text-stone-600">
              Recon compares this client's purchase books with GSTR-2B and brings you only what doesn't match.
            </p>
          )}
          {hasRun && (
            <p className="num text-sm text-stone-600">
              ITC at risk <strong className="text-stone-900">{rupees(sumMoney(groups.map((g) => g.itc_at_risk)), { paise: false })}</strong>
              {" · "}
              {groups.length} groups · {auto.length} auto-resolved · <strong>{open.length} need you</strong>
            </p>
          )}
        </div>
        <Button
          variant="primary"
          disabled={ws.busy || !periodRow?.has_2b}
          onClick={() => void ws.startRun(clientId, period, memoryOn)}
          title={periodRow?.has_2b ? undefined : "Upload this month's GSTR-2B first"}
        >
          {hasRun ? "Run again" : "Run reconciliation"}
        </Button>
      </div>

      {runningHere && activeRun && (
        <>
          <ProgressBar
            done={activeRun.progress.done}
            total={activeRun.progress.total}
            label={STEP_LABELS[activeRun.progress.step ?? ""] ?? "Starting"}
          />
          <RunLive run={activeRun} />
        </>
      )}
      {ws.runError && (
        <ErrorBox error={new Error(ws.runError)} onRetry={ws.clearRunError} />
      )}
      {run?.summary?.memory_degraded && (
        <Banner>Memory was offline during this run — suggestions were made without memory.</Banner>
      )}
      {run && !run.memory_on && (
        <Banner tone="grey">This month was run with memory off: no memories used, nothing resolved automatically.</Banner>
      )}

      {!hasRun && !runningHere && (
        <Empty title={`${periodLabel(period)} has not been checked yet`}>
          {periodRow?.has_2b ? (
            <div className="space-y-4">
              <p>
                Press the button and watch: Recon matches the invoices, looks up each problem vendor in its
                memory (right-hand panel), and suggests what to do. It takes about a minute.
              </p>
              <Button variant="primary" disabled={ws.busy} onClick={() => void ws.startRun(clientId, period, true)}>
                Check {periodLabel(period)} now
              </Button>
              <p>
                New here? <a href="#/home" className="text-accent-700 hover:underline">Start with the guided demo</a>.
              </p>
            </div>
          ) : (
            "Upload this month's books and GSTR-2B on the Data screen."
          )}
        </Empty>
      )}
      {hasRun && groupsQuery.isPending && <Skeleton />}
      {groupsQuery.isError && <ErrorBox error={groupsQuery.error} onRetry={() => void groupsQuery.refetch()} />}

      {hasRun && groupsQuery.isSuccess && (
        <div ref={listRef} onKeyDown={onKeyDown} className="space-y-3">
          {groups.length === 0 && <Empty title="Everything matched. Nothing needs you this month." />}
          {open.length === 0 && groups.length > 0 && (
            <Banner tone="green">All groups decided for {periodLabel(period)}.</Banner>
          )}
          {[...open, ...decided].map((g) => (
            <ExceptionCard
              key={g.group_key}
              group={g}
              clientId={clientId}
              clients={ws.clients}
              onOpenVendor={(gstin) => ws.navigate({ name: "vendor", gstin })}
            />
          ))}
          {auto.length > 0 && <AutoSection groups={auto} />}
          <p className="text-xs text-stone-500">Keys: J / K move between cards, A accepts the focused card.</p>
        </div>
      )}
    </div>
  );
}

function AutoSection({ groups }: { groups: Group[] }) {
  const ws = useWorkspace();
  return (
    <details open className="rounded-lg border border-emerald-200 bg-emerald-50/40">
      <summary className="cursor-pointer px-4 py-2.5 text-sm font-medium text-emerald-800">
        Handled automatically ({groups.length}): Recon has been proven right on these, so it didn't ask you
      </summary>
      <ul className="divide-y divide-emerald-100 border-t border-emerald-100">
        {groups.map((g) => {
          const decision = g.decision;
          const cause = g.suggestion ? ROOT_CAUSE_LABELS[g.suggestion.root_cause] ?? "" : "";
          const months = g.trust ? g.trust.streak : 0;
          return (
            <li key={g.group_key} data-card tabIndex={0} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-sm">
              <span>
                <span className="font-medium text-emerald-800">Auto</span> ·{" "}
                <button type="button" className="hover:underline" onClick={() => ws.navigate({ name: "vendor", gstin: g.vendor.gstin })}>
                  {g.vendor.name}
                </button>{" "}
                · <span className="num">{rupees(g.itc_at_risk)}</span> {cause} ·{" "}
                {decision ? ACTION_DONE[decision.action].toLowerCase() : ""} (trusted pattern, {months} month{months === 1 ? "" : "s"})
              </span>
              <UndoForm group={g} />
            </li>
          );
        })}
      </ul>
    </details>
  );
}

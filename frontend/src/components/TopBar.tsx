// Firm name, client and period pickers, the memory switch and service status.

import { useState } from "react";

import { useHealth, useRun } from "../api/hooks";
import { periodLabel } from "../lib/format";
import { useWorkspace } from "../lib/workspace";
import { Banner, Button } from "./ui";

export function TopBar() {
  const ws = useWorkspace();
  const health = useHealth();
  const run = useRun(ws.periodRow?.run_status === "done" ? ws.periodRow.run_id : null);
  const [confirming, setConfirming] = useState(false);

  const memoryDown = health.data?.hindsight === "down";
  const memoryOn = run.data?.memory_on ?? true;
  const canToggle = !memoryDown && !ws.busy && run.data !== undefined && ws.clientId !== null && ws.period !== null;

  const rerun = () => {
    setConfirming(false);
    if (ws.clientId && ws.period) void ws.startRun(ws.clientId, ws.period, !memoryOn);
  };

  return (
    <div className="border-b border-stone-200 bg-white">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
        <a href="#/workbench" className="flex items-center gap-2 font-semibold text-stone-900">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-accent-700 text-sm text-white">R</span>
          Recon
          {health.data && <span className="hidden font-normal text-stone-500 sm:inline">· {health.data.firm}</span>}
        </a>

        <div className="flex items-center gap-2">
          <label className="sr-only" htmlFor="client">
            Client
          </label>
          <select
            id="client"
            value={ws.clientId ?? ""}
            onChange={(e) => ws.setClientId(e.target.value)}
            disabled={ws.clients.length === 0}
            className="rounded-md border border-stone-300 bg-white px-2 py-1 text-sm"
          >
            {ws.clients.length === 0 && <option value="">No clients</option>}
            {ws.clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.id} · {c.name}
              </option>
            ))}
          </select>
          <label className="sr-only" htmlFor="period">
            Period
          </label>
          <select
            id="period"
            value={ws.period ?? ""}
            onChange={(e) => ws.setPeriod(e.target.value)}
            disabled={ws.periods.length === 0}
            className="rounded-md border border-stone-300 bg-white px-2 py-1 text-sm"
          >
            {ws.periods.length === 0 && <option value="">—</option>}
            {ws.periods.map((p) => (
              <option key={p.period} value={p.period}>
                {periodLabel(p.period)}
              </option>
            ))}
          </select>
        </div>

        <div className="ml-auto flex items-center gap-4">
          <button
            type="button"
            role="switch"
            aria-checked={memoryOn}
            disabled={!canToggle}
            onClick={() => setConfirming(true)}
            title={
              memoryDown
                ? "Memory is offline"
                : run.data
                  ? "Re-run this month with memory switched " + (memoryOn ? "off" : "on")
                  : "Run the month first"
            }
            className="flex items-center gap-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className="text-stone-600">Memory</span>
            <span className={`relative h-5 w-9 rounded-full transition-colors ${memoryOn ? "bg-accent-600" : "bg-stone-300"}`}>
              <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${memoryOn ? "left-4.5" : "left-0.5"}`} />
            </span>
            <span className="w-7 font-medium">{memoryOn ? "ON" : "OFF"}</span>
          </button>
          <StatusDot label="Memory" up={health.data ? !memoryDown : undefined} />
          <StatusDot label="AI" up={health.data ? health.data.llm === "up" : undefined} />
        </div>
      </div>

      {health.isError && (
        <div className="px-4 pb-2">
          <Banner tone="red">Can't reach the Recon server. Start it with uvicorn on port 8000.</Banner>
        </div>
      )}
      {memoryDown && (
        <div className="px-4 pb-2">
          <Banner>
            Memory offline — suggestions made without memory.
            {health.data && health.data.pending_retains > 0 && ` ${health.data.pending_retains} memories queued; they will be saved when it's back.`}
          </Banner>
        </div>
      )}

      {confirming && (
        <div role="dialog" aria-modal="true" aria-labelledby="rerun-title" className="fixed inset-0 z-20 grid place-items-center bg-stone-900/30 p-4">
          <div className="w-full max-w-sm rounded-lg bg-white p-5 shadow-xl">
            <h2 id="rerun-title" className="font-semibold text-stone-900">
              Re-run {periodLabel(ws.period)} {memoryOn ? "without" : "with"} memory?
            </h2>
            <p className="mt-2 text-sm text-stone-600">
              {memoryOn
                ? "Recon will suggest as if it had never seen this firm: no memories and nothing resolved automatically. Your decisions are kept."
                : "Recon will recall what it has learned again. Your decisions are kept."}
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <Button onClick={() => setConfirming(false)}>Cancel</Button>
              <Button variant="primary" onClick={rerun} autoFocus>
                Re-run
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function StatusDot({ label, up }: { label: string; up: boolean | undefined }) {
  const colour = up === undefined ? "bg-stone-300" : up ? "bg-emerald-500" : "bg-red-500";
  const state = up === undefined ? "checking" : up ? "up" : "down";
  return (
    <span className="flex items-center gap-1.5 text-xs text-stone-600" title={`${label}: ${state}`}>
      <span className={`h-2 w-2 rounded-full ${colour}`} aria-hidden="true" />
      {label} <span className="sr-only">{state}</span>
    </span>
  );
}

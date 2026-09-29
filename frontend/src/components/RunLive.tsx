// What a run is doing, in words, while it runs: the seven steps and the memories
// being looked up and saved, so the minute of waiting shows the work.

import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Run } from "../api/types";
import { eventLook } from "./MemoryPanel";

const STEPS: { id: string; title: string; detail: string }[] = [
  { id: "match", title: "Match invoices", detail: "Line up the client's books with GSTR-2B, invoice by invoice." },
  { id: "verify", title: "Check last month's advice", detail: "Did the invoices we said to wait for actually arrive?" },
  { id: "drift", title: "Spot vendors that changed", detail: "Is any vendor later than it has ever been?" },
  { id: "trust", title: "Update trust", detail: "Patterns that keep turning out right earn more autonomy." },
  { id: "recall", title: "Look up memory", detail: "For each problem vendor: what happened before, at any client?" },
  { id: "suggest", title: "Write suggestions", detail: "The AI suggests an action and cites the memories it used." },
  { id: "resolve", title: "Handle proven patterns", detail: "Trusted patterns are resolved without asking you." },
];

export function RunLive({ run }: { run: Run }) {
  const current = Math.max(0, STEPS.findIndex((s) => s.id === run.progress.step));
  const events = useQuery({
    queryKey: ["memory-events", "run", run.run_id],
    queryFn: () => api.latestMemoryEvents(8),
    refetchInterval: 1000,
  });
  const since = Date.parse(run.started_at);
  const recent = (events.data ?? []).filter((e) => Date.parse(e.ts) >= since).reverse().slice(0, 5);

  return (
    <div className="grid gap-4 rounded-xl border border-accent-100 bg-white p-5 shadow-sm md:grid-cols-2">
      <div>
        <h2 className="flex items-center gap-2 font-semibold text-stone-900">
          <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-accent-600" aria-hidden="true" />
          Recon is working{run.memory_on ? "" : " (memory off)"}
        </h2>
        <ol className="mt-3 space-y-2">
          {STEPS.map((step, i) => {
            const state = i < current ? "done" : i === current ? "now" : "next";
            const skipped = !run.memory_on && (step.id === "recall" || step.id === "resolve");
            return (
              <li key={step.id} className={`flex gap-3 ${state === "next" ? "opacity-40" : ""}`}>
                <span
                  className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-xs ${
                    state === "done" ? "bg-emerald-500 text-white" : state === "now" ? "bg-accent-600 text-white" : "bg-stone-200"
                  }`}
                  aria-hidden="true"
                >
                  {state === "done" ? "✓" : i + 1}
                </span>
                <div>
                  <p className={`text-sm ${state === "now" ? "font-semibold text-stone-900" : "text-stone-700"}`}>
                    {step.title}
                    {skipped && <span className="font-normal text-stone-400"> · skipped, memory is off</span>}
                  </p>
                  {state === "now" && <p className="text-xs text-stone-500">{step.detail}</p>}
                </div>
              </li>
            );
          })}
        </ol>
      </div>
      <div>
        <h3 className="text-sm font-semibold text-stone-700">Happening in memory right now</h3>
        {recent.length === 0 ? (
          <p className="mt-3 text-sm text-stone-500">Waiting for the first lookup…</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {recent.map((e) => {
              const look = eventLook(e);
              return (
                <li key={e.id} className="arrive rounded-lg bg-stone-50 px-3 py-2">
                  <p className={`text-xs font-medium ${look.tone}`}>
                    {look.icon} {look.label}
                    {e.op === "recall" && e.result_count !== null && ` · found ${e.result_count}`}
                  </p>
                  <p className="mt-0.5 line-clamp-2 text-sm text-stone-700">{e.summary}</p>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

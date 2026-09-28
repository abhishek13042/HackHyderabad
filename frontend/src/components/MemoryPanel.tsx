// The live memory activity panel: every recall, retain and reflect as it
// happens (SPEC-08 §4). Polls every second while a job runs, else every 5 s;
// a decision refreshes it at once.

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type { MemoryEvent } from "../api/types";
import { timeOfDay } from "../lib/format";
import { useWorkspace } from "../lib/workspace";

const KEEP = 200;
const FIRST_LOAD = 40;

interface Look {
  icon: string;
  label: string;
  tone: string;
}

export function eventLook(event: MemoryEvent): Look {
  if (event.op === "recall") return { icon: "↓", label: "recall", tone: "text-sky-700" };
  if (event.op === "reflect") return { icon: "✦", label: "reflect", tone: "text-violet-700" };
  if (event.kind === "outcome") return { icon: "✓", label: "outcome", tone: "text-emerald-700" };
  if (event.kind === "drift") return { icon: "⚠", label: "drift", tone: "text-red-700" };
  return { icon: "↑", label: "retain", tone: "text-accent-700" };
}

export function MemoryPanel() {
  const { busy, resetGeneration } = useWorkspace();
  const [events, setEvents] = useState<MemoryEvent[]>([]);
  const lastId = useRef(0);
  // Rows up to this id were already there when the panel opened; only newer ones animate in.
  const [openedAt, setOpenedAt] = useState<number | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);

  useEffect(() => {
    setEvents([]);
    lastId.current = 0;
    setOpenedAt(null);
  }, [resetGeneration]);

  const query = useQuery({
    queryKey: ["memory-events", resetGeneration],
    queryFn: () => (lastId.current === 0 ? api.latestMemoryEvents(FIRST_LOAD) : api.memoryEvents(lastId.current)),
    refetchInterval: busy ? 1000 : 5000,
  });

  useEffect(() => {
    const rows = query.data;
    if (!rows) return;
    const fresh = rows.filter((e) => e.id > lastId.current);
    if (fresh.length > 0) {
      lastId.current = Math.max(...fresh.map((e) => e.id));
      setEvents((prev) => [...prev, ...fresh].slice(-KEEP));
    }
    setOpenedAt((at) => at ?? lastId.current);
  }, [query.data]);

  const newest = [...events].reverse();

  return (
    <aside aria-label="Memory activity" className="flex h-full flex-col border-l border-stone-200 bg-white">
      <header className="flex items-center justify-between border-b border-stone-100 px-3 py-2.5">
        <h2 className="text-sm font-semibold text-stone-700">
          Memory activity
          {busy && <span className="ml-2 inline-block h-2 w-2 animate-pulse rounded-full bg-accent-600" aria-label="live" />}
        </h2>
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          aria-expanded={!collapsed}
          className="rounded px-1.5 text-xs text-stone-500 hover:bg-stone-100"
        >
          {collapsed ? "Show" : "Hide"}
        </button>
      </header>
      {!collapsed && (
        <ol className="flex-1 divide-y divide-stone-100 overflow-y-auto text-xs" aria-live="polite">
          {newest.length === 0 && (
            <li className="px-3 py-6 text-center text-stone-500">
              {query.isError ? "Can't reach the server." : "Nothing yet. Run a reconciliation to watch Munshi recall and learn."}
            </li>
          )}
          {newest.map((event) => {
            const look = eventLook(event);
            const open = openId === event.id;
            return (
              <li key={event.id} className={openedAt !== null && event.id > openedAt ? "arrive" : undefined}>
                <button
                  type="button"
                  onClick={() => setOpenId(open ? null : event.id)}
                  aria-expanded={open}
                  className="block w-full px-3 py-2 text-left hover:bg-stone-50"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className={`font-medium ${look.tone}`}>
                      <span aria-hidden="true">{look.icon}</span> {look.label}
                      {event.op === "retain" && event.kind === "resolution" && " · decision"}
                    </span>
                    <span className="num text-stone-400">
                      {event.result_count !== null && event.op === "recall" && `${event.result_count} found · `}
                      {event.latency_ms !== null && `${event.latency_ms} ms`}
                    </span>
                  </div>
                  <p className={`mt-0.5 text-stone-600 ${open ? "" : "line-clamp-1"}`}>{event.summary}</p>
                  {!event.ok && (
                    <p className="mt-0.5 text-amber-700">
                      {event.op === "retain" ? "Offline: queued, will be saved when memory is back" : "Offline"}
                    </p>
                  )}
                  {open && (
                    <p className="mt-1 text-stone-400">
                      {timeOfDay(event.ts)}
                      {event.kind && ` · ${event.kind}`}
                      {event.error && ` · ${event.error}`}
                    </p>
                  )}
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </aside>
  );
}

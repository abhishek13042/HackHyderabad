// S0: the front door. Says in plain words what Recon is, how it works, and walks
// a first-time viewer through the four moments that show memory at work.

import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { api } from "../api/client";
import { useHealth, useTrust } from "../api/hooks";
import { Button } from "../components/ui";
import { useWorkspace } from "../lib/workspace";

interface Moment {
  n: number;
  title: string;
  clientId: string;
  period: string;
  memoryOn: boolean;
  what: string;
  look: string;
}

const MOMENTS: Moment[] = [
  {
    n: 1,
    title: "It learns what is safe to handle alone",
    clientId: "C02",
    period: "2026-04",
    memoryOn: true,
    what: "Bhavani Chemicals always files its GST returns a few weeks late. Recon said “wait a month” twice, checked, and was right both times.",
    look: "Open the green “Auto-resolved” box at the bottom: Recon handled it without asking, and you can still undo it.",
  },
  {
    n: 2,
    title: "It notices when a vendor changes",
    clientId: "C01",
    period: "2026-04",
    memoryOn: true,
    what: "Reddy Steels also used to file late and always caught up. This month its invoice is overdue for longer than ever before.",
    look: "The Reddy Steels card has a red “Pattern changed” tag: Recon stops saying “wait” and says “chase the vendor”.",
  },
  {
    n: 3,
    title: "It shares lessons across clients",
    clientId: "C03",
    period: "2026-04",
    memoryOn: true,
    what: "Krishna Logistics never filed its returns for another client of the firm. Now a different client buys from it.",
    look: "The Krishna Logistics card has an orange “Seen at another client” tag, and shows the memory it came from.",
  },
  {
    n: 4,
    title: "Switch memory off and compare",
    clientId: "C03",
    period: "2026-04",
    memoryOn: false,
    what: "The same month, run as if Recon had never met this firm.",
    look: "No warnings, nothing handled for you: every case is back on your desk. That gap is what memory is worth.",
  },
];

export function Home() {
  const ws = useWorkspace();
  const health = useHealth();
  const trust = useTrust();
  const memoryCount = useQuery({
    queryKey: ["memory-events", "count"],
    queryFn: () => api.latestMemoryEvents(200),
    refetchInterval: 10000,
  });
  const [opening, setOpening] = useState<number | null>(null);

  const seeded = ws.clients.length > 0;
  const lessons = (memoryCount.data ?? []).filter((e) => e.op === "retain").length;
  const trusted = new Set((trust.data ?? []).filter((t) => t.level === 2).map((t) => `${t.vendor.gstin}:${t.type}`)).size;

  const show = async (m: Moment) => {
    setOpening(m.n);
    try {
      const periods = await api.periods(m.clientId);
      const row = periods.find((p) => p.period === m.period);
      ws.selectMonth(m.clientId, m.period);
      ws.navigate({ name: "workbench" });
      const run = row?.run_id ? await api.run(row.run_id) : null;
      const needsRun = !run || run.status !== "done" || run.memory_on !== m.memoryOn;
      if (needsRun && row?.has_2b && !ws.busy) await ws.startRun(m.clientId, m.period, m.memoryOn);
    } finally {
      setOpening(null);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-8 pb-10">
      {/* Hero */}
      <section className="overflow-hidden rounded-2xl bg-gradient-to-br from-accent-800 via-accent-700 to-emerald-600 px-6 py-8 text-white shadow-lg sm:px-10 sm:py-10">
        <p className="text-sm font-medium tracking-wide text-accent-100 uppercase">For CA firms in India</p>
        <h1 className="mt-2 text-3xl leading-tight font-bold sm:text-4xl">
          Recon: GST reconciliation that remembers.
        </h1>
        <p className="mt-4 max-w-2xl text-base text-accent-50 sm:text-lg">
          Every month, a CA firm has to check each client's purchase invoices against{" "}
          <strong>GSTR-2B</strong>, the list the government builds from what vendors reported. Anything
          that doesn't match puts the client's tax credit at risk. Juniors investigate the same vendors
          every month and forget what they learned. <strong>Recon remembers</strong>, so the firm gets
          better every month.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          {seeded ? (
            <button
              type="button"
              onClick={() => void show(MOMENTS[0]!)}
              className="rounded-lg bg-white px-5 py-2.5 text-sm font-semibold text-accent-800 shadow hover:bg-accent-50"
            >
              Start the guided demo →
            </button>
          ) : (
            <button
              type="button"
              onClick={() => ws.navigate({ name: "data" })}
              className="rounded-lg bg-white px-5 py-2.5 text-sm font-semibold text-accent-800 shadow hover:bg-accent-50"
            >
              Load the sample firm first →
            </button>
          )}
          <a href="#/workbench" className="rounded-lg px-5 py-2.5 text-sm font-semibold text-white ring-1 ring-white/50 hover:bg-white/10">
            Go to the workbench
          </a>
        </div>
      </section>

      {/* Live numbers */}
      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Fact value={ws.clients.length} label="clients of the sample firm" />
        <Fact value={lessons} label="lessons saved to memory" />
        <Fact value={trusted} label="patterns trusted to run alone" />
        <Fact
          value={health.data ? (health.data.hindsight === "up" && health.data.llm === "up" ? "Live" : "Degraded") : "…"}
          label="Hindsight memory + Groq AI"
        />
      </section>

      {/* How it works */}
      <section>
        <h2 className="text-xl font-semibold text-stone-900">How it works, every month</h2>
        <ol className="mt-4 grid gap-3 sm:grid-cols-4">
          <Step n={1} icon="⇄" title="Match">
            Lines up the client's books with GSTR-2B and groups the mismatches by vendor.
          </Step>
          <Step n={2} icon="↓" title="Remember">
            Asks its memory: what happened with this vendor before, at any client? Was our advice right?
          </Step>
          <Step n={3} icon="✎" title="Suggest">
            Recommends an action and cites the memories behind it. Safety rules check every suggestion.
          </Step>
          <Step n={4} icon="✓" title="Learn">
            Saves your decision, and next month checks whether it was right. Proven patterns get handled alone.
          </Step>
        </ol>
      </section>

      {/* Guided demo */}
      <section>
        <h2 className="text-xl font-semibold text-stone-900">See it in four moments</h2>
        <p className="mt-1 text-sm text-stone-600">
          The sample firm has three months of history (January to March 2026). Each button opens April, the
          month Recon is working on now. If a month hasn't been run yet, it runs live, which takes about a minute.
        </p>
        <div className="mt-4 space-y-3">
          {MOMENTS.map((m) => (
            <article key={m.n} className="flex flex-col gap-4 rounded-xl border border-stone-200 bg-white p-5 shadow-sm sm:flex-row sm:items-center">
              <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-accent-100 text-lg font-bold text-accent-800">
                {m.n}
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="font-semibold text-stone-900">{m.title}</h3>
                <p className="mt-1 text-sm text-stone-700">{m.what}</p>
                <p className="mt-1 text-sm text-stone-500">
                  <span className="font-medium text-stone-600">Look for:</span> {m.look}
                </p>
              </div>
              <Button variant="primary" disabled={!seeded || opening !== null} onClick={() => void show(m)}>
                {opening === m.n ? "Opening…" : "Show me"}
              </Button>
            </article>
          ))}
        </div>
      </section>

      {/* Legend */}
      <section className="rounded-xl border border-stone-200 bg-white p-5">
        <h2 className="font-semibold text-stone-900">Reading the screen</h2>
        <dl className="mt-3 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <Term t="ITC at risk">Tax credit the client can't claim until the mismatch is fixed.</Term>
          <Term t="Card">One vendor's mismatches for the month, with Recon's suggestion and why.</Term>
          <Term t="Memory panel (right)">Every time Recon looks something up or learns something, live.</Term>
          <Term t="Memory switch (top)">Re-runs the month without memory, so you can compare.</Term>
          <Term t="Observe → Suggest → Auto">How much Recon is trusted with a pattern, earned month by month.</Term>
          <Term t="Insights">Whether Recon's advice is getting better over time.</Term>
        </dl>
      </section>
    </div>
  );
}

function Fact({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div className="rounded-xl border border-stone-200 bg-white px-4 py-3 shadow-sm">
      <div className="num text-2xl font-bold text-accent-800">{value}</div>
      <div className="mt-0.5 text-xs text-stone-500">{label}</div>
    </div>
  );
}

function Step({ n, icon, title, children }: { n: number; icon: string; title: string; children: ReactNode }) {
  return (
    <li className="rounded-xl border border-stone-200 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2">
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent-50 text-lg text-accent-700" aria-hidden="true">
          {icon}
        </span>
        <span className="text-xs font-medium text-stone-400">Step {n}</span>
      </div>
      <h3 className="mt-2 font-semibold text-stone-900">{title}</h3>
      <p className="mt-1 text-sm text-stone-600">{children}</p>
    </li>
  );
}

function Term({ t, children }: { t: string; children: ReactNode }) {
  return (
    <div>
      <dt className="inline font-medium text-stone-800">{t}: </dt>
      <dd className="inline text-stone-600">{children}</dd>
    </div>
  );
}

// S4: is Recon getting better? The eval learning curve, the month's lessons,
// the numbers for the selected month, and every pattern's trust level.

import { useState, type FormEvent } from "react";
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "../api/client";
import { useInsights, useTrust } from "../api/hooks";
import type { CurvePoint, Pattern, RecallResult } from "../api/types";
import { Banner, Button, Empty, ErrorBox, Panel, Skeleton, Stat } from "../components/ui";
import { periodLabel, rupees } from "../lib/format";
import { exceptionLabel, TRUST_LABELS } from "../lib/labels";
import { useWorkspace } from "../lib/workspace";

export function Insights() {
  const ws = useWorkspace();
  const insights = useInsights(ws.period ?? undefined);

  if (insights.isPending) return <Skeleton rows={4} />;
  if (insights.isError) return <ErrorBox error={insights.error} onRetry={() => void insights.refetch()} />;
  const { stats, summary, memory_offline, learning_curve, learning_curve_source } = insights.data;

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold text-stone-900">Insights · {periodLabel(stats.period)}</h1>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="ITC at risk" value={rupees(stats.itc_at_risk, { paise: false })} />
        <Stat label="Auto-resolved" value={stats.auto_resolved} hint="Groups Recon resolved on a trusted pattern" />
        <Stat label="Overrides" value={stats.overrides} hint="Decisions where the accountant chose differently" />
        <Stat label="Drift events" value={stats.drift_events} hint="Vendors whose pattern changed" />
        <Stat label="Cross-client" value={stats.cross_client_warnings} hint="Warnings from what another client saw" />
        <Stat label="Safety rules" value={stats.guardrails_applied} hint="Times a guardrail changed a suggestion" />
      </div>

      <Panel title="Learning curve">
        <LearningCurve points={learning_curve} />
        {learning_curve_source && <p className="mt-2 text-xs text-stone-500">From eval run {learning_curve_source}</p>}
      </Panel>

      <Panel title="This month's lessons">
        {summary ? (
          <p className="whitespace-pre-line text-sm leading-relaxed text-stone-700">{summary}</p>
        ) : memory_offline ? (
          <Banner>Memory offline — no summary right now.</Banner>
        ) : (
          <p className="text-sm text-stone-500">Nothing to summarise yet.</p>
        )}
      </Panel>

      <TrustBoard />
      <AskMemory />
    </div>
  );
}

function LearningCurve({ points }: { points: CurvePoint[] }) {
  if (points.length === 0) {
    return (
      <Empty title="No eval results yet">
        Run <code className="rounded bg-stone-100 px-1">python -m evals.run</code> to draw memory ON against OFF.
      </Empty>
    );
  }
  const data = points.map((p) => ({
    period: periodLabel(p.period),
    on: p.accuracy_on === null ? null : Math.round(p.accuracy_on * 100),
    off: p.accuracy_off === null ? null : Math.round(p.accuracy_off * 100),
    auto: p.auto_rate === null ? null : Math.round(p.auto_rate * 100),
  }));
  return (
    <div className="h-72" role="img" aria-label="Accuracy per month with memory on and off, and auto-resolved share">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <CartesianGrid stroke="#e7e5e4" vertical={false} />
          <XAxis dataKey="period" tick={{ fontSize: 12 }} />
          <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 12 }} />
          <Tooltip formatter={(value) => `${String(value)}%`} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="auto" name="Auto-resolved" fill="#d6d3d1" barSize={28} />
          <Line dataKey="on" name="Accuracy, memory ON" stroke="#0f766e" strokeWidth={2.5} dot={{ r: 3 }} />
          <Line dataKey="off" name="Accuracy, memory OFF" stroke="#a8a29e" strokeWidth={2} strokeDasharray="5 4" dot={{ r: 3 }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

type SortKey = "vendor" | "type" | "level" | "streak";

function sortPatterns(rows: Pattern[], key: SortKey, desc: boolean): Pattern[] {
  const value = (p: Pattern): string | number => {
    switch (key) {
      case "vendor":
        return p.vendor.name;
      case "type":
        return exceptionLabel(p.type);
      case "level":
        return p.level;
      case "streak":
        return p.streak;
    }
  };
  return [...rows].sort((a, b) => {
    const x = value(a);
    const y = value(b);
    const order = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
    return desc ? -order : order;
  });
}

function TrustBoard() {
  const trust = useTrust();
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "level", desc: true });
  const header = (key: SortKey, label: string) => (
    <th className="py-1.5 pr-4 font-medium" aria-sort={sort.key === key ? (sort.desc ? "descending" : "ascending") : "none"}>
      <button
        type="button"
        className="hover:text-stone-800"
        onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : key === "level" || key === "streak" }))}
      >
        {label}
        {sort.key === key && (sort.desc ? " ↓" : " ↑")}
      </button>
    </th>
  );

  return (
    <Panel title="Trust board">
      {trust.isPending && <Skeleton rows={2} />}
      {trust.isError && <ErrorBox error={trust.error} onRetry={() => void trust.refetch()} />}
      {trust.data && trust.data.length === 0 && <p className="text-sm text-stone-500">No patterns yet.</p>}
      {trust.data && trust.data.length > 0 && (
        <div className="max-h-96 overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white text-left text-xs text-stone-500">
              <tr>
                {header("vendor", "Vendor")}
                {header("type", "Issue")}
                {header("level", "Trust")}
                {header("streak", "Streak")}
                <th className="py-1.5 pr-4 text-right font-medium">Right / wrong</th>
              </tr>
            </thead>
            <tbody>
              {sortPatterns(trust.data, sort.key, sort.desc).map((p) => (
                <tr key={`${p.vendor.gstin}-${p.type}`} className="border-t border-stone-100">
                  <td className="py-1.5 pr-4">
                    <a href={`#/vendors/${encodeURIComponent(p.vendor.gstin)}`} className="text-accent-700 hover:underline">
                      {p.vendor.name}
                    </a>
                  </td>
                  <td className="py-1.5 pr-4">{exceptionLabel(p.type)}</td>
                  <td className="py-1.5 pr-4">{TRUST_LABELS[p.level].label}</td>
                  <td className="num py-1.5 pr-4">{p.streak}</td>
                  <td className="num py-1.5 pr-4 text-right">
                    {p.correct} / {p.wrong}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

/** A debug box: what does memory return for a query? (SPEC-08 Q2.) */
function AskMemory() {
  const [q, setQ] = useState("");
  const [result, setResult] = useState<RecallResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [asking, setAsking] = useState(false);
  const ask = async (event: FormEvent) => {
    event.preventDefault();
    if (!q.trim()) return;
    setAsking(true);
    setError(null);
    try {
      setResult(await api.recall(q.trim()));
    } catch (e) {
      setError(e);
    } finally {
      setAsking(false);
    }
  };
  return (
    <Panel title="Ask memory">
      <form onSubmit={(e) => void ask(e)} className="flex gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="e.g. Reddy Traders late filing"
          aria-label="Memory query"
          className="flex-1 rounded-md border border-stone-300 px-2 py-1.5 text-sm"
        />
        <Button type="submit" disabled={asking || !q.trim()}>
          {asking ? "Asking…" : "Recall"}
        </Button>
      </form>
      {error !== null && (
        <div className="mt-3">
          <ErrorBox error={error} />
        </div>
      )}
      {result && (
        <ul className="mt-3 space-y-2 text-sm">
          {result.memories.length === 0 && <li className="text-stone-500">Nothing found.</li>}
          {result.memories.map((m) => (
            <li key={m.id} className="rounded-md bg-stone-50 px-3 py-2 text-stone-700">
              {m.text}
              {(m.period || m.client_id) && (
                <span className="ml-2 text-xs text-stone-500">
                  {[m.client_id, m.period && periodLabel(m.period)].filter(Boolean).join(" · ")}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}


// S3: what Munshi knows about one vendor, month by month across clients.

import { useVendor } from "../api/hooks";
import type { HistoryRow, Vendor } from "../api/types";
import { TrustLadder, trustTitle } from "../components/badges";
import { Banner, Chip, ErrorBox, Panel, Skeleton } from "../components/ui";
import { periodLabel, stateOf } from "../lib/format";
import { actionLabel, exceptionLabel, OUTCOME_LABELS } from "../lib/labels";
import { useWorkspace } from "../lib/workspace";

export function VendorProfile({ gstin }: { gstin: string }) {
  const ws = useWorkspace();
  const vendor = useVendor(gstin);

  return (
    <div className="space-y-4">
      <a href="#/workbench" className="text-sm text-accent-700 hover:underline">
        ← Back to the workbench
      </a>
      {vendor.isPending && <Skeleton rows={4} />}
      {vendor.isError && <ErrorBox error={vendor.error} onRetry={() => void vendor.refetch()} />}
      {vendor.data && <Profile vendor={vendor.data} clientName={(id) => ws.clients.find((c) => c.id === id)?.name ?? id} />}
    </div>
  );
}

function Profile({ vendor, clientName }: { vendor: Vendor; clientName: (id: string) => string }) {
  const driftPeriods = new Set(vendor.drift_events.map((d) => d.period));
  const history = [...vendor.history].sort((a, b) => a.period.localeCompare(b.period) || a.client_id.localeCompare(b.client_id));

  return (
    <>
      <header>
        <h1 className="text-lg font-semibold text-stone-900">{vendor.name}</h1>
        <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-stone-600">
          <span className="font-mono">{vendor.gstin}</span>
          <span>· {stateOf(vendor.gstin)}</span>
          <Chip tone={vendor.registration_status === "ACTIVE" ? "green" : "red"}>{vendor.registration_status}</Chip>
          {!vendor.known && <Chip tone="orange">Not in vendor master</Chip>}
        </p>
        {vendor.clients.length > 0 && (
          <p className="mt-1 text-sm text-stone-600">Supplies {vendor.clients.map(clientName).join(", ")}</p>
        )}
      </header>

      <Panel title="What Munshi knows">
        {vendor.profile ? (
          <p className="whitespace-pre-line text-sm leading-relaxed text-stone-700">{vendor.profile}</p>
        ) : (
          <Banner>Memory offline or nothing learned yet — no profile to show.</Banner>
        )}
      </Panel>

      <Panel title="Timeline">
        {history.length === 0 ? (
          <p className="text-sm text-stone-500">No decisions about this vendor yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-stone-500">
                <tr>
                  <th className="py-1.5 pr-4 font-medium">Month</th>
                  <th className="py-1.5 pr-4 font-medium">Client</th>
                  <th className="py-1.5 pr-4 font-medium">Issue</th>
                  <th className="py-1.5 pr-4 font-medium">Action</th>
                  <th className="py-1.5 pr-4 font-medium">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {history.map((row, i) => (
                  <TimelineRow key={i} row={row} clientName={clientName} drift={driftPeriods.has(row.period)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Trust per issue type">
        {vendor.trust.length === 0 ? (
          <p className="text-sm text-stone-500">No patterns yet.</p>
        ) : (
          <ul className="space-y-3">
            {vendor.trust.map((p) => (
              <li key={`${p.type}-${p.period}`} className="flex flex-wrap items-center justify-between gap-2" title={trustTitle(p)}>
                <span className="text-sm text-stone-700">
                  {exceptionLabel(p.type)}
                  <span className="ml-2 text-xs text-stone-500">
                    {p.correct} right · {p.wrong} wrong
                  </span>
                </span>
                <TrustLadder level={p.level} />
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </>
  );
}

function TimelineRow({ row, clientName, drift }: { row: HistoryRow; clientName: (id: string) => string; drift: boolean }) {
  const outcome = row.outcome ? OUTCOME_LABELS[row.outcome.status] : undefined;
  return (
    <tr className="border-t border-stone-100 align-top">
      <td className="py-2 pr-4 whitespace-nowrap">
        {periodLabel(row.period)}
        {drift && (
          <span className="ml-2">
            <Chip tone="red" title="The vendor's pattern changed this month">
              ⚠ Pattern changed
            </Chip>
          </span>
        )}
      </td>
      <td className="py-2 pr-4">{clientName(row.client_id)}</td>
      <td className="py-2 pr-4">{exceptionLabel(row.type)}</td>
      <td className="py-2 pr-4">
        {actionLabel(row.action)}
        <span className="ml-1 text-xs text-stone-500">{row.decided_by === "AUTO" ? "(auto)" : ""}</span>
        {row.note && <p className="text-xs text-stone-500">“{row.note}”</p>}
      </td>
      <td className="py-2 pr-4">
        {outcome ? (
          <Chip tone={outcome.tone}>
            {outcome.mark} {outcome.label}
          </Chip>
        ) : (
          <span className="text-stone-400">—</span>
        )}
      </td>
    </tr>
  );
}

// One exception group: what is wrong, what Munshi suggests and why, and the
// accountant's decision (SPEC-08 S2).

import { forwardRef, useState, type KeyboardEvent } from "react";

import { errorMessage } from "../api/client";
import { useDecide } from "../api/hooks";
import type { Action, CitedMemory, Client, Group, Invoice } from "../api/types";
import { periodLabel, rupees } from "../lib/format";
import {
  ACTION_DONE,
  ACTION_LABELS,
  CONFIDENCE_LABELS,
  GUARDRAIL_LABELS,
  ROOT_CAUSE_LABELS,
  exceptionLabel,
} from "../lib/labels";
import { FlagChips, TrustChip } from "./badges";
import { UndoForm } from "./UndoForm";
import { Button, Chip, Disclosure } from "./ui";

interface Props {
  group: Group;
  clientId: string;
  clients: Client[];
  onOpenVendor: (gstin: string) => void;
}

export const ExceptionCard = forwardRef<HTMLDivElement, Props>(function ExceptionCard(
  { group, clientId, clients, onOpenVendor },
  ref,
) {
  const [editing, setEditing] = useState(false);
  const decision = group.decision;

  if (decision && !editing) {
    return (
      <div
        ref={ref}
        data-card
        tabIndex={0}
        className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-stone-200 bg-white px-4 py-2.5 text-sm focus-visible:outline-2 focus-visible:outline-accent-600"
      >
        <span>
          <span className="font-medium text-emerald-700">✓ {ACTION_DONE[decision.action]}</span>
          <span className="text-stone-500">
            {" · "}
            <VendorLink group={group} onOpenVendor={onOpenVendor} /> · {exceptionLabel(group.type)} ·{" "}
            <span className="num">{rupees(group.itc_at_risk)}</span>
            {decision.decided_by === "AUTO"
              ? " · resolved automatically"
              : decision.note
                ? " · note saved to memory"
                : " · saved to memory"}
          </span>
        </span>
        {decision.decided_by === "AUTO" ? (
          <UndoForm group={group} />
        ) : (
          <Button variant="ghost" onClick={() => setEditing(true)}>
            Change
          </Button>
        )}
      </div>
    );
  }

  return (
    <OpenCard
      ref={ref}
      group={group}
      clientId={clientId}
      clients={clients}
      onOpenVendor={onOpenVendor}
      onDone={() => setEditing(false)}
      onCancel={decision ? () => setEditing(false) : undefined}
    />
  );
});

const OpenCard = forwardRef<
  HTMLDivElement,
  Props & { onDone: () => void; onCancel: (() => void) | undefined }
>(function OpenCard({ group, clientId, clients, onOpenVendor, onDone, onCancel }, ref) {
  const suggestion = group.suggestion;
  const suggested = suggestion && group.allowed_actions.includes(suggestion.action) ? suggestion.action : null;
  const [choice, setChoice] = useState<Action | null>(null);
  const [note, setNote] = useState("");
  const decide = useDecide();

  const overriding = choice !== null && suggested !== null && choice !== suggested;
  const needsNote = overriding && note.trim() === "";
  const others = group.allowed_actions.filter((a) => a !== suggested);

  const submit = (action: Action) => {
    if (suggested !== null && action !== suggested && note.trim() === "") return;
    decide.mutate(
      { groupKey: group.group_key, body: { action, note: note.trim() || null } },
      { onSuccess: onDone },
    );
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    if ((event.key === "a" || event.key === "A") && suggested && !decide.isPending) {
      event.preventDefault();
      submit(suggested);
    }
  };

  return (
    <article
      ref={ref}
      data-card
      tabIndex={0}
      onKeyDown={onKeyDown}
      aria-label={`${group.vendor.name}: ${exceptionLabel(group.type)}`}
      className="rounded-lg border border-stone-200 bg-white shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-600"
    >
      <header className="flex flex-wrap items-start justify-between gap-2 px-4 pt-3">
        <div>
          <VendorLink group={group} onOpenVendor={onOpenVendor} strong />
          <span className="ml-2 font-mono text-xs text-stone-500">{group.vendor.gstin}</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-stone-600">{exceptionLabel(group.type)}</span>
          <span className="num text-lg font-semibold text-stone-900" title="Input tax credit at risk">
            {rupees(group.itc_at_risk)}
          </span>
        </div>
      </header>
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pb-3 pt-1">
        <Disclosure label={`${group.invoices.length} invoice${group.invoices.length === 1 ? "" : "s"}`}>
          <InvoiceTable invoices={group.invoices} />
        </Disclosure>
        {suggestion && <FlagChips flags={suggestion.flags} />}
      </div>

      <div className="space-y-3 border-t border-stone-100 px-4 py-3">
        {suggestion ? (
          <>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-sm">
                <span className="text-stone-500">Munshi suggests: </span>
                <span className="font-semibold uppercase tracking-wide text-accent-800">
                  {ACTION_LABELS[suggestion.action]}
                </span>
                <span className="text-stone-500"> · {ROOT_CAUSE_LABELS[suggestion.root_cause] ?? suggestion.root_cause}</span>
              </p>
              <span className="text-sm text-stone-600" title={`Confidence ${suggestion.final_confidence.toFixed(2)}`}>
                Confidence: <span className="font-medium">{CONFIDENCE_LABELS[suggestion.confidence_label]}</span>
              </span>
            </div>
            <blockquote className="border-l-2 border-accent-600 pl-3 text-sm text-stone-700">{suggestion.reasoning}</blockquote>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <Memories memories={suggestion.cited_memories} memoryOn={suggestion.memory_on} clientId={clientId} clients={clients} />
              <TrustChip trust={group.trust} />
            </div>
            {suggestion.vendor_message && <VendorMessage text={suggestion.vendor_message} />}
            {suggestion.guardrail_details.length > 0 && (
              <ul className="space-y-0.5 text-xs text-stone-500">
                {suggestion.guardrail_details.map((g, i) => (
                  <li key={i} title={g.detail}>
                    🛡 Safety rule applied: {GUARDRAIL_LABELS[g.rule] ?? g.rule}
                  </li>
                ))}
              </ul>
            )}
          </>
        ) : (
          <p className="text-sm text-stone-500">No suggestion for this group.</p>
        )}
      </div>

      <footer className="space-y-2 rounded-b-lg border-t border-stone-100 bg-stone-50 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          {suggested && (
            <Button variant="primary" disabled={decide.isPending} onClick={() => submit(suggested)} title="Accept (A)">
              ✓ Accept
            </Button>
          )}
          <label className="sr-only" htmlFor={`choice-${group.group_key}`}>
            Choose another action
          </label>
          <select
            id={`choice-${group.group_key}`}
            value={choice && choice !== suggested ? choice : ""}
            onChange={(e) => setChoice(e.target.value ? (e.target.value as Action) : null)}
            className="rounded-md border border-stone-300 bg-white px-2 py-1.5 text-sm"
          >
            <option value="">{suggested ? "Choose another…" : "Choose an action…"}</option>
            {others.map((a) => (
              <option key={a} value={a}>
                {ACTION_LABELS[a]}
              </option>
            ))}
          </select>
          {choice && choice !== suggested && (
            <Button variant="primary" disabled={needsNote || decide.isPending} onClick={() => submit(choice)}>
              Save: {ACTION_LABELS[choice]}
            </Button>
          )}
          {onCancel && (
            <Button variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
          )}
        </div>
        <label className="block">
          <span className="sr-only">Note</span>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={overriding ? 2 : 1}
            maxLength={2000}
            aria-invalid={needsNote}
            aria-describedby={needsNote ? `note-help-${group.group_key}` : undefined}
            placeholder={overriding ? "Why? Required when you choose differently." : "Note (optional)"}
            className={`w-full rounded-md border bg-white px-2 py-1.5 text-sm ${
              needsNote ? "border-red-500 ring-1 ring-red-500" : "border-stone-300"
            }`}
          />
        </label>
        {needsNote && (
          <p id={`note-help-${group.group_key}`} className="text-xs text-red-700">
            A note is required when you choose differently. It becomes Munshi's memory for next month.
          </p>
        )}
        {decide.isError && (
          <p role="alert" className="text-xs text-red-700">
            {errorMessage(decide.error)}
          </p>
        )}
      </footer>
    </article>
  );
});

function VendorLink({ group, onOpenVendor, strong = false }: {
  group: Group;
  onOpenVendor: (gstin: string) => void;
  strong?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpenVendor(group.vendor.gstin)}
      className={`text-left hover:text-accent-700 hover:underline ${strong ? "font-semibold text-stone-900" : ""}`}
    >
      {group.vendor.name}
    </button>
  );
}

function Memories({ memories, memoryOn, clientId, clients }: {
  memories: CitedMemory[];
  memoryOn: boolean;
  clientId: string;
  clients: Client[];
}) {
  if (!memoryOn) return <span className="text-sm text-stone-500">No memories used (memory off)</span>;
  if (memories.length === 0) return <span className="text-sm text-stone-500">No memories used</span>;
  return (
    <Disclosure label={`Based on ${memories.length} memor${memories.length === 1 ? "y" : "ies"}`}>
      <ul className="space-y-2">
        {memories.map((m) => {
          const other = m.client_id && m.client_id !== clientId ? clients.find((c) => c.id === m.client_id) : null;
          return (
            <li key={m.id} className="rounded-md bg-stone-50 px-3 py-2 text-sm">
              <p className="text-stone-700">{m.text}</p>
              <p className="mt-1 flex flex-wrap gap-2 text-xs text-stone-500">
                {m.period && <span>{periodLabel(m.period)}</span>}
                {other ? (
                  <Chip tone="orange">from {other.name}</Chip>
                ) : m.client_id && m.client_id !== clientId ? (
                  <Chip tone="orange">from client {m.client_id}</Chip>
                ) : null}
              </p>
            </li>
          );
        })}
      </ul>
    </Disclosure>
  );
}

function VendorMessage({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <Disclosure label="Draft message to vendor">
      <div className="flex items-start gap-2">
        <pre className="flex-1 whitespace-pre-wrap rounded-md bg-stone-50 px-3 py-2 font-sans text-sm text-stone-700">{text}</pre>
        <Button onClick={copy}>{copied ? "Copied" : "Copy"}</Button>
      </div>
    </Disclosure>
  );
}

const DETAIL_ROWS: [string, string, string][] = [
  ["Total", "book_total", "twob_total"],
  ["Tax head", "book_tax_head", "twob_tax_head"],
  ["GSTIN", "book_gstin", "twob_gstin"],
];

function InvoiceTable({ invoices }: { invoices: Invoice[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-stone-500">
          <tr>
            <th className="py-1 pr-3 font-medium">Invoice</th>
            <th className="py-1 pr-3 font-medium">Date</th>
            <th className="py-1 pr-3 text-right font-medium">Total</th>
            <th className="py-1 pr-3 text-right font-medium">Tax</th>
            <th className="py-1 font-medium">Books vs 2B</th>
          </tr>
        </thead>
        <tbody>
          {invoices.map((inv, i) => (
            <tr key={`${inv.invoice_no}-${i}`} className="border-t border-stone-100 align-top">
              <td className="py-1 pr-3 font-mono text-xs">{inv.invoice_no ?? "—"}</td>
              <td className="py-1 pr-3">{inv.date ?? "—"}</td>
              <td className="num py-1 pr-3 text-right">{rupees(inv.total)}</td>
              <td className="num py-1 pr-3 text-right">{rupees(inv.tax)}</td>
              <td className="py-1 text-xs text-stone-600">
                <Comparison details={inv.details} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Comparison({ details }: { details: Record<string, unknown> }) {
  const rows = DETAIL_ROWS.filter(([, books, twob]) => details[books] != null && details[twob] != null);
  const reason = details["itc_unavailable_reason"];
  if (rows.length === 0 && !reason) return <>—</>;
  const show = (key: string, value: unknown) => (key.endsWith("_total") ? rupees(String(value)) : String(value));
  return (
    <ul>
      {rows.map(([label, books, twob]) => (
        <li key={label}>
          {label}: <span className="num">{show(books, details[books])}</span> vs{" "}
          <span className="num">{show(twob, details[twob])}</span>
        </li>
      ))}
      {typeof reason === "string" && <li>{reason}</li>}
    </ul>
  );
}

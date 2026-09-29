// S1: load sample data or upload a month, see what has been run, reset the demo.

import { useQueries, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, errorMessage } from "../api/client";
import { keys, useHealth } from "../api/hooks";
import type { PeriodRow, UploadResult } from "../api/types";
import { Banner, Button, ErrorBox, Panel, ProgressBar } from "../components/ui";
import { periodLabel } from "../lib/format";
import { useWorkspace } from "../lib/workspace";

export function DataScreen() {
  const health = useHealth();
  const ws = useWorkspace();
  // Keep the progress bar up for the whole seed, though data exists after its first month.
  const seeded = (health.data?.seeded ?? false) && ws.activeJob === null;
  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold text-stone-900">Data</h1>
      {!seeded && <SampleData />}
      <PeriodTable />
      <UploadForm />
      {seeded && <ResetDemo />}
    </div>
  );
}

function SampleData() {
  const ws = useWorkspace();
  const [error, setError] = useState<unknown>(null);
  const job = ws.activeJob;
  const start = async () => {
    setError(null);
    try {
      ws.trackJob(await api.seed());
    } catch (e) {
      setError(e);
    }
  };
  return (
    <Panel title="Sample data">
      <p className="mb-3 text-sm text-stone-600">
        Three fictional clients of a CA firm over four months (Jan–Apr 2026). Loading replays January to March with a
        simulated accountant, so Recon starts April with three months of memory.
      </p>
      {job ? (
        <ProgressBar done={job.done} total={job.total} label={`Replaying history${job.result["last"] ? ` · ${String(job.result["last"])}` : ""}`} />
      ) : (
        <Button variant="primary" onClick={() => void start()} disabled={ws.busy}>
          Load sample data (3 clients × 4 months)
        </Button>
      )}
      {error !== null && (
        <div className="mt-3">
          <ErrorBox error={error} />
        </div>
      )}
    </Panel>
  );
}

function status(row: PeriodRow): string {
  if (!row.has_2b || !row.has_books) return row.has_books ? "Books only" : "2B only";
  if (row.run_status === "running") return "Running…";
  if (row.run_status === "failed") return "Run failed";
  if (row.run_status !== "done") return "Not run";
  return row.open_groups === 0 ? "Decided" : `${row.open_groups} open`;
}

function PeriodTable() {
  const ws = useWorkspace();
  const results = useQueries({
    queries: ws.clients.map((c) => ({ queryKey: keys.periods(c.id), queryFn: () => api.periods(c.id) })),
  });
  if (ws.clients.length === 0) return null;
  const allPeriods = [...new Set(results.flatMap((r) => r.data?.map((p) => p.period) ?? []))].sort();

  const open = (clientId: string, period: string) => {
    ws.selectMonth(clientId, period);
    ws.navigate({ name: "workbench" });
  };

  return (
    <Panel title="Clients and months">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-stone-500">
            <tr>
              <th className="py-1.5 pr-4 font-medium">Client</th>
              {allPeriods.map((p) => (
                <th key={p} className="py-1.5 pr-4 font-medium">
                  {periodLabel(p)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ws.clients.map((client, i) => {
              const rows = results[i]?.data ?? [];
              return (
                <tr key={client.id} className="border-t border-stone-100">
                  <td className="py-2 pr-4">
                    <div className="font-medium text-stone-800">{client.name}</div>
                    <div className="text-xs text-stone-500">
                      {client.id} · {client.business}
                    </div>
                  </td>
                  {allPeriods.map((period) => {
                    const row = rows.find((r) => r.period === period);
                    if (!row) return <td key={period} className="py-2 pr-4 text-stone-400">—</td>;
                    const done = row.run_status === "done";
                    return (
                      <td key={period} className="py-2 pr-4">
                        <div className="flex items-center gap-2">
                          <span className={done ? "text-stone-700" : "text-stone-500"}>{status(row)}</span>
                          {done ? (
                            <Button variant="ghost" onClick={() => open(client.id, period)}>
                              Open
                            </Button>
                          ) : row.has_books && row.has_2b ? (
                            <Button
                              variant="secondary"
                              disabled={ws.busy}
                              onClick={() => {
                                open(client.id, period);
                                void ws.startRun(client.id, period, true);
                              }}
                            >
                              Run
                            </Button>
                          ) : null}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {ws.runError && (
        <div className="mt-3">
          <ErrorBox error={new Error(ws.runError)} onRetry={ws.clearRunError} />
        </div>
      )}
    </Panel>
  );
}

function UploadForm() {
  const ws = useWorkspace();
  const queryClient = useQueryClient();
  const [clientId, setClientId] = useState("");
  const [period, setPeriod] = useState("");
  const [books, setBooks] = useState<File | null>(null);
  const [twob, setTwob] = useState<File | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [sending, setSending] = useState(false);

  const client = clientId || ws.clients[0]?.id || "";
  const ready = client !== "" && /^\d{4}-\d{2}$/.test(period) && books !== null && twob !== null;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!ready || !books || !twob) return;
    const form = new FormData();
    form.set("client_id", client);
    form.set("period", period);
    form.set("purchase_register", books);
    form.set("gstr2b", twob);
    setSending(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.upload(form));
      await queryClient.invalidateQueries({ queryKey: ["periods"] });
    } catch (e) {
      setError(e);
    } finally {
      setSending(false);
    }
  };

  if (ws.clients.length === 0) return null;
  return (
    <Panel title="Upload a month">
      <form onSubmit={(e) => void submit(e)} className="grid gap-3 md:grid-cols-2">
        <label className="text-sm">
          <span className="mb-1 block text-stone-600">Client</span>
          <select value={client} onChange={(e) => setClientId(e.target.value)} className="w-full rounded-md border border-stone-300 bg-white px-2 py-1.5">
            {ws.clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.id} · {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-stone-600">Period</span>
          <input type="month" value={period} onChange={(e) => setPeriod(e.target.value)} className="w-full rounded-md border border-stone-300 px-2 py-1.5" />
        </label>
        <FileDrop label="Purchase register (CSV)" accept=".csv,text/csv" file={books} onFile={setBooks} />
        <FileDrop label="GSTR-2B (JSON)" accept=".json,application/json" file={twob} onFile={setTwob} />
        <div className="md:col-span-2">
          <Button type="submit" variant="primary" disabled={!ready || sending || ws.busy}>
            {sending ? "Uploading…" : "Upload"}
          </Button>
        </div>
      </form>
      {result && (
        <div className="mt-3 space-y-2">
          <Banner tone="green">
            Loaded {result.rows_books} book rows and {result.rows_2b} GSTR-2B rows.
          </Banner>
          {result.warnings.map((w) => (
            <Banner key={w}>{w}</Banner>
          ))}
        </div>
      )}
      {error !== null && (
        <div className="mt-3">
          <ErrorBox error={error} />
        </div>
      )}
    </Panel>
  );
}

function FileDrop({ label, accept, file, onFile }: {
  label: string;
  accept: string;
  file: File | null;
  onFile: (file: File | null) => void;
}) {
  const [over, setOver] = useState(false);
  return (
    <label
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        onFile(e.dataTransfer.files[0] ?? null);
      }}
      className={`flex cursor-pointer flex-col items-center justify-center rounded-md border-2 border-dashed px-4 py-5 text-sm ${
        over ? "border-accent-600 bg-accent-50" : "border-stone-300 bg-stone-50"
      }`}
    >
      <span className="font-medium text-stone-700">{label}</span>
      <span className="mt-1 text-xs text-stone-500">{file ? file.name : "Drop a file here or click to choose"}</span>
      <input type="file" accept={accept} className="sr-only" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
    </label>
  );
}

function ResetDemo() {
  const ws = useWorkspace();
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [working, setWorking] = useState(false);
  const reset = async () => {
    setWorking(true);
    setError(null);
    try {
      await api.reset();
      setTyped("");
      ws.markReset();
    } catch (e) {
      setError(e);
    } finally {
      setWorking(false);
    }
  };
  return (
    <Panel title="Reset demo">
      <p className="mb-3 text-sm text-stone-600">
        Deletes every run, decision and memory, so the demo can start from nothing. Type <strong>RESET</strong> to confirm.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          aria-label="Type RESET to confirm"
          className="rounded-md border border-stone-300 px-2 py-1.5 text-sm"
        />
        <Button variant="danger" disabled={typed !== "RESET" || working || ws.busy} onClick={() => void reset()}>
          {working ? "Resetting…" : "Reset demo"}
        </Button>
      </div>
      {error !== null && <p className="mt-2 text-sm text-red-700">{errorMessage(error)}</p>}
    </Panel>
  );
}

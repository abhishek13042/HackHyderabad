// Undo an automatic decision: pick what should have happened and say why
// (SPEC-06 §7). The pattern drops back to Observe on the next run.

import { useState } from "react";

import { errorMessage } from "../api/client";
import { useUndo } from "../api/hooks";
import type { Action, Group } from "../api/types";
import { ACTION_LABELS } from "../lib/labels";
import { Button } from "./ui";

export function UndoForm({ group }: { group: Group }) {
  const [open, setOpen] = useState(false);
  const current = group.decision?.action;
  const choices = group.allowed_actions.filter((a) => a !== current);
  const [action, setAction] = useState<Action | "">("");
  const [note, setNote] = useState("");
  const undo = useUndo();

  if (!open) {
    return (
      <Button variant="ghost" onClick={() => setOpen(true)}>
        Undo
      </Button>
    );
  }
  const ready = action !== "" && note.trim() !== "";
  return (
    <form
      className="flex w-full flex-wrap items-center gap-2 pt-1"
      onSubmit={(event) => {
        event.preventDefault();
        if (!ready) return;
        undo.mutate({ groupKey: group.group_key, body: { action, note: note.trim() } });
      }}
    >
      <label className="sr-only" htmlFor={`undo-${group.group_key}`}>
        What should have happened
      </label>
      <select
        id={`undo-${group.group_key}`}
        value={action}
        onChange={(e) => setAction(e.target.value as Action | "")}
        className="rounded-md border border-stone-300 bg-white px-2 py-1 text-sm"
      >
        <option value="">What should have happened…</option>
        {choices.map((a) => (
          <option key={a} value={a}>
            {ACTION_LABELS[a]}
          </option>
        ))}
      </select>
      <input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        maxLength={2000}
        placeholder="Why was the automatic decision wrong? (required)"
        aria-label="Why was the automatic decision wrong?"
        className="min-w-48 flex-1 rounded-md border border-stone-300 px-2 py-1 text-sm"
      />
      <Button type="submit" variant="danger" disabled={!ready || undo.isPending}>
        Undo
      </Button>
      <Button variant="ghost" onClick={() => setOpen(false)}>
        Cancel
      </Button>
      {undo.isError && (
        <p role="alert" className="w-full text-xs text-red-700">
          {errorMessage(undo.error)}
        </p>
      )}
    </form>
  );
}

import type { Flag, Trust } from "../api/types";
import { ACTION_LABELS, FLAG_LABELS, TRUST_LABELS } from "../lib/labels";
import { Chip } from "./ui";

export function FlagChips({ flags }: { flags: Flag[] }) {
  if (flags.length === 0) return null;
  return (
    <span className="flex flex-wrap gap-1">
      {flags.map((flag) => {
        const { label, tone } = FLAG_LABELS[flag] ?? { label: flag, tone: "grey" as const };
        return (
          <Chip key={flag} tone={tone}>
            {tone === "red" ? "⚠ " : ""}
            {label}
          </Chip>
        );
      })}
    </span>
  );
}

export function trustTitle(trust: Trust): string {
  const streak = trust.streak_action
    ? `${trust.streak} in a row: ${ACTION_LABELS[trust.streak_action]}`
    : "no streak yet";
  return `${TRUST_LABELS[trust.level].hint} ${streak} · ${trust.correct} right, ${trust.wrong} wrong`;
}

export function TrustChip({ trust }: { trust: Trust | null }) {
  if (!trust) return <Chip title="No history for this vendor and issue yet.">● New pattern</Chip>;
  const { label, tone } = TRUST_LABELS[trust.level];
  return (
    <Chip tone={tone} title={trustTitle(trust)}>
      ● Trust: {label}
    </Chip>
  );
}

/** Observe → Suggest → Auto with the current step highlighted (SPEC-08 S3). */
export function TrustLadder({ level }: { level: 0 | 1 | 2 }) {
  return (
    <ol className="flex items-center gap-1" aria-label={`Trust level: ${TRUST_LABELS[level].label}`}>
      {([0, 1, 2] as const).map((step) => (
        <li key={step} className="flex items-center gap-1">
          <span
            aria-current={step === level ? "step" : undefined}
            className={`rounded px-2 py-0.5 text-xs ${
              step === level
                ? "bg-accent-700 font-semibold text-white"
                : step < level
                  ? "bg-accent-100 text-accent-800"
                  : "bg-stone-100 text-stone-500"
            }`}
          >
            {TRUST_LABELS[step].label}
          </span>
          {step < 2 && <span className="text-stone-400">→</span>}
        </li>
      ))}
    </ol>
  );
}

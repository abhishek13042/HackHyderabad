// Small building blocks shared by every screen.

import type { ButtonHTMLAttributes, ReactNode } from "react";

import { errorMessage } from "../api/client";
import type { Tone } from "../lib/labels";

const TONES: Record<Tone, string> = {
  red: "bg-red-50 text-red-800 ring-red-200",
  orange: "bg-orange-50 text-orange-800 ring-orange-200",
  grey: "bg-stone-100 text-stone-700 ring-stone-200",
  green: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  blue: "bg-sky-50 text-sky-800 ring-sky-200",
  yellow: "bg-amber-50 text-amber-900 ring-amber-200",
};

export function Chip({ tone = "grey", title, children }: { tone?: Tone; title?: string; children: ReactNode }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent-700 text-white hover:bg-accent-800 disabled:bg-stone-300",
  secondary: "bg-white text-stone-800 ring-1 ring-inset ring-stone-300 hover:bg-stone-50 disabled:text-stone-400",
  ghost: "text-accent-700 hover:bg-accent-50 disabled:text-stone-400",
  danger: "bg-red-700 text-white hover:bg-red-800 disabled:bg-stone-300",
};

export function Button({
  variant = "secondary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      {...props}
      className={`inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-600 disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
    />
  );
}

export function Panel({ title, action, children, className = "" }: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-lg border border-stone-200 bg-white ${className}`}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-2 border-b border-stone-100 px-4 py-2.5">
          <h2 className="text-sm font-semibold text-stone-700">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Banner({ tone = "yellow", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <div role="status" className={`rounded-md px-4 py-2 text-sm ring-1 ring-inset ${TONES[tone]}`}>
      {children}
    </div>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading" className="space-y-3">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="h-16 animate-pulse rounded-lg bg-stone-200/70" />
      ))}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-stone-300 bg-white px-6 py-10 text-center">
      <p className="font-medium text-stone-700">{title}</p>
      {children && <div className="mt-2 text-sm text-stone-500">{children}</div>}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-center justify-between gap-4 rounded-md bg-red-50 px-4 py-3 text-sm text-red-800 ring-1 ring-inset ring-red-200">
      <span>{errorMessage(error)}</span>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function ProgressBar({ done, total, label }: { done: number; total: number; label: string }) {
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  return (
    <div className="w-full">
      <div className="mb-1 flex justify-between text-xs text-stone-600">
        <span>{label}</span>
        <span className="num">
          {done}/{total || "…"}
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
        className="h-2 overflow-hidden rounded-full bg-stone-200"
      >
        <div className="h-full bg-accent-600 transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function Disclosure({ label, children, defaultOpen = false }: {
  label: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details className="group" open={defaultOpen}>
      <summary className="cursor-pointer list-none select-none text-sm [&::-webkit-details-marker]:hidden text-accent-700 hover:underline">
        {label} <span className="inline-block transition-transform group-open:rotate-90">▸</span>
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-stone-200 bg-white px-4 py-3" title={hint}>
      <div className="text-xs uppercase tracking-wide text-stone-500">{label}</div>
      <div className="num mt-1 text-2xl font-semibold text-stone-800">{value}</div>
    </div>
  );
}

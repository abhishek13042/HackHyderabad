import { describe, expect, it } from "vitest";

import type { PeriodRow } from "../api/types";
import { defaultPeriod } from "./workspace";

const row = (period: string, extra: Partial<PeriodRow> = {}): PeriodRow => ({
  period,
  has_books: true,
  has_2b: true,
  run_status: null,
  run_id: null,
  open_groups: 0,
  auto_resolved: 0,
  ...extra,
});

describe("defaultPeriod", () => {
  it("opens the latest reconciled month", () => {
    const periods = [row("2026-01", { run_status: "done" }), row("2026-02", { run_status: "done" }), row("2026-03")];
    expect(defaultPeriod(periods)).toBe("2026-02");
  });

  it("else the latest month with a GSTR-2B", () => {
    expect(defaultPeriod([row("2026-01"), row("2026-02"), row("2026-03", { has_2b: false })])).toBe("2026-02");
    expect(defaultPeriod([])).toBeNull();
  });
});

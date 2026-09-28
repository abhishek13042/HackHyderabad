import { describe, expect, it } from "vitest";

import type { MemoryEvent } from "../api/types";
import { eventLook } from "./MemoryPanel";

const event = (op: string, kind: string | null): MemoryEvent => ({
  id: 1,
  ts: "2026-09-28T10:00:00Z",
  op,
  kind,
  summary: "",
  result_count: null,
  latency_ms: null,
  ok: true,
  error: null,
});

describe("eventLook", () => {
  it("gives each kind of memory event its own icon", () => {
    expect(eventLook(event("recall", null)).icon).toBe("↓");
    expect(eventLook(event("reflect", null)).icon).toBe("✦");
    expect(eventLook(event("retain", "resolution")).icon).toBe("↑");
    expect(eventLook(event("retain", "outcome")).icon).toBe("✓");
    expect(eventLook(event("retain", "drift")).icon).toBe("⚠");
  });
});

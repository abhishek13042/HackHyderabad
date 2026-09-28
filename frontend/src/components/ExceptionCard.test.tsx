import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CLIENTS, group, suggestion } from "../test/fixtures";
import { renderWithQuery } from "../test/render";
import { ExceptionCard, memoryFact } from "./ExceptionCard";

function card(g = group()) {
  return renderWithQuery(<ExceptionCard group={g} clientId="C01" clients={CLIENTS} onOpenVendor={() => {}} />);
}

/** Answer every request with 200 {} and hand back the mock to inspect the calls. */
function stubFetch() {
  const fetch = vi.fn((_url: string, _init?: RequestInit) =>
    Promise.resolve(new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } })),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function sentBody(fetch: ReturnType<typeof stubFetch>): unknown {
  const call = fetch.mock.calls[0];
  if (!call) throw new Error("nothing was sent");
  return JSON.parse(String(call[1]?.body));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ExceptionCard", () => {
  it("accepts the suggestion without a note", async () => {
    const fetch = stubFetch();
    card();
    await userEvent.click(screen.getByRole("button", { name: /accept/i }));
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch.mock.calls[0]?.[0]).toContain("/decision");
    expect(sentBody(fetch)).toEqual({ action: "DEFER", note: null });
  });

  it("blocks an override until a note is written (AC-08-2)", async () => {
    const fetch = stubFetch();
    card();
    await userEvent.selectOptions(screen.getByLabelText(/choose another action/i), "CHASE_VENDOR");
    const save = screen.getByRole("button", { name: /save: chase vendor/i });
    expect(save).toBeDisabled();
    expect(screen.getByRole("textbox")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/a note is required/i)).toBeInTheDocument();

    await userEvent.type(screen.getByRole("textbox"), "Vendor confirmed they will file this month");
    expect(save).toBeEnabled();
    await userEvent.click(save);
    expect(sentBody(fetch)).toEqual({ action: "CHASE_VENDOR", note: "Vendor confirmed they will file this month" });
  });

  it("names the other client a memory came from (AC-08-3)", async () => {
    card(
      group({
        suggestion: suggestion({
          flags: ["CROSS_CLIENT_RISK"],
          cited_memories: [
            { id: "m1", text: "Reddy invoice never reached 2B", period: "2026-02", client_id: "C02", occurred_at: null },
          ],
        }),
      }),
    );
    // A flagged card opens its memories without a click.
    expect(screen.getByText("from Mehta Pharma")).toBeVisible();
    expect(screen.getByText(/seen at another client/i)).toBeInTheDocument();
  });

  it("says no memories were used when memory is off (AC-08-5)", () => {
    card(group({ suggestion: suggestion({ memory_on: false }), trust: null }));
    expect(screen.getByText(/no memories used/i)).toBeInTheDocument();
    expect(screen.getByText(/new pattern/i)).toBeInTheDocument();
  });

  it("offers Undo on an automatic decision", () => {
    card(
      group({
        decision: {
          id: 7,
          group_key: "k",
          action: "DEFER",
          suggested_action: "DEFER",
          accepted_suggestion: true,
          decided_by: "AUTO",
          note: null,
          decided_at: "2026-09-28T10:00:00Z",
        },
      }),
    );
    expect(screen.getByText(/resolved automatically/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });
});

describe("memoryFact", () => {
  it("drops the When and Involving parts Hindsight adds", () => {
    expect(memoryFact("Krishna did not file. | When: 2026-04-15 | Involving: Accountant | Late again.")).toBe(
      "Krishna did not file. · Late again.",
    );
  });
});

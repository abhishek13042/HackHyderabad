import { describe, expect, it } from "vitest";

import { parseRoute, routeHash, type Route } from "./route";

describe("hash routes", () => {
  it("round-trips every screen", () => {
    const routes: Route[] = [
      { name: "home" },
      { name: "workbench" },
      { name: "insights" },
      { name: "data" },
      { name: "vendor", gstin: "36AAACR1111R1Z1" },
    ];
    for (const route of routes) {
      expect(parseRoute(routeHash(route))).toEqual(route);
    }
  });

  it("starts at home and falls back to it", () => {
    expect(parseRoute("")).toEqual({ name: "home" });
    expect(parseRoute("#/nowhere")).toEqual({ name: "home" });
    expect(parseRoute("#/vendors/")).toEqual({ name: "workbench" });
  });
});

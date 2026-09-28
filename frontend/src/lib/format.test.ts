import { describe, expect, it } from "vitest";

import { percent, periodLabel, rupees, stateOf, sumMoney } from "./format";

describe("rupees", () => {
  it("groups digits the Indian way", () => {
    expect(rupees("106200.00")).toBe("₹1,06,200.00");
    expect(rupees("12345678.5")).toBe("₹1,23,45,678.50");
    expect(rupees("999")).toBe("₹999.00");
  });

  it("can drop paise and keeps the sign", () => {
    expect(rupees("27000.00", { paise: false })).toBe("₹27,000");
    expect(rupees("-1500.25")).toBe("-₹1,500.25");
  });

  it("shows a dash for missing amounts", () => {
    expect(rupees(null)).toBe("—");
    expect(rupees(undefined)).toBe("—");
  });
});

describe("sumMoney", () => {
  it("adds exactly, without float drift", () => {
    expect(sumMoney(["0.10", "0.20"])).toBe("0.30");
    expect(sumMoney(["18000.00", "2430.55", "-430.55"])).toBe("20000.00");
    expect(sumMoney([])).toBe("0.00");
  });
});

describe("labels", () => {
  it("names periods, percentages and states", () => {
    expect(periodLabel("2026-04")).toBe("Apr 2026");
    expect(periodLabel(null)).toBe("—");
    expect(percent(0.855)).toBe("86%");
    expect(stateOf("36AAACR1111R1Z1")).toBe("Telangana");
  });
});

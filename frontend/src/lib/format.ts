// Display formatting. Money arrives as exact decimal strings and is grouped
// without ever becoming a float (INV-3): ₹1,06,200.00.

import type { Money } from "../api/types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Indian digit grouping: the last three digits, then pairs (12,34,567). */
function groupIndian(digits: string): string {
  if (digits.length <= 3) return digits;
  const head = digits.slice(0, -3);
  const tail = digits.slice(-3);
  return head.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + tail;
}

export function rupees(amount: Money | null | undefined, { paise = true } = {}): string {
  if (amount === null || amount === undefined || amount === "") return "—";
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(amount.trim());
  if (!match) return amount;
  const [, sign, whole = "0", fraction = ""] = match;
  const rupeePart = groupIndian(whole.replace(/^0+(?=\d)/, ""));
  const paisePart = (fraction + "00").slice(0, 2);
  return `${sign}₹${rupeePart}${paise ? "." + paisePart : ""}`;
}

/** Sum of money strings, exactly, in paise. */
export function sumMoney(amounts: Money[]): Money {
  let paise = 0n;
  for (const amount of amounts) {
    const match = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(amount.trim());
    if (!match) continue;
    const [, sign, whole = "0", fraction = ""] = match;
    const value = BigInt(whole) * 100n + BigInt((fraction + "00").slice(0, 2));
    paise += sign ? -value : value;
  }
  const negative = paise < 0n;
  const abs = negative ? -paise : paise;
  const fraction = (abs % 100n).toString().padStart(2, "0");
  return `${negative ? "-" : ""}${abs / 100n}.${fraction}`;
}

/** "2026-04" → "Apr 2026". */
export function periodLabel(period: string | null | undefined): string {
  if (!period) return "—";
  const [year, month] = period.split("-");
  const name = MONTHS[Number(month) - 1];
  return name && year ? `${name} ${year}` : period;
}

export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

export function timeOfDay(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** A few Indian state codes (the first two digits of a GSTIN) used in the dataset and nearby. */
const STATES: Record<string, string> = {
  "07": "Delhi",
  "24": "Gujarat",
  "27": "Maharashtra",
  "29": "Karnataka",
  "32": "Kerala",
  "33": "Tamil Nadu",
  "36": "Telangana",
  "37": "Andhra Pradesh",
};

export function stateOf(gstin: string): string {
  const code = gstin.slice(0, 2);
  return STATES[code] ?? `State ${code}`;
}

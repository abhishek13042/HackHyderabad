"""Score recorded suggestions against the ground truth (SPEC-09 §3 and §4). Pure: no I/O.

Records from every repeat of a condition are pooled, so an accuracy is the share
of all its suggestions that were right. Every number is rounded, and every
mapping sorted, so scoring the same records twice gives the same bytes (AC-09-3).
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import quantiles
from typing import Any

from backend.app.agent import Guardrail
from backend.app.domain.enums import Action, ExceptionType, Flag
from backend.app.domain.policy import is_action_allowed

Record = dict[str, Any]
Truth = dict[str, dict[str, Any]]
"""Ground-truth entries by group key."""

SCORED_FLAGS = (Flag.PATTERN_DRIFT, Flag.CROSS_CLIENT_RISK, Flag.RECURRING_ISSUE, Flag.VENDOR_RISK)
ROUNDING_LIMIT = Decimal("10")
"""The rules-only baseline's hard-coded tolerance, the firm's policy in the dataset."""

TARGETS = {
    "april_accuracy_on": 0.80,
    "april_gap": 0.25,
    "unsafe_shown": 0,
    "json_first_try": 0.95,
    "april_auto_rate": 0.40,
    "auto_correct": 1.0,
}
"""SPEC-00 success criteria, as SPEC-09 §3 states them."""


def share(hits: int, total: int) -> float | None:
    return round(hits / total, 4) if total else None


def correct(r: Record, truth: Truth) -> bool:
    return r["action"] in truth[r["group_key"]]["acceptable_actions"]


def by(records: Iterable[Record], *fields: str) -> dict[tuple[Any, ...], list[Record]]:
    groups: defaultdict[tuple[Any, ...], list[Record]] = defaultdict(list)
    for r in records:
        groups[tuple(r[f] for f in fields)].append(r)
    return dict(groups)


def compute(
    records: Sequence[Record], truth: Truth, vendor_names: dict[str, str]
) -> dict[str, Any]:
    conditions = sorted({r["condition"] for r in records}, key=_condition_order)
    periods = sorted({r["period"] for r in records})
    per_condition = by(records, "condition")
    metrics: dict[str, Any] = {
        "conditions": conditions,
        "periods": periods,
        "repeats": len({r["repeat"] for r in records}),
        "suggestions": {c: len(per_condition[(c,)]) for c in conditions},
        "accuracy": {c: _per_period(per_condition[(c,)], periods, truth) for c in conditions},
        "safety": {c: _safety(per_condition[(c,)]) for c in conditions},
        "root_cause": {c: _root_cause(per_condition[(c,)], truth) for c in conditions},
        "flags": {c: _flags(per_condition[(c,)], truth) for c in conditions},
        "grounding": {c: _grounding(per_condition[(c,)]) for c in conditions},
        "json": {c: _json(per_condition[(c,)]) for c in conditions},
        "autonomy": {c: _autonomy(per_condition[(c,)], periods, truth) for c in conditions},
        "cost": {c: _cost(per_condition[(c,)], periods) for c in conditions},
        "memory_offline_months": {c: _offline(per_condition[(c,)]) for c in conditions},
        "scenarios": scenarios(records, vendor_names),
        "baseline_rules": _baseline(records, periods, truth),
        "matcher": _matcher(records, truth),
    }
    metrics["gap"] = _gap(metrics["accuracy"], periods)
    metrics["targets"] = _targets(metrics, periods)
    return metrics


def _offline(records: Sequence[Record]) -> int:
    """Client-months whose run lost memory part-way and fell back to OFF."""
    return len({(r["repeat"], r["client_id"], r["period"]) for r in records if r["memory_offline"]})


def learning_curve(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    """What the Insights chart plots (`/insights`, AC-09-4)."""
    accuracy, autonomy = metrics["accuracy"], metrics["autonomy"]
    return [
        {
            "period": p,
            "accuracy_on": accuracy.get("on", {}).get(p),
            "accuracy_off": accuracy.get("off", {}).get(p),
            "auto_rate": autonomy.get("on", {}).get(p, {}).get("auto_rate"),
        }
        for p in metrics["periods"]
    ]


def _condition_order(condition: str) -> tuple[int, str]:
    return (0 if condition == "on" else 1, condition)


# --- E1–E3: accuracy and the memory gap ------------------------------------------


def _per_period(records: Sequence[Record], periods: Sequence[str], truth: Truth) -> dict[str, Any]:
    months = by(records, "period")
    out: dict[str, Any] = {
        p: share(sum(correct(r, truth) for r in months.get((p,), [])), len(months.get((p,), [])))
        for p in periods
    }
    out["all"] = share(sum(correct(r, truth) for r in records), len(records))
    return out


def _gap(accuracy: dict[str, dict[str, float | None]], periods: Sequence[str]) -> dict[str, Any]:
    """ON − OFF from the second month on; the first month has nothing to remember."""
    if "on" not in accuracy or "off" not in accuracy:
        return {}
    gap: dict[str, Any] = {}
    for p in periods[1:]:
        on, off = accuracy["on"].get(p), accuracy["off"].get(p)
        gap[p] = round(on - off, 4) if on is not None and off is not None else None
    return gap


# --- E4–E8 ------------------------------------------------------------------------


def _safety(records: Sequence[Record]) -> dict[str, int]:
    """Unsafe suggestions that reached the accountant, and what the guardrails caught."""
    shown = sum(
        not is_action_allowed(ExceptionType(r["exception_type"]), Action(r["action"]))
        for r in records
    )
    return {
        "unsafe_shown": shown,
        "raw_unsafe_caught": _count(records, Guardrail.UNSAFE_ACTION),
        "large_diff_caught": _count(records, Guardrail.LARGE_DIFF),
        "drift_override": _count(records, Guardrail.DRIFT_OVERRIDE),
    }


def _root_cause(records: Sequence[Record], truth: Truth) -> float | None:
    hits = sum(r["root_cause"] == truth[r["group_key"]]["root_cause"] for r in records)
    return share(hits, len(records))


def _flags(records: Sequence[Record], truth: Truth) -> dict[str, dict[str, Any]]:
    out = {}
    for flag in SCORED_FLAGS:
        said = [flag.value in r["flags"] for r in records]
        expected = [flag.value in truth[r["group_key"]]["flags"] for r in records]
        tp = sum(s and e for s, e in zip(said, expected, strict=True))
        fp = sum(s and not e for s, e in zip(said, expected, strict=True))
        fn = sum(e and not s for s, e in zip(said, expected, strict=True))
        out[flag.value] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": share(tp, tp + fp),
            "recall": share(tp, tp + fn),
        }
    return out


def _grounding(records: Sequence[Record]) -> dict[str, Any]:
    """A history claim is either cited, or caught by G3 (UNGROUNDED) and removed."""
    cited = sum(bool(r["cited"]) for r in records)
    ungrounded = _count(records, Guardrail.UNGROUNDED)
    return {
        "citing": share(cited, len(records)),
        "history_claims_grounded": share(cited, cited + ungrounded),
        "g3_rate": share(ungrounded, len(records)),
        "bad_citations": _count(records, Guardrail.BAD_CITATION),
        "cross_client_ungrounded": _count(records, Guardrail.UNGROUNDED_FLAG),
    }


def _json(records: Sequence[Record]) -> dict[str, Any]:
    answered = [r for r in records if r["attempts"] > 0]
    return {
        "first_try": share(sum(r["attempts"] == 1 for r in answered), len(answered)),
        "retried": sum(r["attempts"] > 1 for r in answered),
        "fallbacks": _count(records, Guardrail.INVALID_OUTPUT),
        "ai_unavailable": _count(records, Guardrail.AI_UNAVAILABLE),
    }


def _count(records: Iterable[Record], rule: Guardrail) -> int:
    return sum(rule.value in r["guardrails"] for r in records)


# --- E9–E10 ------------------------------------------------------------------------


def _autonomy(records: Sequence[Record], periods: Sequence[str], truth: Truth) -> dict[str, Any]:
    months = by(records, "period")
    out: dict[str, Any] = {}
    for p in periods:
        month = months.get((p,), [])
        auto = [r for r in month if r["auto_resolved"]]
        out[p] = {
            "auto_rate": share(len(auto), len(month)),
            "auto_correct": share(sum(correct(r, truth) for r in auto), len(auto)),
        }
    auto = [r for r in records if r["auto_resolved"]]
    out["all"] = {
        "auto_rate": share(len(auto), len(records)),
        "auto_correct": share(sum(correct(r, truth) for r in auto), len(auto)),
    }
    return out


def _cost(records: Sequence[Record], periods: Sequence[str]) -> dict[str, Any]:
    months = by(records, "period")
    tokens = {
        p: round(sum(_tokens(r) for r in months[(p,)]) / len(months[(p,)]))
        for p in periods
        if (p,) in months
    }
    latencies = sorted(r["latency_ms"] for r in records)
    return {
        "tokens_per_group": tokens,
        "latency_ms_p50": _percentile(latencies, 50),
        "latency_ms_p95": _percentile(latencies, 95),
        "models": sorted({r["model"] for r in records if r["model"]}),
    }


def _tokens(r: Record) -> int:
    return int(r["prompt_tokens"]) + int(r["completion_tokens"])


def _percentile(values: Sequence[int], pct: int) -> int | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return round(quantiles(values, n=100, method="inclusive")[pct - 1])


# --- Named scenarios (§3) ------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    vendor: str
    """The vendor's name in vendors.json."""
    select: Callable[[Record], bool]
    passes: Callable[[Sequence[Record]], bool]
    """Given the ON records `select` picked in one repeat (never empty)."""
    expect: str


def _cites_client(client_id: str) -> Callable[[Record], bool]:
    return lambda r: any(c["client_id"] == client_id for c in r["cited"])


SCENARIOS = (
    Scenario(
        "S1",
        "Drift",
        "Reddy Steels",
        lambda r: r["period"] == "2026-04" and r["exception_type"] == "MISSING_IN_2B",
        lambda rs: all("PATTERN_DRIFT" in r["flags"] and r["action"] != "DEFER" for r in rs),
        "April: PATTERN_DRIFT flagged and not deferred",
    ),
    Scenario(
        "S2",
        "Consistency",
        "Bhavani Chemicals",
        lambda r: r["period"] == "2026-04" and r["exception_type"] == "MISSING_IN_2B",
        lambda rs: all(r["action"] == "DEFER" and r["auto_resolved"] for r in rs),
        "April: DEFER, resolved automatically",
    ),
    Scenario(
        "S3",
        "Cross-client",
        "Krishna Logistics",
        lambda r: r["period"] == "2026-03" and r["client_id"] == "C03",
        lambda rs: all("CROSS_CLIENT_RISK" in r["flags"] and _cites_client("C01")(r) for r in rs),
        "C03 March: CROSS_CLIENT_RISK, citing a C01 memory",
    ),
    Scenario(
        "S4",
        "Preference",
        "Laxmi Packaging",
        lambda r: r["period"] >= "2026-02" and r["exception_type"] == "AMOUNT_MISMATCH",
        lambda rs: (
            all(r["action"] == "ACCEPT" for r in rs)
            and any("₹10" in c["text"] for r in rs for c in r["cited"])
        ),
        "February on: ACCEPT, with the 'under ₹10' note cited",
    ),
    Scenario(
        "S5",
        "Root cause",
        "Sai Electricals",
        lambda r: r["period"] == "2026-03" and r["client_id"] == "C03",
        lambda rs: all(r["root_cause"] == "WRONG_BUYER_GSTIN" for r in rs),
        "C03 March: root cause WRONG_BUYER_GSTIN, learnt from January's note",
    ),
)


def scenarios(records: Sequence[Record], vendor_names: dict[str, str]) -> list[dict[str, Any]]:
    """Each scenario per condition: repeats passed, and the first repeat's suggestions."""
    gstins = {name: gstin for gstin, name in vendor_names.items()}
    out = []
    for sc in SCENARIOS:
        gstin = gstins.get(sc.vendor)
        entry: dict[str, Any] = {"id": sc.id, "name": sc.name, "vendor": sc.vendor,
                                 "expect": sc.expect}  # fmt: skip
        for (condition,), rs in sorted(by(records, "condition").items()):
            picked = [r for r in rs if r["vendor_gstin"] == gstin and sc.select(r)]
            repeats = by(picked, "repeat")
            passed = sum(sc.passes(group) for group in repeats.values())
            first = repeats[min(repeats)] if repeats else []
            entry[condition] = {
                "passed": passed,
                "of": len({r["repeat"] for r in rs}),
                "found": bool(picked),
                "suggestions": [_brief(r) for r in sorted(first, key=lambda r: r["group_key"])],
            }
        on = entry.get("on")
        entry["pass"] = bool(on and on["found"] and on["passed"] == on["of"])
        out.append(entry)
    return out


def _brief(r: Record) -> dict[str, Any]:
    return {
        "group_key": r["group_key"],
        "action": r["action"],
        "root_cause": r["root_cause"],
        "flags": r["flags"],
        "auto_resolved": r["auto_resolved"],
        "cited_clients": sorted({c["client_id"] or "?" for c in r["cited"]}),
        "reasoning": r["reasoning"],
    }


# --- §4: the rules-only baseline and the matcher -----------------------------------------


RULES: dict[str, str] = {
    "MISSING_IN_2B": "CHASE_VENDOR",
    "MISSING_IN_BOOKS": "BOOK_INVOICE",
    "TAX_HEAD_MISMATCH": "CORRECT_BOOKS",
    "GSTIN_MISMATCH": "CORRECT_BOOKS",
    "ITC_INELIGIBLE": "BLOCK_ITC",
}
"""A fixed rule table: what the same firm could hard-code without any memory."""


def rule_action(r: Record) -> str:
    if r["exception_type"] == "AMOUNT_MISMATCH":
        return "ACCEPT" if Decimal(r["max_diff"]) <= ROUNDING_LIMIT else "CHASE_VENDOR"
    return RULES[r["exception_type"]]


def _baseline(records: Sequence[Record], periods: Sequence[str], truth: Truth) -> dict[str, Any]:
    """Scored once per group (the groups are the same in every condition and repeat)."""
    groups = {r["group_key"]: r for r in records}.values()
    ruled = [{**r, "action": rule_action(r)} for r in groups]
    return _per_period(ruled, periods, truth)


def _matcher(records: Sequence[Record], truth: Truth) -> dict[str, Any]:
    """Group keys the pipeline found vs the ground truth (SPEC-03 AC-03-10)."""
    found = {r["group_key"] for r in records}
    expected = {k for k in truth if k.split(":")[1] in {r["period"] for r in records}}
    hits = len(found & expected)
    return {
        "precision": share(hits, len(found)),
        "recall": share(hits, len(expected)),
        "unexpected": sorted(found - expected),
        "missed": sorted(expected - found),
    }


# --- Targets --------------------------------------------------------------------------------


def _targets(m: dict[str, Any], periods: Sequence[str]) -> list[dict[str, Any]]:
    last = periods[-1] if periods else None
    on = "on" in m["conditions"]

    def row(
        name: str, value: Any, target: str, met: bool | None, unit: str = "share"
    ) -> dict[str, Any]:
        return {"metric": name, "value": value, "target": target, "met": met, "unit": unit}

    def at_least(value: float | None, target: float) -> bool | None:
        return None if value is None else value >= target

    april = m["accuracy"].get("on", {}).get(last) if on and last else None
    gap = m["gap"].get(last) if last else None
    auto = m["autonomy"].get("on", {}).get(last, {}) if on and last else {}
    auto_all = m["autonomy"].get("on", {}).get("all", {}) if on else {}
    unsafe = sum(s["unsafe_shown"] for s in m["safety"].values())
    first_try = [j["first_try"] for j in m["json"].values() if j["first_try"] is not None]
    json_min = min(first_try) if first_try else None
    auto_correct = auto_all.get("auto_correct")
    return [
        row("E1 accuracy, last month, ON", april, "≥ 80%",
            at_least(april, TARGETS["april_accuracy_on"])),
        row("E2 memory gap, last month", gap, "≥ 25 pp", at_least(gap, TARGETS["april_gap"]), "pp"),
        row("E4 unsafe suggestions shown", unsafe, "0", unsafe == TARGETS["unsafe_shown"]),
        row("E8 valid JSON first try", json_min, "≥ 95%",
            at_least(json_min, TARGETS["json_first_try"])),
        row("E9 auto-resolved, last month", auto.get("auto_rate"), "≥ 40%",
            at_least(auto.get("auto_rate"), TARGETS["april_auto_rate"])),
        row("E9 auto-resolved and correct", auto_correct, "100%",
            None if auto_correct is None else auto_correct >= TARGETS["auto_correct"]),
    ]  # fmt: skip

"""Score a saved eval run and write its report (SPEC-09 §6).

    python -m evals.report evals/results/<run_id>

Reads config.json, suggestions.jsonl and the labels saved beside them; writes
metrics.json, learning_curve.json (read by `/insights`), learning_curve.svg and
report.md. Nothing else is read, so re-running it gives the same files (AC-09-3).
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from evals.chart import learning_curve_svg, month_label
from evals.harness import read_records
from evals.metrics import SCENARIOS, compute, learning_curve

CONFIG_FILE = "config.json"
RECORDS_FILE = "suggestions.jsonl"
LABELS_FILE = "ground_truth.json"
VENDORS_FILE = "vendors.json"
METRICS_FILE = "metrics.json"
CURVE_FILE = "learning_curve.json"  # the name backend/app/routers/insights.py reads
CHART_FILE = "learning_curve.svg"
REPORT_FILE = "report.md"


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8")  # fmt: skip


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_report(run_dir: Path) -> dict[str, Any]:
    config = read_json(run_dir / CONFIG_FILE)
    records = read_records(run_dir / RECORDS_FILE)
    if not records:
        raise SystemExit(f"{run_dir / RECORDS_FILE} has no suggestions yet")
    truth = {e["group_key"]: e for e in read_json(run_dir / LABELS_FILE)}
    vendors = {v["gstin"]: v["name"] for v in read_json(run_dir / VENDORS_FILE)}
    metrics = compute(records, truth, vendors)
    metrics["run_id"] = config["run_id"]
    curve = learning_curve(metrics)
    write_json(run_dir / METRICS_FILE, metrics)
    write_json(run_dir / CURVE_FILE, curve)
    (run_dir / CHART_FILE).write_text(learning_curve_svg(curve), encoding="utf-8")
    (run_dir / REPORT_FILE).write_text(markdown(config, metrics, curve), encoding="utf-8")
    return metrics


# --- report.md ------------------------------------------------------------------------


def pct(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.0f}%"


def pp(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:+.0f} pp"


def met(value: bool | None) -> str:
    return {True: "✅ met", False: "❌ missed", None: "– not measured"}[value]


def table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return [*lines, ""]


def markdown(config: dict[str, Any], m: dict[str, Any], curve: list[dict[str, Any]]) -> str:
    conditions, periods = m["conditions"], m["periods"]
    out = [
        f"# Munshi evaluation — run `{m['run_id']}`",
        "",
        "> The data is **synthetic** and its vendor patterns are **planted** (SPEC-02), so",
        "> these numbers show that the learning loop works, not how Munshi does on a real firm.",
        "> The last month is held out: the prompt was never tuned against its labels.",
        "",
        f"- Conditions: {', '.join(conditions)} · repeats: {m['repeats']} · dataset seed: "
        f"{config['seed']} · memory: {config['memory']}",
        f"- Models: {', '.join(config['models'])} · hindsight-client {config['hindsight_client']}",
        f"- Banks (fresh per condition and repeat): {', '.join(sorted(config['banks'].values()))}",
        "- Suggestions scored: " + ", ".join(f"{c} {m['suggestions'][c]}" for c in conditions),
        "",
    ]
    offline = {c: n for c, n in m["memory_offline_months"].items() if n}
    if offline:
        out += [
            "> ⚠ Memory went offline during "
            + ", ".join(f"{n} {c} client-months" for c, n in offline.items())
            + "; those runs fell back to memory OFF.",
            "",
        ]
    out += ["## Targets (SPEC-00)", ""]
    out += table(
        ["Metric", "Value", "Target", "Result"],
        [
            (t["metric"], _value(t["value"], t["unit"]), t["target"], met(t["met"]))
            for t in m["targets"]
        ],
    )
    out += ["## E1–E3 · Learning curve", "", f"![Learning curve]({'learning_curve.svg'})", ""]
    rows = []
    for point in curve:
        p = point["period"]
        rows.append(
            (
                month_label(p),
                pct(point["accuracy_on"]),
                pct(point["accuracy_off"]),
                pp(m["gap"].get(p)),
                pct(point["auto_rate"]),
                pct(m["baseline_rules"].get(p)),
            )
        )
    out += table(
        ["Month", "Accuracy ON", "Accuracy OFF", "Gap", "Auto-resolved (ON)", "Rules only"], rows
    )
    out += [
        "Accuracy: the suggested action is one of the ground truth's acceptable actions.",
        "Rules only: a fixed table (missing in 2B → chase, difference ≤ ₹10 → accept, …) with",
        "no memory, scored on the same groups (SPEC-09 §4).",
        "",
        "## E4 · Safety",
        "",
    ]
    out += table(
        ["Condition", "Unsafe shown", "Unsafe caught (G1)", "Large diff caught (G4)",
         "Drift override (G6)"],
        [(c, s["unsafe_shown"], s["raw_unsafe_caught"], s["large_diff_caught"],
          s["drift_override"]) for c, s in ((c, m["safety"][c]) for c in conditions)],
    )  # fmt: skip
    out += ["## E5–E6 · Root cause and flags", ""]
    flag_names = sorted(next(iter(m["flags"].values())))
    header = ["Condition", "Root cause"] + [f"{f} P / R" for f in flag_names]
    flag_rows = []
    for c in conditions:
        cells = [f"{pct(m['flags'][c][f]['precision'])} / {pct(m['flags'][c][f]['recall'])}"
                 for f in flag_names]  # fmt: skip
        flag_rows.append([c, pct(m["root_cause"][c]), *cells])
    out += table(header, flag_rows)
    out += ["## E7–E8 · Grounding and output validity", ""]
    out += table(
        ["Condition", "Citing ≥ 1 memory", "History claims grounded", "G3 fired", "Bad citations",
         "JSON first try", "Retried", "Fallbacks (G7)", "AI unavailable"],
        [(c, pct(g["citing"]), pct(g["history_claims_grounded"]), pct(g["g3_rate"]),
          g["bad_citations"], pct(j["first_try"]), j["retried"], j["fallbacks"],
          j["ai_unavailable"])
         for c, g, j in ((c, m["grounding"][c], m["json"][c]) for c in conditions)],
    )  # fmt: skip
    out += ["## E9–E10 · Autonomy and cost", ""]
    cost_rows = []
    for c in conditions:
        a, cost = m["autonomy"][c], m["cost"][c]
        cost_rows.append(
            [c]
            + [f"{pct(a[p]['auto_rate'])} ({pct(a[p]['auto_correct'])} right)" for p in periods]
            + [" / ".join(str(cost["tokens_per_group"].get(p, "–")) for p in periods),
               f"{cost['latency_ms_p50']} / {cost['latency_ms_p95']}"]
        )  # fmt: skip
    out += table(
        ["Condition", *(f"Auto {month_label(p)}" for p in periods),
         "Tokens per group (by month)", "Latency p50 / p95 ms"],
        cost_rows,
    )  # fmt: skip
    out += ["## Named scenarios", ""]
    for s in m["scenarios"]:
        on = s.get("on", {})
        status = "✅ pass" if s["pass"] else "❌ fail"
        count = f"{on.get('passed', 0)}/{on.get('of', 0)} repeats" if on else "not run"
        out += [f"### {s['id']} {s['name']} — {s['vendor']}: {status} ({count})", "",
                f"Expected: {s['expect']}.", ""]  # fmt: skip
        for c in conditions:
            got = s.get(c, {})
            if not got.get("found"):
                out += [f"- **{c}**: no matching suggestion.", ""]
                continue
            for b in got["suggestions"]:
                flags = ", ".join(b["flags"]) or "no flags"
                auto = " · auto-resolved" if b["auto_resolved"] else ""
                cites = ", ".join(b["cited_clients"]) or "none"
                out += [
                    f"- **{c}** `{b['group_key']}`: {b['action']} · {b['root_cause']} · {flags}"
                    f"{auto} · cites memories of: {cites}",
                    f"  > {b['reasoning']}",
                ]
            out.append("")
    matcher = m["matcher"]
    out += [
        "## Matcher (deterministic)",
        "",
        f"Group keys found vs ground truth: precision {pct(matcher['precision'])}, "
        f"recall {pct(matcher['recall'])}.",
        "",
        f"_Scenario checks: {', '.join(s.id for s in SCENARIOS)}. "
        "Regenerate with `python -m evals.report` on this folder._",
        "",
    ]
    return "\n".join(out)


def _value(value: Any, unit: str) -> str:
    if isinstance(value, float):
        return pp(value) if unit == "pp" else pct(value)
    return "–" if value is None else str(value)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.report", description=__doc__)
    parser.add_argument("run_dir", type=Path, help="evals/results/<run_id>")
    args = parser.parse_args(argv)
    write_report(args.run_dir)
    print(f"wrote {args.run_dir / REPORT_FILE}")


if __name__ == "__main__":
    main()

"""SPEC-09: the evaluation harness, end to end with memory in RAM and a model that knows the
answers, plus the scoring rules on hand-made records."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from backend.app.llm import Completion, Message
from backend.app.memory import InMemoryBackend
from backend.app.routers.insights import learning_curve
from backend.tests.support import oracle_chat
from evals.harness import Cell, CellRun, Record, Throttled, bank_id
from evals.metrics import compute, rule_action
from evals.report import write_report
from evals.run import main

OUTPUTS = ("metrics.json", "learning_curve.json", "learning_curve.svg", "report.md")


@pytest.fixture(scope="module")
def run_dir(data_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("results")
    argv = ["--conditions", "on,off", "--memory", "ram", "--rpm", "100000", "--out", str(out)]
    return main(argv, chat=oracle_chat(data_dir))


def read(run_dir: Path, name: str) -> Any:
    return json.loads((run_dir / name).read_text(encoding="utf-8"))


# --- AC-09-1 to AC-09-5 -------------------------------------------------------------------


def test_one_command_writes_metrics_and_report(run_dir: Path) -> None:
    """AC-09-1."""
    for name in (*OUTPUTS, "config.json", "suggestions.jsonl", "ground_truth.json"):
        assert (run_dir / name).is_file(), name
    metrics = read(run_dir, "metrics.json")
    assert metrics["conditions"] == ["on", "off"]
    assert metrics["periods"] == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert metrics["suggestions"] == {"on": 37, "off": 37}
    assert "## Targets (SPEC-00)" in (run_dir / "report.md").read_text(encoding="utf-8")


def test_each_condition_gets_a_fresh_bank(run_dir: Path) -> None:
    """AC-09-2."""
    config = read(run_dir, "config.json")
    banks = config["banks"]
    assert banks == {
        "on-r1": bank_id(config["run_id"], "on", 1),
        "off-r1": bank_id(config["run_id"], "off", 1),
    }
    assert len(set(banks.values())) == 2
    assert all(config["run_id"].lower() in b for b in banks.values())


def test_rescoring_saved_results_gives_the_same_files(run_dir: Path) -> None:
    """AC-09-3."""
    before = {name: (run_dir / name).read_bytes() for name in OUTPUTS}
    write_report(run_dir)
    assert {name: (run_dir / name).read_bytes() for name in OUTPUTS} == before


def test_insights_reads_the_learning_curve(run_dir: Path) -> None:
    """AC-09-4."""
    curve, source = learning_curve(run_dir.parent)
    assert source == run_dir.name
    assert [p.period for p in curve] == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert all(p.accuracy_on == 1.0 and p.accuracy_off == 1.0 for p in curve)
    assert curve[0].auto_rate == 0.0
    assert (curve[-1].auto_rate or 0) > 0


def test_scenarios_are_reported_with_the_suggestion_text(run_dir: Path) -> None:
    """AC-09-5. The test model never cites a memory, so S3 must be reported as failed."""
    scenarios = {s["id"]: s for s in read(run_dir, "metrics.json")["scenarios"]}
    assert sorted(scenarios) == ["S1", "S2", "S3", "S4", "S5"]
    for s in scenarios.values():
        assert isinstance(s["pass"], bool)
        assert s["on"]["found"], s["id"]
        assert all(b["reasoning"] for b in s["on"]["suggestions"])
    assert scenarios["S3"]["pass"] is False
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "### S3 Cross-client — Krishna Logistics: ❌ fail" in report


def test_memory_off_never_resolves_automatically(run_dir: Path) -> None:
    metrics = read(run_dir, "metrics.json")
    assert metrics["autonomy"]["off"]["all"]["auto_rate"] == 0.0
    assert metrics["autonomy"]["on"]["all"]["auto_correct"] == 1.0
    assert metrics["safety"]["on"]["unsafe_shown"] == 0
    assert metrics["matcher"] == {"precision": 1.0, "recall": 1.0, "unexpected": [], "missed": []}


# --- Resume and throttling --------------------------------------------------------------------


class FailingAfter:
    """A model that answers `calls` times, then crashes (not an outage the agent absorbs)."""

    def __init__(self, inner: Any, calls: int) -> None:
        self.inner = inner
        self.left = calls

    def complete(self, messages: Sequence[Message]) -> Completion:
        if self.left <= 0:
            raise RuntimeError("process killed")
        self.left -= 1
        completion: Completion = self.inner.complete(messages)
        return completion


def test_a_crashed_run_resumes_where_it_stopped(data_dir: Path, tmp_path: Path) -> None:
    backend = InMemoryBackend()
    saved: dict[tuple[str, str], list[Record]] = {}

    def cell_run(chat: Any) -> CellRun:
        return CellRun(
            cell=Cell("on", 1),
            run_id="t",
            data_dir=data_dir,
            db_path=tmp_path / "on.sqlite",
            backend=backend,
            chat=chat,
            done=set(saved),
        )

    def save(client_id: str, period: str, records: list[Record]) -> None:
        assert (client_id, period) not in saved
        saved[client_id, period] = records

    with pytest.raises(RuntimeError, match="process killed"):
        cell_run(FailingAfter(oracle_chat(data_dir), 12)).execute(save)
    assert 0 < len(saved) < 12
    cell_run(oracle_chat(data_dir)).execute(save)
    assert len(saved) == 12
    assert sum(len(r) for r in saved.values()) == 37


def test_throttle_spaces_calls() -> None:
    now = [0.0]
    slept: list[float] = []

    class Echo:
        def complete(self, messages: Sequence[Message]) -> Completion:
            return Completion("{}", "m", 0, 0)

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    chat = Throttled(Echo(), 30, clock=lambda: now[0], sleep=sleep)
    for _ in range(3):
        chat.complete([])
    assert slept == [2.0, 2.0]


def test_bad_arguments_are_refused() -> None:
    with pytest.raises(SystemExit):
        main(["--conditions", "on,maybe"])
    with pytest.raises(SystemExit):
        main(["--resume", "x", "--memory", "ram"])


# --- Scoring rules ------------------------------------------------------------------------------

KEY_A = "C01:2026-01:36AABCR1234F1ZT:MISSING_IN_2B"
KEY_B = "C01:2026-02:36AABCR1234F1ZT:MISSING_IN_2B"
TRUTH = {
    KEY_A: {"acceptable_actions": ["CHASE_VENDOR"], "root_cause": "UNKNOWN", "flags": []},
    KEY_B: {
        "acceptable_actions": ["DEFER"],
        "root_cause": "LATE_FILING",
        "flags": ["RECURRING_ISSUE"],
    },
}


def rec(key: str, condition: str, action: str, **extra: Any) -> Record:
    client_id, period, gstin, exception_type = key.split(":")
    base: Record = {
        "condition": condition,
        "repeat": 1,
        "group_key": key,
        "client_id": client_id,
        "period": period,
        "vendor_gstin": gstin,
        "exception_type": exception_type,
        "max_diff": "0",
        "action": action,
        "root_cause": "UNKNOWN",
        "flags": [],
        "reasoning": "r",
        "cited": [],
        "guardrails": [],
        "auto_resolved": False,
        "memory_offline": False,
        "model": "m",
        "attempts": 1,
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "latency_ms": 10,
    }
    return base | extra


def test_accuracy_gap_and_flags() -> None:
    records = [
        rec(KEY_A, "on", "CHASE_VENDOR"),
        rec(KEY_B, "on", "DEFER", flags=["RECURRING_ISSUE"], root_cause="LATE_FILING"),
        rec(KEY_A, "off", "CHASE_VENDOR", flags=["RECURRING_ISSUE"]),
        rec(KEY_B, "off", "CHASE_VENDOR", attempts=2),
    ]
    m = compute(records, TRUTH, {})
    assert m["accuracy"]["on"] == {"2026-01": 1.0, "2026-02": 1.0, "all": 1.0}
    assert m["accuracy"]["off"] == {"2026-01": 1.0, "2026-02": 0.0, "all": 0.5}
    assert m["gap"] == {"2026-02": 1.0}
    assert m["flags"]["on"]["RECURRING_ISSUE"] == {
        "tp": 1, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0,
    }  # fmt: skip
    assert m["flags"]["off"]["RECURRING_ISSUE"] == {
        "tp": 0, "fp": 1, "fn": 1, "precision": 0.0, "recall": 0.0,
    }  # fmt: skip
    assert m["root_cause"] == {"on": 1.0, "off": 0.5}
    assert m["json"]["off"]["first_try"] == 0.5


def test_an_unsafe_action_reaching_the_accountant_is_counted() -> None:
    records = [rec(KEY_A, "on", "ACCEPT"), rec(KEY_B, "on", "DEFER", guardrails=["UNSAFE_ACTION"])]
    safety = compute(records, TRUTH, {})["safety"]["on"]
    assert safety["unsafe_shown"] == 1  # INV-1: ACCEPT is never valid for MISSING_IN_2B
    assert safety["raw_unsafe_caught"] == 1


def test_rules_only_baseline() -> None:
    amount = "C01:2026-01:36AAKFL3398P1ZE:AMOUNT_MISMATCH"
    assert rule_action(rec(amount, "on", "x", max_diff="7.00")) == "ACCEPT"
    assert rule_action(rec(amount, "on", "x", max_diff="10.01")) == "CHASE_VENDOR"
    assert rule_action(rec(KEY_B, "on", "x")) == "CHASE_VENDOR"

"""SPEC-06: the learning loop, end to end on the standard dataset with a memory in RAM."""

import random
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

import pytest

from backend.app.domain.entities import GroupKey
from backend.app.domain.enums import Action, DecidedBy, ExceptionType, OutcomeStatus
from backend.app.memory_text import MemoryKind
from backend.app.pipeline import Pipeline, PipelineError, review_date
from backend.app.seed import SeedError, all_periods, load_dataset, seed
from backend.tests.support import ChooserChat, make_pipeline

REDDY, BHAVANI = "36AABCR1234F1ZT", "36AAFFB6621C1ZW"
LAXMI, MUMBAI = "36AAKFL3398P1ZE", "27AACCM8854T1ZF"
MISSING = ExceptionType.MISSING_IN_2B
CLIENTS = ("C01", "C02", "C03")


def levels(pipeline: Pipeline, gstin: str, exception_type: ExceptionType) -> dict[str, set[int]]:
    """Trust levels of a pattern per period, over every client's latest run."""
    rows = pipeline.store.conn.execute(
        "SELECT r.period, t.level FROM trust t JOIN runs r ON r.id = t.run_id"
        " WHERE t.vendor_gstin = ? AND t.exception_type = ?",
        (gstin, exception_type.value),
    )
    found: defaultdict[str, set[int]] = defaultdict(set)
    for row in rows:
        found[row["period"]].add(row["level"])
    return dict(found)


def run_all(pipeline: Pipeline, period: str, *, memory_on: bool = True) -> list[str]:
    """Run every client for a period; returns the auto-resolved group keys."""
    auto: list[str] = []
    for client in CLIENTS:
        auto += pipeline.run(client, period, memory_on=memory_on).summary["auto_resolved"]
    return auto


@pytest.fixture(scope="module")
def april(data_dir: Path) -> Pipeline:
    """January to March seeded with the simulated accountant, then April run for every client."""
    pipeline = make_pipeline(data_dir)
    seed(pipeline, data_dir)
    run_all(pipeline, "2026-04")
    return pipeline


# --- AC-06-1 to AC-06-3: the §5 trajectories ---------------------------------


def test_trust_trajectories_match_the_spec(april: Pipeline) -> None:
    """AC-06-1 (January to March) and the April column of §5."""
    assert levels(april, LAXMI, ExceptionType.AMOUNT_MISMATCH) == {
        "2026-01": {0}, "2026-02": {1}, "2026-03": {2}, "2026-04": {2},
    }  # fmt: skip
    bhavani = levels(april, BHAVANI, MISSING)
    assert bhavani.pop("2026-04") == {2}
    assert bhavani and all(v == {0} for v in bhavani.values())
    reddy = levels(april, REDDY, MISSING)
    assert all(v == {0} for v in reddy.values())
    mumbai = levels(april, MUMBAI, ExceptionType.TAX_HEAD_MISMATCH)
    assert mumbai["2026-03"] == {1} and mumbai["2026-04"] == {1}
    assert all(v == {0} for p, v in mumbai.items() if p < "2026-03")


def test_reddy_drifts_in_april_and_its_deferral_was_wrong(april: Pipeline) -> None:
    """AC-06-2."""
    store = april.store
    assert store.drift_detected(REDDY, "2026-04")
    assert not any(store.drift_detected(REDDY, p) for p in ("2026-01", "2026-02", "2026-03"))
    assert not any(store.drift_detected(BHAVANI, p) for p in all_periods(store))
    reddy = [
        (key, o)
        for key, o in store.outcomes()
        if key.vendor_gstin == REDDY and key.period == "2026-03"
    ]
    assert [(o.status, o.checked_in_period) for _, o in reddy] == [
        (OutcomeStatus.VERIFIED_WRONG, "2026-04")
    ]
    assert reddy[0][1].evidence["due_in"] == "2026-04"
    assert levels(april, REDDY, MISSING)["2026-04"] == {0}
    runs = [store.latest_run(c, "2026-04") for c in CLIENTS]
    assert any(REDDY in r.summary["drift"] for r in runs if r)


def test_bhavani_is_auto_resolved_in_april(april: Pipeline) -> None:
    """AC-06-3."""
    keys = [
        GroupKey.model_validate(k)
        for c in CLIENTS
        if (run := april.store.latest_run(c, "2026-04"))
        for k in run.summary["auto_resolved"]
    ]
    bhavani = [k for k in keys if k.vendor_gstin == BHAVANI]
    assert bhavani
    for key in bhavani:
        decision = april.store.current_decision(key)
        assert decision is not None and decision.decided_by is DecidedBy.AUTO
        assert decision.final_action is Action.DEFER
    assert not [k for k in keys if k.vendor_gstin == REDDY]


def test_every_outcome_and_drift_event_is_retained_once(april: Pipeline) -> None:
    """AC-06-6."""
    conn = april.store.conn

    def retains(kind: MemoryKind) -> int:
        row = conn.execute(
            "SELECT COUNT(*) FROM memory_events WHERE op = 'retain' AND ok = 1 AND kind = ?",
            (kind.value,),
        ).fetchone()
        return int(row[0])

    outcomes = april.store.outcomes()
    assert outcomes and retains(MemoryKind.OUTCOME) == len(outcomes)
    drift_events = conn.execute("SELECT COUNT(*) FROM drift_events").fetchone()[0]
    assert drift_events >= 1 and retains(MemoryKind.DRIFT) == drift_events
    documents = april.memory.backend.banks[april.memory.bank_id]  # type: ignore[attr-defined]
    assert {d for d in documents if d.startswith("outcome:")} == {
        f"outcome:{key}" for key, _ in outcomes
    }
    assert f"drift:{REDDY}:2026-04" in documents
    assert documents[f"drift:{REDDY}:2026-04"].occurred_at.date() == review_date("2026-04")


# --- AC-06-4: only ACCEPT and DEFER are ever automatic -----------------------


def replay(pipeline: Pipeline, periods: Sequence[str]) -> None:
    """Run every period with an accountant who accepts every suggestion."""
    for period in periods:
        for client in CLIENTS:
            run = pipeline.run(client, period)
            for group in pipeline.store.groups(run.id):
                if pipeline.store.current_decision(group.key) is None:
                    action = pipeline.store.suggested_action(group.key)
                    assert action is not None
                    pipeline.decide(group.key, action)


@pytest.mark.parametrize("rng_seed", range(6))
def test_only_accept_or_defer_is_ever_automatic(data_dir: Path, rng_seed: int) -> None:
    rng = random.Random(rng_seed)
    chosen: dict[tuple[str, ExceptionType], Action] = {}

    def choose(key: GroupKey) -> tuple[Action, str, list[str]]:
        pattern = (key.vendor_gstin, key.exception_type)
        action = chosen.setdefault(pattern, rng.choice(list(Action)))
        return action, "UNKNOWN", []

    pipeline = make_pipeline(data_dir, ChooserChat(choose))
    replay(pipeline, all_periods(pipeline.store))
    rows = pipeline.store.conn.execute(
        "SELECT final_action FROM decisions WHERE decided_by = ?", (DecidedBy.AUTO.value,)
    ).fetchall()
    assert {Action(r["final_action"]) for r in rows} <= {Action.ACCEPT, Action.DEFER}


# --- AC-06-5: undo -----------------------------------------------------------


def test_undo_drops_the_pattern_to_observe(data_dir: Path) -> None:
    pipeline = make_pipeline(data_dir)
    seed(pipeline, data_dir)
    key = GroupKey(
        client_id="C01", period="2026-03", vendor_gstin=LAXMI,
        exception_type=ExceptionType.AMOUNT_MISMATCH,
    )  # fmt: skip
    auto = pipeline.store.current_decision(key)
    assert auto is not None and auto.decided_by is DecidedBy.AUTO

    with pytest.raises(PipelineError, match="other than"):
        pipeline.undo(key, auto.final_action)
    undone = pipeline.undo(key, Action.ESCALATE, "Check the rate with the vendor")
    assert undone.decided_by is DecidedBy.ACCOUNTANT and undone.suggested_action is Action.ACCEPT
    with pytest.raises(PipelineError, match="not resolved automatically"):
        pipeline.undo(key, Action.ACCEPT)

    run = pipeline.run("C01", "2026-04")
    assert levels(pipeline, LAXMI, ExceptionType.AMOUNT_MISMATCH)["2026-04"] == {0}
    assert not [k for k in run.summary["auto_resolved"] if LAXMI in k]


def test_undo_in_the_same_period_holds_on_a_rerun(data_dir: Path) -> None:
    pipeline = make_pipeline(data_dir)
    seed(pipeline, data_dir)
    run = pipeline.run("C02", "2026-04")
    (key,) = [GroupKey.model_validate(k) for k in run.summary["auto_resolved"] if BHAVANI in k]
    pipeline.undo(key, Action.CHASE_VENDOR)
    again = pipeline.run("C02", "2026-04")
    # Groups already decided (automatically or not) keep their decision on a re-run.
    assert again.id != run.id and again.summary["auto_resolved"] == []
    assert levels(pipeline, BHAVANI, MISSING)["2026-04"] == {0}
    current = pipeline.store.current_decision(key)
    assert current is not None and current.final_action is Action.CHASE_VENDOR


# --- AC-06-7: memory OFF -----------------------------------------------------


def test_memory_off_never_auto_resolves_but_still_learns(data_dir: Path) -> None:
    pipeline = make_pipeline(data_dir)
    seed(pipeline, data_dir)
    assert run_all(pipeline, "2026-04", memory_on=False) == []
    assert pipeline.store.drift_detected(REDDY, "2026-04")  # still recorded
    rows = pipeline.store.conn.execute(
        "SELECT s.memory_on FROM suggestions s JOIN runs r ON r.id = s.run_id"
        " WHERE r.period = '2026-04'"
    ).fetchall()
    assert rows and not any(r["memory_on"] for r in rows)


def test_memory_off_hides_history_from_the_agent(data_dir: Path) -> None:
    chat = ChooserChat(lambda key: (Action.ESCALATE, "UNKNOWN", []))
    pipeline = make_pipeline(data_dir, chat)
    replay(pipeline, ["2026-01"])
    chat.prompts.clear()
    pipeline.run("C01", "2026-02", memory_on=False)
    assert chat.prompts
    for prompt in chat.prompts:
        assert "MEMORIES: memory is off." in prompt and "TRUST: memory is off" in prompt


# --- Runs --------------------------------------------------------------------


def test_periods_run_in_order(data_dir: Path) -> None:
    pipeline = make_pipeline(data_dir)
    with pytest.raises(PipelineError, match="2026-01 next"):
        pipeline.run("C01", "2026-02")
    with pytest.raises(PipelineError, match="no data"):
        pipeline.run("C01", "2027-01")
    pipeline.run("C01", "2026-01")
    pipeline.run("C01", "2026-02")
    with pytest.raises(PipelineError, match="only the latest"):
        pipeline.run("C01", "2026-01")
    with pytest.raises(PipelineError, match="2026-02 or 2026-03"):
        pipeline.run("C01", "2026-04")


def test_a_rerun_replaces_the_run_and_reopens_its_late_arrivals(data_dir: Path) -> None:
    pipeline = make_pipeline(data_dir)
    replay(pipeline, ["2026-01"])
    first = pipeline.run("C01", "2026-02")
    open_before = len(pipeline.store.open_missing("C01", before="2026-03"))
    again = pipeline.run("C01", "2026-02")
    assert pipeline.store.latest_run("C01", "2026-02") == again
    with pytest.raises(LookupError):
        pipeline.store.run(first.id)
    assert again.summary["late_arrivals"] == first.summary["late_arrivals"]
    assert len(pipeline.store.open_missing("C01", before="2026-03")) == open_before
    assert again.summary["outcomes"] == 0  # already judged on the first run


def test_a_failed_run_is_marked_failed(data_dir: Path) -> None:
    def broken(key: GroupKey) -> tuple[Action, str, list[str]]:
        raise RuntimeError("model exploded")

    pipeline = make_pipeline(data_dir, ChooserChat(broken))
    with pytest.raises(RuntimeError, match="exploded"):
        pipeline.run("C01", "2026-01")
    (row,) = pipeline.store.conn.execute("SELECT status, error FROM runs").fetchall()
    assert row["status"] == "failed" and "exploded" in row["error"]


def test_a_run_reports_its_summary(april: Pipeline) -> None:
    run = april.store.latest_run("C01", "2026-04")
    assert run is not None and run.status == "done"
    assert set(run.summary) == {
        "matched", "exceptions", "groups", "itc_at_risk", "late_arrivals", "outcomes",
        "drift", "auto_resolved", "memory_offline",
    }  # fmt: skip
    assert run.summary["memory_offline"] is False
    assert run.progress == {"step": "resolve", "step_no": 7, "steps": 7}


def test_deciding_an_unknown_group_fails(data_dir: Path) -> None:
    pipeline = make_pipeline(data_dir)
    key = GroupKey(client_id="C01", period="2026-01", vendor_gstin=LAXMI, exception_type=MISSING)
    with pytest.raises(PipelineError, match="no exception group"):
        pipeline.decide(key, Action.ACCEPT)


def test_redeciding_supersedes_the_old_decision(data_dir: Path) -> None:
    pipeline = make_pipeline(data_dir)
    run = pipeline.run("C01", "2026-01")
    key = pipeline.store.groups(run.id)[0].key
    first = pipeline.decide(key, Action.ESCALATE)
    second = pipeline.decide(key, Action.CHASE_VENDOR, "Asked them to file")
    assert first.id != second.id
    assert pipeline.store.current_decision(key) == second
    count = pipeline.store.conn.execute(
        "SELECT COUNT(*) FROM decisions WHERE group_key = ?", (str(key),)
    ).fetchone()[0]
    assert count == 2


def test_drift_is_recorded_once_per_vendor_and_period(april: Pipeline) -> None:
    assert not april.store.add_drift(REDDY, "2026-04", {}, april._clock())


# --- Seeding -----------------------------------------------------------------


def test_the_dataset_loads_once(data_dir: Path) -> None:
    pipeline = make_pipeline(data_dir)
    assert [c.client_id for c in pipeline.store.clients()] == list(CLIENTS)
    assert all_periods(pipeline.store) == ["2026-01", "2026-02", "2026-03", "2026-04"]
    with pytest.raises(SeedError, match="already has data"):
        load_dataset(pipeline.store, data_dir)


def test_seeding_leaves_the_last_period_for_the_demo(data_dir: Path) -> None:
    pipeline = make_pipeline(data_dir)
    runs = seed(pipeline, data_dir)
    assert {r.period for r in runs} == {"2026-01", "2026-02", "2026-03"}
    assert all(r.status == "done" for r in runs)
    undecided = [
        g.key for r in runs for g in pipeline.store.groups(r.id)
        if pipeline.store.current_decision(g.key) is None
    ]  # fmt: skip
    assert undecided == []
    assert pipeline.store.latest_run("C01", "2026-04") is None

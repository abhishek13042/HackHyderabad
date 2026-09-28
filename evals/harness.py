"""Replay the dataset through the real pipeline under one condition (SPEC-09 §2).

Each condition and repeat gets its own SQLite file and a fresh memory bank. Every
client-month runs in order (Jan → Apr, clients in order within a month); the agent
suggests, then the simulated accountant decides with the ground truth, so both
conditions receive identical feedback. The *suggestion* is what gets scored, so
the harness records it before the accountant acts.

Records are plain JSON-ready dicts, one per exception group. The caller saves them
after each client-month, with a checkpoint, so an interrupted run can resume.
"""

import json
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from backend.app.agent import Agent, AgentContext, Suggestion
from backend.app.db import connect, init_db
from backend.app.llm import ChatModel, Completion, Message
from backend.app.matcher import Detail, ExceptionGroup
from backend.app.memory import Memory, MemoryBackend, MemoryRecord, firm_bank
from backend.app.pipeline import Pipeline
from backend.app.seed import (
    accountant_answers,
    all_periods,
    decide_as_accountant,
    load_dataset,
    seed_plan,
)
from backend.app.store import Store

CONDITIONS = ("on", "off")
CITED_TEXT_CHARS = 300
"""Enough of a cited memory to check what it says (scenario S4) without bloating the file."""

Record = dict[str, Any]


class EvalError(RuntimeError):
    """The evaluation cannot give meaningful numbers (e.g. memory is down)."""


def bank_id(run_id: str, condition: str, repeat: int) -> str:
    """A new bank per run, condition and repeat: nothing leaks between them (SPEC-09 §2)."""
    return f"eval-{run_id}-{condition}-r{repeat}".lower()


@dataclass(frozen=True)
class Cell:
    """One condition of one repeat."""

    condition: str
    repeat: int

    @property
    def name(self) -> str:
        return f"{self.condition}-r{self.repeat}"


class RecordingAgent(Agent):
    """The real agent, keeping what it saw and said for the current run."""

    def __init__(self, llm: ChatModel) -> None:
        super().__init__(llm)
        self.seen: list[tuple[ExceptionGroup, AgentContext, Suggestion]] = []

    def suggest_all(self, items: Sequence[tuple[ExceptionGroup, AgentContext]]) -> list[Suggestion]:
        suggestions = super().suggest_all(items)
        self.seen += [(g, c, s) for (g, c), s in zip(items, suggestions, strict=True)]
        return suggestions


class Throttled:
    """Spaces LLM calls to at most `rpm` a minute (Groq's free tier, SPEC-09 §5)."""

    def __init__(
        self,
        chat: ChatModel,
        rpm: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rpm <= 0:
            raise ValueError("rpm must be positive")
        self._chat = chat
        self._gap = 60 / rpm
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next = 0.0

    def complete(self, messages: Sequence[Message]) -> Completion:
        with self._lock:
            now = self._clock()
            slot = max(now, self._next)
            self._next = slot + self._gap
        if slot > now:
            self._sleep(slot - now)
        return self._chat.complete(messages)


@dataclass
class CellRun:
    """What one condition needs to run: its database, memory and model."""

    cell: Cell
    run_id: str
    data_dir: Path
    db_path: Path
    backend: MemoryBackend
    chat: ChatModel
    done: set[tuple[str, str]] = field(default_factory=set)
    """(client, period) runs already recorded, skipped on resume."""

    @property
    def bank(self) -> str:
        return bank_id(self.run_id, self.cell.condition, self.cell.repeat)

    def execute(self, on_month: Callable[[str, str, list[Record]], None]) -> None:
        """Run every client-month not done yet; `on_month(client, period, records)` hears
        about each one after the accountant has decided it."""
        conn = connect(self.db_path)
        try:
            init_db(conn)
            store = Store(conn)
            if not store.has_data():
                load_dataset(store, self.data_dir)
            memory = Memory(self.backend, conn, self.bank)
            if not memory.ensure_bank(firm_bank(self.bank, store.firm().name)):
                raise EvalError(f"memory is unavailable; cannot create bank {self.bank}")
            agent = RecordingAgent(self.chat)
            pipeline = Pipeline(store, memory, agent)
            answers = accountant_answers(self.data_dir)
            memory_on = self.cell.condition == "on"
            for client_id, period in seed_plan(store, all_periods(store)):
                if (client_id, period) in self.done:
                    continue
                agent.seen.clear()
                run = pipeline.run(client_id, period, memory_on=memory_on)
                auto = set(run.summary["auto_resolved"])
                offline = bool(run.summary["memory_offline"])
                records = [
                    record(self.cell, g, c, s, auto=str(g.key) in auto, memory_offline=offline)
                    for g, c, s in agent.seen
                ]
                decide_as_accountant(pipeline, run.id, answers)
                on_month(client_id, period, records)
        finally:
            conn.close()


def record(
    cell: Cell,
    group: ExceptionGroup,
    ctx: AgentContext,
    s: Suggestion,
    *,
    auto: bool,
    memory_offline: bool,
) -> Record:
    """One suggestion with what is needed to score it; labels are joined at report time."""
    key = group.key
    cited = {m.id: m for m in ctx.memories}
    return {
        "condition": cell.condition,
        "repeat": cell.repeat,
        "group_key": str(key),
        "client_id": key.client_id,
        "period": key.period,
        "vendor_gstin": key.vendor_gstin,
        "exception_type": key.exception_type.value,
        "max_diff": str(max((_diff(e.details) for e in group.exceptions), default=Decimal(0))),
        "memory_on": s.memory_on,
        "memories_given": len(ctx.memories),
        "action": s.action.value,
        "root_cause": s.root_cause.value,
        "flags": sorted(f.value for f in s.flags),
        "final_confidence": s.final_confidence,
        "reasoning": s.reasoning,
        "cited": [_cited(cited[i]) for i in s.cited_memory_ids if i in cited],
        "guardrails": [e.rule.value for e in s.guardrail_events],
        "auto_resolved": auto,
        "memory_offline": memory_offline,
        "model": s.model,
        "attempts": s.attempts,
        "prompt_tokens": s.prompt_tokens,
        "completion_tokens": s.completion_tokens,
        "latency_ms": s.latency_ms,
    }


def _diff(details: Any) -> Decimal:
    value = details.get(Detail.AMOUNT_DIFF)
    return abs(Decimal(str(value))) if value is not None else Decimal(0)


def _cited(memory: MemoryRecord) -> dict[str, str | None]:
    return {
        "id": memory.id,
        "client_id": memory.metadata.get("client_id"),
        "text": memory.text[:CITED_TEXT_CHARS],
    }


# --- The records file ----------------------------------------------------------


def append_records(path: Path, records: Iterable[Record]) -> None:
    with path.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def read_records(path: Path) -> list[Record]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]

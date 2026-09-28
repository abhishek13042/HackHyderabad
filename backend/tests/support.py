"""Shared test helpers: a chat model that knows the answers, and a ready pipeline."""

import json
import re
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.agent import MESSAGE_ACTIONS, Agent
from backend.app.db import connect, init_db
from backend.app.domain.entities import GroupKey
from backend.app.domain.enums import Action, Flag
from backend.app.llm import Completion, Message
from backend.app.memory import InMemoryBackend, Memory, firm_bank
from backend.app.pipeline import Pipeline
from backend.app.seed import load_dataset
from backend.app.store import Store

BANK_ID = "munshi-test"
NOW = datetime(2026, 5, 15, 12, tzinfo=UTC)

_CLIENT = re.compile(r"^client: .* \((C\d{2})\) · .* · period: (\w+ \d{4})$", re.MULTILINE)
_VENDOR = re.compile(r"^vendor: .* · GSTIN (\w{15}) ·", re.MULTILINE)
_TYPE = re.compile(r"^type: (\w+) ·", re.MULTILINE)


def group_key_of(prompt: str) -> GroupKey:
    """Read the group back out of the agent's user message (SPEC-05 §6)."""
    client = _CLIENT.search(prompt)
    vendor = _VENDOR.search(prompt)
    exception_type = _TYPE.search(prompt)
    assert client and vendor and exception_type, prompt
    period = datetime.strptime(client.group(2), "%B %Y").replace(tzinfo=UTC).strftime("%Y-%m")
    return GroupKey(
        client_id=client.group(1),
        period=period,
        vendor_gstin=vendor.group(1),
        exception_type=exception_type.group(1),
    )


class ChooserChat:
    """A chat model whose answer is `choose(group_key)`: well-formed, cites nothing."""

    def __init__(self, choose: Callable[[GroupKey], tuple[Action, str, Sequence[str]]]) -> None:
        self.choose = choose
        self.prompts: list[str] = []

    def complete(self, messages: Sequence[Message]) -> Completion:
        prompt = messages[-1].content
        self.prompts.append(prompt)
        action, root_cause, flags = self.choose(group_key_of(prompt))
        answer: dict[str, Any] = {
            "action": action.value,
            "root_cause": root_cause,
            # Cross-client risk needs a citation (G5); this model never cites.
            "flags": [f for f in flags if f != Flag.CROSS_CLIENT_RISK],
            "confidence": 0.9,
            "reasoning": "The listed invoices and amounts support this action.",
            "cited_memory_ids": [],
            "vendor_message": "Please file the listed invoices in GSTR-1."
            if action in MESSAGE_ACTIONS
            else None,
        }
        return Completion(json.dumps(answer), "oracle", prompt_tokens=500, completion_tokens=80)


def oracle_chat(data_dir: Path) -> ChooserChat:
    """Answers the ground truth's best action for every group."""
    truth = {
        e["group_key"]: e
        for e in json.loads((data_dir / "ground_truth.json").read_text(encoding="utf-8"))
    }

    def choose(key: GroupKey) -> tuple[Action, str, Sequence[str]]:
        entry = truth[str(key)]
        return Action(entry["best_action"]), entry["root_cause"], entry["flags"]

    return ChooserChat(choose)


def make_pipeline(data_dir: Path, chat: ChooserChat | None = None) -> Pipeline:
    conn: sqlite3.Connection = connect(":memory:")
    init_db(conn)
    store = Store(conn)
    load_dataset(store, data_dir)
    memory = Memory(InMemoryBackend(), conn, BANK_ID, clock=lambda: NOW)
    memory.ensure_bank(firm_bank(BANK_ID, store.firm().name))
    return Pipeline(store, memory, Agent(chat or oracle_chat(data_dir)), clock=lambda: NOW)

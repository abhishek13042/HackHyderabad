"""What the API shares between requests (SPEC-07).

SQLite connections are per request and per background job; one `Memory` (with
its own connection, lock and caches) is shared, so a reflect cached by one
request serves the next. One run or seed job works at a time: the work lock is
taken by the request that starts the job and released when the job ends.
"""

import json
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.app.agent import Agent
from backend.app.config import Settings
from backend.app.db import connect, init_db
from backend.app.llm import ChatModel, GroqChat
from backend.app.memory import (
    BankProfile,
    HindsightBackend,
    Memory,
    MemoryBackend,
    firm_bank,
    utc_now,
)
from backend.app.pipeline import Pipeline
from backend.app.seed import FIRM_FILE
from backend.app.store import Store

STALE_RUN_ERROR = "the server restarted before this run finished"
DEFAULT_FIRM_NAME = "the firm"


@dataclass
class Job:
    """A background seed job, polled by the UI."""

    id: str
    kind: str
    status: str = "running"
    done: int = 0
    total: int = 0
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Session:
    store: Store
    pipeline: Pipeline


class Services:
    def __init__(
        self,
        *,
        db_path: Path,
        data_dir: Path,
        results_dir: Path,
        bank_id: str,
        memory_backend: MemoryBackend,
        chat: ChatModel,
        llm_configured: bool,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.db_path = db_path
        self.data_dir = data_dir
        self.results_dir = results_dir
        self.bank_id = bank_id
        self.llm_configured = llm_configured
        self.clock = clock
        self.agent = Agent(chat)
        self._memory_conn = self.connect()
        self.memory = Memory(memory_backend, self._memory_conn, bank_id, clock=clock)
        self.work = threading.Lock()
        self.jobs: dict[str, Job] = {}

    @classmethod
    def from_settings(cls, settings: Settings) -> "Services":
        return cls(
            db_path=settings.resolve(settings.db_path),
            data_dir=settings.resolve(settings.data_dir),
            results_dir=settings.resolve(Path("evals/results")),
            bank_id=settings.hindsight_bank_id,
            memory_backend=HindsightBackend.from_settings(settings),
            chat=GroqChat.from_settings(settings),
            llm_configured=bool(settings.groq_api_key.get_secret_value()),
        )

    def connect(self) -> sqlite3.Connection:
        conn = connect(self.db_path)
        init_db(conn)
        return conn

    @contextmanager
    def session(self) -> Iterator[Session]:
        conn = self.connect()
        try:
            store = Store(conn)
            yield Session(store, Pipeline(store, self.memory, self.agent, clock=self.clock))
        finally:
            conn.close()

    # --- Startup ---

    def start(self) -> None:
        """Runs cut off by a restart are failed; the bank is created if needed."""
        with self.session() as s:
            s.store.fail_stale_runs(STALE_RUN_ERROR, self.clock())
            profile = self.bank_profile(s.store)
        if self.memory.ensure_bank(profile):
            self.memory.replay_queue()

    def bank_profile(self, store: Store) -> BankProfile:
        return firm_bank(self.bank_id, self.firm_name(store))

    def firm_name(self, store: Store) -> str:
        """From the database, else the generated dataset, so a fresh bank gets the right name."""
        if store.has_data():
            return store.firm().name
        firm_file = self.data_dir / FIRM_FILE
        if firm_file.is_file():
            name: str = json.loads(firm_file.read_text(encoding="utf-8"))["firm"]["name"]
            return name
        return DEFAULT_FIRM_NAME

    # --- Jobs ---

    def new_job(self, kind: str) -> Job:
        job = Job(id=f"job_{uuid.uuid4().hex[:12]}", kind=kind)
        self.jobs[job.id] = job
        return job

    def close(self) -> None:
        self._memory_conn.close()

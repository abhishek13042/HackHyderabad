"""Run the evaluation and write its report (SPEC-09 §2, AC-09-1).

    python -m evals.run --conditions on,off --seed 42 --repeats 1 --out evals/results/
    python -m evals.run --resume <run_id>               # continue an interrupted run

The dataset is regenerated from `--seed` into the run's `work/` folder, so a run
never depends on (or changes) the app's own database or `data/generated`. Needs
Hindsight and GROQ_API_KEY from `.env`; `--memory ram` swaps Hindsight for the
in-process memory used by the tests (a quick offline check of the harness).
"""

import argparse
import importlib.metadata
import shutil
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.config import PROJECT_ROOT, Settings
from backend.app.llm import ChatModel, GroqChat
from backend.app.memory import HindsightBackend, InMemoryBackend, MemoryBackend
from backend.datagen.build import build_dataset
from backend.datagen.write import write_dataset
from evals.harness import CONDITIONS, Cell, CellRun, Record, Throttled, append_records, bank_id
from evals.report import (
    CONFIG_FILE,
    LABELS_FILE,
    RECORDS_FILE,
    REPORT_FILE,
    VENDORS_FILE,
    read_json,
    write_json,
    write_report,
)

PROGRESS_FILE = "progress.json"
WORK_DIR = "work"
"""Databases and the regenerated dataset: large, rebuilt from the seed, not committed."""
DEFAULT_RPM = 30


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m evals.run",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--conditions", default="on,off", help="comma-separated: on, off")
    parser.add_argument("--seed", type=int, default=42, help="dataset seed (default 42)")
    parser.add_argument("--repeats", type=int, default=1, help="use 3 for final numbers")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "evals" / "results")
    parser.add_argument("--rpm", type=int, default=DEFAULT_RPM, help="LLM calls per minute")
    parser.add_argument("--memory", choices=("hindsight", "ram"), default="hindsight")
    parser.add_argument("--resume", metavar="RUN_ID", help="continue this run")
    args = parser.parse_args(argv)
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    if not conditions or any(c not in CONDITIONS for c in conditions):
        parser.error(f"--conditions takes a list of {', '.join(CONDITIONS)}")
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.resume and args.memory == "ram":
        parser.error("a run with --memory ram cannot resume: its memory died with it")
    args.conditions = conditions
    return args


def main(argv: Sequence[str] | None = None, *, chat: ChatModel | None = None) -> Path:
    """Returns the run's folder. `chat` replaces Groq (tests)."""
    args = parse_args(argv)
    settings = Settings()
    run_dir: Path
    if args.resume:
        run_dir = args.out / args.resume
        config = read_json(run_dir / CONFIG_FILE)
    else:
        run_dir, config = start(args, settings)
    if chat is None:
        if not settings.groq_api_key.get_secret_value():
            print("warning: GROQ_API_KEY is not set, so every suggestion will escalate")
        chat = GroqChat.from_settings(settings)
    shared: MemoryBackend | None = (
        HindsightBackend.from_settings(settings) if config["memory"] == "hindsight" else None
    )
    checkpoint = Checkpoint(run_dir)
    throttled = Throttled(chat, config["rpm"])
    for repeat in range(1, config["repeats"] + 1):
        for condition in config["conditions"]:
            cell = Cell(condition, repeat)
            CellRun(
                cell=cell,
                run_id=config["run_id"],
                data_dir=run_dir / WORK_DIR / "data",
                db_path=run_dir / WORK_DIR / f"{cell.name}.sqlite",
                backend=shared or InMemoryBackend(),
                chat=throttled,
                done=checkpoint.done(cell),
            ).execute(checkpoint.saver(cell))

    write_report(run_dir)
    print(f"wrote {run_dir / REPORT_FILE}")
    return run_dir


class Checkpoint:
    """Records and progress, saved after every client-month so `--resume` can pick up."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        path = run_dir / PROGRESS_FILE
        self.progress: dict[str, list[str]] = read_json(path) if path.is_file() else {}

    def done(self, cell: Cell) -> set[tuple[str, str]]:
        return {_month(d) for d in self.progress.get(cell.name, [])}

    def saver(self, cell: Cell) -> Callable[[str, str, list[Record]], None]:
        def save(client_id: str, period: str, records: list[Record]) -> None:
            append_records(self.run_dir / RECORDS_FILE, records)
            self.progress.setdefault(cell.name, []).append(f"{client_id}:{period}")
            write_json(self.run_dir / PROGRESS_FILE, self.progress)
            print(f"[{cell.name}] {client_id} {period}: {len(records)} groups", flush=True)

        return save


def _month(done: str) -> tuple[str, str]:
    client_id, period = done.split(":")
    return client_id, period


def start(args: argparse.Namespace, settings: Settings) -> tuple[Path, dict[str, Any]]:
    """A new run folder: the dataset from the seed, its labels, and config.json."""
    now = datetime.now(UTC)
    run_id = f"{now:%Y%m%d-%H%M%S}-s{args.seed}"
    run_dir = args.out / run_id
    data_dir = run_dir / WORK_DIR / "data"
    data_dir.mkdir(parents=True)
    write_dataset(build_dataset(args.seed), data_dir)
    for name in (LABELS_FILE, VENDORS_FILE):
        shutil.copyfile(data_dir / name, run_dir / name)
    config = {
        "run_id": run_id,
        "created_at": now.isoformat(timespec="seconds"),
        "seed": args.seed,
        "conditions": args.conditions,
        "repeats": args.repeats,
        "rpm": args.rpm,
        "memory": args.memory,
        "banks": {
            Cell(c, r).name: bank_id(run_id, c, r)
            for r in range(1, args.repeats + 1)
            for c in args.conditions
        },
        "models": [settings.groq_model, settings.groq_fallback_model],
        "llm_configured": bool(settings.groq_api_key.get_secret_value()),
        "hindsight_url": settings.hindsight_base_url if args.memory == "hindsight" else None,
        "hindsight_client": importlib.metadata.version("hindsight-client"),
        "git_sha": git_sha(),
    }
    write_json(run_dir / CONFIG_FILE, config)
    return run_dir, config


def git_sha() -> str | None:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True,
            check=True, timeout=10,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None


if __name__ == "__main__":
    main()

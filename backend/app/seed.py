"""Load the generated dataset and replay history through the learning loop (SPEC-06 §2).

Seeding runs each period in order (clients in order within a period) and has a
simulated accountant decide every group the way the dataset's ground truth
says they did, with their note. The last period is left for the live demo.

Reads only the files in `data/generated` (SPEC-02 §3); the generator itself is
never imported by the app.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from backend.app.domain.entities import Client, Firm, Vendor
from backend.app.domain.enums import Action
from backend.app.ingest import read_gstr2b, read_purchase_register
from backend.app.pipeline import Pipeline
from backend.app.store import RunRow, Store

FIRM_FILE = "firm.json"
VENDORS_FILE = "vendors.json"
GROUND_TRUTH_FILE = "ground_truth.json"
PURCHASE_REGISTER_FILE = "purchase_register.csv"
GSTR2B_FILE = "gstr2b.json"
VENDOR_FIELDS = ("gstin", "name", "registration_status")
"""vendors.json also carries the planted archetype; it is never loaded."""


class SeedError(RuntimeError):
    """The dataset is missing, already loaded, or doesn't cover a group."""


def load_dataset(store: Store, data_dir: Path) -> None:
    """Firm, clients, vendors and every client-period's uploaded files."""
    if store.has_data():
        raise SeedError("the database already has data; reset it first")
    if not (data_dir / FIRM_FILE).is_file():
        raise SeedError(f"no dataset in {data_dir}; run `python -m backend.datagen` first")
    firm_file = json.loads((data_dir / FIRM_FILE).read_text(encoding="utf-8"))
    clients = [Client.model_validate(c) for c in firm_file["clients"]]
    store.add_firm(Firm.model_validate(firm_file["firm"]), clients)
    vendors = json.loads((data_dir / VENDORS_FILE).read_text(encoding="utf-8"))
    store.add_vendors(Vendor(**{f: v[f] for f in VENDOR_FIELDS}) for v in vendors)
    for client in clients:
        for folder in sorted(p for p in (data_dir / client.client_id).iterdir() if p.is_dir()):
            period = folder.name
            books = (folder / PURCHASE_REGISTER_FILE).read_text(encoding="utf-8")
            store.add_books(read_purchase_register(books, client, period))
            gstr2b = (folder / GSTR2B_FILE).read_bytes()
            store.add_twob(read_gstr2b(gstr2b, client, period))


@dataclass(frozen=True)
class AccountantAnswer:
    action: Action
    note: str | None


def accountant_answers(data_dir: Path) -> dict[str, AccountantAnswer]:
    """What the accountant decided for each group key, from the dataset's ground truth."""
    entries = json.loads((data_dir / GROUND_TRUTH_FILE).read_text(encoding="utf-8"))
    return {
        e["group_key"]: AccountantAnswer(Action(e["accountant_action"]), e["accountant_note"])
        for e in entries
    }


def decide_as_accountant(
    pipeline: Pipeline, run_id: str, answers: dict[str, AccountantAnswer]
) -> None:
    """Decide every group of a run as the ground truth says; an automatic decision the
    accountant disagrees with is undone."""
    store = pipeline.store
    for group in store.groups(run_id):
        answer = answers.get(str(group.key))
        if answer is None:
            raise SeedError(f"ground truth has no decision for {group.key}")
        current = store.current_decision(group.key)
        if current is None:
            pipeline.decide(group.key, answer.action, answer.note)
        elif current.final_action is not answer.action:
            pipeline.undo(group.key, answer.action, answer.note)


def all_periods(store: Store) -> list[str]:
    return sorted({p for client in store.clients() for p in store.periods(client.client_id)})


def seed_plan(store: Store, periods: Sequence[str] | None = None) -> list[tuple[str, str]]:
    """The (client, period) runs seeding makes: `periods` (default: all but the last) in
    order, clients in order within a period."""
    if periods is None:
        periods = all_periods(store)[:-1]
    return [
        (client.client_id, period)
        for period in periods
        for client in store.clients()
        if period in store.periods(client.client_id)
    ]


def seed(
    pipeline: Pipeline,
    data_dir: Path,
    periods: Sequence[str] | None = None,
    *,
    on_run: Callable[[RunRow], None] | None = None,
) -> list[RunRow]:
    """Run and decide the `seed_plan` with memory ON. `on_run` hears about each finished run."""
    store = pipeline.store
    answers = accountant_answers(data_dir)
    runs = []
    for client_id, period in seed_plan(store, periods):
        run = pipeline.run(client_id, period, memory_on=True)
        decide_as_accountant(pipeline, run.id, answers)
        runs.append(store.run(run.id))
        if on_run is not None:
            on_run(runs[-1])
    return runs

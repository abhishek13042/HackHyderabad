"""Write a dataset to disk in the layout of SPEC-02 §3.

All text is UTF-8 with LF line endings, so the same seed produces byte-identical
files on every OS (AC-02-1).
"""

import json
from pathlib import Path
from typing import Any

from backend.app.ingest import write_gstr2b, write_purchase_register
from backend.datagen.build import Dataset

PURCHASE_REGISTER_FILE = "purchase_register.csv"
GSTR2B_FILE = "gstr2b.json"


def write_dataset(dataset: Dataset, out: Path) -> list[Path]:
    """Write every file and return their paths, in the order written."""
    written = [
        _write(out / "firm.json", _json(_firm(dataset))),
        _write(out / "vendors.json", _json(_vendors(dataset))),
        _write(
            out / "ground_truth.json",
            _json([entry.model_dump(mode="json") for entry in dataset.ground_truth]),
        ),
    ]
    clients = {client.client_id: client for client in dataset.clients}
    for (client_id, period), books in dataset.books.items():
        folder = out / client_id / period
        written.append(_write(folder / PURCHASE_REGISTER_FILE, write_purchase_register(books)))
        gstr2b = write_gstr2b(
            clients[client_id],
            period,
            dataset.twob_generated_on(period),
            dataset.twob[(client_id, period)],
        )
        written.append(_write(folder / GSTR2B_FILE, gstr2b))
    return written


def _firm(dataset: Dataset) -> dict[str, Any]:
    return {
        "firm": dataset.firm.model_dump(mode="json"),
        "clients": [client.model_dump(mode="json") for client in dataset.clients],
    }


def _vendors(dataset: Dataset) -> list[dict[str, Any]]:
    """Includes the archetype: for evals and humans only, never loaded by the app."""
    return [
        {
            "gstin": vendor.gstin,
            "name": vendor.name,
            "state": vendor.state,
            "registration_status": "CANCELLED" if vendor.cancelled_from else "ACTIVE",
            "cancelled_from": vendor.cancelled_from,
            "archetype": vendor.archetype,
            "clients": list(vendor.client_ids),
        }
        for vendor in dataset.vendors
    ]


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path

"""Generate the demo and eval dataset (SPEC-02).

python -m backend.scripts.generate_data --seed 42 --out data/generated
"""

import argparse
from collections import Counter
from pathlib import Path

from backend.app.config import PROJECT_ROOT
from backend.datagen.build import build_dataset
from backend.datagen.write import write_dataset

DEFAULT_SEED = 42
DEFAULT_OUT = Path("data/generated")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    out: Path = args.out if args.out.is_absolute() else PROJECT_ROOT / args.out
    dataset = build_dataset(args.seed)
    files = write_dataset(dataset, out)

    books = sum(len(rows) for rows in dataset.books.values())
    twob = sum(len(rows) for rows in dataset.twob.values())
    by_type = Counter(entry.group_key.exception_type.value for entry in dataset.ground_truth)
    print(f"Wrote {len(files)} files to {out}")
    print(f"  {books} book invoices, {twob} GSTR-2B entries, {len(dataset.bills)} bills")
    print(f"  {len(dataset.ground_truth)} exception groups:")
    for exception_type, count in sorted(by_type.items()):
        print(f"    {exception_type:<18} {count}")


if __name__ == "__main__":
    main()

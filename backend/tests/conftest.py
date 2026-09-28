from pathlib import Path

import pytest

from backend.datagen.build import build_dataset
from backend.datagen.write import write_dataset


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The standard dataset (seed 42) written to disk, as the app reads it."""
    out = tmp_path_factory.mktemp("generated")
    write_dataset(build_dataset(42), out)
    return out

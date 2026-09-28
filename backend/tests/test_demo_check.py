"""SPEC-10 AC-10-1: the demo rehearsal, twice from reset, over the in-process API."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.memory import InMemoryBackend
from backend.scripts.demo_check import Http, main
from backend.tests.test_api import make_services


def in_process(client: TestClient) -> Http:
    def call(method: str, path: str, body: Any) -> tuple[int, Any]:
        response = client.request(method, f"/api{path}", json=body)
        return response.status_code, response.json()

    return call


def test_the_demo_runs_twice_from_reset(
    tmp_path: Path, data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = InMemoryBackend()
    with TestClient(create_app(make_services(tmp_path, data_dir, backend=backend))) as client:
        assert main(["--yes"], http=in_process(client)) == 0
        # The test model never cites memories, so G5 removes the cross-client flag.
        assert main(["--yes", "--rounds", "1", "--strict"], http=in_process(client)) == 2
    out = capsys.readouterr().out
    assert out.count("--- round") == 3
    for beat in ("Bhavani auto-deferred", "Laxmi auto-accepted", "Reddy drift", "memory OFF"):
        assert f"✓ {beat}" in out
    assert "✗ Krishna cross-client warning" in out
    assert "FAILED" not in out


def test_it_will_not_wipe_without_consent() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_an_unreachable_server_fails_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--yes", "--base-url", "http://127.0.0.1:9"]) == 1
    assert "cannot reach" in capsys.readouterr().out

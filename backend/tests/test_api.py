"""SPEC-07: the HTTP API over a file database, a memory in RAM and a chat model that knows
the answers. Background tasks finish before TestClient returns, so runs are done when polled."""

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.llm import ChatModel, GroqChat
from backend.app.main import create_app
from backend.app.memory import InMemoryBackend
from backend.app.services import Services
from backend.tests.support import BANK_ID, oracle_chat

REDDY, BHAVANI, LAXMI = "36AABCR1234F1ZT", "36AAFFB6621C1ZW", "36AAKFL3398P1ZE"
NOT_MONEY = {"final_confidence", "accuracy_on", "accuracy_off", "auto_rate"}
"""The only keys whose values may be JSON floats (scores and rates, AC-07-2)."""


def make_services(
    root: Path, data_dir: Path, *, chat: ChatModel | None = None, backend: InMemoryBackend | None
) -> Services:
    return Services(
        db_path=root / "munshi.db",
        data_dir=data_dir,
        results_dir=root / "results",
        bank_id=BANK_ID,
        memory_backend=backend or InMemoryBackend(),
        chat=chat or oracle_chat(data_dir),
        llm_configured=True,
    )


class Api:
    """A TestClient that remembers every JSON body it received, for the money check."""

    def __init__(self, client: TestClient, backend: InMemoryBackend) -> None:
        self.client = client
        self.backend = backend
        self.bodies: list[Any] = []

    def call(self, method: str, path: str, expect: int = 200, **kwargs: Any) -> Any:
        response = self.client.request(method, f"/api{path}", **kwargs)
        assert response.status_code == expect, response.text
        body = response.json()
        self.bodies.append(body)
        return body

    def get(self, path: str, expect: int = 200, **kwargs: Any) -> Any:
        return self.call("GET", path, expect, **kwargs)

    def post(self, path: str, expect: int = 200, **kwargs: Any) -> Any:
        return self.call("POST", path, expect, **kwargs)

    def error(self, method: str, path: str, expect: int, **kwargs: Any) -> str:
        body = self.call(method, path, expect, **kwargs)
        assert set(body) == {"error"} and set(body["error"]) == {"code", "message"}
        code: str = body["error"]["code"]
        return code


def open_api(root: Path, data_dir: Path) -> Iterator[Api]:
    backend = InMemoryBackend()
    with TestClient(create_app(make_services(root, data_dir, backend=backend))) as client:
        yield Api(client, backend)


@pytest.fixture
def fresh(tmp_path: Path, data_dir: Path) -> Iterator[Api]:
    yield from open_api(tmp_path, data_dir)


@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory, data_dir: Path) -> Iterator[Api]:
    """Seeded (January to March), then April run for C01 and C02."""
    for api in open_api(tmp_path_factory.mktemp("api"), data_dir):
        job = api.post("/demo/seed", 202)
        assert api.get(f"/demo/jobs/{job['job_id']}")["status"] == "done"
        for client in ("C01", "C02"):
            run_id = api.post(f"/reconciliations/{client}/2026-04/run", 202)["run_id"]
            assert api.get(f"/runs/{run_id}")["status"] == "done"
        yield api


def april(api: Api, client: str = "C01") -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = api.get(f"/reconciliations/{client}/2026-04/groups")
    return groups


def find(groups: list[dict[str, Any]], gstin: str, exception_type: str) -> dict[str, Any]:
    return next(g for g in groups if g["vendor"]["gstin"] == gstin and g["type"] == exception_type)


# --- System and reference data -----------------------------------------------


def test_health_before_seeding(fresh: Api) -> None:
    assert fresh.get("/health") == {
        "ok": True,
        "db": "up",
        "seeded": False,
        "hindsight": "up",
        "llm": "up",
        "bank_id": BANK_ID,
        "firm": "Rao & Associates",
        "pending_retains": 0,
    }
    assert fresh.get("/clients") == []


def test_health_notices_hindsight_coming_back(fresh: Api) -> None:
    fresh.backend.available = False
    assert fresh.get("/memory/recall", params={"q": "Reddy"}, expect=503)["error"]["code"] == (
        "MEMORY_OFFLINE"
    )
    assert fresh.get("/health")["hindsight"] == "down"
    fresh.backend.available = True
    assert fresh.get("/health")["hindsight"] == "up"


def test_clients_and_periods(api: Api) -> None:
    clients = api.get("/clients")
    assert [c["id"] for c in clients] == ["C01", "C02", "C03"]
    assert set(clients[0]) == {"id", "name", "gstin", "business"}
    periods = {p["period"]: p for p in api.get("/periods", params={"client_id": "C01"})}
    assert list(periods) == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert all(p["has_books"] and p["has_2b"] for p in periods.values())
    assert periods["2026-03"]["run_status"] == "done" and periods["2026-03"]["open_groups"] == 0
    assert api.error("GET", "/periods", 404, params={"client_id": "C09"}) == "NOT_FOUND"
    assert api.error("GET", "/periods", 422) == "VALIDATION_ERROR"


def test_unknown_route_uses_the_envelope(fresh: Api) -> None:
    assert fresh.error("GET", "/nothing-here", 404) == "NOT_FOUND"


# --- Runs and groups ---------------------------------------------------------


def test_run_status_and_summary(api: Api) -> None:
    periods = {p["period"]: p for p in api.get("/periods", params={"client_id": "C01"})}
    run = api.get(f"/runs/{periods['2026-04']['run_id']}")
    assert run["status"] == "done" and run["memory_on"] is True and run["error"] is None
    assert run["progress"] == {"step": "resolve", "done": 7, "total": 7}
    summary = run["summary"]
    assert summary["groups"] == len(april(api))
    assert summary["flags"]["PATTERN_DRIFT"] >= 1
    assert isinstance(summary["itc_at_risk"], str) and summary["memory_degraded"] is False
    assert summary["auto_resolved"] == len(summary["auto_resolved_keys"])
    assert api.error("GET", "/runs/run_missing", 404) == "NOT_FOUND"


def test_reddy_shows_pattern_drift_in_april(api: Api) -> None:
    """AC-07-5."""
    reddy = [g for c in ("C01", "C02") for g in april(api, c) if g["vendor"]["gstin"] == REDDY]
    assert reddy, "Reddy Steels has an April group"
    drifting = [g for g in reddy if "PATTERN_DRIFT" in g["suggestion"]["flags"]]
    assert drifting and all(g["suggestion"]["action"] != "DEFER" for g in drifting)
    assert all(g["trust"]["level"] == 0 and g["trust"]["name"] == "OBSERVE" for g in drifting)
    assert drifting[0]["vendor"]["name"] == "Reddy Steels"


def test_groups_are_sorted_and_fully_described(api: Api) -> None:
    groups = april(api)
    risks = [float(g["itc_at_risk"]) for g in groups]
    assert risks == sorted(risks, reverse=True)
    for g in groups:
        assert g["invoices"] and g["suggestion"]["confidence_label"] in {"HIGH", "MEDIUM", "LOW"}
        assert g["suggestion"]["action"] in g["allowed_actions"]
        label = g["suggestion"]["confidence_label"]
        confidence = g["suggestion"]["final_confidence"]
        assert label == ("HIGH" if confidence >= 0.8 else "MEDIUM" if confidence >= 0.5 else "LOW")


def test_run_errors(api: Api, fresh: Api) -> None:
    assert api.error("POST", "/reconciliations/C09/2026-04/run", 404) == "NOT_FOUND"
    assert api.error("POST", "/reconciliations/C01/2027-01/run", 404) == "NOT_FOUND"
    # Periods run in order: C01 has run April, so February is history.
    assert api.error("POST", "/reconciliations/C01/2026-02/run", 409) == "CONFLICT"
    assert api.error("POST", "/reconciliations/C01/2026-04/run?memory=maybe", 422)
    assert api.error("GET", "/reconciliations/C03/2026-04/groups", 404) == "NOT_FOUND"
    assert fresh.error("POST", "/reconciliations/C01/2026-01/run", 404) == "NOT_FOUND"


def test_a_busy_worker_refuses_a_second_job(api: Api) -> None:
    services: Services = api.client.app.state.services  # type: ignore[attr-defined]
    with services.work:
        assert api.error("POST", "/reconciliations/C03/2026-04/run", 409) == "CONFLICT"
        assert api.error("POST", "/demo/reset", 409, json={"confirm": "RESET"}) == "CONFLICT"
    assert api.get("/clients")  # nothing was reset


# --- Decisions ---------------------------------------------------------------


def test_override_needs_a_note(api: Api) -> None:
    """AC-07-3."""
    group = find(april(api), REDDY, "MISSING_IN_2B")
    other = next(a for a in group["allowed_actions"] if a != group["suggestion"]["action"])
    path = f"/exceptions/{group['group_key']}/decision"
    for note in (None, "   "):
        assert api.error("POST", path, 422, json={"action": other, "note": note})
    decided = api.post(path, json={"action": other, "note": "Third month late. Holding GST."})
    assert decided["accepted_suggestion"] is False and decided["decided_by"] == "ACCOUNTANT"
    assert decided["note"] == "Third month late. Holding GST."


def test_disallowed_action_is_rejected(api: Api) -> None:
    """AC-07-4: ACCEPT would claim credit that is not in GSTR-2B."""
    group = find(april(api), REDDY, "MISSING_IN_2B")
    path = f"/exceptions/{group['group_key']}/decision"
    body = {"action": "ACCEPT", "note": "just accept it"}
    assert api.error("POST", path, 422, json=body) == "VALIDATION_ERROR"
    assert api.error("POST", path, 422, json={"action": "PAY_LATER"}) == "VALIDATION_ERROR"


def test_accepting_the_suggestion_needs_no_note_and_redeciding_replaces(api: Api) -> None:
    group = next(g for g in april(api) if g["decision"] is None)
    path = f"/exceptions/{group['group_key']}/decision"
    first = api.post(path, json={"action": group["suggestion"]["action"]})
    assert first["accepted_suggestion"] is True and first["note"] is None
    again = api.post(path, json={"action": group["suggestion"]["action"], "note": "confirmed"})
    assert again["id"] != first["id"]
    current = next(g for g in april(api) if g["group_key"] == group["group_key"])
    assert current["decision"]["id"] == again["id"]


def test_decision_errors(api: Api) -> None:
    missing = f"C01:2026-04:{REDDY}:AMOUNT_MISMATCH"
    assert api.error("POST", f"/exceptions/{missing}/decision", 404, json={"action": "ACCEPT"})
    assert api.error("POST", "/exceptions/not-a-key/decision", 422, json={"action": "ACCEPT"})


def test_undo_an_automatic_decision(api: Api) -> None:
    auto = [g for g in april(api, "C02") if g["decision"] and g["decision"]["decided_by"] == "AUTO"]
    assert auto, "something was auto-resolved in April"
    group = auto[0]
    action = group["decision"]["action"]
    other = next(a for a in group["allowed_actions"] if a not in {action, "ESCALATE"})
    path = f"/exceptions/{group['group_key']}/undo"
    assert api.error("POST", path, 422, json={"action": other}) == "VALIDATION_ERROR"
    assert api.error("POST", path, 422, json={"action": action, "note": "no"})
    undone = api.post(path, json={"action": other, "note": "Vendor confirmed a credit note."})
    assert undone["decided_by"] == "ACCOUNTANT" and undone["action"] == other
    assert api.error("POST", path, 409, json={"action": action, "note": "again"}) == "CONFLICT"


# --- Memory, trust, insights -------------------------------------------------


def test_vendor_page(api: Api) -> None:
    reddy = api.get(f"/vendors/{REDDY}")
    assert reddy["name"] == "Reddy Steels" and reddy["known"] is True
    assert [e["period"] for e in reddy["drift_events"]] == ["2026-04"]
    wrong = [h for h in reddy["history"] if h["outcome"] and h["period"] == "2026-03"]
    assert wrong and wrong[0]["outcome"]["status"] == "VERIFIED_WRONG"
    assert reddy["profile"] and {t["type"] for t in reddy["trust"]} >= {"MISSING_IN_2B"}
    assert api.error("GET", "/vendors/36AAAAA0000A1Z5", 404) == "NOT_FOUND"


def test_trust_table(api: Api) -> None:
    patterns = api.get("/trust")
    laxmi = next(
        p for p in patterns if p["vendor"]["gstin"] == LAXMI and p["type"] == "AMOUNT_MISMATCH"
    )
    assert (laxmi["level"], laxmi["name"], laxmi["streak_action"]) == (2, "AUTO", "ACCEPT")
    bhavani = next(p for p in patterns if p["vendor"]["gstin"] == BHAVANI)
    assert bhavani["name"] == "AUTO" and bhavani["period"] == "2026-04"


def test_insights(api: Api) -> None:
    services: Services = api.client.app.state.services  # type: ignore[attr-defined]
    out = api.get("/insights", params={"period": "2026-04"})
    assert out["summary"] and out["memory_offline"] is False
    assert out["learning_curve"] == [] and out["learning_curve_source"] is None
    stats = out["stats"]
    assert stats["period"] == "2026-04" and stats["runs"] == 2 and stats["drift_events"] == 1
    assert stats["auto_resolved"] >= 1 and isinstance(stats["itc_at_risk"], str)
    suggestions = [
        g["suggestion"]
        for client in ("C01", "C02")
        for g in api.get(f"/reconciliations/{client}/2026-04/groups")
        if g["suggestion"]
    ]
    assert stats["guardrails_applied"] == sum(len(s["guardrail_events"]) for s in suggestions)
    assert stats["cross_client_warnings"] == sum(
        "CROSS_CLIENT_RISK" in s["flags"] for s in suggestions
    )

    run_dir = services.results_dir / "20260928-120000-seed42"
    run_dir.mkdir(parents=True)
    point = {"period": "2026-04", "accuracy_on": 0.9, "accuracy_off": 0.6, "auto_rate": 0.3}
    (run_dir / "learning_curve.json").write_text(json.dumps([point]), encoding="utf-8")
    out = api.get("/insights")
    assert out["learning_curve"] == [point]
    assert out["learning_curve_source"] == run_dir.name and out["stats"]["period"] == "2026-04"
    assert api.error("GET", "/insights", 422, params={"period": "April"}) == "VALIDATION_ERROR"


def test_memory_events_and_recall(api: Api) -> None:
    events = api.get("/memory/events", params={"limit": 5})
    assert len(events) == 5 and all(isinstance(e["ok"], bool) for e in events)
    later = api.get("/memory/events", params={"since": events[-1]["id"], "limit": 5})
    assert later[0]["id"] > events[-1]["id"]
    assert api.error("GET", "/memory/events", 422, params={"limit": 0})
    newest = api.get("/memory/events", params={"limit": 3, "latest": True})
    assert [e["id"] for e in newest] == sorted(e["id"] for e in newest)
    assert newest[-1]["id"] == max(
        e["id"] for e in api.get("/memory/events", params={"limit": 500})
    )
    recalled = api.get("/memory/recall", params={"q": "Reddy Steels late filing"})
    assert recalled["memories"] and all(m["id"] and m["text"] for m in recalled["memories"])
    assert api.error("GET", "/memory/recall", 422)


# --- Uploads -----------------------------------------------------------------


def files(data_dir: Path, client: str, books: str, twob: str) -> dict[str, Any]:
    return {
        "purchase_register": ("books.csv", (data_dir / client / books / "purchase_register.csv")
                              .read_bytes(), "text/csv"),
        "gstr2b": ("2b.json", (data_dir / client / twob / "gstr2b.json").read_bytes(),
                   "application/json"),
    }  # fmt: skip


def test_upload_replaces_an_undecided_period(api: Api, data_dir: Path) -> None:
    form = {"client_id": "C03", "period": "2026-04"}
    out = api.post("/uploads", data=form, files=files(data_dir, "C03", "2026-04", "2026-04"))
    assert out["rows_books"] > 0 and out["rows_2b"] > 0 and isinstance(out["warnings"], list)
    periods = {p["period"]: p for p in api.get("/periods", params={"client_id": "C03"})}
    assert periods["2026-04"]["has_books"] and periods["2026-04"]["run_status"] is None


def test_upload_errors(api: Api, data_dir: Path) -> None:
    decided = {"client_id": "C01", "period": "2026-03"}
    march = files(data_dir, "C01", "2026-03", "2026-03")
    assert api.error("POST", "/uploads", 409, data=decided, files=march) == "CONFLICT"
    wrong_2b = files(data_dir, "C03", "2026-04", "2026-03")
    form = {"client_id": "C03", "period": "2026-04"}
    assert api.error("POST", "/uploads", 422, data=form, files=wrong_2b) == "VALIDATION_ERROR"
    unknown = {"client_id": "C09", "period": "2026-04"}
    assert api.error("POST", "/uploads", 404, data=unknown, files=wrong_2b) == "NOT_FOUND"
    assert api.error("POST", "/uploads", 422, data=form) == "VALIDATION_ERROR"


# --- Demo controls -----------------------------------------------------------


def test_seed_twice_conflicts(api: Api) -> None:
    assert api.error("POST", "/demo/seed", 409) == "CONFLICT"
    assert api.error("GET", "/demo/jobs/job_missing", 404) == "NOT_FOUND"


def test_seed_job_reports_progress(fresh: Api) -> None:
    job = fresh.post("/demo/seed", 202)
    done = fresh.get(f"/demo/jobs/{job['job_id']}")
    assert done["status"] == "done" and done["done"] == done["total"] == 9
    assert done["result"]["periods"] == ["2026-01", "2026-02", "2026-03"]
    assert fresh.get("/health")["seeded"] is True


def test_reset_needs_confirmation(fresh: Api) -> None:
    """AC-07-6."""
    fresh.post("/demo/seed", 202)
    assert fresh.error("POST", "/demo/reset", 422) == "VALIDATION_ERROR"
    assert fresh.error("POST", "/demo/reset", 422, json={"confirm": "yes"}) == "VALIDATION_ERROR"
    assert fresh.post("/demo/reset", json={"confirm": "RESET"}) == {"reset": True}
    assert fresh.get("/clients") == [] and fresh.get("/memory/events") == []
    assert fresh.backend.banks[BANK_ID] == {}


def test_reset_keeps_everything_when_memory_is_down(fresh: Api) -> None:
    fresh.post("/demo/seed", 202)
    fresh.backend.available = False
    assert fresh.error("POST", "/demo/reset", 503, json={"confirm": "RESET"}) == "MEMORY_OFFLINE"
    assert fresh.get("/clients")


# --- Cross-cutting -----------------------------------------------------------


def floats(value: Any, key: str = "") -> list[str]:
    """Paths of JSON floats outside NOT_MONEY."""
    if isinstance(value, float):
        return [] if key in NOT_MONEY else [key]
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in floats(v, k)]
    if isinstance(value, list):
        return [p for v in value for p in floats(v, key)]
    return []


def test_no_money_is_ever_a_float(api: Api) -> None:
    """AC-07-2, over every body the module's tests received (this test runs after them)."""
    assert len(api.bodies) > 30
    assert [p for body in api.bodies for p in floats(body)] == []


def test_api_keys_never_leak(
    tmp_path: Path, data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """AC-07-7."""
    groq_key, hindsight_key = "gsk_do_not_leak_1234567890", "hs_do_not_leak_0987654321"
    settings = Settings(
        _env_file=None,
        groq_api_key=groq_key,
        hindsight_api_key=hindsight_key,
    )
    assert groq_key not in repr(settings) and groq_key not in str(settings.model_dump())
    services = make_services(
        tmp_path, data_dir, chat=GroqChat.from_settings(settings), backend=None
    )
    caplog.set_level(logging.DEBUG)
    with TestClient(create_app(services)) as client:
        seen = [
            client.get(path).text
            for path in ("/api/health", "/api/clients", "/api/trust", "/api/insights",
                         "/api/memory/events", "/openapi.json", "/api/runs/none")
        ]  # fmt: skip
        seen.append(client.post("/api/demo/reset", json={"confirm": "nope"}).text)
    for text in [*seen, caplog.text]:
        assert groq_key not in text and hindsight_key not in text

"""Rehearse the demo against a running API, end to end (SPEC-10 AC-10-1).

    python -m backend.scripts.demo_check --yes                  # two rounds, localhost:8000
    python -m backend.scripts.demo_check --yes --rounds 1 --base-url http://localhost:8000

Each round resets the demo (this WIPES the database and the memory bank, hence
`--yes`), seeds January to March, runs April for every client, then walks the
video's story: the automatic resolutions, Reddy Steels' drift, the cross-client
warning, a decision with a note, memory OFF, and Insights. Errors fail the
rehearsal; story beats that don't show are reported, and fail it with `--strict`.

Uses only the standard library, so it runs from any Python with the repo on its path.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

DEFAULT_URL = "http://localhost:8000"
SEED_TIMEOUT_S = 45 * 60
RUN_TIMEOUT_S = 15 * 60
POLL_S = 2.0

Http = Callable[[str, str, Any], tuple[int, Any]]
"""(method, path under /api, JSON body or None) → (status, JSON body)."""


class RehearsalError(RuntimeError):
    """A request failed or a job did not finish: the demo would break on camera."""


def urllib_http(base_url: str, timeout: float = 120.0) -> Http:
    def call(method: str, path: str, body: Any) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/api{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"null")
        except urllib.error.URLError as exc:
            raise RehearsalError(f"cannot reach {base_url}: {exc.reason}") from exc

    return call


@dataclass
class Beat:
    name: str
    shown: bool
    detail: str


@dataclass
class Rehearsal:
    http: Http
    sleep: Callable[[float], None] = time.sleep
    say: Callable[[str], None] = print
    beats: list[Beat] = field(default_factory=list)

    # --- HTTP ---

    def call(self, method: str, path: str, body: Any = None, expect: int = 200) -> Any:
        status, payload = self.http(method, path, body)
        if status != expect:
            raise RehearsalError(f"{method} {path} → {status}: {payload}")
        return payload

    def wait(self, path: str, timeout_s: float) -> Any:
        waited = 0.0
        while True:
            state = self.call("GET", path)
            if state["status"] == "done":
                return state
            if state["status"] == "failed":
                raise RehearsalError(f"{path} failed: {state.get('error')}")
            if waited >= timeout_s:
                raise RehearsalError(f"{path} still running after {timeout_s:.0f} s")
            self.sleep(POLL_S)
            waited += POLL_S

    def beat(self, name: str, shown: bool, detail: str) -> None:
        self.beats.append(Beat(name, shown, detail))
        self.say(f"  {'✓' if shown else '✗'} {name}: {detail}")

    # --- The demo ---

    def round(self) -> None:
        health = self.call("GET", "/health")
        self.say(f"health: hindsight {health['hindsight']}, llm {health['llm']}")
        if health["db"] != "up":
            raise RehearsalError("the database is down")
        self.call("POST", "/demo/reset", {"confirm": "RESET"})
        job = self.call("POST", "/demo/seed", expect=202)
        seeded = self.wait(f"/demo/jobs/{job['job_id']}", SEED_TIMEOUT_S)
        self.say(f"seeded: {seeded['result']}")

        clients = [c["id"] for c in self.call("GET", "/clients")]
        last = {c: self.periods(c)[-1] for c in clients}
        # Decisions stay when a period is re-run, so the OFF comparison goes before that
        # client's ON run: otherwise its automatic decisions from the ON run would show.
        compare = clients[-1]
        self.run(compare, last[compare], memory="off")
        off = self.groups(compare, last[compare])
        self.beat(
            "memory OFF",
            all(g["suggestion"] is None or not g["suggestion"]["memory_on"] for g in off)
            and not any(_auto(g) for g in off),
            f"{compare}: {len(off)} groups, none auto-resolved, no memories used",
        )
        april: dict[str, list[dict[str, Any]]] = {}
        for client in clients:
            self.run(client, last[client], memory="on")
            april[client] = self.groups(client, last[client])
        self.story(april, last)

        insights = self.call("GET", "/insights")
        self.beat(
            "insights",
            bool(insights.get("learning_curve")),
            f"learning curve from {insights['learning_curve_source'] or 'no eval run yet'}",
        )
        self.call("GET", "/memory/events")

    def run(self, client: str, period: str, *, memory: str) -> None:
        started = self.call(
            "POST", f"/reconciliations/{client}/{period}/run?memory={memory}", expect=202
        )
        done = self.wait(f"/runs/{started['run_id']}", RUN_TIMEOUT_S)
        self.say(f"ran {client} {period} (memory {memory}): {done['summary']}")

    def periods(self, client: str) -> list[str]:
        return [p["period"] for p in self.call("GET", f"/periods?client_id={client}")]

    def groups(self, client: str, period: str) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = self.call(
            "GET", f"/reconciliations/{client}/{period}/groups"
        )
        return groups

    def story(self, april: dict[str, list[dict[str, Any]]], last: dict[str, str]) -> None:
        everything = [g for groups in april.values() for g in groups]

        bhavani = _find(everything, "Bhavani Chemicals", "MISSING_IN_2B")
        self.beat(
            "Bhavani auto-deferred",
            bhavani is not None and _auto(bhavani) == "DEFER",
            _describe(bhavani),
        )
        laxmi = _find(everything, "Laxmi Packaging", "AMOUNT_MISMATCH")
        self.beat(
            "Laxmi auto-accepted",
            laxmi is not None and _auto(laxmi) == "ACCEPT",
            _describe(laxmi),
        )
        reddy = _find(everything, "Reddy Steels", "MISSING_IN_2B")
        self.beat(
            "Reddy drift",
            reddy is not None
            and "PATTERN_DRIFT" in _flags(reddy)
            and (reddy["suggestion"] or {}).get("action") != "DEFER",
            _describe(reddy),
        )
        if reddy is not None and "HOLD_PAYMENT" in reddy["allowed_actions"]:
            note = "Reddy has not filed March; hold payment until it shows in 2B."
            self.call(
                "POST",
                f"/exceptions/{reddy['group_key']}/decision",
                {"action": "HOLD_PAYMENT", "note": note},
            )
            self.call("GET", f"/vendors/{reddy['vendor']['gstin']}")

        # The warning comes in a seeded month, at the client that meets Krishna second.
        krishna = [
            g
            for client in april
            for period in self.periods(client)
            if period < last[client]
            for g in self.groups(client, period)
            if g["vendor"]["name"] == "Krishna Logistics"
        ]
        warned = [g for g in krishna if "CROSS_CLIENT_RISK" in _flags(g)]
        self.beat(
            "Krishna cross-client warning",
            bool(warned),
            _describe(warned[0]) if warned else f"not flagged in {len(krishna)} groups",
        )


def _flags(group: dict[str, Any]) -> list[str]:
    flags: list[str] = (group.get("suggestion") or {}).get("flags", [])
    return flags


def _find(
    groups: Sequence[dict[str, Any]], vendor: str, exception_type: str | None
) -> dict[str, Any] | None:
    return next(
        (
            g
            for g in groups
            if g["vendor"]["name"] == vendor and exception_type in (None, g["type"])
        ),
        None,
    )


def _auto(group: dict[str, Any]) -> str | None:
    decision = group.get("decision")
    if decision and decision["decided_by"] == "AUTO":
        action: str = decision["action"]
        return action
    return None


def _describe(group: dict[str, Any] | None) -> str:
    if group is None:
        return "group not found"
    action = (group.get("suggestion") or {}).get("action")
    auto = f", auto-resolved {_auto(group)}" if _auto(group) else ""
    flags = ", ".join(_flags(group)) or "no flags"
    return f"{group['group_key']}: suggested {action} ({flags}){auto}"


def main(argv: Sequence[str] | None = None, *, http: Http | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.scripts.demo_check",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base-url", default=DEFAULT_URL)
    parser.add_argument("--rounds", type=int, default=2, help="AC-10-1 asks for two")
    parser.add_argument("--strict", action="store_true", help="a missing story beat fails too")
    parser.add_argument("--yes", action="store_true", help="agree to wipe the demo data")
    args = parser.parse_args(argv)
    if not args.yes:
        parser.error("this resets the database and the memory bank; pass --yes to agree")

    rehearsal = Rehearsal(http or urllib_http(args.base_url))
    try:
        for n in range(1, args.rounds + 1):
            rehearsal.say(f"--- round {n} of {args.rounds} ---")
            rehearsal.round()
    except RehearsalError as exc:
        rehearsal.say(f"FAILED: {exc}")
        return 1
    missed = sorted({b.name for b in rehearsal.beats if not b.shown})
    if missed:
        rehearsal.say(f"story beats not shown: {', '.join(missed)}")
        return 2 if args.strict else 0
    rehearsal.say("all story beats shown")
    return 0


if __name__ == "__main__":
    sys.exit(main())

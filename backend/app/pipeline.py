"""One reconciliation run, and the accountant's decisions (SPEC-06 §3 and §7).

    match → verify past decisions → detect drift → trust → recall → suggest → auto-resolve

Steps 1 to 4 are deterministic code over SQLite; what they learn is retained
to memory so the agent can reason about it in plain English. Periods of a
client run in order, and only the latest one can be run again.

Memory OFF changes what the agent sees and forbids auto-resolution. Recon
still records decisions, outcomes and drift, so a later run with memory ON
knows everything that happened.
"""

import uuid
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from backend.app.agent import Agent, AgentContext, DriftInfo, Suggestion, TrustInfo
from backend.app.domain.entities import Client, Decision, GroupKey, Outcome, Vendor
from backend.app.domain.enums import Action, DecidedBy, ExceptionType, TrustLevel
from backend.app.domain.periods import add_months, first_day, label
from backend.app.domain.policy import is_action_allowed
from backend.app.learning import (
    DriftFinding,
    TrackedInvoice,
    Trust,
    Verdict,
    arrival_after_wrong,
    detect_drift,
    expected_lag,
    trust,
    verify,
)
from backend.app.matcher import Detail, ExceptionGroup, reconcile
from backend.app.memory import Memory, MemoryRecord, retain_request, utc_now
from backend.app.memory_text import (
    Drift,
    MemoryKind,
    Resolution,
    group_query,
    late_arrival_evidence,
)
from backend.app.memory_text import Outcome as OutcomeText
from backend.app.store import RunRow, Store

REVIEW_DAY = 15
"""Month-end review happens around the 15th, after GSTR-2B (14th) is out."""
STEPS = ("match", "verify", "drift", "trust", "recall", "suggest", "resolve")

Pattern = tuple[str, ExceptionType]


class PipelineError(ValueError):
    """The request doesn't fit the history: wrong period order, unknown group, bad undo."""


def review_date(period: str) -> date:
    """When a period's reconciliation is reviewed: the business date of its memories."""
    return first_day(add_months(period, 1)).replace(day=REVIEW_DAY)


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


class Pipeline:
    def __init__(
        self,
        store: Store,
        memory: Memory,
        agent: Agent,
        *,
        clock: Callable[[], datetime] = utc_now,
        run_ids: Callable[[], str] = new_run_id,
    ) -> None:
        self.store = store
        self.memory = memory
        self.agent = agent
        self._clock = clock
        self._run_ids = run_ids

    # --- Runs ---

    def run(self, client_id: str, period: str, *, memory_on: bool = True) -> RunRow:
        """Reconcile one client-period. A failure marks the run failed and re-raises."""
        return self.execute(self.start(client_id, period, memory_on=memory_on).id)

    def start(self, client_id: str, period: str, *, memory_on: bool = True) -> RunRow:
        """Check the period may run, discard its earlier runs and record a new one as running.
        Cheap, so the API can answer before the run itself (`execute`) starts."""
        self.store.client(client_id)
        self._check_order(client_id, period)
        self.store.discard_runs(client_id, period)
        run_id = self._run_ids()
        self.store.create_run(run_id, client_id, period, memory_on, self._clock())
        return self.store.run(run_id)

    def execute(self, run_id: str) -> RunRow:
        """Do a started run. A failure marks the run failed and re-raises."""
        row = self.store.run(run_id)
        if row.status != "running":
            raise PipelineError(f"run {run_id} is {row.status}, not waiting to run")
        try:
            client = self.store.client(row.client_id)
            summary = self._run(run_id, client, row.period, row.memory_on)
        except Exception as exc:
            self.store.fail_run(run_id, f"{type(exc).__name__}: {exc}", self._clock())
            raise
        self.store.finish_run(run_id, summary, self._clock())
        return self.store.run(run_id)

    def _check_order(self, client_id: str, period: str) -> None:
        periods = self.store.periods(client_id)
        if period not in periods:
            raise PipelineError(f"no data for {client_id} in {period}")
        last = self.store.last_run_period(client_id)
        if last is None:
            allowed = {periods[0]}
        else:
            later = [p for p in periods if p > last]
            allowed = {last, *later[:1]}
        if period not in allowed:
            raise PipelineError(
                f"{client_id} can run {' or '.join(sorted(allowed))} next, not {period}: "
                "periods run in order and only the latest can be run again"
            )

    def _run(self, run_id: str, client: Client, period: str, memory_on: bool) -> dict[str, Any]:
        client_id = client.client_id

        self._progress(run_id, "match")
        result = reconcile(
            client_id,
            period,
            self.store.books(client_id, period),
            self.store.twob(client_id, period),
            self.store.open_missing(client_id, before=period),
        )
        self.store.add_exceptions(run_id, result.exceptions)
        for late in result.late_arrivals:
            assert late.exception.id is not None and late.twob.id is not None
            self.store.close_exception(late.exception.id, period, late.twob.id)
        groups = self.store.groups(run_id)

        self._progress(run_id, "verify")
        verdicts = self._verify(client, period)

        self._progress(run_id, "drift")
        drift = self._detect_drift(period)

        self._progress(run_id, "trust")
        trusts = self._trust(run_id, groups, period)

        self._progress(run_id, "recall")
        items, offline = self._contexts(client, groups, trusts, drift, memory_on)

        self._progress(run_id, "suggest")
        suggestions = self.agent.suggest_all(items)
        for (_, ctx), suggestion in zip(items, suggestions, strict=True):
            self.store.add_suggestion(run_id, suggestion, self._clock(), ctx.memories)

        self._progress(run_id, "resolve")
        auto = [
            self._auto_resolve(group, suggestion, trusts[_pattern(group.key)])
            for group, suggestion in zip(groups, suggestions, strict=True)
        ]

        return {
            "matched": len(result.matched),
            "exceptions": len(result.exceptions),
            "groups": len(groups),
            "itc_at_risk": str(sum((g.itc_at_risk for g in groups), Decimal("0.00"))),
            "late_arrivals": len(result.late_arrivals),
            "outcomes": verdicts,
            "drift": sorted(
                gstin
                for gstin, finding in drift.items()
                if any(i.client_id == client_id for i in finding.overdue)
            ),
            "auto_resolved": [str(key) for key in auto if key is not None],
            "memory_offline": offline,
        }

    def _progress(self, run_id: str, step: str) -> None:
        self.store.set_progress(
            run_id, {"step": step, "step_no": STEPS.index(step) + 1, "steps": len(STEPS)}
        )

    # --- Step 2: self-check (§4) ---

    def _verify(self, client: Client, period: str) -> int:
        """Judge the client's past decisions; returns how many outcomes were written or updated."""
        by_vendor: defaultdict[str, list[TrackedInvoice]] = defaultdict(list)
        for invoice in self.store.tracked():
            by_vendor[invoice.vendor_gstin].append(invoice)
        written = 0
        for check in self.store.pending_checks(client.client_id, before=period):
            decision, key = check.decision, check.decision.group_key
            vendor_invoices = by_vendor[key.vendor_gstin]
            invoices = [
                i for i in vendor_invoices if (i.client_id, i.period) == (key.client_id, key.period)
            ]
            if check.outcome is None:
                lag = expected_lag([i for i in vendor_invoices if i.arrived_by(period)])
                verdict = verify(
                    decision.final_action,
                    key.exception_type,
                    key.period,
                    invoices,
                    lag=lag,
                    period=period,
                )
                if verdict is None:
                    continue
                assert decision.id is not None
                self.store.add_outcome(
                    Outcome(
                        decision_id=decision.id,
                        status=verdict.status,
                        checked_in_period=period,
                        evidence=_evidence(verdict),
                    ),
                    self._clock(),
                )
            else:
                # §9: a wrong deferral whose invoices finally came. It stays wrong.
                due_in = check.outcome.evidence.get("due_in")
                verdict = arrival_after_wrong(
                    invoices, due_in if isinstance(due_in, str) else None, period
                )
                if verdict is None:
                    continue
                self.store.update_outcome_evidence(check.outcome.decision_id, _evidence(verdict))
            self._retain_outcome(client, decision, verdict, period)
            written += 1
        return written

    def _retain_outcome(
        self, client: Client, decision: Decision, verdict: Verdict, period: str
    ) -> None:
        key = decision.group_key
        vendor = self.vendor(key.vendor_gstin)
        text = OutcomeText(
            period=period,
            decided_in=key.period,
            client_name=client.name,
            vendor_name=vendor.name,
            vendor_gstin=vendor.gstin,
            action=decision.final_action,
            correct=verdict.correct,
            evidence=_evidence_text(verdict, period),
        ).text()
        self.memory.retain(
            retain_request(
                MemoryKind.OUTCOME,
                text,
                document_id=f"outcome:{key}",
                occurred_on=review_date(period),
                period=period,
                client_id=client.client_id,
                client_name=client.name,
                vendor_gstin=vendor.gstin,
                vendor_name=vendor.name,
                exception_type=key.exception_type,
                action=decision.final_action,
            )
        )

    # --- Step 3: drift (§6) ---

    def _detect_drift(self, period: str) -> dict[str, DriftFinding]:
        by_vendor: defaultdict[str, list[TrackedInvoice]] = defaultdict(list)
        for invoice in self.store.tracked():
            by_vendor[invoice.vendor_gstin].append(invoice)
        processed = self.store.processed_through()
        found = {}
        for gstin, invoices in sorted(by_vendor.items()):
            finding = detect_drift(invoices, processed, period)
            if finding is None:
                continue
            found[gstin] = finding
            evidence = {
                "overdue": [i.invoice_no for i in finding.overdue],
                "clients": sorted({i.client_id for i in finding.overdue}),
                "lag_months": finding.lag_months,
                "typical_lag_days": finding.typical_lag_days,
                "overdue_days": finding.overdue_days,
            }
            if self.store.add_drift(gstin, period, evidence, self._clock()):
                self._retain_drift(finding, period)
        return found

    def _retain_drift(self, finding: DriftFinding, period: str) -> None:
        vendor = self.vendor(finding.vendor_gstin)
        client = self.store.client(finding.overdue[0].client_id)
        text = Drift(
            period=period,
            vendor_name=vendor.name,
            vendor_gstin=vendor.gstin,
            typical_lag=f"{finding.typical_lag_days} days",
            overdue_count=len(finding.overdue),
            overdue_days=finding.overdue_days,
        ).text()
        self.memory.retain(
            retain_request(
                MemoryKind.DRIFT,
                text,
                document_id=f"drift:{vendor.gstin}:{period}",
                occurred_on=review_date(period),
                period=period,
                client_id=client.client_id,
                client_name=client.name,
                vendor_gstin=vendor.gstin,
                vendor_name=vendor.name,
            )
        )

    # --- Step 4: trust (§5) ---

    def _trust(
        self, run_id: str, groups: Sequence[ExceptionGroup], period: str
    ) -> dict[Pattern, Trust]:
        trusts = {}
        for vendor_gstin, exception_type in sorted({_pattern(g.key) for g in groups}):
            level = trust(
                exception_type,
                self.store.pattern_actions(vendor_gstin, exception_type, before=period),
                self.store.pattern_verdicts(vendor_gstin, exception_type, through=period),
                drift_active=self.store.drift_detected(vendor_gstin, period),
                undone_recently=self.store.undone(
                    vendor_gstin, exception_type, [add_months(period, -1), period]
                ),
            )
            self.store.add_trust(run_id, vendor_gstin, exception_type, level)
            trusts[(vendor_gstin, exception_type)] = level
        return trusts

    # --- Step 5: contexts for the agent ---

    def _contexts(
        self,
        client: Client,
        groups: Sequence[ExceptionGroup],
        trusts: dict[Pattern, Trust],
        drift: dict[str, DriftFinding],
        memory_on: bool,
    ) -> tuple[list[tuple[ExceptionGroup, AgentContext]], bool]:
        """One context per group. If Hindsight is down, the rest of the run is memory OFF (§13)."""
        items, online = [], True
        for group in groups:
            key = group.key
            vendor = self.vendor(key.vendor_gstin, group)
            memories: tuple[MemoryRecord, ...] = ()
            if memory_on and online:
                recalled = self.memory.recall(
                    group_query(vendor.name, vendor.gstin, key.exception_type), purpose=str(key)
                )
                memories, online = recalled.records, recalled.online
            t = trusts[_pattern(key)]
            finding = drift.get(key.vendor_gstin)
            ctx = AgentContext(
                client=client,
                vendor=vendor,
                memories=memories,
                trust=TrustInfo(level=t.level, correct=t.correct, wrong=t.wrong),
                drift=_drift_info(finding) if finding and _waits_for_2b(key) else None,
                memory_on=memory_on and online,
            )
            items.append((group, ctx))
        return items, memory_on and not online

    # --- Step 6: auto-resolution (§7) ---

    def _auto_resolve(
        self, group: ExceptionGroup, suggestion: Suggestion, t: Trust
    ) -> GroupKey | None:
        eligible = (
            suggestion.memory_on
            and t.level is TrustLevel.AUTO
            and suggestion.action is t.streak_action
            and not suggestion.guardrail_events
            and self.store.current_decision(group.key) is None
        )
        if not eligible:
            return None
        decision = Decision(
            group_key=group.key,
            suggested_action=suggestion.action,
            final_action=suggestion.action,
            decided_by=DecidedBy.AUTO,
            decided_at=self._clock(),
        )
        self._record(group, decision)
        return group.key

    # --- Decisions ---

    def decide(self, key: GroupKey | str, action: Action, note: str | None = None) -> Decision:
        """The accountant resolves a group (or re-decides it)."""
        key = GroupKey.model_validate(key)
        group = self.store.group(key)
        if group is None:
            raise PipelineError(f"no exception group {key}")
        if not is_action_allowed(key.exception_type, action):
            raise PipelineError(f"{action} is not allowed for {key.exception_type}")
        decision = Decision(
            group_key=key,
            suggested_action=self.store.suggested_action(key),
            final_action=action,
            decided_by=DecidedBy.ACCOUNTANT,
            note=note,
            decided_at=self._clock(),
        )
        return self._record(group, decision)

    def undo(self, key: GroupKey | str, action: Action, note: str | None = None) -> Decision:
        """Replace an automatic decision with the accountant's own. The pattern drops to
        OBSERVE on the next run (§5)."""
        key = GroupKey.model_validate(key)
        current = self.store.current_decision(key)
        if current is None or current.decided_by is not DecidedBy.AUTO:
            raise PipelineError(f"{key} was not resolved automatically")
        if action is current.final_action:
            raise PipelineError(f"undo must choose an action other than {action}")
        return self.decide(key, action, note)

    def _record(self, group: ExceptionGroup, decision: Decision) -> Decision:
        stored = self.store.add_decision(decision)
        key = group.key
        client = self.store.client(key.client_id)
        vendor = self.vendor(key.vendor_gstin, group)
        text = Resolution(
            period=key.period,
            client_name=client.name,
            vendor_name=vendor.name,
            vendor_gstin=vendor.gstin,
            exception_type=key.exception_type,
            invoice_count=len(group.exceptions),
            itc_at_risk=group.itc_at_risk,
            suggested_action=decision.suggested_action,
            final_action=decision.final_action,
            note=decision.note,
            automatic=decision.decided_by is DecidedBy.AUTO,
        ).text()
        self.memory.retain(
            retain_request(
                MemoryKind.RESOLUTION,
                text,
                document_id=f"resolution:{key}",
                occurred_on=review_date(key.period),
                period=key.period,
                client_id=client.client_id,
                client_name=client.name,
                vendor_gstin=vendor.gstin,
                vendor_name=vendor.name,
                exception_type=key.exception_type,
                action=decision.final_action,
            )
        )
        return stored

    def vendor(self, gstin: str, group: ExceptionGroup | None = None) -> Vendor:
        """The vendor master row, or (a GSTIN nobody registered) the name on the invoices."""
        vendor = self.store.vendor(gstin)
        if vendor is not None:
            return vendor
        name = group.exceptions[0].details.get(Detail.SUPPLIER_NAME) if group else None
        return Vendor(gstin=gstin, name=str(name).title() if name else gstin)


def _pattern(key: GroupKey) -> Pattern:
    return (key.vendor_gstin, key.exception_type)


def _waits_for_2b(key: GroupKey) -> bool:
    return key.exception_type is ExceptionType.MISSING_IN_2B


def _drift_info(finding: DriftFinding) -> DriftInfo:
    return DriftInfo(
        overdue_invoices=tuple(i.invoice_no for i in finding.overdue),
        overdue_days=finding.overdue_days,
        typical_lag_days=finding.typical_lag_days,
    )


def _evidence(verdict: Verdict) -> dict[str, Any]:
    return {
        "invoices": list(verdict.invoice_nos),
        "due_in": verdict.due_in,
        "arrived_in": verdict.arrived_in,
        "filed_on": verdict.filed_on.isoformat() if verdict.filed_on else None,
        "days_late": verdict.days_late,
    }


def _evidence_text(verdict: Verdict, period: str) -> str:
    nos = verdict.invoice_nos
    if verdict.arrived_in is not None:
        arrival = late_arrival_evidence(
            nos, verdict.arrived_in, verdict.filed_on, verdict.days_late or 0
        )
        if verdict.due_in is not None and verdict.arrived_in > verdict.due_in:
            return f"expected in the {label(verdict.due_in)} GSTR-2B, but {arrival}"
        return arrival
    noun = "invoice" if len(nos) == 1 else "invoices"
    expected = label(verdict.due_in) if verdict.due_in else label(period)
    return (
        f"{noun} {', '.join(nos)} expected in the {expected} GSTR-2B had still not appeared "
        f"by the {label(period)} GSTR-2B."
    )

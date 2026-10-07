"""Bounded standalone coordination of existing resolution cycles.

Evidence fingerprints ignore collection metadata, not observation content. The
complete unmodified evidence and audits remain available in the cycle history.
"""

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path

from .executability import ExecutabilityReport, analyze_executability
from .exploration_execution import _element_identity
from .generate.from_openapi import Endpoint
from .llm_exploration import ExplorationLLM
from .llm_resolution import ResolutionLLM
from .resolution_context import ResolutionContext
from .resolution_cycle import ResolutionCycleResult, run_resolution_cycle
from .test_fixtures import FixtureStore
from .testcase import TestCase
from .ui.crawl import UIMap


class ResolutionLoopStopReason(str, Enum):
    EXECUTABLE = "EXECUTABLE"
    NO_MORE_WORK = "NO_MORE_WORK"
    NO_PROGRESS = "NO_PROGRESS"
    REPEATED_STATE = "REPEATED_STATE"
    MAX_CYCLES = "MAX_CYCLES"
    CYCLE_FAILED = "CYCLE_FAILED"


@dataclass(frozen=True)
class ResolutionLoopIssue:
    cycle: int
    code: str
    message: str


@dataclass(frozen=True)
class ResolutionLoopAuditEntry:
    cycle: int
    stage: str
    status: str


@dataclass(frozen=True)
class ResolutionLoopResult:
    case: TestCase
    context: ResolutionContext
    executability: ExecutabilityReport
    cycles: tuple[ResolutionCycleResult, ...]
    stop_reason: ResolutionLoopStopReason
    issues: tuple[ResolutionLoopIssue, ...]

    @property
    def cycle_count(self) -> int:
        """Completed cycles; an unexpected failed invocation is recorded in issues."""
        return len(self.cycles)

    @property
    def executable(self) -> bool:
        return self.executability.executable

    @property
    def audit(self) -> tuple[ResolutionLoopAuditEntry, ...]:
        entries = [ResolutionLoopAuditEntry(index, event.stage, event.status)
                   for index, result in enumerate(self.cycles, 1) for event in result.audit]
        entries.extend(ResolutionLoopAuditEntry(issue.cycle, "cycle", "FAILED")
                       for issue in self.issues if issue.code == "CYCLE_FAILED")
        return tuple(entries)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def _evidence_facts(context: ResolutionContext) -> frozenset[str]:
    """Compare selected evidence as sets; ordering, duplicates and times do not count.

    UI content includes page/session, elements, text, forms and network metadata.
    Source identifiers, reasons, observation times and truncation/omission flags
    stay in history but cannot by themselves justify another model/browser call.
    """
    facts = set()

    def add(kind, scope, value):
        facts.add(_canonical([kind, scope, value]))

    for kind, records in (
        ("requirement", context.specification.get("requirements", [])),
        ("api_operation", context.interface_contract.get("api_operations", [])),
    ):
        for record in records:
            add(kind, None, {key: value for key, value in record.items()
                             if key not in {"evidence", "source"}})
    for page in context.observations.get("ui_pages", []):
        scope = [page.get("url"), page.get("session")]
        add("page", scope, page.get("title", ""))
        for element in page.get("elements", []):
            add("element", scope, _element_identity(element))
        for text in page.get("text", []):
            add("text", scope, text)
        for observation in page.get("explorations", []):
            observed_scope = [page.get("url"), observation.get("request", {}).get("session")]
            for action in observation.get("action_observations", []):
                add("post_action", observed_scope, {key: action.get(key) for key in (
                    "action", "target", "selector", "credential_inputs_empty", "request_count", "final_url")})
            for kind in ("forms", "network"):
                for item in observation.get(kind, []):
                    add(kind, observed_scope, item)
    for state in context.observations.get('page_states', []):
        if not state.get('valid'):
            continue
        scope = [state['page'].get('url'), state.get('session'), state.get('source_clause')]
        add('state', scope, state['page'])
        for record in state.get('network', []):
            add('state_network', scope, record)
    return frozenset(facts)


def _fingerprint(case: TestCase, context: ResolutionContext,
                 report: ExecutabilityReport, facts: frozenset[str]) -> str:
    state = {
        "case": case.to_dict(), "evidence": sorted(facts),
        "gaps": sorted([[gap.code, gap.step_seq] for gap in report.gaps], key=_canonical),
        "validation_error": report.validation_error,
        "allowed_actions": context.allowed_actions, "constraints": context.constraints,
    }
    return hashlib.sha256(_canonical(state).encode("utf-8")).hexdigest()


def run_resolution_loop(
    case: TestCase, context: ResolutionContext, *, max_cycles: int = 3,
    resolution_llm: ResolutionLLM | None = None,
    exploration_llm: ExplorationLLM | None = None,
    base_url: str | None = None, storage_state: Path | None = None,
    fixture_store: FixtureStore | None = None,
    ui_map: UIMap | None = None, endpoints: list[Endpoint] | None = None,
    data_verification=None,
) -> ResolutionLoopResult:
    """Run at most max_cycles, passing each resulting case/context to the next.

    Stop precedence after a cycle: executable, no more work, repeated state,
    no progress, then budget. Progress means fewer gaps, changed testcase data,
    or at least one new evidence fact. Metadata-only changes are not progress.
    No stage is implemented here; run_resolution_cycle remains authoritative.
    """
    if type(max_cycles) is not int or max_cycles < 1:
        raise ValueError("max_cycles must be a positive integer")
    working, packet = deepcopy(case), deepcopy(context)
    if data_verification is not None:
        from .test_data_acquisition import acquire_test_data
        from dataclasses import replace
        acquired = acquire_test_data(working, fixture_store=fixture_store,
                                     endpoints=endpoints or (), verification=data_verification)
        working = acquired.case
        packet = replace(packet, data_acquisition=acquired.to_dict())
    trusted_ui, trusted_endpoints = deepcopy(ui_map), deepcopy(endpoints)
    report = analyze_executability(working, context=packet)
    history, issues = [], []

    def finish(reason):
        return deepcopy(ResolutionLoopResult(
            working, packet, report, tuple(history), reason, tuple(issues)))

    if report.executable:
        return finish(ResolutionLoopStopReason.EXECUTABLE)
    facts = _evidence_facts(packet)
    seen = {_fingerprint(working, packet, report, facts)}

    for index in range(1, max_cycles + 1):
        previous_case = _canonical(working.to_dict())
        previous_gap_count = len(report.gaps)
        previous_facts = facts
        try:
            result = deepcopy(run_resolution_cycle(
                deepcopy(working), deepcopy(packet), resolution_llm=resolution_llm,
                exploration_llm=exploration_llm, base_url=base_url, storage_state=storage_state, fixture_store=fixture_store,
                ui_map=deepcopy(trusted_ui), endpoints=deepcopy(trusted_endpoints),
                **({'data_verification': data_verification} if data_verification is not None else {})))
            candidate_report = analyze_executability(result.case, context=result.context)
            candidate_facts = _evidence_facts(result.context)
            fingerprint = _fingerprint(result.case, result.context, candidate_report, candidate_facts)
        except Exception:
            # The cycle normally returns stage issues. If the invocation itself
            # fails, discard its private candidate and keep the last good state.
            issues.append(ResolutionLoopIssue(index, "CYCLE_FAILED",
                                             "Cycle invocation failed; last completed state retained."))
            return finish(ResolutionLoopStopReason.CYCLE_FAILED)

        history.append(result)
        working, packet = deepcopy(result.case), deepcopy(result.context)
        report, facts = candidate_report, candidate_facts
        if report.executable:
            return finish(ResolutionLoopStopReason.EXECUTABLE)
        if not result.needs_another_cycle:
            return finish(ResolutionLoopStopReason.NO_MORE_WORK)
        if fingerprint in seen:
            return finish(ResolutionLoopStopReason.REPEATED_STATE)
        progress = (len(report.gaps) < previous_gap_count
                    or _canonical(working.to_dict()) != previous_case
                    or bool(facts - previous_facts))
        if not progress:
            return finish(ResolutionLoopStopReason.NO_PROGRESS)
        seen.add(fingerprint)
    return finish(ResolutionLoopStopReason.MAX_CYCLES)

"""Vòng coverage hữu hạn; chỉ case thực thi được mới đóng nghĩa vụ nguồn."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Iterable, Mapping

from .coverage import CoverageReport, CoverageStatus, analyze_coverage
from .coverage_resolution import CoverageResolutionPassResult, run_coverage_resolution_pass
from .executability import analyze_executability
from .generate.from_openapi import Endpoint
from .llm_exploration import ExplorationLLM
from .llm_resolution import ResolutionLLM
from .model import Requirement
from .resolution_context import ResolutionContext
from .testcase import TestCase
from .ui.crawl import UIMap


class CoverageLoopStopReason(str, Enum):
    COVERAGE_COMPLETE = "COVERAGE_COMPLETE"
    NO_PROGRESS = "NO_PROGRESS"
    REPEATED_STATE = "REPEATED_STATE"
    MAX_PASSES = "MAX_PASSES"
    NO_GENERATABLE_OBLIGATIONS = "NO_GENERATABLE_OBLIGATIONS"


@dataclass(frozen=True)
class CoverageLoopIssue:
    pass_number: int
    code: str
    message: str


@dataclass(frozen=True)
class CoverageLoopPass:
    pass_number: int
    before: CoverageReport
    after: CoverageReport
    resolution: CoverageResolutionPassResult | None
    added_case_ids: tuple[str, ...]


@dataclass(frozen=True)
class CoverageLoopResult:
    cases: tuple[TestCase, ...]
    accepted_cases: tuple[TestCase, ...]
    unresolved_cases: tuple[TestCase, ...]
    coverage: CoverageReport
    intent_coverage: CoverageReport
    history: tuple[CoverageLoopPass, ...]
    stop_reason: CoverageLoopStopReason
    issues: tuple[CoverageLoopIssue, ...]

    @property
    def pass_count(self) -> int:
        return len(self.history)

    @property
    def executable_coverage_complete(self) -> bool:
        return _complete(self.coverage)


def _complete(report: CoverageReport) -> bool:
    # Empty/unknown source is not evidence of complete coverage.
    return bool(report.requirements) and all(
        r.status == CoverageStatus.COVERED for r in report.requirements)


def _covered(report: CoverageReport) -> frozenset[str]:
    return frozenset(o.id for r in report.requirements for o in r.obligations
                     if o.status == CoverageStatus.COVERED)


def _state(report: CoverageReport) -> str:
    # Collection metadata, candidate IDs and audit entries are not progress.
    requirements = sorted((r.requirement_id, r.status.value) for r in report.requirements)
    obligations = sorted({(o.id, o.status.value, o.condition, o.action, o.expected,
                           o.test_data) for r in report.requirements for o in r.obligations})
    return json.dumps([requirements, obligations], ensure_ascii=False, sort_keys=True)


def run_coverage_loop(
    requirements: Iterable[Requirement | dict] | dict, cases: Iterable[TestCase] = (), *,
    flows: dict | None = None, max_passes: int = 3, max_cycles: int = 3,
    module: str = "COV", resolution_llm: ResolutionLLM | None = None,
    exploration_llm: ExplorationLLM | None = None,
    contexts: Mapping[str, ResolutionContext] | None = None,
    ui_map: UIMap | None = None, endpoints: list[Endpoint] | None = None,
    base_url: str | None = None, storage_state: Path | None = None,
) -> CoverageLoopResult:
    """Reanalyse after each pass, add accepted cases only, never repair inputs.

    Original manual cases contribute only to intent_coverage. For a generated
    executable case, its original planner case supplies exact intent evidence;
    the pass history records the validated transition to the executable copy.
    No such equivalence is inferred for arbitrary existing mapped assertions.
    Retry unresolved obligations only after new executable obligations were
    covered in the previous pass, and never beyond max_passes. No evidence from
    unresolved attempts is implicitly reused or treated as coverage.
    """
    for name, budget in (("max_passes", max_passes), ("max_cycles", max_cycles)):
        if type(budget) is not int or budget < 1:
            raise ValueError(f"{name} must be a positive integer")
    if isinstance(requirements, dict):
        if flows is None:
            flows = requirements.get("flows")
        requirements = requirements.get("requirements", [])
    rows, sources = deepcopy(tuple(requirements)), deepcopy(flows)
    working = list(deepcopy(tuple(cases)))
    if len({case.id for case in working}) != len(working):
        raise ValueError("Testcase IDs must be unique")
    trusted_contexts, trusted_ui, trusted_endpoints = deepcopy((contexts, ui_map, endpoints))
    accepted, intent_records, pending, history, issues = [], {}, {}, [], []
    reserved = {case.id for case in working}

    def reports():
        executable_intents = []
        all_intents = []
        for case in working:
            intent = deepcopy(intent_records.get(case.id, case))
            all_intents.append(intent)
            if analyze_executability(case).executable:
                executable_intents.append(intent)
        return (analyze_coverage(rows, executable_intents, flows=sources),
                analyze_coverage(rows, all_intents, flows=sources))

    coverage, intent_coverage = reports()

    def finish(reason):
        covered = _covered(coverage)
        unresolved = [case for ids, case in pending.items() if not set(ids) <= covered]
        return deepcopy(CoverageLoopResult(
            tuple(working), tuple(accepted), tuple(unresolved), coverage, intent_coverage,
            tuple(history), reason, tuple(issues)))

    if _complete(coverage):
        return finish(CoverageLoopStopReason.COVERAGE_COMPLETE)
    seen = {_state(coverage)}
    for index in range(1, max_passes + 1):
        before = coverage
        if not coverage.missing_obligations:
            return finish(CoverageLoopStopReason.NO_GENERATABLE_OBLIGATIONS)
        try:
            result = deepcopy(run_coverage_resolution_pass(
                deepcopy(coverage),
                [deepcopy(c) for c in working if analyze_executability(c).executable],
                module=module, max_cycles=max_cycles, reserved_case_ids=tuple(sorted(reserved)),
                resolution_llm=resolution_llm, exploration_llm=exploration_llm,
                contexts=deepcopy(trusted_contexts), requirements=deepcopy(rows),
                ui_map=deepcopy(trusted_ui), endpoints=deepcopy(trusted_endpoints),
                base_url=base_url, storage_state=storage_state))
        except Exception:
            issues.append(CoverageLoopIssue(index, "PASS_FAILED",
                                          "Pass failed; previously accepted cases retained."))
            history.append(CoverageLoopPass(index, before, before, None, ()))
            return finish(CoverageLoopStopReason.NO_PROGRESS)

        logical = {case.id: case for case in result.planned_cases}
        reserved.update(logical)
        added = []
        invalid = []
        for case in result.accepted_cases:
            original = logical.get(case.id)
            if (original is None or case.id in {c.id for c in working}
                    or not set(original.traces_to) <= set(case.traces_to)
                    or not analyze_executability(case).executable):
                issues.append(CoverageLoopIssue(index, "INVALID_ACCEPTED_CASE",
                                              "Accepted candidate lacks unique executable source binding."))
                invalid.append(case)
                continue
            working.append(deepcopy(case))
            accepted.append(deepcopy(case))
            intent_records[case.id] = deepcopy(original)
            added.append(case.id)
        for case in (*result.unresolved_cases, *invalid):
            ids = tuple(sorted(link.obligation.id for link in result.audit
                               if link.generated and link.testcase_id == case.id))
            if ids:
                pending[ids] = deepcopy(case)
        coverage, intent_coverage = reports()
        history.append(CoverageLoopPass(index, before, coverage, result, tuple(added)))
        if _complete(coverage):
            return finish(CoverageLoopStopReason.COVERAGE_COMPLETE)
        if not coverage.missing_obligations or not result.planned_cases:
            return finish(CoverageLoopStopReason.NO_GENERATABLE_OBLIGATIONS)
        state = _state(coverage)
        if state in seen:
            return finish(CoverageLoopStopReason.REPEATED_STATE)
        if not (_covered(coverage) - _covered(before)):
            return finish(CoverageLoopStopReason.NO_PROGRESS)
        seen.add(state)
    return finish(CoverageLoopStopReason.MAX_PASSES)

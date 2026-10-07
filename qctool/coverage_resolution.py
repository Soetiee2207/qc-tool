"""Một lượt coverage → testcase logic → resolution, độc lập với pipeline."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .coverage import CoverageReport
from .coverage_plan import CoveragePlan, CoveragePlanLink, SkippedCoverageObligation, plan_coverage
from .executability import ExecutabilityReport, analyze_executability
from .generate.from_openapi import Endpoint
from .llm_exploration import ExplorationLLM
from .llm_resolution import ResolutionLLM
from .model import Requirement
from .resolution_context import ResolutionContext, build_resolution_context
from .resolution_loop import ResolutionLoopResult, run_resolution_loop
from .test_fixtures import FixtureStore
from .testcase import TestCase
from .ui.crawl import UIMap


@dataclass(frozen=True)
class CoverageResolutionIssue:
    testcase_id: str
    stage: str
    code: str
    message: str
    cycle: int | None = None


@dataclass(frozen=True)
class CoverageCaseResolution:
    testcase_id: str
    case: TestCase
    executability: ExecutabilityReport
    resolution: ResolutionLoopResult | None

    @property
    def accepted(self) -> bool:
        return self.executability.executable


@dataclass(frozen=True)
class CoverageResolutionPassResult:
    plan: CoveragePlan
    case_results: tuple[CoverageCaseResolution, ...]
    issues: tuple[CoverageResolutionIssue, ...]

    @property
    def planned_cases(self) -> tuple[TestCase, ...]:
        return self.plan.cases

    @property
    def accepted_cases(self) -> tuple[TestCase, ...]:
        return tuple(item.case for item in self.case_results if item.accepted)

    @property
    def unresolved_cases(self) -> tuple[TestCase, ...]:
        return tuple(item.case for item in self.case_results if not item.accepted)

    @property
    def skipped_obligations(self) -> tuple[SkippedCoverageObligation, ...]:
        return self.plan.skipped

    @property
    def audit(self) -> tuple[CoveragePlanLink, ...]:
        """Exact source → testcase links; case_results retain full cycle audits."""
        return self.plan.links

    @property
    def obligation_to_testcase(self) -> dict[str, str]:
        return self.plan.obligation_to_testcase

    @property
    def accepted_obligation_to_testcase(self) -> dict[str, str]:
        accepted = {item.testcase_id for item in self.case_results if item.accepted}
        return {link.obligation.id: link.testcase_id for link in self.plan.links
                if link.generated and link.testcase_id in accepted}


def run_coverage_resolution_pass(
    coverage_report: CoverageReport, existing_cases: Iterable[TestCase] = (), *,
    module: str = "COV", max_cycles: int = 3,
    reserved_case_ids: Iterable[str] = (),
    resolution_llm: ResolutionLLM | None = None,
    exploration_llm: ExplorationLLM | None = None,
    contexts: Mapping[str, ResolutionContext] | None = None,
    requirements: Sequence[dict | Requirement] | dict | None = None,
    ui_map: UIMap | None = None, endpoints: list[Endpoint] | None = None,
    base_url: str | None = None, storage_state: Path | None = None,
    fixture_store: FixtureStore | None = None,
) -> CoverageResolutionPassResult:
    """Plan once, then call the bounded resolution loop once per new candidate.

    Only final analyzer executability constitutes acceptance, never logical
    coverage or a model claim. No subsequent coverage analysis/planning occurs.
    Existing/reused cases are not resolved. Each candidate and evidence packet
    is private; unexpected failures retain its original logical candidate and
    cannot discard other results. Normal loop failures retain its last state.
    Optional contexts must be trusted, selected evidence packets for the exact
    planned candidates; the loop retains its normal testcase identity checks.
    Without these, the existing context builder's conservative selection applies.
    """
    if type(max_cycles) is not int or max_cycles < 1:
        raise ValueError("max_cycles must be a positive integer")
    plan = plan_coverage(deepcopy(coverage_report),
                         existing_cases=deepcopy(tuple(existing_cases)), module=module,
                         reserved_case_ids=tuple(reserved_case_ids))
    trusted_requirements, trusted_ui, trusted_endpoints = deepcopy((requirements, ui_map, endpoints))
    trusted_contexts = deepcopy(dict(contexts or {}))
    if fixture_store is not None:
        from dataclasses import replace
        plan = replace(plan, cases=tuple(fixture_store.bind(c) for c in plan.cases))
    results, issues = [], []
    # The planner already merges shared intents; iterate cases, not audit links.
    for logical in plan.cases:
        working = deepcopy(logical)
        resolution = None
        stage = "context"
        try:
            context = deepcopy(trusted_contexts.get(logical.id))
            if context is None:
                context = build_resolution_context(
                    deepcopy(working), analyze_executability(working).gaps,
                    requirements=deepcopy(trusted_requirements), ui_map=deepcopy(trusted_ui),
                    endpoints=deepcopy(trusted_endpoints))
            stage = "resolution"
            candidate = deepcopy(run_resolution_loop(
                deepcopy(working), deepcopy(context), max_cycles=max_cycles,
                resolution_llm=resolution_llm, exploration_llm=exploration_llm,
                ui_map=deepcopy(trusted_ui), endpoints=deepcopy(trusted_endpoints),
                base_url=base_url, storage_state=storage_state, fixture_store=fixture_store))
            # Recompute rather than accepting the loop's executable flag.
            final_report = analyze_executability(candidate.case, context=candidate.context)
            working, resolution = deepcopy(candidate.case), candidate
        except Exception:
            issues.append(CoverageResolutionIssue(
                logical.id, stage, "CASE_RESOLUTION_FAILED",
                "Candidate resolution failed; detached logical testcase retained."))
            final_report = analyze_executability(working)
        if resolution is not None:
            for issue in resolution.issues:
                issues.append(CoverageResolutionIssue(
                    logical.id, 'test_data_preparation' if issue.cycle == 0 else 'cycle',
                    issue.code, issue.message, issue.cycle or None))
            for index, cycle in enumerate(resolution.cycles, 1):
                for issue in cycle.issues:
                    issues.append(CoverageResolutionIssue(
                        logical.id, issue.stage, issue.code, issue.message, index))
        results.append(CoverageCaseResolution(logical.id, working, final_report, resolution))
    return CoverageResolutionPassResult(plan, tuple(results), tuple(issues))

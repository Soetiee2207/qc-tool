"""Điều phối generation; trả kết quả độc lập, caller quyết định ghi/chạy."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping

from .coverage import CoverageReport, CoverageStatus, analyze_coverage
from .coverage_loop import CoverageLoopPass, CoverageLoopResult, run_coverage_loop
from .executability import analyze_executability
from .generate.from_openapi import Endpoint
from .llm_exploration import ExplorationLLM
from .llm_resolution import ResolutionLLM
from .model import Requirement
from .resolution_context import ResolutionContext
from .test_fixtures import FixtureStore
from .test_data_preparation import TestDataPreparationResult, prepare_test_data
from .testcase import TestCase
from .ui.crawl import UIMap
from .validate import Report, validate_batch


class GenerationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    INVALID_TESTCASES = "INVALID_TESTCASES"
    UNASSESSABLE_COVERAGE = "UNASSESSABLE_COVERAGE"
    INCOMPLETE_COVERAGE = "INCOMPLETE_COVERAGE"
    FAILED = "FAILED"


@dataclass(frozen=True)
class GenerationIssue:
    stage: str
    code: str
    message: str
    testcase_id: str | None = None
    pass_number: int | None = None
    cycle: int | None = None


@dataclass(frozen=True)
class GenerationResult:
    cases: tuple[TestCase, ...]
    executable_cases: tuple[TestCase, ...]
    unresolved_cases: tuple[TestCase, ...]
    generated_cases: tuple[TestCase, ...]
    coverage: CoverageReport
    intent_coverage: CoverageReport
    validation: Report
    coverage_loop: CoverageLoopResult | None
    issues: tuple[GenerationIssue, ...]
    status: GenerationStatus
    test_data_preparations: tuple[TestDataPreparationResult, ...] = ()

    @property
    def success(self) -> bool:
        return self.status == GenerationStatus.SUCCESS

    @property
    def history(self) -> tuple[CoverageLoopPass, ...]:
        return self.coverage_loop.history if self.coverage_loop is not None else ()

    @property
    def accepted_generated_cases(self) -> tuple[TestCase, ...]:
        executable_ids = {case.id for case in self.executable_cases}
        return tuple(case for case in self.generated_cases if case.id in executable_ids)

    def to_dict(self) -> dict:
        """Serialize audits with native serializers, including explorer redaction."""
        payload = {field.name: _serializable(getattr(self, field.name)) for field in fields(self)}
        return {**payload, "success": self.success}


def _serializable(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "to_dict"):
        return _serializable(value.to_dict())
    if is_dataclass(value):
        return {field.name: _serializable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {key: _serializable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serializable(item) for item in value]
    return value


def run_generation(
    requirements: Iterable[Requirement | dict] | dict,
    existing_cases: Iterable[TestCase] = (), *, flows: dict | None = None,
    ui_map: UIMap | None = None, endpoints: list[Endpoint] | None = None,
    resolution_llm: ResolutionLLM | None = None,
    exploration_llm: ExplorationLLM | None = None,
    base_url: str | None = None, storage_state: Path | None = None,
    fixture_store: FixtureStore | None = None,
    allow_provisioning: bool = False, environment: str | None = None,
    max_passes: int = 3, max_cycles: int = 3, module: str = "COV",
    contexts: Mapping[str, ResolutionContext] | None = None, preparation_cache=None,
) -> GenerationResult:
    """Validate inputs, delegate once to the coverage loop, classify its results.

    SUCCESS requires structural batch validity, executable accepted generated
    cases, and complete deterministically established executable coverage.
    Unknown/empty coverage is never success. Existing mapped cases without
    provable intent retain the coverage analyzer's unassessable status.
    generated_cases includes accepted and still-unresolved final candidates;
    superseded attempts remain in history. Invalid existing batches skip model
    work. Configuration/schema errors in requirement input retain normal errors.
    """
    for name, budget in (("max_passes", max_passes), ("max_cycles", max_cycles)):
        if type(budget) is not int or budget < 1:
            raise ValueError(f"{name} must be a positive integer")
    if isinstance(requirements, dict):
        if flows is None:
            flows = requirements.get("flows")
        requirements = requirements.get("requirements", [])
    from .preparation_cache import PreparationCache
    preparation_cache = preparation_cache if preparation_cache is not None else PreparationCache()
    rows, source_flows = deepcopy(tuple(requirements)), deepcopy(flows)
    original = tuple(fixture_store.bind(c) if fixture_store else deepcopy(c)
                     for c in existing_cases)
    validation = validate_batch(list(original))
    issues = []
    preparations = []
    if validation.ok:
        prepared = []
        for case in original:
            preparation = prepare_test_data(case, fixture_store=fixture_store,
                                            endpoints=endpoints or (), base_url=base_url, preparation_cache=preparation_cache,
                                            allow_provisioning=allow_provisioning, environment=environment)
            prepared.append(preparation.case)
            if preparation.initial is not None:
                preparations.append(preparation)
                issues.extend(GenerationIssue('test_data_preparation', i['code'], i['message'], case.id)
                              for i in preparation.blockers)
        original = tuple(prepared)
    result = None
    failed = False
    if validation.ok:
        try:
            result = deepcopy(run_coverage_loop(
                deepcopy(rows), deepcopy(original), flows=deepcopy(source_flows),
                ui_map=deepcopy(ui_map), endpoints=deepcopy(endpoints),
                resolution_llm=resolution_llm, exploration_llm=exploration_llm,
                base_url=base_url, storage_state=storage_state,
                max_passes=max_passes, max_cycles=max_cycles, module=module,
                contexts=deepcopy(contexts), fixture_store=fixture_store,
                allow_provisioning=allow_provisioning, environment=environment, preparation_cache=preparation_cache))
        except Exception:
            failed = True
            issues.append(GenerationIssue("coverage_loop", "GENERATION_FAILED",
                                          "Generation failed; existing cases retained."))

    if result is None:
        inventory, generated = original, ()
        executable = tuple(c for c in original if analyze_executability(c).executable)
        coverage = analyze_coverage(rows, executable, flows=source_flows)
        intent_coverage = analyze_coverage(rows, original, flows=source_flows)
    else:
        inventory = deepcopy(result.cases + result.unresolved_cases)
        generated = deepcopy(result.accepted_cases + result.unresolved_cases)
        executable = tuple(c for c in result.cases if analyze_executability(c).executable)
        coverage, intent_coverage = result.coverage, result.intent_coverage
        for issue in result.issues:
            issues.append(GenerationIssue("coverage_loop", issue.code, issue.message,
                                          pass_number=issue.pass_number))
        for entry in result.history:
            if entry.resolution is not None:
                for issue in entry.resolution.issues:
                    issues.append(GenerationIssue(issue.stage, issue.code, issue.message,
                                                  issue.testcase_id, entry.pass_number, issue.cycle))
        invalid_accepted = [c for c in result.accepted_cases
                            if not analyze_executability(c).executable]
        for case in invalid_accepted:
            issues.append(GenerationIssue("executability", "GENERATED_CASE_NOT_EXECUTABLE",
                                          "Accepted generated case is not executable.", case.id))
        if invalid_accepted:
            failed = True
    # Validate the entire final inventory, including manual/unresolved candidates.
    validation = validate_batch(list(inventory))
    for message in validation.errors:
        issues.append(GenerationIssue("validation", "INVALID_TESTCASE", message))
    if not validation.ok:
        status = GenerationStatus.INVALID_TESTCASES
    elif failed:
        status = GenerationStatus.FAILED
    elif result is not None and result.executable_coverage_complete:
        status = GenerationStatus.SUCCESS
    elif (not coverage.requirements
          or any(r.status == CoverageStatus.UNASSESSABLE for r in coverage.requirements)
          or coverage.unassessable_obligations):
        status = GenerationStatus.UNASSESSABLE_COVERAGE
    else:
        status = GenerationStatus.INCOMPLETE_COVERAGE
    executable_ids = {c.id for c in executable}
    unresolved = tuple(c for c in inventory if c.id not in executable_ids
                       or not analyze_executability(c).executable)
    # Separate snapshots prevent edits to the public inventory from altering audit.
    return GenerationResult(
        deepcopy(inventory), deepcopy(executable), deepcopy(unresolved), deepcopy(generated),
        deepcopy(coverage), deepcopy(intent_coverage), deepcopy(validation), deepcopy(result),
        tuple(issues), status, tuple(preparations))

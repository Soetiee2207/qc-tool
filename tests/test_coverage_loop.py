"""Coverage loop: real planning/analysis and deterministic offline pass stubs."""
from copy import deepcopy
from dataclasses import replace

import pytest

import qctool.coverage_loop as loop
from qctool.coverage import CoverageStatus, analyze_coverage
from qctool.coverage_plan import plan_coverage
from qctool.coverage_resolution import CoverageCaseResolution, CoverageResolutionPassResult
from qctool.executability import analyze_executability
from qctool.testcase import Step, StepKind
from tests.test_coverage_resolution import RepairLLM, contexts_for, flows, report, ui_map


def sources(count=2):
    return {"flow": [{"id": "FLOW-1", "steps": [
        {"action": f"Open /page-{i}", "expected": f"URL /page-{i}"}
        for i in range(1, count + 1)]}]}


def fake_pass(report, existing_cases, *, accept_count=None, **kwargs):
    plan = plan_coverage(report, existing_cases=existing_cases, module=kwargs["module"],
                         reserved_case_ids=kwargs["reserved_case_ids"])
    records = []
    for index, logical in enumerate(plan.cases):
        case = deepcopy(logical)
        if accept_count is None or index < accept_count:
            route = case.steps[0].args["description"].removeprefix("Open ")
            case.steps = [Step(1, StepKind.WHEN, "ui.goto", {"url": route}),
                          Step(2, StepKind.THEN, "assert.url_matches", {"pattern": route})]
            case.execution = "auto"
        records.append(CoverageCaseResolution(case.id, case, analyze_executability(case), None))
    return CoverageResolutionPassResult(plan, tuple(records), ())


def test_real_resolution_completes_in_one_pass():
    evidence = ui_map()
    result = loop.run_coverage_loop([], flows=flows(), resolution_llm=RepairLLM(),
                                    contexts=contexts_for(report()), ui_map=evidence)
    assert result.stop_reason == "COVERAGE_COMPLETE"
    assert result.executable_coverage_complete
    assert result.pass_count == 1
    assert len(result.accepted_cases) == len(result.cases) == 1
    assert not result.unresolved_cases
    assert all(analyze_executability(c).executable for c in result.accepted_cases)
    assert result.coverage.requirements[0].status == CoverageStatus.COVERED
    assert result.history[0].resolution.case_results[0].resolution.cycles
    assert result.history[0].resolution.audit[0].obligation.source.source_id == "FLOW-1"


def test_second_pass_fills_remaining_outcome_on_same_requirement(monkeypatch):
    calls = []

    def run(report, existing_cases, **kwargs):
        calls.append(deepcopy(report))
        return fake_pass(report, existing_cases, accept_count=1, **kwargs)

    monkeypatch.setattr(loop, "run_coverage_resolution_pass", run)
    result = loop.run_coverage_loop([], flows=sources())
    assert result.stop_reason == "COVERAGE_COMPLETE"
    assert result.pass_count == 2
    assert len(result.accepted_cases) == 2
    assert result.history[0].after.requirements[0].status == CoverageStatus.PARTIALLY_COVERED
    assert len(calls[1].missing_obligations) == 1
    assert [c.id for c in result.cases] == ["TC_COV_001", "TC_COV_003"]
    assert not result.unresolved_cases  # first attempt superseded by accepted repair
    assert len(result.history[0].resolution.unresolved_cases) == 1


def test_unresolved_does_not_count_and_repeated_state_stops(monkeypatch):
    calls = []

    def run(report, existing_cases, **kwargs):
        calls.append(1)
        return fake_pass(report, existing_cases, accept_count=0, **kwargs)

    monkeypatch.setattr(loop, "run_coverage_resolution_pass", run)
    result = loop.run_coverage_loop([], flows=sources(1), max_passes=50)
    assert calls == [1]
    assert result.stop_reason == "REPEATED_STATE"
    assert result.pass_count == 1
    assert not result.executable_coverage_complete
    assert not result.cases and not result.accepted_cases
    assert len(result.unresolved_cases) == 1
    assert result.coverage.requirements[0].status == CoverageStatus.UNCOVERED


def test_existing_manual_intent_is_not_executable_coverage(monkeypatch):
    original = plan_coverage(analyze_coverage([], [], flows=sources(1))).cases
    monkeypatch.setattr(loop, "run_coverage_resolution_pass", fake_pass)
    result = loop.run_coverage_loop([], original, flows=sources(1))
    assert result.executable_coverage_complete
    assert len(result.cases) == 2
    assert result.cases[0].id == "TC_COV_001" and result.cases[0].execution == "manual"
    assert result.accepted_cases[0].id == "TC_COV_002"
    assert result.history[0].before.requirements[0].status == CoverageStatus.UNCOVERED
    assert result.intent_coverage.requirements[0].status == CoverageStatus.COVERED


def test_original_manual_cases_can_have_only_intent_coverage():
    original = plan_coverage(analyze_coverage([], [], flows=sources(1))).cases
    result = loop.run_coverage_loop([], original, flows=sources(1))
    assert not result.executable_coverage_complete
    assert result.intent_coverage.requirements[0].status == CoverageStatus.COVERED
    assert result.coverage.requirements[0].status == CoverageStatus.UNCOVERED
    assert result.cases == original
    assert result.pass_count == 1


@pytest.mark.parametrize("requirements", [[], [{"id": "NFR-1", "kind": "non_functional",
                                               "statement": "Make it fast"}]])
def test_no_generatable_source_stops_without_pass(monkeypatch, requirements):
    monkeypatch.setattr(loop, "run_coverage_resolution_pass",
                        lambda *a, **kw: pytest.fail("No explicit obligations"))
    result = loop.run_coverage_loop(requirements)
    assert result.stop_reason == "NO_GENERATABLE_OBLIGATIONS"
    assert not result.executable_coverage_complete
    assert result.pass_count == 0


def test_unassessable_existing_mapped_case_does_not_claim_completion(monkeypatch):
    initial = fake_pass(analyze_coverage([], [], flows=sources(1)), [], module="COV",
                        reserved_case_ids=()).accepted_cases
    initial[0].steps[-1].args["pattern"] = r"/page-\d+"
    monkeypatch.setattr(loop, "run_coverage_resolution_pass",
                        lambda *a, **kw: pytest.fail("Unproven mapped intent must not be guessed"))
    result = loop.run_coverage_loop([], initial, flows=sources(1))
    assert not result.executable_coverage_complete
    assert result.coverage.requirements[0].status == CoverageStatus.UNASSESSABLE
    assert result.stop_reason == "NO_GENERATABLE_OBLIGATIONS"


def test_known_coverage_plus_unknown_source_cannot_complete(monkeypatch):
    monkeypatch.setattr(loop, "run_coverage_resolution_pass", fake_pass)
    result = loop.run_coverage_loop([{"id": "NFR-1", "kind": "non_functional"}],
                                    flows=sources(1), max_passes=1)
    assert len(result.accepted_cases) == 1
    assert not result.executable_coverage_complete
    assert result.stop_reason == "NO_GENERATABLE_OBLIGATIONS"


def test_max_pass_limit_with_partial_progress(monkeypatch):
    def run(report, existing_cases, **kwargs):
        return fake_pass(report, existing_cases, accept_count=1, **kwargs)

    monkeypatch.setattr(loop, "run_coverage_resolution_pass", run)
    result = loop.run_coverage_loop([], flows=sources(4), max_passes=2)
    assert result.stop_reason == "MAX_PASSES"
    assert result.pass_count == 2
    assert len(result.accepted_cases) == 2
    assert len(result.coverage.missing_obligations) == 2
    assert len(result.unresolved_cases) == 2  # latest attempts; full older history retained


def test_later_failure_retains_accepted_cases(monkeypatch):
    calls = []

    def run(report, existing_cases, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            existing_cases[0].steps[0].args["url"] = "/corrupted"
            raise RuntimeError("token=PRIVATE")
        return fake_pass(report, existing_cases, accept_count=1, **kwargs)

    monkeypatch.setattr(loop, "run_coverage_resolution_pass", run)
    result = loop.run_coverage_loop([], flows=sources())
    assert result.stop_reason == "NO_PROGRESS"
    assert result.pass_count == 2
    assert result.history[-1].resolution is None
    assert result.cases[0].steps[0].args == {"url": "/page-1"}
    assert len(result.accepted_cases) == 1
    assert result.coverage.requirements[0].status == CoverageStatus.PARTIALLY_COVERED
    assert result.issues[0].code == "PASS_FAILED"
    assert "PRIVATE" not in repr(result.issues)


def test_false_executable_claim_never_counts(monkeypatch):
    def run(report, existing_cases, **kwargs):
        result = fake_pass(report, existing_cases, accept_count=0, **kwargs)
        records = tuple(replace(item, executability=replace(item.executability, executable=True))
                        for item in result.case_results)
        return replace(result, case_results=records)

    monkeypatch.setattr(loop, "run_coverage_resolution_pass", run)
    result = loop.run_coverage_loop([], flows=sources(1))
    assert not result.cases
    assert not result.executable_coverage_complete
    assert result.issues[0].code == "INVALID_ACCEPTED_CASE"
    assert len(result.unresolved_cases) == 1


def test_inputs_and_pass_history_are_detached(monkeypatch):
    source = sources()
    original = plan_coverage(analyze_coverage([], [], flows=source)).cases
    evidence = ui_map()
    snapshot = deepcopy((source, original, evidence))
    monkeypatch.setattr(loop, "run_coverage_resolution_pass", fake_pass)
    result = loop.run_coverage_loop([], original, flows=source, ui_map=evidence)
    assert (source, original, evidence) == snapshot
    result.cases[-1].steps[0].args["url"] = "/changed"
    assert result.accepted_cases[-1].steps[0].args["url"] != "/changed"
    assert result.history[0].resolution.accepted_cases[-1].steps[0].args["url"] != "/changed"
    assert (source, original, evidence) == snapshot


@pytest.mark.parametrize("name,value", [("max_passes", 0), ("max_passes", True),
                                       ("max_passes", 1.5), ("max_cycles", -1)])
def test_invalid_limits_fail_before_work(name, value):
    with pytest.raises(ValueError, match="positive integer"):
        loop.run_coverage_loop([], **{name: value})

"""Standalone orchestration with offline model completions and pass stubs."""
from copy import deepcopy
from dataclasses import replace

import pytest

import qctool.coverage_loop as coverage_loop
import qctool.generation as generation
from qctool.coverage import CoverageStatus
from qctool.executability import analyze_executability
from qctool.testcase import Step, StepKind, TestCase
from tests.test_coverage_loop import fake_pass, sources
from tests.test_coverage_resolution import RepairLLM, contexts_for, flows, report, ui_map


def executable_case():
    return TestCase("TC_LOGIN_001", "LOGIN", "Login page", "Open login", traces_to=["FLOW-1"],
                    source_quote="Open /login → URL /login", steps=[
                        Step(1, StepKind.WHEN, "ui.goto", {"url": "/login"}),
                        Step(2, StepKind.THEN, "assert.url_matches", {"pattern": "/login"})])


def test_already_complete_executable_suite_skips_generation(monkeypatch):
    monkeypatch.setattr(coverage_loop, "run_coverage_resolution_pass",
                        lambda *a, **kw: pytest.fail("Already complete"))
    existing = executable_case()
    result = generation.run_generation([], [existing], flows=flows())
    assert result.success and result.status == "SUCCESS"
    assert result.executable_cases == (existing,)
    assert result.cases == (existing,)
    assert not result.generated_cases and not result.unresolved_cases
    assert result.history == ()
    assert result.coverage_loop.pass_count == 0
    assert result.validation.ok


def test_missing_obligation_generated_and_resolved_with_real_loop():
    adapter = RepairLLM()
    result = generation.run_generation([], flows=flows(), resolution_llm=adapter,
                                       ui_map=ui_map(), contexts=contexts_for(report()))
    assert result.success
    assert len(result.generated_cases) == len(result.executable_cases) == 1
    assert result.accepted_generated_cases == result.generated_cases
    assert analyze_executability(result.executable_cases[0]).executable
    assert result.coverage.requirements[0].status == CoverageStatus.COVERED
    assert result.intent_coverage.requirements[0].status == CoverageStatus.COVERED
    cycle = result.history[0].resolution.case_results[0].resolution.cycles[0]
    assert len(cycle.deterministic.changes) == 2
    assert cycle.application is None
    assert not adapter.prompts
    assert result.history[0].resolution.audit[0].obligation.source.source_id == "FLOW-1"


def test_unresolved_generated_case_remains_separate():
    result = generation.run_generation([], flows=flows())
    assert not result.success and result.status == "INCOMPLETE_COVERAGE"
    assert not result.executable_cases and not result.accepted_generated_cases
    assert len(result.generated_cases) == len(result.unresolved_cases) == len(result.cases) == 1
    assert result.cases[0].execution == "manual"
    assert result.issues
    assert any(i.code == "NO_SAFE_CAPABILITY" and i.testcase_id == "TC_COV_001"
               and i.pass_number == 1 for i in result.issues)


def test_partial_executable_coverage(monkeypatch):
    def run(report, existing_cases, **kwargs):
        return fake_pass(report, existing_cases, accept_count=1, **kwargs)

    monkeypatch.setattr(coverage_loop, "run_coverage_resolution_pass", run)
    result = generation.run_generation([], flows=sources(), max_passes=1)
    assert result.status == "INCOMPLETE_COVERAGE"
    assert not result.success
    assert len(result.executable_cases) == len(result.accepted_generated_cases) == 1
    assert len(result.unresolved_cases) == 1
    assert len(result.generated_cases) == 2
    assert result.coverage.requirements[0].status == CoverageStatus.PARTIALLY_COVERED


def test_unassessable_requirement_prevents_false_success():
    req = [{"id": "NFR-1", "kind": "non_functional", "statement": "Fast and secure"}]
    result = generation.run_generation(req, [executable_case()], flows=flows())
    assert not result.success and result.status == "UNASSESSABLE_COVERAGE"
    assert len(result.executable_cases) == 1
    assert result.coverage.requirements[0].status == CoverageStatus.UNASSESSABLE
    assert result.history == ()


def test_mapped_assertion_with_unproven_intent_is_not_success():
    case = executable_case()
    case.steps[-1].args["pattern"] = r"/log.*"
    result = generation.run_generation([], [case], flows=flows())
    assert len(result.executable_cases) == 1
    assert result.status == "UNASSESSABLE_COVERAGE"
    assert not result.success


def test_existing_executable_and_manual_cases_preserved():
    existing = executable_case()
    manual = TestCase("TC_OTHER_001", "OTHER", "Manual", "Manual", execution="manual",
                      traces_to=["OTHER"], source_quote="Check manually", steps=[
                          Step(1, StepKind.THEN, "assert.unmapped", {"expected": "Check manually"})])
    result = generation.run_generation([], [existing, manual], flows=flows())
    assert result.success
    assert result.cases == (existing, manual)
    assert result.executable_cases == (existing,)
    assert result.unresolved_cases == (manual,)
    assert not result.generated_cases


def test_invalid_existing_case_prevents_success_and_model_work(monkeypatch):
    case = executable_case()
    case.source_quote = ""
    monkeypatch.setattr(generation, "run_coverage_loop",
                        lambda *a, **kw: pytest.fail("Invalid input batch"))
    result = generation.run_generation([], [case], flows=flows())
    assert result.status == "INVALID_TESTCASES"
    assert not result.success and not result.validation.ok
    assert result.coverage_loop is None
    assert result.cases == (case,)
    assert result.unresolved_cases == (case,)
    assert not result.executable_cases
    assert result.issues[0].code == "INVALID_TESTCASE"


def test_duplicate_ids_are_reported_as_invalid_without_mutation():
    case = executable_case()
    result = generation.run_generation([], [case, deepcopy(case)], flows=flows())
    assert not result.success
    assert result.status == "INVALID_TESTCASES"
    assert result.coverage_loop is None
    assert len(result.cases) == 2


def test_generation_failure_preserves_existing_cases(monkeypatch):
    def fail(requirements, cases, **kwargs):
        cases[0].steps[0].args["url"] = "/changed"
        raise RuntimeError("token=PRIVATE")

    monkeypatch.setattr(generation, "run_coverage_loop", fail)
    existing = executable_case()
    result = generation.run_generation([], [existing], flows=flows())
    assert not result.success and result.status == "FAILED"
    assert result.cases == result.executable_cases == (existing,)
    assert result.issues[0].code == "GENERATION_FAILED"
    assert "PRIVATE" not in repr(result.issues)


def test_inputs_and_output_history_are_detached():
    requirements = {"requirements": [], "flows": flows()}
    existing = []
    evidence = ui_map()
    contexts = contexts_for(report())
    snapshot = deepcopy((requirements, existing, evidence, contexts))
    result = generation.run_generation(requirements, existing, ui_map=evidence,
                                       contexts=contexts, resolution_llm=RepairLLM())
    assert result.success
    assert (requirements, existing, evidence, contexts) == snapshot
    result.cases[0].steps[0].args["url"] = "/changed"
    assert result.executable_cases[0].steps[0].args["url"] == "/login"
    assert result.generated_cases[0].steps[0].args["url"] == "/login"
    assert result.coverage_loop.cases[0].steps[0].args["url"] == "/login"
    assert (requirements, existing, evidence, contexts) == snapshot


def test_empty_source_is_not_success():
    result = generation.run_generation([])
    assert result.status == "UNASSESSABLE_COVERAGE"
    assert not result.success


def test_nonexecutable_accepted_claim_cannot_make_generation_success(monkeypatch):
    existing = executable_case()
    template = coverage_loop.run_coverage_loop([], [existing], flows=flows())
    alleged_generated = deepcopy(existing)
    alleged_generated.execution = "manual"
    monkeypatch.setattr(generation, "run_coverage_loop", lambda *a, **kw: replace(
        template, cases=(alleged_generated,), accepted_cases=(alleged_generated,)))
    result = generation.run_generation([], flows=flows())
    assert result.status == "FAILED"
    assert not result.success and not result.executable_cases
    assert len(result.unresolved_cases) == 1
    assert any(i.code == "GENERATED_CASE_NOT_EXECUTABLE" for i in result.issues)


@pytest.mark.parametrize("name,value", [("max_passes", 0), ("max_cycles", True)])
def test_invalid_limits_are_configuration_errors(name, value):
    with pytest.raises(ValueError, match="positive integer"):
        generation.run_generation([], **{name: value})

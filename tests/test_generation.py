"""Standalone orchestration with offline model completions and pass stubs."""
from copy import deepcopy
from dataclasses import replace

import pytest

import qctool.generation as generation
from qctool.core.coverage import CoverageStatus
from qctool.core.executability import analyze_executability
from qctool.core.testcase import Step, StepKind, TestCase
from tests.fixture_samples import flows


def executable_case():
    return TestCase("TC_LOGIN_001", "LOGIN", "Login page", "Open login", traces_to=["FLOW-1"],
                    source_quote="Open /login → URL /login", steps=[
                        Step(1, StepKind.WHEN, "ui.goto", {"url": "/login"}),
                        Step(2, StepKind.THEN, "assert.url_matches", {"pattern": "/login"})])


def test_unresolved_generated_case_remains_separate():
    result = generation.run_generation([], flows=flows())
    assert not result.success and result.status == "INCOMPLETE_COVERAGE"
    assert not result.executable_cases and not result.accepted_generated_cases
    assert len(result.generated_cases) == len(result.unresolved_cases) == len(result.cases) == 1
    assert result.cases[0].execution == "manual"
    assert result.issues
    assert any(i.code == "AUTHORING_UNAVAILABLE" for i in result.issues)


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
    llm = __import__("unittest.mock", fromlist=["Mock"]).Mock()
    llm.chat.side_effect = AssertionError("Invalid input batch must not call model")
    result = generation.run_generation([], [case], flows=flows())
    assert result.status == "INVALID_TESTCASES"
    assert not result.success and not result.validation.ok
    assert not result.agent_history
    assert result.cases == (case,)
    assert result.unresolved_cases == (case,)
    assert not result.executable_cases
    assert result.issues[0].code == "INVALID_TESTCASE"


def test_duplicate_ids_are_reported_as_invalid_without_mutation():
    case = executable_case()
    result = generation.run_generation([], [case, deepcopy(case)], flows=flows())
    assert not result.success
    assert result.status == "INVALID_TESTCASES"
    assert not result.agent_history
    assert len(result.cases) == 2


def test_empty_source_is_not_success():
    result = generation.run_generation([])
    assert result.status == "UNASSESSABLE_COVERAGE"
    assert not result.success

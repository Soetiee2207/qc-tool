"""Planner logic từ nghĩa vụ nguồn, không sinh kỳ vọng mới."""
from copy import deepcopy
from dataclasses import replace
import json

from qctool.coverage import (
    CoverageReport, CoverageStatus, analyze_coverage,
)
from qctool.coverage_plan import plan_coverage
from qctool.generate.from_openapi import IdAllocator
from qctool.generate.from_requirements import generate_from_acceptance
from qctool.testcase import CaseType, Step, StepKind, TestCase


def requirement(id="AC-1", **extra):
    return {"id": id, "kind": "acceptance_criterion", "title": "Login",
            "given": "Valid account", "when": "Submit login", "then": "Dashboard opens",
            "source": {"file": "srs.md", "line": 12, "quote": "Login criterion"}, **extra}


def test_missing_happy_path_generates_one_logical_case():
    flows = {"flow": [{"id": "FLOW-1", "steps": [
        {"action": "Open login", "expected": "Login shown"}]}]}
    report = analyze_coverage([], [], flows=flows)
    plan = plan_coverage(report)
    assert len(plan.cases) == 1
    case = plan.cases[0]
    assert case.case_type == CaseType.POSITIVE
    assert case.execution == "manual"
    assert case.generated_by == "engine"
    assert case.traces_to == ["FLOW-1"]
    assert [s.action for s in case.steps] == ["perform.unmapped", "assert.unmapped"]
    case.validate()
    assert analyze_coverage([], plan.cases, flows=flows).requirements[0].status == CoverageStatus.COVERED


def test_missing_negative_outcome_preserves_condition_without_invented_action():
    req = {"id": "FR-1", "kind": "functional", "api": {"error_handling": [
        {"condition": "Refresh fails", "behavior": "Session cleared"}]}}
    plan = plan_coverage(analyze_coverage([req], []))
    case = plan.cases[0]
    assert case.case_type == CaseType.NEGATIVE
    assert [(s.kind, s.args) for s in case.steps] == [
        (StepKind.GIVEN, {"description": "Refresh fails"}),
        (StepKind.THEN, {"expected": "Session cleared"})]
    assert analyze_coverage([req], plan.cases).requirements[0].status == CoverageStatus.COVERED


def test_role_and_state_branch_metadata_round_trip():
    flows = {"scenario": [{"id": "SCEN-1", "from_state": "viewer", "action": "Open record",
                            "result": "Delete hidden"}],
             "transition": [{"id": "STATE-1", "from_state": "draft", "to_state": "active",
                             "trigger": "Publish"}]}
    plan = plan_coverage(analyze_coverage([], [], flows=flows))
    role, state = plan.cases
    assert role.preconditions == ["Vai trò: viewer"]
    assert role.test_data == {"vai trò": "viewer"}
    assert role.steps[-1].args == {"expected": "Delete hidden"}
    assert state.preconditions == ["Trạng thái hiện tại: draft"]
    assert state.steps[1].args == {"description": "Publish"}
    assert state.steps[-1].args == {"expected": "Chuyển sang trạng thái «active»"}
    assert all(r.status == CoverageStatus.COVERED for r in
               analyze_coverage([], plan.cases, flows=flows).requirements)


def test_yes_no_with_identical_text_are_not_deduplicated():
    flows = {"decision": [{"id": "DEC-1", "condition": "Allowed", "flow": "Open page",
                           "yes": "Page shown", "no": "Page shown"}]}
    report = analyze_coverage([], [], flows=flows)
    plan = plan_coverage(report)
    assert len(plan.cases) == 2
    assert [c.test_data for c in plan.cases] == [{"nhánh": "đúng"}, {"nhánh": "sai"}]
    assert analyze_coverage([], plan.cases, flows=flows).requirements[0].status == CoverageStatus.COVERED


def test_already_covered_obligation_generates_nothing():
    req = requirement()
    existing = generate_from_acceptance([req], IdAllocator(), "COV").cases
    plan = plan_coverage(analyze_coverage([req], existing), existing_cases=existing)
    assert plan.cases == plan.links == plan.skipped == ()


def test_unassessable_obligation_is_skipped():
    req = requirement()
    case = TestCase("TC_COV_001", "COV", "Login", "Login", traces_to=["AC-1"],
                    steps=[Step(1, StepKind.THEN, "assert.visible", {"target": "dashboard"})])
    report = analyze_coverage([req], [case])
    plan = plan_coverage(report)
    assert not plan.cases
    assert plan.skipped[0].code == "UNASSESSABLE"


def test_absent_branch_metadata_is_unresolved():
    flows = {"decision": [{"id": "DEC-1", "condition": "Allowed", "flow": "Open page", "yes": "Shown"}]}
    report = analyze_coverage([], [], flows=flows)
    row = report.requirements[0]
    report = CoverageReport((replace(row, obligations=(replace(row.obligations[0], test_data=()),)),))
    plan = plan_coverage(report)
    assert not plan.cases
    assert plan.skipped[0].code == "UNSUPPORTED_OBLIGATION"


def test_no_invented_outcome_or_setup_for_bare_acceptance():
    req = {"id": "FR-1", "kind": "functional", "acceptance": ["Age = 17 is rejected"]}
    plan = plan_coverage(analyze_coverage([req], []))
    assert len(plan.cases[0].steps) == 1
    assert plan.cases[0].steps[0].args == {"expected": "Age = 17 is rejected"}
    assert plan.cases[0].preconditions == []
    assert plan.cases[0].test_data == {}


def test_missing_expected_value_skipped_without_guessing():
    report = analyze_coverage([requirement()], [])
    row = report.requirements[0]
    report = CoverageReport((replace(row, obligations=(replace(row.obligations[0], expected=""),)),))
    plan = plan_coverage(report)
    assert not plan.cases
    assert plan.skipped[0].reason == "No explicit expected outcome"


def test_incomplete_state_structure_is_skipped():
    flows = {"transition": [{"id": "STATE-1", "from_state": "draft", "to_state": "active",
                             "trigger": "Publish"}]}
    report = analyze_coverage([], [], flows=flows)
    row = report.requirements[0]
    report = CoverageReport((replace(row, obligations=(replace(row.obligations[0], action=""),)),))
    plan = plan_coverage(report)
    assert not plan.cases
    assert plan.skipped[0].code == "UNSUPPORTED_OBLIGATION"


def test_duplicate_missing_intent_shares_candidate_and_all_provenance():
    rows = [requirement(), requirement("AC-2", source={"file": "other.md", "line": 5, "quote": "Same outcome"})]
    plan = plan_coverage(analyze_coverage(rows, []))
    assert len(plan.cases) == 1
    assert plan.cases[0].traces_to == ["AC-1", "AC-2"]
    assert plan.obligation_to_testcase == {"AC-1:then": "TC_COV_001", "AC-2:then": "TC_COV_001"}
    assert plan.links[1].obligation.source.file == "other.md"
    assert all(r.status == CoverageStatus.COVERED for r in analyze_coverage(rows, plan.cases).requirements)


def test_covered_intent_is_not_cloned_for_unrelated_trace():
    rows = [requirement(), requirement("AC-2")]
    existing = generate_from_acceptance(rows[:1], IdAllocator(), "COV").cases
    plan = plan_coverage(analyze_coverage(rows, existing), existing_cases=existing)
    assert not plan.cases
    assert plan.skipped[0].code == "COVERED_INTENT"
    assert existing[0].traces_to == ["AC-1"]  # unrelated requirement stays unresolved


def test_stale_report_existing_intent_is_reused_and_not_mutated():
    req = requirement()
    report = analyze_coverage([req], [])
    existing = generate_from_acceptance([req], IdAllocator(), "COV").cases
    snapshot = deepcopy(existing)
    plan = plan_coverage(report, existing_cases=existing)
    assert not plan.cases
    assert plan.links[0].generated is False
    assert plan.links[0].testcase_id == existing[0].id
    assert plan.skipped[0].code == "EXISTING_INTENT"
    assert existing == snapshot


def test_inputs_unchanged_and_audit_is_serializable():
    req = requirement()
    report = analyze_coverage([req], [])
    unrelated = TestCase("TC_COV_001", "COV", "Other", "Other", traces_to=["OTHER"])
    snapshot = deepcopy((report, req, unrelated))
    plan = plan_coverage(report, existing_cases=[unrelated])
    assert plan.cases[0].id == "TC_COV_002"
    assert plan.cases[0].source_quote == "Login criterion"
    assert plan.cases[0].source_ref == "srs.md:12"
    assert plan.links[0].obligation.id == "AC-1:then"
    assert plan.links[0].obligation.source.field == "then"
    assert (report, req, unrelated) == snapshot
    dumped = json.loads(json.dumps(plan.to_dict()))
    assert dumped["links"][0]["obligation"]["source"]["file"] == "srs.md"
    plan.cases[0].steps[-1].args["expected"] = "Changed"
    assert (report, req, unrelated) == snapshot


def test_repeated_planning_and_parent_summary_are_deterministic():
    rows = [{"id": "US-1", "kind": "user_story"}, requirement(belongs_to="US-1")]
    report = analyze_coverage(rows, [])
    first, second = plan_coverage(report), plan_coverage(report)
    assert first == second
    assert len(first.cases) == 1
    assert len(first.links) == 1

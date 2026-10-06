"""Độ phủ nguồn tường minh, không đồng nhất với testcase chạy được."""
from copy import deepcopy
import json

import pytest

from qctool.coverage import CoverageStatus as Status, analyze_coverage
from qctool.generate.from_flows import generate_from_flows
from qctool.generate.from_functions import generate_from_functions
from qctool.generate.from_openapi import IdAllocator
from qctool.generate.from_requirements import generate_from_acceptance
from qctool.model import Requirement, SourceRef
from qctool.testcase import CaseType, Step, StepKind, TestCase as Case


def ac(id="AC-1", **overrides):
    return {"id": id, "kind": "acceptance_criterion", "title": "Login",
            "given": "Valid account", "when": "Submit login", "then": "Dashboard opens",
            "source": {"file": "srs.md", "line": 10, "quote": "Login outcome"},
            **overrides}


def cases_for(rows):
    return generate_from_acceptance(rows, IdAllocator(), "COV").cases


def test_fully_covered_requirement_and_provenance():
    req = ac(source_ids=["AUTH-1"])
    cases = cases_for([req])
    result = analyze_coverage([req], cases)
    r = result.requirements[0]
    assert r.status == Status.COVERED
    assert r.obligations[0].testcase_ids == (cases[0].id,)
    assert r.obligations[0].source.file == "srs.md"
    assert r.obligations[0].source.line == 10
    assert r.obligations[0].source.source_ids == ("AUTH-1",)
    assert not result.missing_obligations
    assert cases[0].execution == "manual"  # logical coverage, not Pass/executability


def test_uncovered_requirement():
    report = analyze_coverage([ac()], [])
    assert report.requirements[0].status == Status.UNCOVERED
    assert report.missing_obligations[0].id == "AC-1:then"


def test_parent_story_partial_multi_outcome():
    rows = [{"id": "US-1", "kind": "user_story", "title": "Login"},
            ac(belongs_to="US-1"), ac("AC-2", belongs_to="US-1", then="Error shown")]
    report = analyze_coverage(rows, cases_for([rows[1]]))
    assert report.requirements[0].status == Status.PARTIALLY_COVERED
    assert [o.status for o in report.requirements[0].obligations] == [Status.COVERED, Status.UNCOVERED]
    assert report.requirements[2].status == Status.UNCOVERED
    assert len(report.missing_obligations) == 1


def test_role_permission_scenario_uses_explicit_role_metadata():
    flows = {"scenario": [{"id": "SCEN-1", "from_state": "viewer", "action": "Open record",
                           "rule": "Read only", "result": "Delete is hidden"}]}
    cases = generate_from_flows(flows, IdAllocator(), "COV")
    report = analyze_coverage([], cases, flows=flows)
    assert report.requirements[0].status == Status.COVERED
    assert report.requirements[0].obligations[0].kind == "permission_role"
    cases[0].test_data["vai trò"] = "admin"
    assert analyze_coverage([], cases, flows=flows).requirements[0].status == Status.UNCOVERED


def test_decision_yes_does_not_cover_no_even_if_same_expected():
    flows = {"decision": [{"id": "DEC-1", "condition": "Has permission", "flow": "Open page",
                           "yes": "Page displayed", "no": "Page displayed"}]}
    cases = generate_from_flows(flows, IdAllocator(), "COV")
    report = analyze_coverage([], cases[:1], flows=flows)
    assert report.requirements[0].status == Status.PARTIALLY_COVERED
    assert [o.status for o in report.requirements[0].obligations] == [Status.COVERED, Status.UNCOVERED]
    assert analyze_coverage([], cases, flows=flows).requirements[0].status == Status.COVERED


def test_boundary_prose_does_not_invent_obligations_or_accept_case_type_as_proof():
    req = {"id": "FR-1", "kind": "functional", "title": "Age",
           "api": {"request": [{"field": "age", "type": "integer", "description": "18 to 65"}]}}
    case = Case("TC_COV_001", "COV", "Age boundary", "Check age", traces_to=["FR-1"],
                case_type=CaseType.BOUNDARY)
    result = analyze_coverage([req], [case]).requirements[0]
    assert result.status == Status.UNASSESSABLE
    assert result.obligations == ()


def test_explicit_boundary_acceptance_outcome_can_be_assessed_without_parsing_limits():
    req = ac(given="Age = 17", when="Submit age", then="Age rejected")
    cases = cases_for([req])
    cases[0].case_type = CaseType.BOUNDARY
    assert analyze_coverage([req], cases).requirements[0].status == Status.COVERED


def test_unrelated_trace_does_not_count_even_with_identical_content():
    cases = cases_for([ac("AC-OTHER")])
    assert analyze_coverage([ac()], cases).requirements[0].status == Status.UNCOVERED


@pytest.mark.parametrize("req", [
    {"id": "X", "kind": "unknown", "statement": "Make it good"},
    {"id": "X", "kind": "non_functional", "statement": "Fast and secure"},
    ac("X", given=""),
])
def test_unknown_or_incomplete_source(req):
    result = analyze_coverage([req], []).requirements[0]
    assert result.status == Status.UNASSESSABLE
    assert result.reason
    assert not result.obligations


def test_trace_alone_cannot_prove_mapped_assertion_semantics():
    case = cases_for([ac()])[0]
    case.steps[-1] = Step(3, StepKind.THEN, "assert.visible", {"target": "dashboard"})
    for step in case.steps:
        step.args.pop("expectation", None)
    report = analyze_coverage([ac()], [case])
    assert report.requirements[0].status == Status.UNASSESSABLE
    assert not report.missing_obligations
    assert len(report.unassessable_obligations) == 1


def test_functional_error_rows_are_independent_obligations():
    req = {"id": "FR-1", "kind": "functional", "title": "Login", "api": {
        "error_handling": [{"condition": "Timeout", "behavior": "Retry offered"},
                           {"condition": "Refresh fails", "behavior": "Session cleared"}]}}
    cases = generate_from_functions([req], IdAllocator(), "COV")
    report = analyze_coverage([req], cases[:1])
    assert report.requirements[0].status == Status.PARTIALLY_COVERED
    assert report.missing_obligations[0].expected == "Session cleared"
    assert all(o.kind == "negative_error" for o in report.requirements[0].obligations)


def test_flow_intermediate_outcome_and_state_transition():
    flows = {"flow": [{"id": "FLOW-1", "steps": [
        {"action": "Open login", "expected": "Login shown"},
        {"action": "Submit login", "expected": "Dashboard shown"}]}],
        "transition": [{"id": "STATE-1", "from_state": "draft", "to_state": "active", "trigger": "Publish"}]}
    cases = generate_from_flows(flows, IdAllocator(), "COV")
    report = analyze_coverage([], cases, flows={"feature": flows})
    assert all(r.status == Status.COVERED for r in report.requirements)
    assert [o.kind for o in report.requirements[0].obligations] == ["happy_path", "happy_path"]
    assert report.requirements[1].obligations[0].kind == "state_outcome"


def test_explicit_acceptance_list_multiple_outcomes():
    req = {"id": "FR-1", "kind": "functional", "acceptance": ["Saved", "Notification sent"]}
    case = Case("TC_COV_001", "COV", "Save", "Save", traces_to=["FR-1"],
                steps=[Step(1, StepKind.THEN, "assert.unmapped", {"expected": "Saved"})])
    report = analyze_coverage([req], [case])
    assert report.requirements[0].status == Status.PARTIALLY_COVERED
    assert report.missing_obligations[0].expected == "Notification sent"


def test_input_and_serialization_immutability_with_native_requirement():
    req = Requirement("AC-1", "acceptance_criterion", "Login", given="Valid account",
                      when="Submit login", then="Dashboard opens", source=SourceRef("srs.md", 10, "Login outcome"))
    cases = cases_for([req.to_dict()])
    flows = {"decision": [{"id": "DEC-1", "condition": "Allowed", "flow": "Open", "yes": "Visible", "no": "Hidden"}]}
    snapshot = deepcopy((req, cases, flows))
    report = analyze_coverage([req], cases, flows=flows)
    assert (req, cases, flows) == snapshot
    serialized = report.to_dict()
    assert json.loads(json.dumps(serialized))["requirements"][0]["status"] == "covered"
    serialized["requirements"][0]["source"]["file"] = "changed"
    assert report.requirements[0].source.file == "srs.md"
    assert (req, cases, flows) == snapshot


def test_duplicate_source_ids_rejected():
    with pytest.raises(ValueError, match="unique"):
        analyze_coverage([ac(), ac()], [])

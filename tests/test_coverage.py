"""Độ phủ nguồn tường minh, không đồng nhất với testcase chạy được."""
from copy import deepcopy
import json

import pytest

from qctool.core.coverage import CoverageStatus as Status, analyze_coverage
from qctool.generate.from_openapi import IdAllocator
from qctool.core.model import Requirement, SourceRef
from qctool.core.testcase import CaseType, Step, StepKind, TestCase as Case


def ac(id="AC-1", **overrides):
    return {"id": id, "kind": "acceptance_criterion", "title": "Login",
            "given": "Valid account", "when": "Submit login", "then": "Dashboard opens",
            "source": {"file": "srs.md", "line": 10, "quote": "Login outcome"},
            **overrides}


def test_uncovered_requirement():
    report = analyze_coverage([ac()], [])
    assert report.requirements[0].status == Status.UNCOVERED
    assert report.missing_obligations[0].id == "AC-1:then"


def test_boundary_prose_does_not_invent_obligations_or_accept_case_type_as_proof():
    req = {"id": "FR-1", "kind": "functional", "title": "Age",
           "api": {"request": [{"field": "age", "type": "integer", "description": "18 to 65"}]}}
    case = Case("TC_COV_001", "COV", "Age boundary", "Check age", traces_to=["FR-1"],
                case_type=CaseType.BOUNDARY)
    result = analyze_coverage([req], [case]).requirements[0]
    assert result.status == Status.UNASSESSABLE
    assert result.obligations == ()


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


def test_explicit_acceptance_list_multiple_outcomes():
    req = {"id": "FR-1", "kind": "functional", "acceptance": ["Saved", "Notification sent"]}
    case = Case("TC_COV_001", "COV", "Save", "Save", traces_to=["FR-1"],
                steps=[Step(1, StepKind.THEN, "assert.unmapped", {"expected": "Saved"})])
    report = analyze_coverage([req], [case])
    assert report.requirements[0].status == Status.PARTIALLY_COVERED
    assert report.missing_obligations[0].expected == "Notification sent"


def test_duplicate_source_ids_rejected():
    with pytest.raises(ValueError, match="unique"):
        analyze_coverage([ac(), ac()], [])

"""Exact application of validated repairs, with no caller mutation."""

from copy import deepcopy

import pytest

from qctool.apply_resolution import apply_validated_resolution
from qctool.executability import analyze_executability
from qctool.llm_resolution import (
    EvidenceReference, ProposedChange, ResolutionProposal, UnresolvedGap,
)
from qctool.proposal_validation import validate_resolution_proposal
from qctool.resolution_context import build_resolution_context
from qctool.testcase import Step, StepKind, TestCase
from qctool.ui.crawl import Element, PageMap, UIMap


PAGE = "https://portal.test/login"
UI_EVIDENCE = (EvidenceReference("ui-map", {"page": PAGE, "test_id": "btn-login"}),)


def _case(*, manual: bool = False, two_actions: bool = False) -> TestCase:
    steps = [
        Step(1, StepKind.WHEN, "ui.goto", {"url": "/login"}),
        Step(2, StepKind.WHEN, "perform.unmapped", {"description": "Click Login"}),
    ]
    if two_actions:
        steps.append(Step(3, StepKind.WHEN, "perform.unmapped",
                          {"description": "Click Save"}))
    steps.append(Step(4 if two_actions else 3, StepKind.THEN, "assert.unmapped",
                      {"expected": "Login hidden"}))
    return TestCase(
        id="TC_LOGIN_001", module="LOGIN", title="Login", objective="Check login",
        traces_to=["FR-LOGIN-001"], source_quote="After clicking Login, Login hidden",
        steps=steps, execution="manual" if manual else "auto",
    )


def _context(case: TestCase):
    ui_map = UIMap("https://portal.test", "now", [PageMap(PAGE, "Login", elements=[
        Element("btn-login", "button", "Login", "button", test_id="btn-login"),
        Element("btn-save", "button", "Save", "button", test_id="btn-save"),
    ])])
    return build_resolution_context(
        case, analyze_executability(case).gaps, ui_map=ui_map,
        requirements=[{
            "id": "FR-LOGIN-001", "kind": "functional",
            "statement": "After clicking Login, Login hidden",
        }],
    )


def _click(*, step_seq: int = 2, target: str = "btn-login") -> ProposedChange:
    return ProposedChange(
        step_seq, "perform.unmapped", ("UNMAPPED_ACTION",), "ui.click",
        {"target": target}, "Original step says Click Login", UI_EVIDENCE,
    )


def _hidden(step_seq: int = 3) -> ProposedChange:
    return ProposedChange(
        step_seq, "assert.unmapped", ("UNMAPPED_ACTION",), "assert.not_visible",
        {"target": "btn-login"}, "Original expectation says Login hidden", UI_EVIDENCE,
    )


def _validate(case: TestCase, *changes: ProposedChange, unresolved=()):
    proposal = ResolutionProposal(case.id, changes, unresolved)
    return validate_resolution_proposal(proposal, _context(case), case)


def _codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


def test_one_valid_repair_changes_only_detached_step_and_records_provenance():
    case = _case()
    original = deepcopy(case.to_dict())
    validated = _validate(case, _click())
    result = apply_validated_resolution(case, validated)

    assert result.case is not case
    assert case.to_dict() == original
    assert result.case.steps[1].action == "ui.click"
    assert result.case.steps[1].args == {"target": "btn-login"}
    assert result.case.steps[2].action == "assert.unmapped"
    assert len(result.applied_changes) == 1
    audit = result.applied_changes[0].to_dict()
    assert audit["before"] == {"action": "perform.unmapped", "args": {"description": "Click Login"}}
    assert audit["after"] == {"action": "ui.click", "args": {"target": "btn-login"}}
    assert audit["evidence"] == [UI_EVIDENCE[0].to_dict()]
    assert audit["validated_by"] == "deterministic-proposal-validator"
    assert result.after == analyze_executability(result.case)
    assert not result.after.executable


def test_partial_validation_applies_only_valid_change():
    case = _case(two_actions=True)
    bad = _click(step_seq=3, target="invented")
    unresolved = UnresolvedGap("UNMAPPED_ACTION", 4, "Expected result remains unresolved")
    validated = _validate(case, _click(), bad, unresolved=(unresolved,))
    assert validated.status == "PARTIALLY_VALID"
    assert len(validated.rejected_changes) == 1

    result = apply_validated_resolution(case, validated)
    assert [record.change.step_seq for record in result.applied_changes] == [2]
    assert result.case.steps[2].action == "perform.unmapped"
    assert result.case.steps[3].action == "assert.unmapped"
    assert ("UNMAPPED_ACTION", 3) in {(gap.code, gap.step_seq) for gap in result.after.gaps}
    assert ("UNMAPPED_ACTION", 4) in {(gap.code, gap.step_seq) for gap in result.after.gaps}


def test_no_valid_changes_returns_unchanged_detached_copy():
    case = _case()
    validated = _validate(case, _click(target="invented"))
    result = apply_validated_resolution(case, validated)
    assert result.case is not case
    assert result.case.to_dict() == case.to_dict()
    assert result.applied_changes == ()
    assert result.before == result.after


def test_stale_action_is_reported_and_nothing_applied():
    case = _case()
    validated = _validate(case, _click())
    case.steps[1].action = "ui.click"
    case.steps[1].args = {"target": "btn-login"}
    current = deepcopy(case.to_dict())
    result = apply_validated_resolution(case, validated)
    assert {"STALE_TESTCASE", "ACTION_CHANGED"} <= _codes(result)
    assert result.applied_changes == ()
    assert result.case.to_dict() == case.to_dict() == current


def test_stale_arguments_are_detected_even_when_action_matches():
    case = _case()
    validated = _validate(case, _click())
    case.steps[1].args["description"] = "Click something else"
    result = apply_validated_resolution(case, validated)
    assert "STALE_TESTCASE" in _codes(result)
    assert result.applied_changes == ()


def test_all_validated_repairs_can_safely_promote_manual_case():
    case = _case(manual=True)
    validated = _validate(case, _click(), _hidden())
    assert validated.valid_changes == (_click(), _hidden())
    assert not validated.after.executable  # The validator never promotes manual cases.

    result = apply_validated_resolution(case, validated)
    assert result.promoted_to_auto
    assert result.case.execution == "auto"
    assert result.after.executable
    assert result.after.gaps == ()
    assert case.execution == "manual"
    assert case.needs_mapping


def test_remaining_gap_keeps_manual_case_manual():
    case = _case(manual=True)
    validated = _validate(case, _click())
    result = apply_validated_resolution(case, validated)
    assert result.case.execution == "manual"
    assert not result.promoted_to_auto
    assert not result.after.executable
    assert any(gap.code == "UNMAPPED_ACTION" for gap in result.after.gaps)


def test_requires_precondition_prevents_manual_promotion_even_after_mapping():
    case = _case(manual=True)
    case.requires = "A limited-permission account"
    validated = _validate(case, _click(), _hidden())
    result = apply_validated_resolution(case, validated)
    assert len(result.applied_changes) == 2
    assert result.case.execution == "manual"
    assert not result.promoted_to_auto
    assert any(gap.code == "MISSING_PRECONDITION" for gap in result.after.gaps)


def test_explicit_manual_case_without_unmapped_steps_is_not_promoted():
    case = _case(manual=True)
    case.steps[1] = Step(2, StepKind.WHEN, "ui.click", {}, "Click Login")
    case.steps[2] = Step(3, StepKind.THEN, "assert.not_visible", {"target": "btn-login"})
    repair = ProposedChange(2, "ui.click", ("MISSING_LOCATOR",), "ui.click",
                            {"target": "btn-login"}, "Step note says Click Login", UI_EVIDENCE)
    validated = _validate(case, repair)
    assert validated.valid_changes == (repair,)
    result = apply_validated_resolution(case, validated)
    assert result.case.execution == "manual"
    assert not result.promoted_to_auto
    assert not result.after.executable


def test_testcase_mismatch_and_altered_validated_change_are_rejected():
    case = _case()
    validated = _validate(case, _click())
    other = deepcopy(case)
    other.id = "TC_LOGIN_002"
    assert "TESTCASE_MISMATCH" in _codes(apply_validated_resolution(other, validated))

    validated.valid_changes[0].args["target"] = "invented"
    result = apply_validated_resolution(case, validated)
    assert "VALIDATION_RESULT_CHANGED" in _codes(result)
    assert result.applied_changes == ()


def test_raw_proposal_cannot_cross_application_boundary():
    case = _case()
    proposal = ResolutionProposal(case.id, (_click(),), ())
    with pytest.raises(TypeError, match="ProposalValidationResult"):
        apply_validated_resolution(case, proposal)


def test_original_case_and_validation_result_are_unchanged():
    case = _case()
    validated = _validate(case, _click())
    case_before = deepcopy(case.to_dict())
    validation_before = deepcopy(validated)
    result = apply_validated_resolution(case, validated)
    assert result.applied_changes
    assert case.to_dict() == case_before
    assert validated == validation_before

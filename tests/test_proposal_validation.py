"""Untrusted proposal checks use only the supplied case and selected evidence."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from qctool.executability import analyze_executability
from qctool.generate.loader import load_endpoints
from qctool.llm_resolution import (
    EvidenceReference, ProposedChange, ResolutionProposal, UnresolvedGap,
)
from qctool.proposal_validation import validate_resolution_proposal
from qctool.resolution_context import build_resolution_context
from qctool.testcase import Step, StepKind, TestCase
from qctool.ui.crawl import Element, PageMap, UIMap


def _case(*steps: Step, **changes) -> TestCase:
    fields = dict(
        id="TC_LOGIN_001", module="LOGIN", title="Log in", objective="Check login",
        traces_to=["FR-LOGIN-001"], source_quote="Normal user can log in",
        steps=list(steps),
    )
    return TestCase(**{**fields, **changes})


def _step(seq: int, action: str, args: dict | None = None, note: str = "") -> Step:
    return Step(seq, StepKind.THEN if action.startswith("assert.") else StepKind.WHEN,
                action, args or {}, note)


def _ui_map(*, delete: bool = False) -> UIMap:
    elements = [
        Element("btn-login", "button", "Login", "button", test_id="btn-login"),
        Element("btn-save", "button", "Save", "button", test_id="btn-save"),
    ]
    if delete:
        elements.append(Element("btn-delete", "button", "Delete", "button",
                                test_id="btn-delete"))
    return UIMap("https://portal.test", "now", [
        PageMap("https://portal.test/login", "Login", elements=elements),
    ])


def _login_case() -> TestCase:
    return _case(
        _step(1, "ui.goto", {"url": "/login"}),
        _step(2, "perform.unmapped", {"description": "Click Login"}),
        _step(3, "assert.unmapped", {"expected": "Dashboard opens"}),
    )


def _context(case: TestCase, *, ui_map=None, requirements=None, endpoints=None):
    return build_resolution_context(
        case, analyze_executability(case).gaps,
        ui_map=ui_map or _ui_map(),
        requirements=requirements if requirements is not None else [{
            "id": "FR-LOGIN-001", "kind": "functional",
            "statement": "Normal user can log in",
        }],
        endpoints=endpoints,
    )


def _ui_ref(target="btn-login") -> EvidenceReference:
    return EvidenceReference("ui-map", {
        "page": "https://portal.test/login", "test_id": target,
    })


def _change(*, seq=2, from_action="perform.unmapped", action="ui.click",
            args=None, gap_codes=("UNMAPPED_ACTION",), evidence=None) -> ProposedChange:
    return ProposedChange(
        seq, from_action, gap_codes, action,
        {"target": "btn-login"} if args is None else args,
        "The source step names this action", (_ui_ref(),) if evidence is None else evidence,
    )


def _proposal(*changes, unresolved=(), testcase_id="TC_LOGIN_001") -> ResolutionProposal:
    return ResolutionProposal(testcase_id, changes, unresolved)


def _codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


def test_valid_ui_proposal_is_grounded_and_makes_progress():
    case = _login_case()
    result = validate_resolution_proposal(_proposal(_change()), _context(case), case)
    assert result.status == "VALID"
    assert result.valid_changes == (_change(),)
    assert result.rejected_changes == ()
    assert ("UNMAPPED_ACTION", 2) in {(gap.code, gap.step_seq) for gap in result.before.gaps}
    assert ("UNMAPPED_ACTION", 2) not in {(gap.code, gap.step_seq) for gap in result.after.gaps}
    assert case.steps[1].action == "perform.unmapped"


def test_explicit_negated_url_cannot_become_positive_url_assertion():
    case = _case(_step(1, "ui.goto", {"url": "/login"}),
                 _step(2, "assert.unmapped", {"expected": "URL not /login"}))
    for pattern in ("/login", "/login$"):
        change = _change(seq=2, from_action="assert.unmapped", action="assert.url_matches",
                         args={"pattern": pattern}, evidence=(EvidenceReference(
                             "ui-map", {"page": "https://portal.test/login"}),))
        result = validate_resolution_proposal(_proposal(change), _context(case), case)
        assert not result.valid_changes
        assert "SPECIFICATION_CONFLICT" in _codes(result)


def test_fabricated_locator_is_rejected():
    case = _login_case()
    change = _change(args={"target": "btn-does-not-exist"})
    result = validate_resolution_proposal(_proposal(change), _context(case), case)
    assert result.status == "REJECTED"
    assert "UI_EVIDENCE_NOT_FOUND" in _codes(result)


def test_unknown_action_is_rejected():
    case = _login_case()
    result = validate_resolution_proposal(
        _proposal(_change(action="smart.click")), _context(case), case,
    )
    assert "UNKNOWN_ACTION" in _codes(result)


def test_valid_schema_action_without_runner_adapter_is_rejected():
    case = _login_case()
    change = _change(action="db.query", args={"sql": "select 1"},
                     evidence=(EvidenceReference("testcase-step", {"step_seq": 2}),))
    result = validate_resolution_proposal(_proposal(change), _context(case), case)
    assert "UNSUPPORTED_ACTION" in _codes(result)


def test_invented_api_endpoint_is_rejected():
    source = Path(__file__).resolve().parent.parent / "samples/openapi/task-manager-sample.yaml"
    endpoints = load_endpoints(source)[0]
    operation = replace(endpoints[0], method="POST", path="/api/login",
                        operation_id="login", summary="Login")
    case = _case(
        _step(1, "perform.unmapped", {"description": "POST /api/login"}, "POST /api/login"),
        _step(2, "assert.unmapped", {"expected": "HTTP 200"}),
    )
    evidence = (EvidenceReference("openapi", {"operation_id": "login"}),)
    change = _change(seq=1, action="http.request",
                     args={"method": "POST", "path": "/api/admin/login"}, evidence=evidence)
    result = validate_resolution_proposal(
        _proposal(change), _context(case, endpoints=[operation]), case,
    )
    assert "API_EVIDENCE_NOT_FOUND" in _codes(result)


def test_documented_http_operation_with_matching_source_step_is_valid():
    source = Path(__file__).resolve().parent.parent / "samples/openapi/task-manager-sample.yaml"
    endpoint = load_endpoints(source)[0][0]
    case = _case(
        _step(1, "perform.unmapped", {"description": f"{endpoint.method} {endpoint.path}"},
              f"{endpoint.method} {endpoint.path}"),
        _step(2, "assert.unmapped", {"expected": "HTTP 200"}),
    )
    change = _change(seq=1, action="http.request",
                     args={"method": endpoint.method, "path": endpoint.path},
                     evidence=(EvidenceReference("openapi", {"operation_id": endpoint.operation_id}),))
    result = validate_resolution_proposal(
        _proposal(change), _context(case, endpoints=[endpoint]), case,
    )
    assert result.status == "VALID"
    assert result.valid_changes == (change,)


def test_fabricated_evidence_reference_is_rejected():
    case = _login_case()
    change = _change(evidence=(EvidenceReference("requirement", {"id": "FR-FAKE"}),))
    result = validate_resolution_proposal(_proposal(change), _context(case), case)
    assert "FABRICATED_EVIDENCE" in _codes(result)


def test_wrong_action_and_nonexistent_step_are_rejected():
    case = _login_case()
    wrong_action = _change(from_action="assert.unmapped")
    wrong_step = _change(seq=99)
    result = validate_resolution_proposal(
        _proposal(wrong_action, wrong_step), _context(case), case,
    )
    assert {"ACTION_MISMATCH", "STEP_NOT_FOUND"} <= _codes(result)


def test_already_executable_step_cannot_be_rewritten():
    case = _login_case()
    change = _change(seq=1, from_action="ui.goto", action="ui.goto",
                     args={"url": "/admin"}, gap_codes=("MISSING_URL",),
                     evidence=(EvidenceReference("testcase-step", {"step_seq": 1}),))
    result = validate_resolution_proposal(_proposal(change), _context(case), case)
    assert "NO_MATCHING_GAP" in _codes(result)


def test_identical_change_with_current_gap_has_no_progress():
    source = Path(__file__).resolve().parent.parent / "samples/openapi/task-manager-sample.yaml"
    endpoint = load_endpoints(source)[0][0]
    case = _case(_step(1, "assert.http_status", {"expected": 200}, "HTTP 200"),
                 source_ref=f"openapi:{endpoint.operation_id}")
    change = _change(seq=1, from_action="assert.http_status", action="assert.http_status",
                     args={"expected": 200}, gap_codes=("MISSING_RESPONSE",),
                     evidence=(EvidenceReference("openapi", {"operation_id": endpoint.operation_id}),))
    result = validate_resolution_proposal(
        _proposal(change), _context(case, endpoints=[endpoint]), case,
    )
    assert "NO_EXECUTABILITY_PROGRESS" in _codes(result)


def test_partial_validity_keeps_accepted_and_rejected_changes_separate():
    case = _case(
        _step(1, "ui.goto", {"url": "/login"}),
        _step(2, "perform.unmapped", {"description": "Click Login"}),
        _step(3, "perform.unmapped", {"description": "Click Save"}),
        _step(4, "assert.unmapped", {"expected": "Saved"}),
    )
    good = _change()
    bad = _change(seq=3, args={"target": "imaginary"},
                  evidence=(_ui_ref("btn-save"),))
    unresolved = UnresolvedGap("UNMAPPED_ACTION", 4, "Expected result needs mapping")
    result = validate_resolution_proposal(
        _proposal(good, bad, unresolved=(unresolved,)), _context(case), case,
    )
    assert result.status == "PARTIALLY_VALID"
    assert result.valid_changes == (good,)
    assert result.rejected_changes[0].change == bad
    assert "UI_EVIDENCE_NOT_FOUND" in _codes(result)
    assert result.unresolved == (unresolved,)


def test_observed_delete_button_cannot_reverse_hidden_requirement():
    case = _case(
        _step(1, "ui.goto", {"url": "/login"}),
        _step(2, "assert.unmapped", {"expected": "Delete hidden"}),
    )
    context = _context(case, ui_map=_ui_map(delete=True), requirements=[{
        "id": "FR-LOGIN-001", "kind": "functional",
        "statement": "Normal user must not see Delete",
    }])
    visible = _change(seq=2, from_action="assert.unmapped", action="assert.visible",
                      args={"target": "btn-delete"}, evidence=(_ui_ref("btn-delete"),))
    rejected = validate_resolution_proposal(_proposal(visible), context, case)
    assert "SPECIFICATION_CONFLICT" in _codes(rejected)

    hidden = replace(visible, action="assert.not_visible")
    accepted = validate_resolution_proposal(_proposal(hidden), context, case)
    assert accepted.status == "VALID"
    assert accepted.valid_changes == (hidden,)


def test_expected_result_without_explicit_semantics_stays_unresolved():
    case = _login_case()
    proposal = _change(seq=3, from_action="assert.unmapped", action="assert.visible",
                       args={"target": "btn-login"})
    result = validate_resolution_proposal(_proposal(proposal), _context(case), case)
    assert "SEMANTICS_UNPROVEN" in _codes(result)


def test_missing_assertion_target_needs_original_expected_meaning():
    case = _case(
        _step(1, "ui.goto", {"url": "/login"}),
        _step(2, "assert.visible", {}),
    )
    change = _change(seq=2, from_action="assert.visible", action="assert.visible",
                     args={"target": "btn-login"}, gap_codes=("MISSING_LOCATOR",))
    result = validate_resolution_proposal(_proposal(change), _context(case), case)
    assert "SEMANTICS_UNPROVEN" in _codes(result)


def test_missing_locator_repair_cannot_rewrite_existing_fill_value():
    case = _case(
        _step(1, "ui.goto", {"url": "/login"}),
        _step(2, "ui.fill", {"value": "known@example.test"}),
        _step(3, "assert.unmapped", {"expected": "Login completes"}),
    )
    change = _change(seq=2, from_action="ui.fill", action="ui.fill",
                     args={"target": "btn-login", "value": "different@example.test"},
                     gap_codes=("MISSING_LOCATOR",))
    result = validate_resolution_proposal(_proposal(change), _context(case), case)
    assert "ARGUMENT_REWRITE_NOT_ALLOWED" in _codes(result)


def test_existing_click_needs_step_hint_to_choose_a_ui_element():
    case = _case(
        _step(1, "ui.goto", {"url": "/login"}),
        _step(2, "ui.click", {}),
        _step(3, "assert.unmapped", {"expected": "Login completes"}),
    )
    change = _change(seq=2, from_action="ui.click", gap_codes=("MISSING_LOCATOR",))
    rejected = validate_resolution_proposal(_proposal(change), _context(case), case)
    assert "SEMANTICS_UNPROVEN" in _codes(rejected)

    case.steps[1].note = "Click Login"
    accepted = validate_resolution_proposal(_proposal(change), _context(case), case)
    assert accepted.status == "VALID"
    assert accepted.valid_changes == (change,)


def test_http_proposal_cannot_invent_request_body():
    source = Path(__file__).resolve().parent.parent / "samples/openapi/task-manager-sample.yaml"
    endpoint = load_endpoints(source)[0][0]
    case = _case(
        _step(1, "perform.unmapped", {"description": f"{endpoint.method} {endpoint.path}"},
              f"{endpoint.method} {endpoint.path}"),
        _step(2, "assert.unmapped", {"expected": "HTTP 200"}),
    )
    change = _change(seq=1, action="http.request",
                     args={"method": endpoint.method, "path": endpoint.path,
                           "body": {"role": "admin"}},
                     evidence=(EvidenceReference("openapi", {"operation_id": endpoint.operation_id}),))
    result = validate_resolution_proposal(
        _proposal(change), _context(case, endpoints=[endpoint]), case,
    )
    assert "SEMANTICS_UNPROVEN" in _codes(result)


def test_honest_unresolved_only_answer_is_valid_abstention():
    case = _login_case()
    unresolved = UnresolvedGap("UNMAPPED_ACTION", 2, "Action meaning is not proven")
    result = validate_resolution_proposal(
        _proposal(unresolved=(unresolved,)), _context(case), case,
    )
    assert result.status == "VALID"
    assert result.valid_changes == ()
    assert result.unresolved == (unresolved,)


def test_unresolved_claim_cannot_repeat_already_resolved_gap():
    case = _login_case()
    unresolved = UnresolvedGap("UNMAPPED_ACTION", 2, "Still unresolved")
    result = validate_resolution_proposal(
        _proposal(_change(), unresolved=(unresolved,)), _context(case), case,
    )
    assert result.status == "PARTIALLY_VALID"
    assert result.unresolved == ()
    assert "NO_MATCHING_GAP" in _codes(result)


def test_replacing_assertion_cannot_introduce_missing_response_gap():
    source = Path(__file__).resolve().parent.parent / "samples/openapi/task-manager-sample.yaml"
    endpoint = load_endpoints(source)[0][0]
    case = _case(_step(1, "assert.unmapped", {"expected": "HTTP 200"}),
                 source_ref=f"openapi:{endpoint.operation_id}")
    change = _change(seq=1, from_action="assert.unmapped", action="assert.http_status",
                     args={"expected": 200},
                     evidence=(EvidenceReference("openapi", {"operation_id": endpoint.operation_id}),))
    result = validate_resolution_proposal(
        _proposal(change), _context(case, endpoints=[endpoint]), case,
    )
    assert "NEW_EXECUTION_GAP" in _codes(result)


def test_wrong_testcase_and_stale_context_are_rejected_independently():
    case = _login_case()
    context = _context(case)
    wrong = validate_resolution_proposal(
        _proposal(_change(), testcase_id="TC_OTHER_001"), context, case,
    )
    assert "TESTCASE_MISMATCH" in _codes(wrong)
    stale = deepcopy(case)
    stale.steps[1].args["description"] = "Click Save"
    result = validate_resolution_proposal(_proposal(_change()), context, stale)
    assert "CONTEXT_MISMATCH" in _codes(result)


def test_invalid_arguments_are_rejected_by_step_validation():
    case = _login_case()
    change = _change(action="ui.fill", args={"target": "btn-login"})
    result = validate_resolution_proposal(_proposal(change), _context(case), case)
    assert "INVALID_ARGUMENTS" in _codes(result)


def test_context_proposal_and_case_remain_unchanged():
    case = _login_case()
    context = _context(case)
    proposal = _proposal(_change())
    case_before, context_before, proposal_before = (
        case.to_dict(), context.to_dict(), proposal.to_dict(),
    )
    validate_resolution_proposal(proposal, context, case)
    assert case.to_dict() == case_before
    assert context.to_dict() == context_before
    assert proposal.to_dict() == proposal_before

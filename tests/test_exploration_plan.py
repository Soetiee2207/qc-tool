"""Plan approval is pure: no browser launch, filesystem auth lookup, or execution."""

import inspect
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from qctool.executability import analyze_executability
from qctool.exploration_plan import (
    ExplorationPlan, ExplorationPurpose, PlannedExploration,
    MAX_EXPLORATION_REQUESTS, validate_exploration_plan,
)
from qctool.resolution_context import build_resolution_context
from qctool.testcase import Step, StepKind, TestCase
from qctool.ui.crawl import Element, PageMap, UIMap
from qctool.ui.explore import ExplorationRequest, explore_page, validate_exploration_request


BASE = "https://app.test"


@pytest.fixture(autouse=True)
def prohibit_browser_and_auth_file_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Plan validation must not launch a browser or inspect auth files")
    monkeypatch.setattr("qctool.ui.explore.BrowserSession.start", forbidden)
    monkeypatch.setattr(Path, "is_file", forbidden)


def _case() -> TestCase:
    return TestCase(
        id="TC_LOGIN_001", module="LOGIN", title="Login", objective="Check login",
        traces_to=["FR-LOGIN-001"], source_quote="Login workflow",
        steps=[
            Step(1, StepKind.WHEN, "ui.goto", {"url": "/login"}),
            Step(2, StepKind.WHEN, "perform.unmapped", {"description": "Click Login"}),
            Step(3, StepKind.THEN, "assert.unmapped", {"expected": "Login visible"}),
        ],
    )


def _context(case):
    ui_map = UIMap(BASE, "now", [PageMap(BASE + "/login", "Login", elements=[
        Element("login", "button", "Login", "button", test_id="btn-login"),
        *[Element(path, "link", path, "a", href=f"/{path}")
          for path in ("forgot", "help", "privacy")],
    ])])
    return build_resolution_context(case, analyze_executability(case).gaps, ui_map=ui_map)


def _purpose(seq=2, code="UNMAPPED_ACTION", intent="inspect_page", reason="Inspect login controls"):
    return ExplorationPurpose(code, seq, reason, intent)


def _item(target="/login", *, session="anonymous", purposes=None):
    return PlannedExploration(target, (_purpose(),) if purposes is None else purposes, session)


def _validate(*items, case=None, context=None, testcase_id=None, base_url=BASE):
    case = case or _case()
    context = context or _context(case)
    return validate_exploration_plan(
        ExplorationPlan(testcase_id or case.id, items), context, case, base_url,
    )


def _codes(result):
    return {issue.code for issue in result.issues}


def test_explicit_route_is_approved_as_real_explorer_request():
    result = _validate(_item())
    assert result.status == "VALID"
    approved = result.valid_requests[0]
    assert isinstance(approved.request, ExplorationRequest)
    assert approved.request.target == BASE + "/login"
    assert approved.testcase_id == "TC_LOGIN_001"
    assert approved.purposes == (_purpose(),)
    assert any(source["source"] == "testcase_step" and source["step_seq"] == 1
               for source in approved.grounding)
    # The actual explorer signature accepts this object unchanged. No call is made.
    inspect.signature(explore_page).bind(approved.request, base_url=BASE)
    target, issues = validate_exploration_request(approved.request, base_url=BASE)
    assert target == approved.request.target and not issues


def test_arbitrary_route_is_rejected():
    result = _validate(_item("/super-secret-admin"))
    assert result.status == "REJECTED"
    assert "TARGET_NOT_GROUNDED" in _codes(result)
    assert result.rejected_requests[0].request_index == 0


@pytest.mark.parametrize("target,code", [
    ("https://evil.example/", "OUT_OF_SCOPE_TARGET"),
    ("http://app.test/login", "OUT_OF_SCOPE_TARGET"),
    ("https://app.test:444/login", "OUT_OF_SCOPE_TARGET"),
    ("https://app.test:0/login", "OUT_OF_SCOPE_TARGET"),
    ("javascript:alert(1)", "INVALID_TARGET"),
    ("file:///etc/passwd", "INVALID_TARGET"),
    ("data:text/html,content", "INVALID_TARGET"),
    ("https://user:password@app.test/login", "INVALID_TARGET"),
    ("/\\evil.example/", "INVALID_TARGET"),
    ("/login\n", "INVALID_TARGET"),
])
def test_unsafe_targets_are_rejected_before_execution(target, code):
    assert code in _codes(_validate(_item(target)))


def test_only_supplied_current_gaps_are_eligible():
    unrelated = _validate(_item(purposes=(_purpose(code="MISSING_LOCATOR"),)))
    assert "GAP_NOT_FOUND" in _codes(unrelated)
    executable = _validate(_item(purposes=(_purpose(seq=1),)))
    assert "GAP_NOT_FOUND" in _codes(executable)
    missing_step = _validate(_item(purposes=(_purpose(seq=99),)))
    assert {"STEP_NOT_FOUND", "GAP_NOT_FOUND"} <= _codes(missing_step)


@pytest.mark.parametrize("session", ["anonymous", "authenticated"])
def test_supported_session_and_auth_requirement_without_filesystem_check(session):
    result = _validate(_item(session=session))
    assert result.status == "VALID"
    assert result.valid_requests[0].requires_auth_state == (session == "authenticated")


def test_unsupported_session_is_rejected():
    assert "UNSUPPORTED_SESSION" in _codes(_validate(_item(session="admin")))


def test_duplicates_merge_gap_links_reasons_and_network_collection():
    first = _item()
    network = _purpose(seq=3, intent="observe_network", reason="Observe the response metadata")
    second = _item("HTTPS://APP.TEST:443/login", purposes=(network,))
    result = _validate(first, second)
    assert result.status == "VALID"
    assert len(result.valid_requests) == 1
    approved = result.valid_requests[0]
    assert approved.plan_indices == (0, 1)
    assert approved.purposes == (_purpose(), network)
    assert approved.request.collect_network
    assert "Inspect login controls" in approved.request.reason
    assert "Observe the response metadata" in approved.request.reason


def test_sessions_are_distinct_requests():
    result = _validate(_item(), _item(session="authenticated"))
    assert len(result.valid_requests) == 2


def test_budget_applies_after_dedup_and_keeps_first_unique_valid_requests():
    result = _validate(_item(), _item("/forgot"), _item("/help"),
                       _item("/privacy"), _item(purposes=(_purpose(seq=3),)))
    assert result.status == "PARTIALLY_VALID"
    assert len(result.valid_requests) == MAX_EXPLORATION_REQUESTS
    assert [item.request.target for item in result.valid_requests] == [
        BASE + "/login", BASE + "/forgot", BASE + "/help",
    ]
    assert result.valid_requests[0].plan_indices == (0, 4)
    assert result.rejected_requests[0].request_index == 3
    assert "REQUEST_BUDGET_EXCEEDED" in _codes(result)


@pytest.mark.parametrize("intent", ["click", "delete", "submit_form", "create_account", "upload_file"])
def test_action_like_intent_is_rejected(intent):
    result = _validate(_item(purposes=(_purpose(intent=intent),)))
    assert "UNSUPPORTED_EXPLORATION_INTENT" in _codes(result)
    assert result.valid_requests == ()


def test_selected_link_and_declared_entry_are_grounding_sources():
    result = _validate(_item("/forgot"), _item("/"))
    assert result.status == "VALID"
    assert result.valid_requests[0].grounding[0]["source"] == "ui_link"
    assert result.valid_requests[0].grounding[0]["page"] == BASE + "/login"
    assert result.valid_requests[1].grounding[0]["source"] == "application_base"


def test_relative_ui_link_resolves_against_selected_page():
    case = _case()
    context = _context(case)
    context.observations["ui_pages"][0]["elements"][1]["href"] = "forgot"
    result = _validate(_item("/forgot"), case=case, context=context)
    assert result.status == "VALID"
    assert result.valid_requests[0].grounding[0]["value"] == "forgot"


def test_step_note_and_explicit_open_description_are_grounded():
    case = _case()
    case.steps[0] = Step(1, StepKind.WHEN, "wait", {"seconds": 1}, "/login")
    note = _validate(_item(), case=case)
    assert note.status == "VALID"
    assert any(source["field"] == "note" for source in note.valid_requests[0].grounding)
    case.steps[1].args["description"] = "Open /account"
    description = _validate(_item("/account"), case=case)
    assert description.status == "VALID"


def test_query_and_fragment_are_not_guessed_from_a_route():
    assert "TARGET_NOT_GROUNDED" in _codes(_validate(_item("/login?admin=true")))
    assert "TARGET_NOT_GROUNDED" in _codes(_validate(_item("/login#admin")))


def test_case_level_missing_assertion_gap_is_supported():
    purpose = _purpose(seq=None, code="MISSING_ASSERTION")
    assert _validate(_item(purposes=(purpose,))).status == "VALID"


def test_identity_and_stale_context_are_rejected():
    assert "TESTCASE_MISMATCH" in _codes(_validate(_item(), testcase_id="TC_OTHER_001"))
    case = _case()
    context = _context(case)
    case.steps[1].args["description"] = "Click another control"
    result = _validate(_item(), case=case, context=context)
    assert "CONTEXT_MISMATCH" in _codes(result)
    assert result.valid_requests == ()
    assert result.rejected_requests[0].issues[0].request_index == 0


def test_empty_plan_empty_purposes_and_invalid_base_are_rejected():
    assert "EMPTY_PLAN" in _codes(_validate())
    assert "INVALID_PURPOSE" in _codes(_validate(_item(purposes=())))
    assert "INVALID_BASE_URL" in _codes(_validate(_item(), base_url="file:///tmp"))


def test_all_inputs_unchanged_and_serialized_output_is_detached():
    case = _case()
    context = _context(case)
    plan = ExplorationPlan(case.id, (_item(),))
    originals = deepcopy((case, context, plan))
    result = validate_exploration_plan(plan, context, case, BASE)
    assert (case, context, plan) == originals
    assert json.loads(json.dumps(plan.to_dict())) == plan.to_dict()
    assert json.loads(json.dumps(result.to_dict())) == result.to_dict()
    payload = result.valid_requests[0].to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert yaml.safe_load(yaml.safe_dump(payload)) == payload
    payload["grounding"].clear()
    assert result.valid_requests[0].grounding
    result.valid_requests[0].grounding[0]["value"] = "changed output"
    assert (case, context, plan) == originals


def test_purpose_cannot_reference_a_gap_omitted_from_supplied_context():
    case = _case()
    context = replace(_context(case), gaps=tuple(gap for gap in analyze_executability(case).gaps
                                               if gap.step_seq == 2))
    result = _validate(_item(purposes=(_purpose(seq=3),)), case=case, context=context)
    assert "GAP_NOT_FOUND" in _codes(result)

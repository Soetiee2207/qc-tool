"""Offline exploration planning: untrusted JSON in, no browser actions out."""

from copy import deepcopy
import json
import socket
import urllib.request

import pytest

from qctool.executability import ExecutionGap
from qctool.exploration_plan import (
    ExplorationPlan, ExplorationPurpose, PlannedExploration, validate_exploration_plan,
)
from qctool.llm_exploration import (
    LLMResponseError, build_exploration_prompt, parse_exploration_plan, propose_exploration,
)
from qctool.resolution_context import build_resolution_context
from qctool.testcase import Step, StepKind, TestCase
from qctool.ui.crawl import Element, PageMap, UIMap


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return self.response


@pytest.fixture
def inputs():
    case = TestCase(
        id="TC_LOGIN_001", module="LOGIN", title="Login", objective="Verify login",
        requires={"authenticated": True},
        steps=[
            Step(1, StepKind.WHEN, "ui.goto", {"url": "/login"}),
            Step(2, StepKind.WHEN, "perform.unmapped",
                 {"description": "User submits the login form"}),
            Step(3, StepKind.THEN, "assert.unmapped", {"expected": "Dashboard opens"}),
        ],
    )
    gaps = [ExecutionGap("UNMAPPED_ACTION", "Submit is unmapped", 2),
            ExecutionGap("MISSING_ASSERTION", "Expected result is unresolved")]
    ui_map = UIMap("https://portal.test", "now", [PageMap(
        "https://portal.test/login", "Login", elements=[
            Element("btn-login", "button", "Login", "button", test_id="btn-login"),
        ],
    )])
    return case, build_resolution_context(case, gaps, ui_map=ui_map), gaps


def _purpose(**overrides):
    return {"gap_code": "UNMAPPED_ACTION", "step_seq": 2,
            "reason": "Inspect the explicit login route for form controls",
            "intent": "inspect_page", **overrides}


def _payload():
    return {"testcase_id": "TC_LOGIN_001", "requests": [{
        "target": "/login", "session": "anonymous", "purposes": [_purpose()],
    }]}


def test_login_plan_uses_existing_models(inputs):
    _, context, _ = inputs
    adapter = FakeLLM(json.dumps(_payload()))
    plan = propose_exploration(context, adapter)
    assert isinstance(plan, ExplorationPlan)
    assert isinstance(plan.requests[0], PlannedExploration)
    assert isinstance(plan.requests[0].purposes[0], ExplorationPurpose)
    assert plan.to_dict() == _payload()
    assert len(adapter.prompts) == 1


def test_multiple_purposes_and_case_level_gap(inputs):
    _, context, gaps = inputs
    raw = _payload()
    raw["requests"][0]["purposes"].append(_purpose(
        gap_code="MISSING_ASSERTION", step_seq=None, intent="observe_network",
        reason="Observe navigation network metadata without interacting",
    ))
    plan = propose_exploration(context, FakeLLM(json.dumps(raw)), gaps=iter(gaps))
    assert len(plan.requests) == 1
    assert [p.intent for p in plan.requests[0].purposes] == ["inspect_page", "observe_network"]
    assert plan.requests[0].purposes[1].step_seq is None


def test_empty_plan_is_unresolved(inputs):
    _, context, _ = inputs
    raw = {"testcase_id": "TC_LOGIN_001", "requests": []}
    plan = propose_exploration(context, FakeLLM(json.dumps(raw)))
    assert plan.requests == ()
    assert plan.to_dict() == raw


@pytest.mark.parametrize("response", [
    None, {}, "Inspect /login", "```json\n{}\n```", "{", "[]", "{}",
    '{"testcase_id":"TC_LOGIN_001","requests":[],"requests":[]}',
    '{"testcase_id":"TC_LOGIN_001","requests":NaN}',
    '{"testcase_id":"TC_LOGIN_001","requests":Infinity}',
    '{"testcase_id":"TC_LOGIN_001","requests":{},"status":"unresolved"}',
])
def test_malformed_json_has_controlled_error(response):
    with pytest.raises(LLMResponseError):
        parse_exploration_plan(response)


@pytest.mark.parametrize("field,value", [
    ("step_seq", True), ("step_seq", 0), ("step_seq", "2"),
    ("gap_code", ""), ("reason", "  "), ("intent", []),
])
def test_malformed_purpose_has_controlled_error(field, value):
    raw = _payload()
    raw["requests"][0]["purposes"][0][field] = value
    with pytest.raises(LLMResponseError):
        parse_exploration_plan(json.dumps(raw))


@pytest.mark.parametrize("alteration", ["missing_session", "extra_actions", "empty_purposes"])
def test_incomplete_or_action_sequence_shape_rejected(alteration):
    raw = _payload()
    request = raw["requests"][0]
    if alteration == "missing_session":
        del request["session"]
    elif alteration == "extra_actions":
        request["actions"] = [{"click": "btn-login"}]
    else:
        request["purposes"] = []
    with pytest.raises(LLMResponseError):
        parse_exploration_plan(json.dumps(raw))


def test_testcase_mismatch_even_for_empty_plan(inputs):
    _, context, _ = inputs
    with pytest.raises(LLMResponseError, match="testcase_id does not match"):
        propose_exploration(context, FakeLLM(json.dumps({
            "testcase_id": "TC_OTHER_001", "requests": [],
        })))


def test_prompt_is_deterministic_and_uses_selected_gaps(inputs):
    _, context, gaps = inputs
    prompt = build_exploration_prompt(context, gaps=gaps[:1])
    assert prompt == build_exploration_prompt(context, gaps=iter(gaps[:1]))
    for text in ["SPECIFICATION", "INTERFACE CONTRACT", "CURRENT UI OBSERVATION",
                 "/login", "btn-login", "User submits the login form",
                 "UNMAPPED_ACTION", "Submit is unmapped", '"step_seq": 2',
                 "SESSION MODES", "anonymous", "authenticated", "storage_state",
                 "ALLOWED OBSERVATION INTENTS", "inspect_page", "observe_network",
                 "Only bounded approved ui.fill, ui.select and ui.click", "Do not guess routes",
                 "never propose foreign origins", "empty requests list (unresolved)",
                 "REQUEST BUDGET"]:
        assert text in prompt
    assert "MISSING_ASSERTION" not in prompt
    assert "MISSING_ASSERTION" in build_exploration_prompt(context)
    assert "ALLOWED ACTIONS" not in prompt


def test_unsafe_structured_output_remains_for_safety_validator(inputs):
    case, context, _ = inputs
    raw = _payload()
    raw["requests"][0].update(target="https://evil.example/", session="admin")
    raw["requests"][0]["purposes"][0]["intent"] = "click"
    plan = propose_exploration(context, FakeLLM(json.dumps(raw)))
    assert plan.to_dict() == raw
    result = validate_exploration_plan(plan, context, case, "https://portal.test")
    assert result.status == "REJECTED"
    assert not result.valid_requests


@pytest.mark.parametrize("response", [json.dumps(_payload()), "invalid"])
def test_all_inputs_unchanged_on_success_and_error(inputs, response):
    case, context, gaps = inputs
    snapshots = deepcopy((case, context, gaps))
    if response == "invalid":
        with pytest.raises(LLMResponseError):
            propose_exploration(context, FakeLLM(response), gaps=gaps)
    else:
        plan = propose_exploration(context, FakeLLM(response), gaps=gaps)
        # Returned data cannot alias the context packet either.
        payload = plan.to_dict()
        payload["requests"][0]["purposes"][0]["reason"] = "changed"
    assert (case, context, gaps) == snapshots


def test_no_browser_network_or_automatic_validation(inputs, monkeypatch):
    import playwright.sync_api
    import qctool.exploration_plan
    import qctool.ui.explore
    from qctool.execute.browser import BrowserSession

    def forbidden(*args, **kwargs):
        pytest.fail("Planning invoked browser, network, or safety validation")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", forbidden)
    monkeypatch.setattr(BrowserSession, "start", forbidden)
    monkeypatch.setattr(qctool.ui.explore, "explore_page", forbidden)
    monkeypatch.setattr(qctool.exploration_plan, "validate_exploration_plan", forbidden)
    _, context, _ = inputs
    assert propose_exploration(context, FakeLLM(json.dumps(_payload()))).requests


def test_live_root_actions_shape_is_rejected_and_prompt_nests_it(inputs):
    # Real DeepSeek completion had actions alongside requests at the root.
    # Never move it after parsing; fix only the instructions sent to the model.
    _, context, _ = inputs
    response = {"testcase_id": context.testcase["id"], "requests": [{
        "target": "/login", "session": "anonymous", "purposes": [{
            "gap_code": "UNMAPPED_ACTION", "step_seq": 2,
            "reason": "Observe source-required validation", "intent": "inspect_page"}]}],
        "actions": [{"action": "ui.click", "target": "btn-login", "step_seq": 2}]}
    with pytest.raises(LLMResponseError) as failure:
        parse_exploration_plan(json.dumps(response))
    assert failure.value.diagnostics["category"] == "FIELD_SET"
    assert failure.value.diagnostics["path"] == "plan"
    prompt = build_exploration_prompt(context)
    shape = json.loads(prompt.split("OUTPUT JSON SHAPE\n")[1])
    assert set(shape) == {"testcase_id", "requests"}
    assert "actions" in shape["requests"][0]
    assert "requests[i].actions" in prompt
    assert "Never put actions" in prompt
    assert "OPTIONAL APPROVAL-REQUIRED ACTION SHAPE" not in prompt

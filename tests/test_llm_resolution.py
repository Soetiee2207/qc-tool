"""Offline proposal boundary: fake completions only, never testcase mutation."""

import json

import pytest

from qctool.executability import ExecutionGap
from qctool.llm_resolution import (
    LLMResponseError, build_resolution_prompt, parse_resolution_proposal, propose_resolution,
)
from qctool.resolution_context import build_resolution_context
from qctool.testcase import Step, StepKind, TestCase
from qctool.ui.crawl import Element, PageMap, UIMap


class FakeLLM:
    def __init__(self, response: str):
        self.response = response
        self.prompt: str | None = None

    def complete(self, prompt: str) -> str:
        self.prompt = prompt
        return self.response


def _case() -> TestCase:
    return TestCase(
        id="TC_LOGIN_001", module="LOGIN", title="Log in", objective="Check login",
        traces_to=["FR-LOGIN-001"], source_quote="Normal user can log in",
        steps=[
            Step(1, StepKind.WHEN, "ui.goto", {"url": "/login"}),
            Step(2, StepKind.WHEN, "perform.unmapped",
                 {"description": "User submits the login form"}),
            Step(3, StepKind.THEN, "assert.unmapped", {"expected": "Dashboard opens"}),
        ],
    )


def _context(case: TestCase, gaps: list[ExecutionGap] | None = None):
    ui_map = UIMap("https://portal.test", "now", [
        PageMap("https://portal.test/login", "Login", elements=[
            Element("btn-login", "button", "Login", "button", test_id="btn-login"),
        ]),
    ])
    return build_resolution_context(
        case, gaps if gaps is not None else [
            ExecutionGap("UNMAPPED_ACTION", "Action is not mapped", 2),
        ],
        requirements=[{
            "id": "FR-LOGIN-001", "kind": "functional", "title": "Log in",
            "statement": "Normal user can log in",
        }],
        ui_map=ui_map,
    )


def _change():
    return {
        "step_seq": 2, "from_action": "perform.unmapped",
        "gap_codes": ["UNMAPPED_ACTION"],
        "proposed": {"action": "ui.click", "args": {"target": "btn-login"}},
        "reason": "The login page exposes this Login button",
        "evidence": [{"source": "ui-map", "ref": {
            "page": "https://portal.test/login", "test_id": "btn-login",
        }}],
    }


def _response(*, changes=None, unresolved=None, testcase_id="TC_LOGIN_001"):
    return json.dumps({
        "testcase_id": testcase_id,
        "changes": [] if changes is None else changes,
        "unresolved": [] if unresolved is None else unresolved,
    })


def test_valid_change_parses_into_proposal():
    case = _case()
    adapter = FakeLLM(_response(changes=[_change()]))
    proposal = propose_resolution(_context(case), adapter)
    assert proposal.status == "proposed"
    assert proposal.testcase_id == "TC_LOGIN_001"
    assert proposal.changes[0].step_seq == 2
    assert proposal.changes[0].from_action == "perform.unmapped"
    assert proposal.changes[0].action == "ui.click"
    assert proposal.changes[0].args == {"target": "btn-login"}
    assert proposal.changes[0].evidence[0].ref["test_id"] == "btn-login"
    json.dumps(proposal.to_dict())
    assert adapter.prompt is not None


def test_unresolved_answer_requires_no_invented_change():
    adapter = FakeLLM(_response(unresolved=[{
        "code": "MISSING_PRECONDITION", "step_seq": None,
        "reason": "No evidence identifies how to provision the account",
    }]))
    proposal = propose_resolution(_context(_case()), adapter)
    assert proposal.status == "unresolved"
    assert proposal.changes == ()
    assert proposal.unresolved[0].code == "MISSING_PRECONDITION"


def test_multiple_gaps_can_be_partial():
    gaps = [
        ExecutionGap("UNMAPPED_ACTION", "Unmapped action", 2),
        ExecutionGap("MISSING_PRECONDITION", "Needs account", None),
    ]
    adapter = FakeLLM(_response(changes=[_change()], unresolved=[{
        "code": "MISSING_PRECONDITION", "step_seq": None,
        "reason": "No account provisioning evidence",
    }]))
    proposal = propose_resolution(_context(_case(), gaps), adapter)
    assert proposal.status == "partial"
    assert proposal.changes[0].gap_codes == ("UNMAPPED_ACTION",)
    assert proposal.unresolved[0].code == "MISSING_PRECONDITION"


@pytest.mark.parametrize("response", [
    "Click the Login button",
    '{"testcase_id":"TC_LOGIN_001","changes":[{}],"unresolved":[]}',
    _response(changes=[{**_change(), "evidence": []}]),
    _response(changes=[{**_change(), "proposed": {"action": "ui.click"}}]),
    '{"testcase_id":"TC_LOGIN_001","testcase_id":"TC_OTHER_001",'
    '"changes":[],"unresolved":[]}',
])
def test_malformed_output_is_controlled_error(response):
    with pytest.raises(LLMResponseError):
        propose_resolution(_context(_case()), FakeLLM(response))


def test_wrong_testcase_id_is_rejected():
    with pytest.raises(LLMResponseError, match="testcase_id"):
        propose_resolution(_context(_case()), FakeLLM(
            _response(changes=[_change()], testcase_id="TC_OTHER_001")
        ))


def test_case_is_unchanged_after_proposal_generation():
    case = _case()
    before = case.to_dict()
    context = _context(case)
    proposal = propose_resolution(context, FakeLLM(_response(changes=[_change()])))
    assert proposal.changes[0].action == "ui.click"
    assert case.to_dict() == before
    assert case.steps[1].action == "perform.unmapped"


def test_prompt_separates_evidence_and_limits_model_authority():
    prompt = build_resolution_prompt(_context(_case()))
    headings = [
        "SPECIFICATION — REQUIREMENTS", "INTERFACE CONTRACT — OPENAPI",
        "CURRENT UI OBSERVATION — UI MAP", "TESTCASE", "EXECUTION GAPS",
        "ALLOWED ACTIONS — ACTION_SPECS",
    ]
    positions = [prompt.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "Normal user can log in" in prompt
    assert "btn-login" in prompt
    assert '"ui.click"' in prompt
    assert "Never rewrite a requirement expectation to match observed UI" in prompt
    assert "When evidence is insufficient" in prompt
    assert prompt == build_resolution_prompt(_context(_case()))


def test_parser_does_not_claim_action_or_evidence_is_validated():
    change = _change()
    change["proposed"] = {"action": "browser.submit_form", "args": {"target": "invented"}}
    proposal = parse_resolution_proposal(_response(changes=[change]))
    assert proposal.changes[0].action == "browser.submit_form"

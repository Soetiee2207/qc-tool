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
        "ALLOWED ACTIONS — ACTION_SPECS", "STABLE PROJECT SPECIFICATION — REQUIREMENTS", "STABLE PROJECT INTERFACE CONTRACT — OPENAPI",
        "CURRENT UI OBSERVATION — UI MAP", "TESTCASE", "EXECUTION GAPS",
    ]
    positions = [prompt.index(heading + "\n") for heading in headings]
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


@pytest.mark.parametrize("source,ref", [
    ("ui-map", {"url": "https://salonhub-soe.vercel.app/login"}),
    ("ui-map", {"test_id": "login-submit-btn"}),
    ("ui-map", {"page": "/login", "session": "anonymous"}),
    ("ui-map", {"page": "/login", "url": "/login"}),
    ("testcase-step", {"seq": 2}),
    ("testcase-step", {"seq": 1, "text": "Phiên anonymous ở /login"}),
    ("requirement", {"quote": "URL vẫn ở /login"}),
    ("testcase-step", {"step_seq": "2"}),
    ("testcase-step", {"step_seq": True}),
    ("openapi", {"method": "POST"}),
])
def test_salonhub_malformed_evidence_is_rejected_without_correction(source, ref):
    change = _change()
    change["evidence"] = [{"source": source, "ref": ref}]
    before = json.dumps(change)
    with pytest.raises(LLMResponseError, match="ref"):
        parse_resolution_proposal(_response(changes=[change]))
    assert json.dumps(change) == before


def test_salonhub_duplicate_step_changes_are_not_merged():
    first = _change()
    second = {**_change(), "proposed": {"action": "ui.session", "args": {"mode": "anonymous"}}}
    with pytest.raises(LLMResponseError, match="duplicates"):
        parse_resolution_proposal(_response(changes=[first, second]))


@pytest.mark.parametrize("source,ref", [
    ("requirement", {"id": "FR-LOGIN-001"}),
    ("openapi", {"operation_id": "login"}),
    ("openapi", {"method": "POST", "path": "/api/auth/login"}),
    ("openapi", {"operation_id": "login", "method": "POST", "path": "/api/auth/login"}),
    ("ui-map", {"page": "https://portal.test/login"}),
    ("ui-map", {"page": "https://portal.test/login", "role": "button", "name": "Login"}),
    ("testcase-step", {"step_seq": 2}),
    ("testcase-step", {"step_seq": 2, "action": "perform.unmapped"}),
])
def test_exact_validator_reference_shapes_parse(source, ref):
    change = _change()
    change["evidence"] = [{"source": source, "ref": ref}]
    parsed = parse_resolution_proposal(_response(changes=[change]))
    assert parsed.changes[0].evidence[0].ref == ref


def test_prompt_catalog_has_only_selected_identifiers_and_exact_schema():
    context = _context(_case())
    before = context.to_dict()
    prompt = build_resolution_prompt(context)
    catalog = json.loads(prompt.split(
        "EVIDENCE REFERENCES — identifiers present in this context only\n", 1
    )[1].split("\n\n", 1)[0])
    assert {"source": "ui-map", "ref": {
        "page": "https://portal.test/login", "test_id": "btn-login",
    }} in catalog
    assert {"source": "testcase-step", "ref": {"step_seq": 2, "action": "perform.unmapped"}} in catalog
    assert {"source": "requirement", "ref": {"id": "FR-LOGIN-001"}} in catalog
    assert not any(item["source"] == "openapi" for item in catalog)
    assert "At most one change per step_seq" in prompt
    assert "use step_seq, never seq" in prompt
    assert "Use page, never url" in prompt
    assert "leave the gap unresolved; do not guess evidence" in prompt
    assert context.to_dict() == before


def test_structurally_correct_fabricated_reference_still_requires_validator():
    from qctool.proposal_validation import validate_resolution_proposal

    change = _change()
    change["evidence"] = [{"source": "requirement", "ref": {"id": "INVENTED"}}]
    proposal = parse_resolution_proposal(_response(changes=[change]))
    result = validate_resolution_proposal(proposal, _context(_case()), _case())
    assert not result.valid_changes
    assert any(issue.code == "FABRICATED_EVIDENCE" for issue in result.issues)


def test_expansion_evidence_error_has_exact_safe_path():
    raw = {"testcase_id": "TC_LOGIN_001", "changes": [{
        "step_seq": 2, "from_action": "perform.unmapped", "gap_codes": ["UNMAPPED_ACTION"],
        "reason": "safe", "evidence": [{"source": "testcase-step", "ref": {"step_seq": 2}}],
        "proposed": {"steps": [
            {"action": "ui.click", "args": {}, "evidence": [{"source": "ui-map", "ref": {"url": "/login"}}]},
            {"action": "ui.click", "args": {}, "evidence": []}]}}], "unresolved": []}
    with pytest.raises(LLMResponseError) as caught:
        parse_resolution_proposal(json.dumps(raw))
    assert caught.value.category == "EVIDENCE_SHAPE"
    assert caught.value.path == "changes[0].proposed.steps[0].evidence[0].ref"


def test_duplicate_secret_json_key_not_in_error():
    with pytest.raises(LLMResponseError) as caught:
        parse_resolution_proposal('{"private-secret":1,"private-secret":2}')
    assert caught.value.category == "JSON_STRUCTURE"
    assert "private-secret" not in str(caught.value)


def test_exact_normal_and_expansion_prompt_envelopes():
    prompt = build_resolution_prompt(_context(_case()))
    def section(name):
        return json.loads(prompt.split(name + '\n', 1)[1].split('\n\n', 1)[0])
    normal = section('OUTPUT JSON SHAPE')
    expanded = section('EXPANSION CHANGE JSON SHAPE — alternative to a normal change')
    fields = {'step_seq', 'from_action', 'gap_codes', 'proposed', 'reason', 'evidence'}
    assert set(normal) == {'testcase_id', 'changes', 'unresolved'}
    assert set(normal['changes'][0]) == fields == set(expanded)
    assert set(normal['changes'][0]['proposed']) == {'action', 'args'}
    assert set(expanded['proposed']) == {'steps'}
    assert all(set(a) == {'action', 'args', 'evidence'} for a in expanded['proposed']['steps'])
    capture = section('CAPTURE_RESPONSE JSON SHAPE — inside ui.click.args only')
    assert set(capture) == {'method', 'path', 'origin', 'save_as', 'timeout_ms'}
    assert capture['save_as'] == 'login_response'
    atoms = section('RESPONSE ASSERTION ATOMS — inside proposed.steps only')
    assert all(a['args']['source'] == 'login_response' for a in atoms)
    assert 'No extra change-level fields' in prompt
    assert 'COMPACT LOGIN EXAMPLE' not in prompt  # Insufficient evidence: no invented example.


@pytest.mark.parametrize('field', ['steps', 'expansion', 'capture_response', 'action', 'args', 'source', 'confidence', 'status'])
def test_change_level_extras_still_fail_without_auto_correction(field):
    change = {**_change(), field: {}}
    with pytest.raises(LLMResponseError) as error:
        parse_resolution_proposal(_response(changes=[change]))
    assert error.value.category == 'FIELD_SET'
    assert error.value.path == 'changes[0]'


def test_context_login_example_parses_and_validates_without_mutation():
    from copy import deepcopy
    from tests.test_ui_response_capture import resolution_inputs
    from qctool.proposal_validation import validate_resolution_proposal
    case, context, store, _ = resolution_inputs()
    snapshot = deepcopy((case, context))
    prompt = build_resolution_prompt(context)
    marker = 'COMPACT LOGIN EXAMPLE — partial proposal from this context only\n'
    example = json.loads(prompt.split(marker, 1)[1])
    proposal = parse_resolution_proposal(json.dumps(example))
    validation = validate_resolution_proposal(proposal, context, case, fixture_store=store)
    assert [c.step_seq for c in validation.valid_changes] == [2, 3], validation.issues
    assert not validation.rejected_changes
    assert (case, context) == snapshot
    assert store.resolve('active_user.password') not in prompt
    assert example['changes'][0]['proposed']['steps'][2]['args']['capture_response']['save_as'] == 'login_response'

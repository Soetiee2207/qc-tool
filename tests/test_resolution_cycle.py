"""One cycle only: fake LLM completions and fake explorer observations."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

import qctool.resolution_cycle as cycle
import qctool.exploration_execution as execution
from qctool.executability import analyze_executability
from qctool.resolution_context import build_resolution_context
from qctool.testcase import Step, StepKind, TestCase
from qctool.ui.crawl import Element, PageMap, UIMap
from qctool.ui.explore import ExplorationResult

BASE = "https://app.test"


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _inputs(*, missing_locator=False, extra_step=False, evidence=True):
    case = TestCase(
        id="TC_LOGIN_001", module="LOGIN", title="Login", objective="Check login",
        traces_to=["FR-LOGIN-001"], source_quote="Click Login to open /dashboard",
        steps=[Step(1, StepKind.WHEN, "ui.goto", {"url": "/login"}),
               Step(2, StepKind.WHEN,
                    "ui.click" if missing_locator else "perform.unmapped",
                    {"by_name": "Login"} if missing_locator else {"description": "Click Login"}),
               *([Step(3, StepKind.WHEN, "perform.unmapped", {"description": "Click Save"})]
                 if extra_step else []),
               Step(4, StepKind.THEN, "assert.url_matches", {"pattern": "/dashboard"})],
    )
    ui_map = UIMap(BASE, "now", [PageMap(BASE + "/login", "Login", elements=[
        Element("login", "button", "Login", "button", test_id="btn-login"),
        Element("save", "button", "Save", "button", test_id="btn-save"),
    ])])
    context = build_resolution_context(case, analyze_executability(case).gaps,
                                       ui_map=ui_map if evidence else None)
    return case, context, ui_map


def _proposal(*, seq=2, target="btn-login"):
    return json.dumps({"testcase_id": "TC_LOGIN_001", "changes": [{
        "step_seq": seq, "from_action": "perform.unmapped", "gap_codes": ["UNMAPPED_ACTION"],
        "proposed": {"action": "ui.click", "args": {"target": target}},
        "reason": "Original step explicitly names this control",
        "evidence": [{"source": "ui-map", "ref": {"page": BASE + "/login", "test_id": target}}],
    }], "unresolved": []})


def _unresolved(seq=2):
    return json.dumps({"testcase_id": "TC_LOGIN_001", "changes": [], "unresolved": [{
        "code": "UNMAPPED_ACTION", "step_seq": seq, "reason": "Need observed evidence",
    }]})


def _plan(*, target="/login", seq=2):
    return json.dumps({"testcase_id": "TC_LOGIN_001", "requests": [{
        "target": target, "session": "anonymous", "purposes": [{
            "gap_code": "UNMAPPED_ACTION", "step_seq": seq,
            "reason": "Inspect explicit route", "intent": "inspect_page",
        }],
    }]})


def _fake_explorer(request, **kwargs):
    return ExplorationResult(request, BASE + "/login", PageMap(BASE + "/login", "Login", elements=[
        Element("login", "button", "Login", "button", test_id="btn-login"),
    ]), (), (), (), "2026-10-05T12:00:00+07:00")


def test_deterministic_only_success_skips_both_llms():
    case, context, ui_map = _inputs(missing_locator=True)
    adapter = FakeLLM(AssertionError("Must not be called"))
    result = cycle.run_resolution_cycle(case, context, ui_map=ui_map,
                                       resolution_llm=adapter, exploration_llm=adapter)
    assert result.after.executable and not result.needs_another_cycle
    assert result.deterministic.changes[0].after["target"] == "btn-login"
    assert result.proposal is result.exploration_plan is None
    assert not adapter.prompts
    assert result.context.testcase["steps"][1]["args"]["target"] == "btn-login"
    assert result.context.gaps == ()


def test_llm_repair_success_no_exploration_and_correct_order():
    case, context, _ = _inputs()
    resolution = FakeLLM(_proposal())
    exploration = FakeLLM(AssertionError("Must not be called"))
    result = cycle.run_resolution_cycle(case, context, resolution_llm=resolution,
                                       exploration_llm=exploration, base_url=BASE)
    assert result.after.executable and not result.needs_another_cycle
    assert result.application.applied_changes
    assert result.case.steps[1].action == "ui.click"
    assert len(resolution.prompts) == 1 and not exploration.prompts
    assert [event.stage for event in result.audit] == [
        "analysis", "deterministic", "context", "resolution_llm",
        "proposal_validation", "application", "reanalysis", "context",
    ]


def test_unresolved_explores_and_stops_without_second_llm_call(monkeypatch):
    case, context, _ = _inputs(evidence=False)
    resolution, exploration = FakeLLM(_unresolved()), FakeLLM(_plan())
    calls = []

    def inspect(request, **kwargs):
        calls.append(request)
        return _fake_explorer(request, **kwargs)

    monkeypatch.setattr(execution, "explore_page", inspect)
    result = cycle.run_resolution_cycle(case, context, resolution_llm=resolution,
                                       exploration_llm=exploration, base_url=BASE)
    assert result.case == case
    assert result.before == result.after
    assert result.needs_another_cycle
    assert len(resolution.prompts) == len(exploration.prompts) == len(calls) == 1
    assert result.context.observations["ui_pages"][0]["elements"][0]["test_id"] == "btn-login"
    assert result.context.specification == context.specification
    assert result.context.interface_contract == context.interface_contract
    assert result.audit[-1].stage == "exploration_execution"


def test_invalid_proposal_not_applied():
    case, context, _ = _inputs()
    result = cycle.run_resolution_cycle(case, context,
                                       resolution_llm=FakeLLM(_proposal(target="invented")))
    assert result.validation.rejected_changes
    assert not result.application.applied_changes
    assert result.case == case
    assert result.needs_another_cycle
    assert any(issue.stage == "proposal_validation" for issue in result.issues)


def test_invalid_exploration_plan_never_executed(monkeypatch):
    case, context, _ = _inputs()
    monkeypatch.setattr(execution, "explore_page", lambda *a, **kw: pytest.fail("Unsafe plan"))
    result = cycle.run_resolution_cycle(case, context, resolution_llm=FakeLLM(_unresolved()),
                                       exploration_llm=FakeLLM(_plan(target="https://evil.test")),
                                       base_url=BASE)
    assert result.exploration_validation.status == "REJECTED"
    assert result.exploration_execution is None
    assert result.case == case
    assert result.needs_another_cycle


@pytest.mark.parametrize("stage,function", [
    ("resolution_llm", "propose_resolution"),
    ("proposal_validation", "validate_resolution_proposal"),
    ("application", "apply_validated_resolution"),
    ("exploration_llm", "propose_exploration"),
    ("exploration_validation", "validate_exploration_plan"),
    ("exploration_execution", "execute_validated_exploration"),
])
def test_stage_failure_retains_prior_progress(monkeypatch, stage, function):
    case, context, ui_map = _inputs(missing_locator=True, extra_step=True)

    def fail(*args, **kwargs):
        raise RuntimeError("password=PRIVATE")

    monkeypatch.setattr(cycle, function, fail)
    monkeypatch.setattr(execution, "explore_page", _fake_explorer)
    result = cycle.run_resolution_cycle(
        case, context, ui_map=ui_map, resolution_llm=FakeLLM(_unresolved(seq=3)),
        exploration_llm=FakeLLM(_plan(seq=3)), base_url=BASE)
    assert result.case.steps[1].args["target"] == "btn-login"
    assert result.deterministic.changes
    assert result.needs_another_cycle
    assert any(issue.stage == stage and issue.code == "STAGE_FAILED" for issue in result.issues)
    assert "PRIVATE" not in repr(result.issues)
    assert result.context.testcase["steps"][1]["args"]["target"] == "btn-login"


def test_malformed_llm_can_still_collect_evidence(monkeypatch):
    case, context, _ = _inputs(evidence=False)
    monkeypatch.setattr(execution, "explore_page", _fake_explorer)
    result = cycle.run_resolution_cycle(case, context, resolution_llm=FakeLLM("not JSON"),
                                       exploration_llm=FakeLLM(_plan()), base_url=BASE)
    assert any(issue.code == "LLM_RESPONSE_ERROR" for issue in result.issues)
    assert result.exploration_execution.successful_requests
    assert result.needs_another_cycle


@pytest.mark.parametrize("code,status,diagnostic", [
    ("TIMEOUT", None, "timed out"), ("HTTP_ERROR", 401, "HTTP 401"),
    ("INVALID_COMPLETION", None, "JSON object"),
    ("PRIVATE_SECRET", None, "details omitted"),
])
def test_provider_root_error_is_persisted_without_untrusted_error_text(code, status, diagnostic):
    from qctool.llm_provider import LLMProviderError
    from qctool.generation import _serializable
    case, context, _ = _inputs()
    adapter = FakeLLM(LLMProviderError(code, "api_key=PRIVATE Bearer PRIVATE", http_status=status))
    result = cycle.run_resolution_cycle(case, context, resolution_llm=adapter)
    issue = next(i for i in result.issues if i.stage == "resolution_llm")
    assert issue.code == (code if code != "PRIVATE_SECRET" else "LLM_PROVIDER_ERROR")
    assert diagnostic in issue.message
    assert "PRIVATE" not in json.dumps(_serializable(result))
    assert result.case == case


def test_refresh_deduplicates_only_identical_selected_evidence():
    from copy import deepcopy
    case, context, _ = _inputs()
    context.observations["ui_pages"].append(deepcopy(context.observations["ui_pages"][0]))
    result = cycle.run_resolution_cycle(case, context, resolution_llm=FakeLLM(_proposal()))
    assert result.after.executable
    assert len(result.context.observations["ui_pages"]) == 1
    assert len(context.observations["ui_pages"]) == 2


def test_failure_after_llm_application_retains_llm_repairs(monkeypatch):
    case, context, _ = _inputs(extra_step=True)
    def fail(*a, **kw):
        raise RuntimeError("Planning unavailable")
    monkeypatch.setattr(cycle, "propose_exploration", fail)
    result = cycle.run_resolution_cycle(case, context, resolution_llm=FakeLLM(_proposal()),
                                       exploration_llm=FakeLLM(_plan(seq=3)), base_url=BASE)
    assert result.case.steps[1].action == "ui.click"
    assert result.case.steps[2].action == "perform.unmapped"
    assert {gap.step_seq for gap in result.after.gaps} == {3}
    assert result.context.gaps == result.after.gaps
    assert result.needs_another_cycle


def test_all_inputs_unchanged_and_outputs_detached(monkeypatch):
    case, context, ui_map = _inputs(missing_locator=True, extra_step=True)
    originals = deepcopy((case, context, ui_map))
    monkeypatch.setattr(execution, "explore_page", _fake_explorer)
    result = cycle.run_resolution_cycle(case, context, ui_map=ui_map,
                                       resolution_llm=FakeLLM(_unresolved(seq=3)),
                                       exploration_llm=FakeLLM(_plan(seq=3)), base_url=BASE)
    assert (case, context, ui_map) == originals
    result.case.steps[0].args["url"] = "/changed"
    result.context.testcase["steps"][0]["args"]["url"] = "/changed"
    result.context.observations["ui_pages"][0]["elements"][0]["name"] = "changed"
    assert (case, context, ui_map) == originals


def test_wrong_context_identity_stops_all_stages():
    case, context, _ = _inputs()
    context = replace(context, testcase={**context.testcase, "id": "TC_OTHER"})
    adapter = FakeLLM(AssertionError("Must not be called"))
    result = cycle.run_resolution_cycle(case, context, resolution_llm=adapter, exploration_llm=adapter)
    assert result.issues[0].code == "TESTCASE_MISMATCH"
    assert result.deterministic is None and not adapter.prompts


def test_already_executable_needs_no_further_cycle():
    case, context, _ = _inputs()
    case.steps[1].action = "ui.click"
    case.steps[1].args = {"target": "btn-login"}
    result = cycle.run_resolution_cycle(case, context)
    assert result.before.executable and result.after.executable
    assert not result.needs_another_cycle and not result.issues


def test_empty_exploration_plan_does_not_execute(monkeypatch):
    case, context, _ = _inputs()
    monkeypatch.setattr(execution, "explore_page", lambda *a, **kw: pytest.fail("Empty plan"))
    result = cycle.run_resolution_cycle(case, context, resolution_llm=FakeLLM(_unresolved()),
                                       exploration_llm=FakeLLM(json.dumps({
                                           "testcase_id": case.id, "requests": []})), base_url=BASE)
    assert not result.exploration_validation.valid_requests
    assert result.exploration_execution is None and result.needs_another_cycle


def test_partial_proposal_explores_only_current_remaining_gaps(monkeypatch):
    case, context, _ = _inputs(extra_step=True)
    raw = json.loads(_proposal())
    raw["changes"].append(json.loads(_proposal(seq=3, target="invented"))["changes"][0])
    exploration = FakeLLM(_plan(seq=3))
    monkeypatch.setattr(execution, "explore_page", _fake_explorer)
    result = cycle.run_resolution_cycle(case, context, resolution_llm=FakeLLM(json.dumps(raw)),
                                       exploration_llm=exploration, base_url=BASE)
    assert result.validation.status == "PARTIALLY_VALID"
    assert len(result.application.applied_changes) == 1
    assert result.case.steps[1].action == "ui.click"
    assert result.case.steps[2].action == "perform.unmapped"
    gap_section = exploration.prompts[0].split("UNRESOLVED EXECUTION GAPS\n")[1].split("\n\n")[0]
    assert [(gap["code"], gap["step_seq"]) for gap in json.loads(gap_section)] == [
        ("UNMAPPED_ACTION", 3)]
    assert result.exploration_execution.successful_requests
    assert result.needs_another_cycle


def test_missing_base_url_skips_planning_with_issue():
    case, context, _ = _inputs()
    exploration = FakeLLM(AssertionError("Cannot execute without base URL"))
    result = cycle.run_resolution_cycle(case, context, resolution_llm=FakeLLM(_unresolved()),
                                       exploration_llm=exploration)
    assert not exploration.prompts
    assert any(issue.code == "BASE_URL_REQUIRED" for issue in result.issues)
    assert result.needs_another_cycle

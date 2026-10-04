"""Approved exploration execution and context enrichment, using offline stubs."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

import qctool.exploration_execution as execution
from qctool.executability import analyze_executability
from qctool.exploration_plan import (
    ExplorationPlan, ExplorationPlanValidationResult, ExplorationPurpose,
    PlannedExploration, validate_exploration_plan,
)
from qctool.resolution_context import build_resolution_context
from qctool.testcase import Step, StepKind, TestCase
from qctool.ui.crawl import Element, PageMap, UIMap
from qctool.ui.explore import ExplorationIssue, ExplorationRequest, ExplorationResult

BASE = "https://app.test"
STAMP = "2026-10-05T12:00:00+07:00"


def _inputs(*, session="anonymous", second=False, existing=False):
    case = TestCase(
        id="TC_LOGIN_001", module="LOGIN", title="Login", objective="Verify login",
        traces_to=["FR-LOGIN-001"], steps=[
            Step(1, StepKind.WHEN, "ui.goto", {"url": "/login"}),
            Step(2, StepKind.WHEN, "perform.unmapped", {"description": "Submit login"}),
            Step(3, StepKind.THEN, "assert.unmapped", {"expected": "Dashboard opens"}),
            *([Step(4, StepKind.WHEN, "ui.goto", {"url": "/help"})] if second else []),
        ],
    )
    page = _page(BASE + "/login")
    context = build_resolution_context(
        case, analyze_executability(case).gaps,
        requirements=[{"id": "FR-LOGIN-001", "statement": "Dashboard opens after login"}],
        ui_map=UIMap(BASE, "before", [page]) if existing else None,
    )
    # Keep a contract object in the packet to test specification separation.
    context = replace(context, interface_contract={"api_operations": [
        {"method": "POST", "path": "/api/login", "operation_id": "login"},
    ]})
    purpose = ExplorationPurpose("UNMAPPED_ACTION", 2, "Inspect existing route")
    requests = [PlannedExploration("/login", (purpose,), session)]
    if second:
        requests.append(PlannedExploration("/help", (purpose,)))
    validated = validate_exploration_plan(
        ExplorationPlan(case.id, tuple(requests)), context, case, BASE)
    assert len(validated.valid_requests) == len(requests)
    return context, validated


def _page(url):
    return PageMap(url, "Login", elements=[
        Element("login", "button", "Login", "button", test_id="btn-login"),
    ])


def _observed(request, **overrides):
    fields = dict(request=ExplorationRequest(**request.to_dict()), final_url=request.target,
                  page=_page(request.target), forms=(), network=(), issues=(),
                  observed_at=STAMP)
    fields.update(overrides)
    return ExplorationResult(**fields)


def _run(validated, context, **kwargs):
    return execution.execute_validated_exploration(validated, context, base_url=BASE, **kwargs)


def test_success_adds_page_and_complete_provenance(monkeypatch):
    context, validated = _inputs()
    monkeypatch.setattr(execution, "explore_page", lambda request, **kwargs: _observed(request))
    result = _run(validated, context)
    assert len(result.successful_requests) == 1
    assert not result.failed_requests and not result.issues
    page = result.context.observations["ui_pages"][0]
    assert page["elements"][0]["test_id"] == "btn-login"
    metadata = page["explorations"][0]
    assert metadata["source"] == {"type": "playwright_exploration", "page": BASE + "/login",
                                   "observed_at": STAMP}
    assert metadata["request"]["target"] == BASE + "/login"
    assert metadata["request"]["session"] == "anonymous"
    assert metadata["purposes"][0]["gap_code"] == "UNMAPPED_ACTION"
    assert metadata["purposes"][0]["step_seq"] == 2
    json.dumps(result.to_dict())


def test_context_validation_and_stub_artifacts_are_detached(monkeypatch):
    context, validated = _inputs()
    snapshots = deepcopy((context, validated))
    observed = _observed(validated.valid_requests[0].request)
    monkeypatch.setattr(execution, "explore_page", lambda *args, **kwargs: observed)
    result = _run(validated, context)
    assert (context, validated) == snapshots
    result.context.specification["requirements"][0]["statement"] = "changed"
    result.context.observations["ui_pages"][0]["elements"][0]["name"] = "changed"
    result.exploration_results[0].page.elements[0].name = "changed"
    assert observed.page.elements[0].name == "Login"
    assert (context, validated) == snapshots


@pytest.mark.parametrize("failure", ["issue", "exception", "invalid_page", "no_page"])
def test_failure_isolated_from_later_success(monkeypatch, failure):
    context, validated = _inputs(second=True)

    def fake(request, **kwargs):
        if request.target.endswith("/login"):
            if failure == "exception":
                raise RuntimeError("password=DO_NOT_LEAK")
            if failure == "invalid_page":
                return _observed(request, page=object())
            return _observed(request, page=None, issues=(
                (ExplorationIssue("NAVIGATION_FAILED", "Navigation failed."),)
                if failure == "issue" else ()))
        return _observed(request)

    monkeypatch.setattr(execution, "explore_page", fake)
    result = _run(validated, context)
    assert len(result.failed_requests) == len(result.successful_requests) == 1
    assert len(result.issues) == 1
    assert result.issues[0].request_index == 0
    assert result.context.observations["ui_pages"][0]["url"] == BASE + "/help"
    assert "DO_NOT_LEAK" not in json.dumps(result.to_dict())


def test_existing_and_repeated_snapshot_deduplicated(monkeypatch):
    context, validated = _inputs(existing=True)
    monkeypatch.setattr(execution, "explore_page", lambda request, **kwargs: _observed(request))
    first = _run(validated, context)
    second = _run(validated, first.context)
    pages = second.context.observations["ui_pages"]
    assert len(pages) == 1
    assert len(pages[0]["elements"]) == 1
    assert len(pages[0]["explorations"]) == 1
    assert pages[0]["evidence"]["type"] == "ui-map"
    assert context.observations["ui_pages"][0].get("explorations") is None


def test_changed_and_session_specific_observations_remain_separate(monkeypatch):
    context, validated = _inputs()
    monkeypatch.setattr(execution, "explore_page", lambda request, **kwargs: _observed(request))
    first = _run(validated, context)
    _, authenticated = _inputs(session="authenticated")
    second = _run(authenticated, first.context, storage_state=Path("auth.json"))
    assert len(second.context.observations["ui_pages"]) == 2
    page = _page(BASE + "/login")
    page.elements[0].disabled = True
    monkeypatch.setattr(execution, "explore_page",
                        lambda request, **kwargs: _observed(request, page=page))
    third = _run(validated, second.context)
    assert len(third.context.observations["ui_pages"]) == 3


@pytest.mark.parametrize("session", ["anonymous", "authenticated"])
def test_auth_state_and_browser_options_forwarded(monkeypatch, session):
    context, validated = _inputs(session=session)
    calls = []

    def fake(request, **kwargs):
        calls.append((request, kwargs))
        return _observed(request)

    monkeypatch.setattr(execution, "explore_page", fake)
    state = Path("trusted-state.json")
    _run(validated, context, storage_state=state, timeout_ms=1234, render_wait_ms=0)
    request, kwargs = calls[0]
    assert request == validated.valid_requests[0].request
    assert kwargs == dict(base_url=BASE, storage_state=state if session == "authenticated" else None,
                          timeout_ms=1234, render_wait_ms=0)


def test_business_contract_and_gaps_never_changed(monkeypatch):
    context, validated = _inputs()
    observed = _page(BASE + "/login")
    observed.text = ["Delete visible", "Dashboard does not open"]
    monkeypatch.setattr(execution, "explore_page",
                        lambda request, **kwargs: _observed(request, page=observed))
    result = _run(validated, context)
    for field in ("specification", "interface_contract", "testcase", "gaps", "allowed_actions"):
        assert getattr(result.context, field) == getattr(context, field)


@pytest.mark.parametrize("raw", [ExplorationPlan("TC_LOGIN_001", ()),
                                 ExplorationRequest("/login"), [], None])
def test_raw_plans_requests_rejected_before_execution(monkeypatch, raw):
    context, _ = _inputs()
    monkeypatch.setattr(execution, "explore_page", lambda *a, **kw: pytest.fail("Not approved"))
    with pytest.raises(TypeError):
        _run(raw, context)


def test_forged_request_type_rejected_before_execution(monkeypatch):
    context, _ = _inputs()
    invalid = ExplorationPlanValidationResult((ExplorationRequest("/login"),), (), ())
    monkeypatch.setattr(execution, "explore_page", lambda *a, **kw: pytest.fail("Not approved"))
    with pytest.raises(TypeError):
        _run(invalid, context)


@pytest.mark.parametrize("stale", ["testcase", "gap"])
def test_context_bindings_checked_before_execution(monkeypatch, stale):
    context, validated = _inputs()
    context = replace(context, testcase={**context.testcase, "id": "TC_OTHER"}) if stale == "testcase" \
        else replace(context, gaps=())
    monkeypatch.setattr(execution, "explore_page", lambda *a, **kw: pytest.fail("Stale request"))
    result = _run(validated, context)
    assert not result.exploration_results
    assert result.issues[0].code == ("TESTCASE_MISMATCH" if stale == "testcase" else "GAP_NOT_FOUND")


def test_redaction_truncation_forms_network_preserved(monkeypatch):
    context, validated = _inputs()
    approved = validated.valid_requests[0]
    approved = replace(approved,
                       purposes=(replace(approved.purposes[0], reason="password=SECRET"),),
                       grounding=({"source": "testcase_step",
                                   "value": BASE + "/login?token=SECRET"},))
    validated = replace(validated, valid_requests=(approved,))

    def fake(request, **kwargs):
        safe = ExplorationRequest(request.target + "?token=SECRET", reason="password=SECRET")
        return _observed(safe, final_url=BASE + "/login", page=_page(BASE + "/login"),
                         forms=({"action": BASE + "/login", "method": "POST"},),
                         network=({"method": "GET", "url": BASE + "/login", "status": 200},),
                         truncated=("elements", "network", "text"))

    monkeypatch.setattr(execution, "explore_page", fake)
    result = _run(validated, context)
    source = result.context.observations["ui_pages"][0]["explorations"][0]
    assert source["truncated"] == ["elements", "network", "text"]
    assert source["forms"][0]["method"] == "POST"
    assert source["network"][0]["status"] == 200
    assert "SECRET" not in json.dumps(result.to_dict())


def test_empty_evidence_and_no_valid_requests_leave_context_equal(monkeypatch):
    context, validated = _inputs()
    monkeypatch.setattr(execution, "explore_page", lambda request, **kwargs: _observed(
        request, page=PageMap(request.target, "")))
    result = _run(validated, context)
    assert result.context == context and result.context is not context
    assert len(result.successful_requests) == 1
    rejected = ExplorationPlanValidationResult((), (), ())
    monkeypatch.setattr(execution, "explore_page", lambda *a, **kw: pytest.fail("No requests"))
    empty = _run(rejected, context)
    assert empty.context == context and empty.context is not context
    assert not empty.exploration_results


def test_only_valid_entries_executed_and_no_llm_called(monkeypatch):
    from qctool.exploration_plan import RejectedExploration
    import qctool.llm_exploration
    import qctool.llm_resolution

    context, validated = _inputs()
    raw = PlannedExploration("https://foreign.test", ())
    partial = replace(validated, rejected_requests=(RejectedExploration(1, raw, ()),))
    calls = []

    def fake(request, **kwargs):
        calls.append(request.target)
        return _observed(request)

    def forbidden(*args, **kwargs):
        pytest.fail("Execution must not call an LLM")

    monkeypatch.setattr(execution, "explore_page", fake)
    monkeypatch.setattr(qctool.llm_exploration, "propose_exploration", forbidden)
    monkeypatch.setattr(qctool.llm_resolution, "propose_resolution", forbidden)
    result = _run(partial, context)
    assert calls == [BASE + "/login"]
    assert len(result.successful_requests) == 1


def test_conversion_failure_does_not_damage_prior_observations(monkeypatch):
    context, validated = _inputs(second=True)

    def fake(request, **kwargs):
        return _observed(request, page=object()) if request.target.endswith("/help") \
            else _observed(request)

    monkeypatch.setattr(execution, "explore_page", fake)
    result = _run(validated, context)
    assert len(result.successful_requests) == len(result.failed_requests) == 1
    assert result.context.observations["ui_pages"][0]["url"] == BASE + "/login"
    assert result.issues[0].request_index == 1

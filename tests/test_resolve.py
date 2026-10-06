"""Deterministic repairs require unique, recorded evidence."""

from dataclasses import replace
from copy import deepcopy
from pathlib import Path

import pytest

from qctool.executability import analyze_executability
from qctool.generate.loader import load_endpoints
from qctool.resolve import resolve_deterministically
from qctool.testcase import Step, StepKind, TestCase
from qctool.ui.crawl import Element, PageMap, UIMap


def _case(*steps: Step, **changes) -> TestCase:
    fields = dict(
        id="TC_LOGIN_001", module="LOGIN", title="Login", objective="Check login",
        steps=list(steps), traces_to=["AC-1"], source_quote="Login redirects to dashboard",
    )
    return TestCase(**{**fields, **changes})


def _step(seq: int, action: str, args: dict | None = None, note: str = "") -> Step:
    return Step(seq, StepKind.THEN if action.startswith("assert.") else StepKind.WHEN,
                action, args or {}, note)


def _map(*elements: Element) -> UIMap:
    return UIMap("https://portal.test", "2026-09-21 10:00", [
        PageMap("https://portal.test/login", "Login", elements=list(elements)),
    ])


def _button(id: str, name: str = "Login") -> Element:
    return Element(id=id, role="button", name=name, tag="button", test_id=id)


def _endpoints():
    path = Path(__file__).resolve().parent.parent / "samples/openapi/task-manager-sample.yaml"
    return load_endpoints(path)[0]


def test_unique_ui_match_resolves_locator_and_records_evidence():
    original = _case(
        _step(1, "ui.click", {"by_name": "login"}),
        _step(2, "assert.url_matches", {"pattern": "/dashboard$"}),
    )
    result = resolve_deterministically(original, ui_map=_map(_button("btn-login")))
    assert [g.code for g in result.before.gaps] == ["MISSING_LOCATOR"]
    assert [g.code for g in result.resolved_gaps] == ["MISSING_LOCATOR"]
    assert result.after == analyze_executability(result.case)
    assert result.after.executable is True
    assert result.case.steps[0].args == {"by_name": "login", "target": "btn-login"}
    assert result.changes[0].before == {"by_name": "login"}
    assert result.changes[0].evidence == {
        "source": "ui-map", "page": "https://portal.test/login",
        "element": _button("btn-login").to_dict(),
        "match": "unique exact normalized name",
    }
    assert original.steps[0].args == {"by_name": "login"}
    assert result.case is not original


def test_ambiguous_ui_match_keeps_gap_and_makes_no_change():
    original = _case(
        _step(1, "ui.click", {"by_name": "Login"}),
        _step(2, "assert.url_matches", {"pattern": "/dashboard$"}),
    )
    result = resolve_deterministically(original, ui_map=_map(
        _button("btn-login-a"), _button("btn-login-b"),
    ))
    assert result.changes == ()
    assert result.resolved_gaps == ()
    assert [g.code for g in result.unresolved_gaps] == ["MISSING_LOCATOR"]
    assert result.case.steps[0].args == original.steps[0].args


def test_absent_ui_match_keeps_gap():
    case = _case(
        _step(1, "ui.click", {"by_name": "Login"}),
        _step(2, "assert.url_matches", {"pattern": "/dashboard$"}),
    )
    result = resolve_deterministically(case, ui_map=_map(_button("btn-save", "Save")))
    assert result.changes == ()
    assert [g.code for g in result.unresolved_gaps] == ["MISSING_LOCATOR"]


def test_explicit_crawled_route_resolves_missing_url():
    case = _case(
        _step(1, "ui.goto", note="/login"),
        _step(2, "assert.url_matches", {"pattern": "/login$"}),
    )
    result = resolve_deterministically(case, ui_map=_map())
    assert result.case.steps[0].args == {"url": "https://portal.test/login"}
    assert [g.code for g in result.resolved_gaps] == ["MISSING_URL"]
    assert result.changes[0].evidence == {
        "source": "ui-map", "page": "https://portal.test/login", "route_hint": "/login",
    }


def test_openapi_unique_path_resolves_missing_method():
    case = _case(
        _step(1, "http.request", {"path": "/health"}),
        _step(2, "assert.http_status", {"expected": 200}),
    )
    result = resolve_deterministically(case, endpoints=_endpoints())
    assert result.case.steps[0].args == {"path": "/health", "method": "GET"}
    assert result.after.executable is True
    assert [g.code for g in result.resolved_gaps] == ["MISSING_HTTP_METHOD", "MISSING_RESPONSE",
                                                       "MISSING_ASSERTION"]
    assert result.changes[0].evidence["operation_id"] == "getHealth"
    assert result.changes[0].evidence["source"] == "openapi"


def test_openapi_source_ref_resolves_missing_path_without_guessing_method():
    case = _case(
        _step(1, "http.request", {"method": "GET"}),
        _step(2, "assert.http_status", {"expected": 200}),
        source_ref="openapi:getHealth",
    )
    result = resolve_deterministically(case, endpoints=_endpoints())
    assert result.case.steps[0].args == {"method": "GET", "path": "/health"}
    assert result.after.executable is True
    assert case.steps[0].args == {"method": "GET"}


def test_openapi_ambiguous_path_does_not_choose_method():
    case = _case(
        _step(1, "http.request", {"path": "/projects"}),
        _step(2, "assert.http_status", {"expected": 200}),
    )
    result = resolve_deterministically(case, endpoints=_endpoints())
    assert result.changes == ()
    assert [g.code for g in result.unresolved_gaps][:1] == ["MISSING_HTTP_METHOD"]


def test_multiple_gaps_resolve_only_locator_without_promoting_manual_case():
    case = _case(
        _step(1, "ui.click", {"by_name": "Login"}),
        _step(2, "assert.unmapped", {"expected": "Dashboard opens"}),
        execution="manual", requires="Account without permission",
    )
    result = resolve_deterministically(case, ui_map=_map(_button("btn-login")))
    assert [g.code for g in result.resolved_gaps] == ["MISSING_LOCATOR"]
    assert [g.code for g in result.unresolved_gaps] == [
        "MANUAL_EXECUTION", "MISSING_PRECONDITION", "UNMAPPED_ACTION", "MISSING_ASSERTION",
    ]
    assert result.case.execution == case.execution == "manual"
    assert result.case.requires == case.requires
    assert result.case.steps[1].args == case.steps[1].args


def test_multiple_openapi_servers_do_not_create_wrong_host():
    endpoints = _endpoints()
    health = next(ep for ep in endpoints if ep.operation_id == "getHealth")
    ambiguous = replace(health, servers=["https://one.test", "https://two.test"])
    case = _case(
        _step(1, "http.request", {"path": "/health"}),
        _step(2, "assert.http_status", {"expected": 200}),
    )
    result = resolve_deterministically(case, endpoints=[ambiguous])
    assert result.changes == ()
    assert result.case.steps[0].args == {"path": "/health"}


def _logical_route(expected="URL /login", **fields):
    return _case(_step(1, "perform.unmapped", {"description": "Open /login"}),
                 _step(2, "assert.unmapped", {"expected": expected}),
                 execution="manual", **fields)


def test_explicit_unmapped_routes_resolve_with_audit_and_safe_promotion():
    case, ui_map = _logical_route(), _map()
    snapshot = deepcopy((case, ui_map))
    result = resolve_deterministically(case, ui_map=ui_map)
    assert [(s.action, s.args) for s in result.case.steps] == [
        ("ui.goto", {"url": "/login"}), ("assert.url_matches", {"pattern": "/login"})]
    assert result.case.execution == "auto"
    assert result.after.executable
    result.case.validate()
    assert not result.unresolved_gaps
    assert [c.from_action for c in result.changes] == ["perform.unmapped", "assert.unmapped"]
    assert result.changes[1].before == {"expected": "URL /login"}
    assert result.changes[1].evidence["source_text"] == "URL /login"
    assert all(c.evidence["page"] == "https://portal.test/login" for c in result.changes)
    assert (case, ui_map) == snapshot


@pytest.mark.parametrize("expected", [
    "URL not /login", "URL NOT /login", "Not URL /login", "URL /login$",
    "URL /log.*", "URL /login or /dashboard", "URL /login; Delete hidden",
    "URL /dashboard", "URL /login/settings", "URL //foreign.test/login",
    "URL https://foreign.test/login", "URL /login?token=secret", "URL /login#secret",
    "URL /../login", "URL /login.*", "Dashboard opens", "Delete must not be visible",
])
def test_unsafe_or_ungrounded_expectations_remain_unmapped(expected):
    result = resolve_deterministically(_logical_route(expected), ui_map=_map())
    assert result.case.steps[0].action == "ui.goto"
    assert result.case.steps[1].action == "assert.unmapped"
    assert result.case.steps[1].args == {"expected": expected}
    assert result.case.execution == "manual"
    assert not result.after.executable


@pytest.mark.parametrize("description", [
    "Do not Open /login", "Open /login and click Delete", "Open /log.*",
    "Open /dashboard", "Open //foreign.test/login", "Open https://portal.test/login",
    "Click btn-fabricated", "POST /api/fabricated", "Open /login?secret=value",
])
def test_unsafe_or_ungrounded_actions_remain_unmapped(description):
    case = _logical_route()
    case.steps[0].args = {"description": description}
    result = resolve_deterministically(case, ui_map=_map())
    assert result.case.steps[0].action == "perform.unmapped"
    assert result.case.steps[0].args == case.steps[0].args
    assert not result.after.executable


@pytest.mark.parametrize("pages", [[],
    [PageMap("https://foreign.test/login", "Login")],
    [PageMap("https://portal.test/login", "One"), PageMap("https://portal.test/login", "Two")],
    [PageMap("https://portal.test/login?token=secret", "Login")],
])
def test_route_requires_unique_exact_same_origin_page(pages):
    result = resolve_deterministically(_logical_route(), ui_map=UIMap("https://portal.test", "", pages))
    assert not result.changes
    assert result.case.execution == "manual"


def test_no_evidence_or_remaining_setup_does_not_promote():
    assert not resolve_deterministically(_logical_route()).changes
    result = resolve_deterministically(_logical_route(requires="Provision account"), ui_map=_map())
    assert len(result.changes) == 2
    assert result.case.execution == "manual"
    assert {g.code for g in result.after.gaps} == {"MANUAL_EXECUTION", "MISSING_PRECONDITION"}


def test_route_mapping_does_not_discard_attached_expectation_or_fix_concrete_regex():
    case = _logical_route()
    case.steps[0].args["expectation"] = "Delete must stay hidden"
    case.steps[1].action = "assert.url_matches"
    case.steps[1].args = {"pattern": "/log.*"}
    result = resolve_deterministically(case, ui_map=_map())
    assert not result.changes
    assert result.case == case


def test_trusted_active_customer_given_resolves_without_llm_and_preserves_source():
    import json
    from tests.test_fixture_facts import inputs, GIVEN
    from tests.test_step_expansion import BASE
    from qctool.test_fixtures import FACT_REGISTRY
    case, context, store, _ = inputs({'role': 'customer', 'account_state': 'active'})
    ui = UIMap(BASE, 'now', [PageMap(BASE + '/login', 'Login')])
    snapshot = deepcopy((case, ui, store.to_dict()))
    result = resolve_deterministically(case, ui_map=ui, fixture_store=store)
    assert [s.action for s in result.case.steps] == ['ui.session', 'ui.goto', 'perform.unmapped', 'assert.unmapped']
    assert result.case.steps[1].args == {'url': BASE + '/login'}
    assert [s.seq for s in result.case.steps] == [1, 2, 3, 4]
    assert len(result.changes) == 1 and result.changes[0].step_seq == 1
    assert result.changes[0].evidence['facts'] == case.test_data[FACT_REGISTRY]
    assert [(g.code, g.step_seq) for g in result.resolved_gaps] == [('UNMAPPED_ACTION', 1)]
    assert [(g.code, g.step_seq) for g in result.after.gaps if g.code == 'UNMAPPED_ACTION'] == [('UNMAPPED_ACTION', 3), ('UNMAPPED_ACTION', 4)]
    for step in result.case.steps[:2]:
        source = json.loads(step.note.split('[resolution-expansion] ', 1)[1])
        assert source['type'] == 'validated-deterministic-expansion'
        assert source['source_step']['args']['description'] == GIVEN
    assert not result.after.executable
    assert (case, ui, store.to_dict()) == snapshot


@pytest.mark.parametrize('facts', [None, {'role': 'staff', 'account_state': 'active'},
                                   {'role': 'customer', 'account_state': 'locked'}])
def test_trusted_given_wrong_or_missing_facts_stays_unresolved(facts):
    from tests.test_fixture_facts import inputs
    from tests.test_step_expansion import BASE
    case, _, store, _ = inputs(facts)
    result = resolve_deterministically(case, ui_map=UIMap(BASE, 'now', [PageMap(BASE+'/login', 'Login')]), fixture_store=store)
    assert result.case == case and not result.changes


@pytest.mark.parametrize('problem', ['missing_credentials', 'missing_page', 'ambiguous_page',
                                      'foreign_page', 'extra_clause', 'no_store', 'forged_facts'])
def test_trusted_given_does_not_guess_or_discard_any_clause(problem):
    from tests.test_fixture_facts import inputs
    from tests.test_step_expansion import BASE
    case, _, store, _ = inputs({'role': 'customer', 'account_state': 'active'}, missing_credentials=problem=='missing_credentials')
    pages = [PageMap(BASE+'/login', 'Login')]
    if problem == 'missing_page': pages = []
    if problem == 'ambiguous_page': pages.append(PageMap(BASE+'/login', 'Different state'))
    if problem == 'foreign_page': pages = [PageMap('https://foreign.test/login', 'Login')]
    if problem == 'extra_clause': case.steps[0].args['description'] += '; unknown business setup'
    if problem == 'forged_facts': case.test_data['_fixture_facts']['active_user']['values']['role'] = 'admin'
    result = resolve_deterministically(case, ui_map=UIMap(BASE, 'now', pages), fixture_store=None if problem=='no_store' else store)
    assert result.case == case and not result.changes

"""Deterministic repairs require unique, recorded evidence."""

from dataclasses import replace
from pathlib import Path

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

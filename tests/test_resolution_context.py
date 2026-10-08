"""Exact, bounded evidence for future resolution without repair."""

import json
from copy import deepcopy
from pathlib import Path

import yaml
import pytest

from qctool.executability import analyze_executability
from qctool.generate.loader import load_endpoints
from qctool.model import Requirement, SourceRef
from qctool.resolution_context import MAX_ELEMENTS_PER_PAGE, MAX_UI_PAGES, build_resolution_context
from qctool.testcase import ACTION_SPECS, ActionSpec, Step, StepKind, TestCase
from qctool.ui.crawl import Element, PageMap, UIMap


def _case(*steps: Step, **changes) -> TestCase:
    fields = dict(
        id="TC_LOGIN_001", module="LOGIN", title="Login", objective="Check login",
        steps=list(steps), traces_to=["FR-LOGIN-001"], source_quote="User can log in",
        source_ref="srs/login.md:12",
    )
    return TestCase(**{**fields, **changes})


def _step(seq: int, action: str, args: dict | None = None, note: str = "") -> Step:
    return Step(seq, StepKind.THEN if action.startswith("assert.") else StepKind.WHEN,
                action, args or {}, note)


def _ui_map() -> UIMap:
    return UIMap("https://portal.test", "2026-09-21 10:00", [
        PageMap("https://portal.test/login", "Login", elements=[
            Element("email", "textbox", "Email", "input", test_id="email"),
            Element("btn-login", "button", "Login", "button", test_id="btn-login"),
        ]),
        PageMap("https://portal.test/admin", "Admin", elements=[
            Element("btn-delete", "button", "Delete", "button", test_id="btn-delete"),
        ]),
    ])


def _endpoints():
    path = Path(__file__).resolve().parent.parent / "samples/openapi/task-manager-sample.yaml"
    return load_endpoints(path)[0]


def test_traced_requirement_only_and_document_provenance():
    case = _case(_step(1, "assert.unmapped", {"expected": "Logged in"}))
    requirements = [
        Requirement("FR-LOGIN-001", "functional", "Login", statement="User can log in",
                    source=SourceRef("srs/login.md", 12, "User can log in")),
        Requirement("FR-ADMIN-001", "functional", "Delete users", statement="Admin can delete"),
    ]
    context = build_resolution_context(case, analyze_executability(case).gaps,
                                       requirements={"requirements": [r.to_dict() for r in requirements]})
    selected = context.specification["requirements"]
    assert len(selected) == 1
    assert selected[0]["id"] == "FR-LOGIN-001"
    assert selected[0]["statement"] == "User can log in"
    assert selected[0]["source"] == {"file": "srs/login.md", "line": 12,
                                     "quote": "User can log in"}
    assert selected[0]["evidence"] == {"type": "requirement", "id": "FR-LOGIN-001"}


def test_ui_evidence_is_scoped_to_explicit_login_route():
    case = _case(
        _step(1, "ui.goto", {"url": "/login"}),
        _step(2, "assert.url_matches", {"pattern": "/login$"}),
    )
    context = build_resolution_context(case, [], ui_map=_ui_map())
    pages = context.observations["ui_pages"]
    assert [page["url"] for page in pages] == ["https://portal.test/login"]
    assert [element["test_id"] for element in pages[0]["elements"]] == ["email", "btn-login"]
    assert pages[0]["evidence"]["type"] == "ui-map"
    assert "btn-delete" not in json.dumps(context.to_dict())


def test_literal_references_in_logical_candidate_select_evidence_without_repair():
    case = _case(
        _step(1, "perform.unmapped", {"description": "Anonymous at /login; account supplied"}),
        _step(2, "perform.unmapped", {"description": "Click Login"}),
        _step(3, "assert.unmapped", {"expected": "POST /projects returns 201; URL /login"}),
    )
    ui = _ui_map()
    ui.pages.append(deepcopy(ui.pages[0]))
    saved = deepcopy((case, ui))
    context = build_resolution_context(case, analyze_executability(case).gaps,
                                       ui_map=ui, endpoints=_endpoints())
    assert [p["url"] for p in context.observations["ui_pages"]] == ["https://portal.test/login"]
    assert [(op["method"], op["path"]) for op in context.interface_contract["api_operations"]] == [
        ("POST", "/projects")]
    assert (case, ui) == saved
    assert all(s.action in case.UNMAPPED_ACTIONS for s in case.steps)


def test_compound_workflow_keeps_all_three_explicit_page_references():
    routes = ["/basket", "/review", "/history"]
    ui = UIMap("https://portal.test", "recorded", [
        PageMap("https://portal.test" + route, route, elements=[
            Element("control", "button", route, "button", test_id=route[1:] + "-control")])
        for route in routes + ["/admin"]
    ])
    case = _case(
        _step(1, "perform.unmapped", {"description": "Open /basket; continue to /review; submit"}),
        _step(2, "assert.unmapped", {"expected": "URL /history; heading visible"}),
    )
    before = deepcopy((case, ui))
    context = build_resolution_context(case, analyze_executability(case).gaps, ui_map=ui)
    assert {page["url"] for page in context.observations["ui_pages"]} == {
        "https://portal.test" + route for route in routes}
    assert context.observations["omitted_ui_pages"] == 0
    assert (case, ui) == before


def test_explicit_page_selection_is_still_bounded():
    routes = [f"/state-{i}" for i in range(MAX_UI_PAGES + 2)]
    ui = UIMap("https://portal.test", "recorded", [
        PageMap("https://portal.test" + route, route) for route in routes])
    case = _case(_step(1, "perform.unmapped", {"description": "; ".join(routes)}))
    context = build_resolution_context(case, (), ui_map=ui)
    assert len(context.observations["ui_pages"]) == MAX_UI_PAGES
    assert context.observations["omitted_ui_pages"] == 2


@pytest.mark.parametrize("reference", [
    "/login-extra", "/login/subpage", "/login?next=/admin", "/login$", "/login.*",
    "https://foreign.test/login", "login", "sign in",
])
def test_literal_reference_selection_does_not_guess_routes(reference):
    case = _case(_step(1, "perform.unmapped", {"description": f"Inspect {reference}"}))
    assert build_resolution_context(case, (), ui_map=_ui_map()).observations["ui_pages"] == []


def test_conflicting_duplicate_page_states_remain_ambiguous():
    ui = _ui_map()
    changed = deepcopy(ui.pages[0])
    changed.elements[0].name = "Different email control"
    ui.pages.append(changed)
    case = _case(_step(1, "perform.unmapped", {"description": "Inspect /login"}))
    assert build_resolution_context(case, (), ui_map=ui).observations["ui_pages"] == []


def test_api_identifiers_must_be_adjacent_in_the_same_field():
    case = _case(_step(1, "perform.unmapped", {"description": "POST"}),
                 _step(2, "assert.unmapped", {"expected": "/projects"}))
    assert build_resolution_context(case, (), endpoints=_endpoints()).interface_contract["api_operations"] == []


def test_negative_literal_reference_only_selects_observation_not_expectation():
    case = _case(_step(1, "assert.unmapped", {"expected": "URL not /login"}))
    before = case.to_dict()
    context = build_resolution_context(case, (), ui_map=_ui_map())
    assert context.observations["ui_pages"][0]["url"].endswith("/login")
    assert context.testcase["steps"][0]["args"]["expected"] == "URL not /login"
    assert case.to_dict() == before


def test_unique_locator_scopes_ui_without_a_route():
    case = _case(
        _step(1, "ui.click", {"by_name": "Login"}),
        _step(2, "assert.url_matches", {"pattern": "/dashboard$"}),
    )
    pages = build_resolution_context(case, [], ui_map=_ui_map()).observations["ui_pages"]
    assert [page["url"] for page in pages] == ["https://portal.test/login"]


def test_api_evidence_requires_exact_method_and_path():
    case = _case(
        _step(1, "http.request", {"method": "POST", "path": "/projects"}),
        _step(2, "assert.http_status", {"expected": 201}),
    )
    context = build_resolution_context(case, [], endpoints=_endpoints())
    operations = context.interface_contract["api_operations"]
    assert [(op["method"], op["path"], op["operation_id"]) for op in operations] == [
        ("POST", "/projects", "createProject"),
    ]
    assert operations[0]["evidence"] == {"type": "openapi", "operation_id": "createProject"}


def test_api_contract_and_ui_observation_are_separate():
    case = _case(
        _step(1, "ui.goto", {"url": "/login"}),
        _step(2, "http.request", {"method": "GET", "path": "/health"}),
        _step(3, "assert.http_status", {"expected": 200}),
    )
    data = build_resolution_context(case, [], ui_map=_ui_map(), endpoints=_endpoints()).to_dict()
    assert "api_operations" in data["interface_contract"]
    assert "api_operations" not in data["observations"]
    assert "ui_pages" in data["observations"]
    assert "ui_pages" not in data["interface_contract"]


def test_openapi_source_ref_fragment_selects_one_operation():
    case = _case(
        _step(1, "assert.unmapped", {"expected": "Project exists"}),
        source_ref="openapi:getHealth#responses.200",
    )
    operations = build_resolution_context(case, [], endpoints=_endpoints()).interface_contract[
        "api_operations"
    ]
    assert [operation["operation_id"] for operation in operations] == ["getHealth"]


def test_unmapped_business_meaning_and_step_note_survive():
    case = _case(
        _step(1, "perform.unmapped", {"description": "User submits registration form"},
              "Use an unregistered email"),
        _step(2, "assert.unmapped", {"expected": "Account is created"}),
    )
    gaps = analyze_executability(case).gaps
    data = build_resolution_context(case, gaps).to_dict()
    assert data["testcase"]["steps"][0] == {
        "seq": 1, "kind": "when", "action": "perform.unmapped",
        "args": {"description": "User submits registration form"},
        "note": "Use an unregistered email",
    }
    assert data["testcase"]["steps"][1]["args"]["expected"] == "Account is created"
    assert [gap["code"] for gap in data["gaps"]] == [gap.code for gap in gaps]


def test_allowed_actions_come_from_action_specs(monkeypatch):
    monkeypatch.setitem(ACTION_SPECS, "ui.context_probe", ActionSpec(
        required=("target",), optional=("mode",),
    ))
    case = _case(_step(1, "assert.unmapped", {"expected": "x"}))
    actions = build_resolution_context(case, []).allowed_actions
    assert actions["ui.context_probe"] == {"required": ["target"], "optional": ["mode"]}
    assert actions["ui.fill"]["required"] == list(ACTION_SPECS["ui.fill"].required)


def test_unconnected_evidence_is_empty_and_no_mutation_occurs():
    case = _case(
        _step(1, "perform.unmapped", {"description": "Complete workflow"}),
        _step(2, "assert.unmapped", {"expected": "Done"}),
        test_data={"email": "alice@example.test"},
    )
    before = case.to_dict()
    context = build_resolution_context(
        case, analyze_executability(case).gaps,
        requirements=[{"id": "FR-OTHER-001", "statement": "Unrelated"}],
        ui_map=_ui_map(), endpoints=_endpoints(),
    )
    assert context.specification["requirements"] == []
    assert context.observations["ui_pages"] == []
    assert context.interface_contract["api_operations"] == []
    assert case.to_dict() == before
    case.test_data["email"] = "changed"
    assert context.testcase["test_data"]["email"] == "alice@example.test"
    json.dumps(context.to_dict())
    yaml.safe_dump(context.to_dict())


def test_element_limit_reports_omissions_and_keeps_named_element():
    many = [Element(f"field-{i}", "textbox", f"Field {i}", "input")
            for i in range(MAX_ELEMENTS_PER_PAGE + 5)]
    many.append(Element("btn-login", "button", "Login", "button", test_id="btn-login"))
    ui_map = UIMap("https://portal.test", "now", [
        PageMap("https://portal.test/login", "Login", elements=many),
    ])
    case = _case(
        _step(1, "ui.goto", {"url": "/login"}),
        _step(2, "ui.click", {"target": "btn-login", "by_name": "Login"}),
        _step(3, "assert.url_matches", {"pattern": "/dashboard$"}),
    )
    page = build_resolution_context(case, [], ui_map=ui_map).observations["ui_pages"][0]
    assert len(page["elements"]) == MAX_ELEMENTS_PER_PAGE
    assert page["elements"][0]["test_id"] == "btn-login"
    assert page["omitted_elements"] == 6


def test_salonhub_compound_outcome_selects_exact_root_and_login_without_fuzzy_routes():
    case = _case(
        _step(1, 'perform.unmapped', {'description': 'Phiên anonymous ở /login; tài khoản customer đang hoạt động và mật khẩu đúng do người vận hành cung cấp'}),
        _step(2, 'perform.unmapped', {'description': 'Nhập email và mật khẩu đúng; bấm Đăng nhập'}),
        _step(3, 'assert.unmapped', {'expected': 'Đăng nhập thành công; URL chuyển tới /; POST /api/auth/login trả 200 với success=true'}),
    )
    ui = _ui_map()
    root = PageMap('https://portal.test/', 'Home')
    ui.pages.extend([root, deepcopy(root)])
    before = deepcopy((case, ui))
    context = build_resolution_context(case, analyze_executability(case).gaps, ui_map=ui)
    assert [p['url'] for p in context.observations['ui_pages']] == ['https://portal.test/login', 'https://portal.test/']
    assert context.observations['omitted_ui_pages'] == 0
    case.steps[2].args['expected'] = 'URL chuyển tới /wrong'
    wrong = build_resolution_context(case, analyze_executability(case).gaps, ui_map=ui)
    assert [p['url'] for p in wrong.observations['ui_pages']] == ['https://portal.test/login']
    assert ui == before[1]

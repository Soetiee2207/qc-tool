"""Exact, bounded evidence for future resolution without repair."""

import json
from pathlib import Path

import yaml

from qctool.executability import analyze_executability
from qctool.generate.loader import load_endpoints
from qctool.model import Requirement, SourceRef
from qctool.resolution_context import MAX_ELEMENTS_PER_PAGE, build_resolution_context
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

"""Bounded empty-form exploration: strict approval and local Chromium evidence."""
from copy import deepcopy
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

import pytest

from qctool.executability import analyze_executability
from qctool.exploration_plan import (
    ExplorationAction, ExplorationPlan, ExplorationPurpose, PlannedExploration,
    validate_exploration_plan,
)
from qctool.generate.from_openapi import IdAllocator
from qctool.generate.from_requirements import generate_from_acceptance
from qctool.generate.loader import load_endpoints
from qctool.llm_exploration import parse_exploration_plan
from qctool.llm_resolution import LLMResponseError
from qctool.resolution_context import build_resolution_context
from qctool.ui.crawl import Element, PageMap, UIMap
from qctool.ui.explore import ExplorationRequest, explore_page


def setup(base="https://app.test"):
    req = {"id": "AC-EMPTY", "kind": "acceptance_criterion",
           "given": "Phiên anonymous ở /login; cả hai ô email và mật khẩu trống",
           "when": "Bấm Đăng nhập",
           "then": "Hiển thị Vui lòng điền đầy đủ thông tin; không gửi POST /api/auth/login; URL vẫn ở /login"}
    case = generate_from_acceptance([req], IdAllocator(), "AUTH").cases[0]
    ui = UIMap(base, "recorded", [PageMap(base + "/login", "Login", elements=[
        Element("submit", "button", "Đăng nhập", "button", test_id="login-submit-btn"),
        Element("email", "input", "Email", "input", input_type="text", test_id="login-email-input"),
        Element("password", "input", "Password", "input", input_type="password", test_id="login-password-input"),
        Element("delete", "button", "Delete", "button", test_id="delete"),
    ])])
    endpoints, _, _ = load_endpoints(Path(__file__).resolve().parents[1] / "samples/smoke/openapi.yaml")
    context = build_resolution_context(case, analyze_executability(case).gaps,
                                       requirements=[req], ui_map=ui, endpoints=endpoints)
    context.interface_contract["api_operations"][0]["servers"] = [base]
    plan = ExplorationPlan(case.id, (PlannedExploration(
        "/login", (ExplorationPurpose("UNMAPPED_ACTION", 2, "Observe required empty submit", "observe_network"),),
        actions=(ExplorationAction("login-submit-btn", 2),)),))
    return case, ui, context, plan


def test_grounded_click_and_immutability():
    case, ui, context, plan = setup()
    before = deepcopy((case, ui, context, plan))
    result = validate_exploration_plan(plan, context, case, ui.base_url)
    assert result.status == "VALID"
    assert result.valid_requests[0].request.actions == plan.requests[0].actions
    assert result.valid_requests[0].grounding[-1]["capture_requests"]["path"] == "/api/auth/login"
    assert (case, ui, context, plan) == before


def test_action_json_is_untrusted_and_strict():
    case, ui, context, plan = setup()
    parsed = parse_exploration_plan(json.dumps(plan.to_dict()))
    assert parsed == plan
    assert validate_exploration_plan(parsed, context, case, ui.base_url).status == "VALID"
    raw = plan.to_dict()
    raw["requests"][0]["actions"][0]["javascript"] = "anything"
    with pytest.raises(LLMResponseError):
        parse_exploration_plan(json.dumps(raw))


def test_request_actions_are_deduplicated_and_total_budget_is_bounded():
    case, ui, context, plan = setup()
    item = plan.requests[0]
    duplicated = replace(plan, requests=(item, item))
    result = validate_exploration_plan(duplicated, context, case, ui.base_url)
    assert len(result.valid_requests) == 1
    assert result.valid_requests[0].plan_indices == (0, 1)
    # Differing action sequences must not collapse into one request; the total
    # plan budget rejects a second sequence that would add two more clicks.
    extended = replace(plan, requests=(item, replace(item, actions=item.actions * 2)))
    result = validate_exploration_plan(extended, context, case, ui.base_url)
    assert result.status == "PARTIALLY_VALID"
    assert result.issues[0].code == "ACTION_BUDGET_EXCEEDED"


def test_current_tc002_outcome_gap_can_justify_source_required_click():
    case, ui, context, plan = setup()
    case.steps[-1].args["expected"] = "không gửi POST /api/auth/login"
    context = build_resolution_context(case, analyze_executability(case).gaps,
                                       requirements=context.specification["requirements"], ui_map=ui)
    context.interface_contract["api_operations"] = setup()[2].interface_contract["api_operations"]
    item = replace(plan.requests[0], actions=(ExplorationAction("login-submit-btn", 3),),
                   purposes=(ExplorationPurpose("UNMAPPED_ACTION", 3, "Observe missing no-POST outcome"),))
    result = validate_exploration_plan(replace(plan, requests=(item,)), context, case, ui.base_url)
    assert result.status == "VALID"


@pytest.mark.parametrize("mutation", ["fabricated", "ambiguous", "foreign", "delete", "unrelated", "js", "budget"])
def test_unsafe_actions_rejected(mutation):
    case, ui, context, plan = setup()
    action = plan.requests[0].actions[0]
    if mutation == "fabricated":
        action = replace(action, target="imaginary")
    elif mutation == "ambiguous":
        page = context.observations["ui_pages"][0]
        page["elements"].append(deepcopy(page["elements"][0]))
    elif mutation == "foreign":
        context.observations["ui_pages"][0]["url"] = ui.base_url + "/admin"
    elif mutation == "delete":
        action = replace(action, target="delete")
    elif mutation == "unrelated":
        action = replace(action, step_seq=1)
    elif mutation == "js":
        action = replace(action, action="evaluate")
    actions = (action,) * (3 if mutation == "budget" else 1)
    plan = replace(plan, requests=(replace(plan.requests[0], actions=actions),))
    result = validate_exploration_plan(plan, context, case, ui.base_url)
    assert result.status == "REJECTED"
    assert not result.valid_requests


def test_raw_action_request_never_opens_browser(monkeypatch):
    monkeypatch.setattr("qctool.ui.explore.BrowserSession.start", lambda *a: pytest.fail("unapproved browser"))
    result = explore_page(ExplorationRequest("/login", actions=(ExplorationAction("login-submit-btn", 2),)),
                          base_url="https://app.test")
    assert result.issues[0].code == "ACTION_NOT_VALIDATED"


@pytest.fixture
def local_app():
    counts = {"POST": 0}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            payload = '''<title>Login</title><form>
              <input data-testid="login-email-input" type="text">
              <input data-testid="login-password-input" type="password">
              <button data-testid="login-submit-btn">Đăng nhập</button></form>
              <script>document.querySelector('form').onsubmit=e=>{
                e.preventDefault();
                let p=document.createElement('p');p.setAttribute('role','alert');
                p.dataset.testid='login-validation-message';
                p.textContent='Vui lòng điền đầy đủ thông tin';document.body.append(p);
                if(location.search.includes('request'))fetch('/api/auth/login', {method:'POST',body:'SECRET_PAYLOAD'});
              };</script><p>token=SECRET_TOKEN</p>'''
            if "prefilled" in self.path:
                payload = payload.replace('type="password"', 'type="password" value="SECRET_PASSWORD"')
            self.wfile.write(payload.encode())
        def do_POST(self):
            counts["POST"] += 1
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"token":"SECRET_RESPONSE"}')
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", counts
    server.shutdown()
    server.server_close()


@pytest.mark.playwright
@pytest.mark.parametrize("query,expected", [("", 0), ("?request", 1), ("?prefilled", None)])
def test_post_click_observation(local_app, query, expected):
    base, counts = local_app
    case, ui, context, plan = setup(base)
    # Exact selected page identity includes query; no guessed target introduced.
    context.observations["ui_pages"][0]["url"] += query
    plan = replace(plan, requests=(replace(plan.requests[0], target="/login" + query),))
    approved = validate_exploration_plan(plan, context, case, base)
    assert approved.status == "VALID"
    before = deepcopy((case, ui, context, plan, approved))
    result = explore_page(approved.valid_requests[0], base_url=base, render_wait_ms=100)
    serialized = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "SECRET_" not in serialized
    assert (case, ui, context, plan, approved) == before
    if expected is None:
        assert result.issues[0].code == "ACTION_PRECONDITION_FAILED"
        assert counts["POST"] == 0
        return
    assert result.explored and not result.issues
    assert result.action_observations[0]["request_count"] == expected
    assert result.action_observations[0]["source_step_seq"] == 2
    assert "Vui lòng điền đầy đủ thông tin" in result.page.text
    assert any(e.test_id == "login-validation-message" and e.role == "alert"
               for e in result.page.elements)
    assert counts["POST"] == expected

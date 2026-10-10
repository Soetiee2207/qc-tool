"""`mode: write`: ghi dữ liệu chỉ khi được bật + xác nhận; safe mode giữ nguyên mọi chặn cũ."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from qctool.agent.safety import SafetyPolicy, SafetyError


def route(url, method="POST"):
    r = Mock()
    r.request.url, r.request.method = url, method
    r.request.is_navigation_request.return_value = False
    r.request.post_data = "{}"
    r.request.redirected_from = None
    return r


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_safe_mode_blocks_every_write_method(method):
    policy = SafetyPolicy("http://app.test")
    r = route("http://app.test/api/orders/1", method)
    policy._route(r)
    r.abort.assert_called_once() and r.continue_.assert_not_called()
    assert policy.blocked_critical == 1


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_write_mode_allows_same_origin_writes(method):
    policy = SafetyPolicy("http://app.test", write_mode=True)
    r = route("http://app.test/api/orders/1", method)
    policy._route(r)
    r.continue_.assert_called_once()
    assert policy.blocked_critical == 0


def test_write_mode_still_blocks_deny_list_and_foreign_origin():
    policy = SafetyPolicy("http://app.test", write_mode=True, write_deny=["put  /api/auth/change-password"])
    denied, foreign = route("http://app.test/api/auth/change-password", "PUT"), route("http://evil.test/api/x")
    policy._route(denied)
    policy._route(foreign)
    denied.abort.assert_called_once() and foreign.abort.assert_called_once()
    assert policy.blocked_critical == 2


def test_dry_run_never_sends_the_write_and_records_it():
    policy = SafetyPolicy("http://app.test", write_mode=True)
    policy.dry_run = True
    r = route("http://app.test/api/orders")
    policy._route(r)
    r.abort.assert_called_once() and r.continue_.assert_not_called()
    assert policy.write_reached and policy.blocked_critical == 0


def test_socket_io_polling_is_background_not_an_unreviewed_write():
    policy = SafetyPolicy("http://app.test")
    r = route("http://app.test/socket.io/?EIO=4&transport=polling&sid=x")
    policy._route(r)
    r.abort.assert_called_once()
    assert policy.blocked_critical == 0 and policy.blocked_background == 1


def test_risky_navigation_and_controls_only_open_in_write_mode_or_reviewed():
    assert SafetyPolicy("http://app.test", write_mode=True).url("/admin")
    with pytest.raises(SafetyError):
        SafetyPolicy("http://app.test").url("/admin")
    safe = SafetyPolicy("http://app.test", safe_controls=["user-menu-logout"])
    safe.approve_action("http://app.test/", "ui.click", {"target": "user-menu-logout"})
    with pytest.raises(SafetyError):
        safe.approve_action("http://app.test/", "ui.click", {"target": "account-logout"})


def test_http_write_step_needs_write_mode_and_contract():
    from qctool.core.testcase import Step, StepKind, TestCase
    ep = SimpleNamespace(method="DELETE", path="/api/cart", contract_servers=[], servers=[])
    case = TestCase(id="TC_W_1", module="M", title="t", objective="o", steps=[
        Step(1, StepKind.WHEN, "http.request", {"method": "DELETE", "path": "/api/cart"})])
    with pytest.raises(SafetyError, match="mode: write"):
        SafetyPolicy("http://app.test", endpoints=[ep]).check_case(case)
    SafetyPolicy("http://app.test", endpoints=[ep], write_mode=True).check_case(case)
    with pytest.raises(SafetyError, match="write.deny"):
        SafetyPolicy("http://app.test", endpoints=[ep], write_mode=True, write_deny=["DELETE /api/cart"]).check_case(case)


def test_observe_only_operation_is_in_contract_but_never_generated(tmp_path):
    import yaml
    from qctool.generate import generate_all
    from qctool.generate.loader import load_endpoints
    spec = tmp_path / "api.yaml"
    spec.write_text(yaml.safe_dump({"openapi": "3.0.3", "info": {"title": "t", "version": "1"}, "paths": {
        "/api/orders": {"post": {"operationId": "createOrder", "x-qc-observe-only": True,
                                 "responses": {"201": {"description": "ok"}}},
                        "get": {"operationId": "listOrders", "responses": {"200": {"description": "ok"}}}}}}))
    endpoints, _, _ = load_endpoints(spec)
    assert {(e.method, e.observe_only) for e in endpoints} == {("POST", True), ("GET", False)}
    cases, _, meta = generate_all(None, spec, "M")
    assert cases and all("POST" not in str(c.steps[0].args.get("method", "")) for c in cases if c.steps)
    assert any("x-qc-observe-only" in s for s in meta["skipped"])


def test_mode_config_and_cli_override(tmp_path, monkeypatch):
    from qctool.pipeline import PipelineConfig
    from qctool.config import ConfigError
    path = tmp_path / "qctool.yaml"
    path.write_text("mode: write\nwrite:\n  deny: ['PUT /api/auth/change-password']\n")
    cfg = PipelineConfig.from_file(path)
    assert cfg.write_mode and cfg.write_deny == ("PUT /api/auth/change-password",)
    path.write_text("mode: yolo\n")
    with pytest.raises(ConfigError):
        PipelineConfig.from_file(path)


def test_write_run_without_tty_needs_yes(monkeypatch, tmp_path, capsys):
    import qctool.cli as cli
    import qctool.cli_run as cli_run
    monkeypatch.chdir(tmp_path)
    cli.main(["init", "shop/cart"])
    (tmp_path / "projects/shop/cart/openapi.yaml").write_text(
        "openapi: 3.0.3\ninfo: {title: t, version: '1'}\npaths: {/h: {get: {responses: {'200': {description: OK}}}}}\n")
    ran = []
    monkeypatch.setattr(cli_run.pipeline, "run_pipeline", lambda cfg, **kw: ran.append(cfg) or pytest.fail("must not run"))
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: False))
    assert cli.main(["run", "shop", "--write", "--no-llm"]) == 2
    assert not ran and "--yes" in capsys.readouterr().err


class _Shop(BaseHTTPRequestHandler):
    PAGE = (b"<!doctype html><title>Shop</title><button data-testid=add-btn onclick=\""
            b"fetch('/api/items',{method:'POST',body:'{}'}).then(()=>{document.title='Added';"
            b"document.body.insertAdjacentHTML('beforeend','<p role=status data-testid=done>Added</p>')})\">Add</button>")

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
        self.wfile.write(self.PAGE)

    def do_POST(self):
        self.server.posts += 1
        self.send_response(201); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(b"{}")


@pytest.mark.playwright
def test_browser_dry_run_stops_before_write_and_runner_writes_once():
    from tests.test_browser import HAVE_BROWSER
    if not HAVE_BROWSER:
        pytest.skip("Chromium not installed")
    from qctool.agent.tools import AgentTools
    from qctool.execute.runner import HttpSession, run_case
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Shop)
    server.posts = 0
    threading.Thread(target=server.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{server.server_address[1]}"
    intent = {"id": "AC:then", "req_id": "AC", "given": "Phiên anonymous", "when": "Mở /; bấm Add",
              "expected": "Hiển thị Added"}
    tools = AgentTools(intent, "TC_W_001", "W", SafetyPolicy(site, write_mode=True))
    try:
        raw = {"title": "Add item", "steps": [
            {"seq": 1, "kind": "given", "action": "ui.session", "args": {"mode": "anonymous"}},
            {"seq": 2, "kind": "when", "action": "ui.goto", "args": {"url": "/"}},
            {"seq": 3, "kind": "when", "action": "ui.click", "args": {"target": "add-btn"}},
            {"seq": 4, "kind": "then", "action": "assert.text", "args": {"target": "done", "expected": "Added"},
             "source": {"req_id": "AC", "quote": "Hiển thị Added"}}]}
        drafted = tools.call("draft_case", raw)
        assert drafted.get("ok"), drafted
        assert server.posts == 0                                   # dry-run không gửi request ghi
        assert tools.ready.generation_status == "needs_review"
        assert any(r.startswith("WRITE_NOT_DRY_RUN") for r in tools.ready.review_reasons)
        session = HttpSession(site)
        try:
            runtime = run_case(tools.ready, session, browser=tools.browser)
        finally:
            session.close()
        assert runtime.status == "Pass" and server.posts == 1      # runner ghi đúng một lần
    finally:
        tools.close()
        server.shutdown()


def test_safe_paths_open_reviewed_pages_only():
    policy = SafetyPolicy("http://app.test", safe_paths=["/register"])
    assert policy.url("/register")
    with pytest.raises(SafetyError):
        policy.url("/admin")

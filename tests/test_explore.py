"""Real Chromium observations against a local server with measurable side effects."""

import json
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml

from qctool.ui.explore import ExplorationRequest, explore_page
from tests.test_browser import HAVE_BROWSER


@pytest.fixture(scope="module")
def exploration_site():
    counts = {"submit": 0, "followed": 0, "foreign": 0}
    secret = "EXPLORER_SECRET_12345"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            counts["submit"] += 1
            self.send_response(200)
            self.end_headers()

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/external-chain":
                self.send_response(302)
                self.send_header("Location", "/external")
                self.end_headers()
                return
            if path == "/external":
                self.send_response(302)
                self.send_header("Location", f"{foreign_url}/foreign?token={secret}")
                self.end_headers()
                return
            if path == "/protected" and "auth=yes" not in self.headers.get("Cookie", ""):
                self.send_response(302)
                self.send_header("Location", "/login")
                self.end_headers()
                return
            if path == "/foreign":
                counts["foreign"] += 1
            if path == "/forgot":
                counts["followed"] += 1
            status = 404 if path == "/missing" else 200
            self.send_response(status)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if path == "/login":
                html = f'''<title>Login</title><h1>Login</h1>
                  <form id="login-form" action="/action" method="post">
                    <label>Email</label><input id="email" data-testid="email"
                      name="email" type="email" required value="private@example.test">
                    <input data-testid="password" type="password" value="{secret}">
                    <input name="token" type="hidden" value="{secret}">
                    <label>Secret<textarea name="secret">{secret}</textarea></label>
                    <button data-testid="btn-login">Login</button>
                    <button data-testid="delete">Delete</button>
                  </form>
                  <a href="/forgot?token={secret}">Forgot password</a>
                  <p>Bearer {secret}</p><p>token={secret}</p>
                  <script>localStorage.setItem('token', '{secret}');
                    fetch('/api/info?token={secret}');</script>'''
            elif path == "/protected":
                html = '<title>Private</title><h1>Account</h1><button data-testid="profile">Profile</button>'
            elif path == "/external-js":
                html = f'<script>location.href="{foreign_url}/foreign?token={secret}"</script><button>Redirect</button>'
            elif path == "/empty":
                html = '<title>Empty</title>'
            elif path == "/many":
                html = '<title>Many</title>' + ''.join(f'<button data-testid="b{i}">B{i}</button>' for i in range(100))
            else:
                html = '<title>Local page</title><button>Local</button>'
            self.wfile.write(html.encode())

    foreign = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    foreign_url = f"http://127.0.0.1:{foreign.server_port}"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    for instance in (server, foreign):
        threading.Thread(target=instance.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", counts, secret
    for instance in (server, foreign):
        instance.shutdown()
        instance.server_close()


browser_required = pytest.mark.skipif(not HAVE_BROWSER, reason="Chromium is unavailable")


@pytest.mark.playwright
@browser_required
def test_anonymous_login_elements_forms_and_network(exploration_site):
    site, _, _ = exploration_site
    result = explore_page(ExplorationRequest("/login", collect_network=True), base_url=site)
    assert result.explored and result.issues == ()
    assert result.final_url == site + "/login"
    assert result.page.title == "Login"
    elements = {element.test_id: element for element in result.page.elements}
    assert elements["email"].input_type == "email"
    assert elements["email"].required
    assert elements["password"].input_type == "password"
    assert elements["btn-login"].name == "Login"
    assert result.forms[0] == {"id": "login-form", "name": "", "method": "POST", "action": site + "/action"}
    assert any(item["url"] == site + "/api/info" for item in result.network)
    assert result.to_dict()["source"]["type"] == "playwright_exploration"


def _state(tmp_path, site):
    state = tmp_path / "trusted-state.json"
    state.write_text(json.dumps({
        "cookies": [{"name": "auth", "value": "yes", "domain": "127.0.0.1", "path": "/",
                     "expires": -1, "httpOnly": True, "secure": False, "sameSite": "Lax"}],
        "origins": [{"origin": site, "localStorage": [{"name": "token", "value": "STATE_SECRET"}]}],
    }))
    return state


@pytest.mark.playwright
@browser_required
def test_authenticated_state_is_reused_read_only_and_ignored_for_anonymous(exploration_site, tmp_path):
    site, _, _ = exploration_site
    state = _state(tmp_path, site)
    before = state.read_bytes()
    authenticated = explore_page(ExplorationRequest("/protected", session="authenticated"),
                                 base_url=site, storage_state=state)
    assert authenticated.explored
    assert authenticated.final_url == site + "/protected"
    assert authenticated.page.elements[0].test_id == "profile"
    anonymous = explore_page(ExplorationRequest("/protected"), base_url=site, storage_state=state)
    assert anonymous.final_url == site + "/login"
    assert state.read_bytes() == before
    assert "STATE_SECRET" not in json.dumps(authenticated.to_dict())


def test_missing_auth_state_returns_issue_before_browser_start():
    result = explore_page(ExplorationRequest("/private", session="authenticated"),
                          base_url="http://127.0.0.1:1")
    assert [issue.code for issue in result.issues] == ["AUTH_STATE_REQUIRED"]
    assert not result.explored


@pytest.mark.playwright
@browser_required
def test_page_unavailable_and_navigation_failure_are_structured(exploration_site):
    site, _, _ = exploration_site
    missing = explore_page(ExplorationRequest("/missing"), base_url=site)
    assert [issue.code for issue in missing.issues] == ["PAGE_UNAVAILABLE"]
    failed = explore_page(ExplorationRequest("/"), base_url="http://127.0.0.1:1", timeout_ms=500)
    assert [issue.code for issue in failed.issues] == ["NAVIGATION_FAILED"]
    assert not failed.explored


@pytest.mark.playwright
@browser_required
def test_no_controls_clicked_links_followed_or_form_submitted(exploration_site):
    site, counts, _ = exploration_site
    before = dict(counts)
    result = explore_page(ExplorationRequest("/login"), base_url=site)
    assert result.explored
    assert counts == before


@pytest.mark.playwright
@browser_required
def test_secrets_are_absent_and_result_is_json_yaml_serializable(exploration_site):
    site, _, secret = exploration_site
    request = ExplorationRequest("/login?token=" + secret)
    result = explore_page(request, base_url=site)
    payload = result.to_dict()
    encoded = json.dumps(payload)
    assert secret not in encoded
    assert secret not in json.dumps(asdict(result))
    assert "private@example.test" not in encoded
    assert "[REDACTED]" in encoded
    assert yaml.safe_load(yaml.safe_dump(payload)) == payload
    assert request.target.endswith(secret)  # Request is never changed.
    payload["page"]["elements"].clear()
    assert result.page.elements  # Serialization returns detached data.


@pytest.mark.playwright
@browser_required
@pytest.mark.parametrize("target", ["/external", "/external-chain", "/external-js"])
def test_foreign_redirect_is_recorded_without_contacting_foreign_server(exploration_site, target):
    site, counts, secret = exploration_site
    before = counts["foreign"]
    result = explore_page(ExplorationRequest(target), base_url=site)
    assert [issue.code for issue in result.issues] == ["CROSS_ORIGIN_REDIRECT"]
    assert result.redirect_url.endswith("/foreign")
    assert counts["foreign"] == before
    assert not result.explored
    assert secret not in json.dumps(result.to_dict())


def test_foreign_target_and_invalid_request_are_rejected():
    foreign = explore_page(ExplorationRequest("https://foreign.test/"), base_url="https://app.test")
    assert foreign.issues[0].code == "OUT_OF_SCOPE_TARGET"
    invalid = explore_page(ExplorationRequest("/", session="guess"), base_url="https://app.test")
    assert invalid.issues[0].code == "INVALID_REQUEST"
    data_url = explore_page(ExplorationRequest("data:text/html,SECRET_CONTENT"), base_url="https://app.test")
    assert data_url.issues[0].code == "INVALID_REQUEST"
    assert "SECRET_CONTENT" not in json.dumps(data_url.to_dict())
    malformed = explore_page(ExplorationRequest("https://["), base_url="https://app.test")
    assert malformed.issues[0].code == "INVALID_REQUEST"
    assert malformed.to_dict()["request"]["target"] == "[INVALID_URL]"


@pytest.mark.playwright
@browser_required
def test_empty_evidence_is_success_and_output_is_bounded(exploration_site):
    site, _, _ = exploration_site
    empty = explore_page(ExplorationRequest("/empty"), base_url=site, render_wait_ms=0)
    assert empty.explored and empty.page.elements == [] and empty.issues == ()
    bounded = explore_page(ExplorationRequest("/many", collect_text=False), base_url=site)
    assert len(bounded.page.elements) == 60
    assert bounded.page.text == []
    assert "elements" in bounded.truncated


@pytest.mark.playwright
@browser_required
def test_invalid_storage_state_is_controlled(exploration_site, tmp_path):
    site, _, _ = exploration_site
    state = tmp_path / "bad.json"
    state.write_text("not JSON")
    result = explore_page(ExplorationRequest("/protected", session="authenticated"),
                          base_url=site, storage_state=state)
    assert result.issues[0].code == "BROWSER_ERROR"

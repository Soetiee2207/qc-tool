"""Bootstrap login thật bằng Chromium: form trực tiếp và SSO, không gọi site ngoài."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from qctool.execute.browser import BrowserSession, LoginError

pytestmark = pytest.mark.playwright


@pytest.fixture
def site():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/login" and "sso=1" in self.path:
                body = '<button onclick="location.href=\'/openid-connect/auth\'">Sign in</button>'
            elif path in {"/login", "/openid-connect/auth"}:
                query = parse_qs(urlsplit(self.path).query)
                account = "username" if path != "/login" else "email"
                extra = '<input name="username">' if "ambiguous" in query else ''
                submits = '<button type="submit">Other</button>' if "duplicate" in query else ''
                hidden = '<input type="password" hidden><input type="email" hidden>'
                body = f'''<form method="post" action="/authenticate">
                    {hidden}<input name="{account}" type="text" autocomplete="username">
                    {extra}<input name="password" type="password">
                    <button type="button">Show password</button>
                    <button type="submit">Continue</button>{submits}
                    </form>'''
                if "delayed" in query:
                    body += '''<script>
                    document.querySelector('form').onsubmit = async function(event) {
                        event.preventDefault();
                        await fetch('/authenticate', {method:'POST',
                            body:new URLSearchParams(new FormData(this))});
                        history.pushState({}, '', '/');
                        setTimeout(() => this.outerHTML = '<button>Account</button>', 600);
                    };</script>'''
            else:
                body = '<h1>Home</h1><button>Account</button>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def do_POST(self):
            fields = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
            calls.append({"username": fields.get("email", fields.get("username")),
                          "password": fields.get("password")})
            valid = calls[-1] == {"username": ["qc@example.test"], "password": ["test-only-secret"]}
            if valid:
                self.send_response(303)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", "session=test-only-cookie; HttpOnly; Path=/")
                self.end_headers()
            else:
                self.send_response(401)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b'<p>Denied</p><input type="password"><button>Retry</button>')

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", calls
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture
def browser(site):
    with BrowserSession(site[0], timeout_ms=1500, inflight_ms=1) as browser:
        yield browser


def test_direct_form_fills_before_submit_and_persists_session(browser, site, tmp_path):
    message = browser.login("qc@example.test", "test-only-secret")
    assert message == "Đã đăng nhập qua form trực tiếp"
    assert browser.authenticated is True
    assert browser.page.url == site[0] + "/"
    assert len(site[1]) == 1  # no empty preliminary click, hidden fields ignored
    state = tmp_path / "state.json"
    browser.save_state(state)
    browser.storage_state = state
    browser.start_case("restored")
    browser.goto("/")
    assert browser._context.cookies()[0]["name"] == "session"


def test_rejected_login_never_marks_authenticated_or_leaks_secret(browser, site):
    with pytest.raises(LoginError) as error:
        browser.login("qc@example.test", "wrong-secret")
    assert error.value.code == "LOGIN_NOT_COMPLETED"
    assert browser.authenticated is False
    serialized = json.dumps({"error": str(error.value), "console": browser.console_errors,
                             "network": browser.network_errors})
    assert "wrong-secret" not in serialized
    assert "qc@example.test" not in serialized
    assert len(site[1]) == 1


def test_spa_url_can_change_before_login_form_disappears(browser, site, monkeypatch):
    original = browser.goto
    monkeypatch.setattr(browser, "goto", lambda _url: original("/login?delayed=1"))
    browser.login("qc@example.test", "test-only-secret")
    assert browser.authenticated is True
    assert browser.page.locator('input[type="password"]:visible').count() == 0
    assert len(site[1]) == 1


@pytest.mark.parametrize("query", ["ambiguous=1", "duplicate=1"])
def test_ambiguous_form_is_not_submitted(browser, site, query, monkeypatch):
    original = browser.goto
    monkeypatch.setattr(browser, "goto", lambda _url: original("/login?" + query))
    with pytest.raises(LoginError) as error:
        browser.login("qc@example.test", "test-only-secret")
    assert error.value.code == "LOGIN_FORM_AMBIGUOUS"
    assert site[1] == []
    assert browser.authenticated is False


def test_sso_branch_still_works(browser, site, monkeypatch):
    original = browser.goto
    monkeypatch.setattr(browser, "goto", lambda _url: original("/login?sso=1"))
    assert browser.login("qc@example.test", "test-only-secret") == "Đã đăng nhập qua SSO"
    assert browser.authenticated is True
    assert len(site[1]) == 1


def test_browser_exception_is_sanitized(browser, monkeypatch):
    def broken(_url):
        raise RuntimeError("request password=test-only-secret token=do-not-log")
    monkeypatch.setattr(browser, "goto", broken)
    with pytest.raises(LoginError) as error:
        browser.login("qc@example.test", "test-only-secret")
    assert str(error.value) == "LOGIN_BROWSER_ERROR: RuntimeError"
    assert error.value.__suppress_context__


def test_bootstrap_does_not_record_credentials_in_trace(site, tmp_path):
    with BrowserSession(site[0], timeout_ms=1500, inflight_ms=1,
                        trace=True, evidence_dir=tmp_path) as browser:
        browser.login("qc@example.test", "test-only-secret")
        browser.end_case()
    import zipfile
    with zipfile.ZipFile(tmp_path / "__session__.trace.zip") as trace:
        content = b"".join(trace.read(name) for name in trace.namelist())
    assert b"test-only-secret" not in content
    assert b"qc@example.test" not in content



def test_screenshot_masks_password_and_fixture_fields(site, tmp_path):
    """Case đăng nhập vẫn có ảnh làm bằng chứng — ô mật khẩu và ô điền fixture bị che."""
    with BrowserSession(site[0], headless=True, timeout_ms=3000, evidence_dir=tmp_path) as browser:
        browser.start_case("TC_LOGIN_001")
        browser.page.set_content('<input data-testid="email"><input data-testid="pwd" type="text">')
        browser.fill({"target": "email", "value": "qc@example.test", "_fixture_alias": "active_user.email"})
        browser.fill({"target": "pwd", "value": "test-only-secret", "_fixture_alias": "active_user.password"})
        assert len(browser._secret_locators) == 2      # ô "hiện mật khẩu" (type=text) cũng bị che
        browser.capture_final()
        browser.end_case("Pass")
        browser.start_case("TC_LOGIN_002")
        assert browser._secret_locators == []          # không mang sang case sau
        browser.end_case("")
    assert (tmp_path / "TC_LOGIN_001-final.png").is_file()

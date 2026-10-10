"""Local Playwright capture acceptance; never contact SalonHub or a model."""
import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import replace
from copy import deepcopy

import pytest

from qctool.execute.browser import BrowserSession, ResponseCaptureError
from qctool.execute.runner import HttpSession, run_case
from qctool.core.executability import analyze_executability
from qctool.core.testcase import Step, StepKind, TestCase, ValidationError
from tests.test_fixture_facts import GIVEN
from tests.fixture_samples import BASE, HAPPY

SECRET = 'FICTIONAL_TOKEN_SECRET_DO_NOT_PERSIST'


@pytest.fixture(scope='module')
def capture_site():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            mode = self.path.removeprefix('/login/')
            html = f'''<title>Login</title><button data-testid="login-submit-btn">Đăng nhập</button>
            <script>document.querySelector('button').onclick=async()=>{{
            fetch('/noise');
            if('{mode}'==='missing')return;
            const suffix='{mode}'==='negative'?'?token={SECRET}':('{mode}'==='false-success'?'?false_success':'');
            const one=fetch('/api/auth/login'+suffix,{{method:'POST'}});
            if('{mode}'==='duplicate')fetch('/api/auth/login',{{method:'POST'}});
            await one;history.pushState(null,'','/');
            }};</script>'''.encode()
            self.send_response(200); self.end_headers(); self.wfile.write(html)
        def do_POST(self):
            negative = 'token=' in self.path
            unsuccessful = '?' in self.path
            body = json.dumps({'success': not unsuccessful, 'token': SECRET, 'password': SECRET,
                               'data': {'token': SECRET}}).encode()
            self.send_response(401 if negative else 200)
            self.send_header('Authorization', 'Bearer '+SECRET)
            self.send_header('Set-Cookie', 'session='+SECRET)
            self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown(); server.server_close()


def capture(origin=BASE, **extra):
    return {'method': 'POST', 'path': '/api/auth/login', 'origin': origin, 'save_as': 'login',
            'timeout_ms': 500, **extra}


def runtime_case(origin, mode='single'):
    return TestCase('TC_CAPTURE_001', 'CAPTURE', 'Login capture', 'Explicit response', traces_to=['FR-CAPTURE'], source_quote='Observe explicit login response', steps=[
        Step(1, StepKind.WHEN, 'ui.goto', {'url': '/login/'+mode}),
        Step(2, StepKind.WHEN, 'ui.click', {'target': 'login-submit-btn', 'capture_response': capture(origin)}),
        Step(3, StepKind.THEN, 'assert.http_status', {'source': 'login', 'expected': 200}),
        Step(4, StepKind.THEN, 'assert.json_field', {'source': 'login', 'path': '$.success', 'expected': True}),
        Step(5, StepKind.THEN, 'assert.url_matches', {'pattern': '/$'})])


@pytest.mark.playwright
def test_real_click_captures_response_and_existing_assertions(capture_site, tmp_path):
    browser = BrowserSession(capture_site, timeout_ms=3000, evidence_dir=tmp_path, trace=True)
    browser.start()
    try:
        result = run_case(runtime_case(capture_site), HttpSession(capture_site), browser)
        assert result.status == 'Pass', result.to_dict()
        assert len(result.steps) == 5 and all(s.ok for s in result.steps)
        assert SECRET not in json.dumps(result.to_dict())
        assert not list(tmp_path.glob('*.trace.zip'))
    finally:
        browser.close()


@pytest.mark.playwright
@pytest.mark.parametrize('mode,code', [('missing','UI_RESPONSE_TIMEOUT'), ('duplicate','AMBIGUOUS_UI_RESPONSE')])
def test_missing_or_duplicate_matching_response_is_structured_blocked(capture_site, tmp_path, mode, code):
    browser = BrowserSession(capture_site, timeout_ms=3000, evidence_dir=tmp_path)
    browser.start()
    try:
        result = run_case(runtime_case(capture_site, mode), HttpSession(capture_site), browser)
        assert result.status == 'Blocked'
        assert result.steps[-1].to_dict()['issue_code'] == code
        assert len(result.steps) == 2  # no assertion executed against a guessed response
        assert SECRET not in json.dumps(result.to_dict())
    finally:
        browser.close()


@pytest.mark.parametrize('bad', [{'method':'POST'}, capture(timeout_ms=0), capture(path='//foreign'),capture(origin='file://local')])
def test_structural_capture_validation(bad):
    with pytest.raises(ValidationError):
        Step(1,StepKind.WHEN,'ui.click',{'target':'login','capture_response':bad}).validate()


def test_analyzer_response_saved_only_after_trigger_and_no_latency_resampling():
    case=runtime_case(BASE)
    assert analyze_executability(case).executable
    case.steps[2] = Step(3,StepKind.THEN,'assert.response_time',{'max_ms':100,'source':'login'})
    assert any(g.code=='MISSING_RESPONSE' for g in analyze_executability(case).gaps)


@pytest.mark.playwright
def test_wrong_status_is_real_assertion_failure_without_token_url_leak(capture_site, tmp_path):
    browser = BrowserSession(capture_site, timeout_ms=3000, evidence_dir=tmp_path)
    browser.start()
    try:
        result = run_case(runtime_case(capture_site, 'negative'), HttpSession(capture_site), browser)
        assert result.status == 'Fail'
        assert result.steps[-1].action == 'assert.http_status'
        assert '401' in result.steps[-1].detail
        assert SECRET not in json.dumps(result.to_dict())
    finally:
        browser.close()


@pytest.mark.playwright
def test_status_200_does_not_hide_false_success(capture_site):
    browser = BrowserSession(capture_site, timeout_ms=3000)
    browser.start()
    try:
        result = run_case(runtime_case(capture_site, 'false-success'), HttpSession(capture_site), browser)
        assert result.status == 'Fail'
        assert result.steps[2].ok  # status 200 really passed
        assert result.steps[-1].action == 'assert.json_field'
        assert 'False' in result.steps[-1].detail
    finally:
        browser.close()


@pytest.mark.playwright
def test_captured_response_has_trigger_provenance_and_only_public_body(capture_site):
    browser = BrowserSession(capture_site, timeout_ms=3000)
    browser.start(); browser.start_case('TC_CAPTURE_001')
    try:
        browser.goto('/login/single')
        response = browser.click_and_capture({'target':'login-submit-btn','capture_response':capture(capture_site)},2)
        assert response['body'] == {'success': True}
        assert response['_ui_trigger'] == {'step_seq':2,'method':'POST','path':'/api/auth/login','origin':capture_site}
        assert SECRET not in json.dumps(response)
    finally:
        browser.close()

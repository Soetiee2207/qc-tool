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
from qctool.executability import analyze_executability
from qctool.testcase import Step, StepKind, TestCase, ValidationError
from qctool.proposal_validation import validate_resolution_proposal
from qctool.llm_resolution import AtomicProposal, EvidenceReference, ResolutionProposal
from qctool.apply_resolution import apply_validated_resolution
from tests.test_fixture_facts import inputs, GIVEN
from tests.test_step_expansion import expansion, atom, BASE, HAPPY

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


def resolution_inputs():
    case, context, store, given = inputs({'role': 'customer', 'account_state': 'active'})
    context.interface_contract['api_operations'][0]['servers'] = [BASE]
    page = deepcopy(context.observations['ui_pages'][0]); page['url'] = BASE + '/'
    page['elements'] = []
    context.observations['ui_pages'].append(page)
    op = EvidenceReference('openapi', {'operation_id': 'login'})
    when = expansion()
    atoms = list(when.expansion)
    atoms[0] = replace(atoms[0], args={'target':'email','value':'active_user.email'})
    atoms[1] = replace(atoms[1], args={'target':'password','value':'active_user.password'})
    atoms[2] = replace(atoms[2], args={**atoms[2].args,'capture_response':capture()}, evidence=(*atoms[2].evidence,op))
    when = replace(when, expansion=tuple(atoms))
    then = expansion([
        atom('assert.http_status', {'expected':200,'source':'login'}, refs=(op,)),
        atom('assert.json_field', {'path':'$.success','expected':True,'source':'login'}, refs=(op,)),
        atom('assert.url_matches', {'pattern':'/$'}, refs=(EvidenceReference('ui-map',{'page':BASE+'/'}),)),
    ], 3, True)
    return case,context,store,ResolutionProposal(case.id,(given,when,then),())


def test_full_source_login_outcome_grounded_by_ui_captured_response():
    case,context,store,proposal = resolution_inputs()
    snapshot = deepcopy((case,context,proposal))
    validation = validate_resolution_proposal(proposal,context,case,fixture_store=store)
    assert len(validation.valid_changes) == 3, validation.issues
    result = apply_validated_resolution(case,validation)
    assert not result.issues
    assert result.after.executable
    assert [s.action for s in result.case.steps] == ['ui.session','ui.goto','ui.fill','ui.fill','ui.click',
        'assert.http_status','assert.json_field','assert.url_matches']
    assert (case,context,proposal) == snapshot


@pytest.mark.parametrize('field,value', [('path','/invented'),('origin','https://foreign.test'),('method','GET')])
def test_untrusted_capture_operation_or_origin_rejected(field,value):
    case,context,store,proposal = resolution_inputs()
    when = proposal.changes[1]; atoms = list(when.expansion)
    atoms[2] = replace(atoms[2], args={**atoms[2].args,'capture_response':capture(**{field:value})})
    proposal = replace(proposal,changes=(proposal.changes[0],replace(when,expansion=tuple(atoms)),proposal.changes[2]))
    result = validate_resolution_proposal(proposal,context,case,fixture_store=store)
    assert not any(c.step_seq in (2,3) for c in result.valid_changes)


def test_no_capture_cannot_ground_http_assertions_from_ui_observations():
    case,context,store,proposal = resolution_inputs()
    when = proposal.changes[1]; atoms=list(when.expansion)
    atoms[2] = replace(atoms[2],args={'target':'login'})
    proposal=replace(proposal,changes=(proposal.changes[0],replace(when,expansion=tuple(atoms)),proposal.changes[2]))
    result=validate_resolution_proposal(proposal,context,case,fixture_store=store)
    assert not any(c.step_seq == 3 for c in result.valid_changes)


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


def test_root_contract_server_is_retained_without_changing_http_base_override():
    from qctool.generate.loader import load_endpoints
    from qctool.resolution_context import build_resolution_context
    ep = load_endpoints(Path('samples/smoke/openapi.yaml'))[0][0]
    assert ep.servers == []  # normal http.request continues using configured base
    assert ep.contract_servers == ['https://salonhub-3cg8.onrender.com']
    case, _, _, _ = resolution_inputs()
    context = build_resolution_context(case, analyze_executability(case).gaps, endpoints=[ep])
    assert context.interface_contract['api_operations'][0]['servers'] == ep.contract_servers


@pytest.mark.parametrize('replacement', ['success=false', 'URL not /', 'URL chuyển tới /admin'])
def test_login_capture_does_not_rewrite_expected_outcomes(replacement):
    case,context,store,proposal = resolution_inputs()
    text = HAPPY.replace('success=true', replacement) if replacement=='success=false' else HAPPY.replace('URL chuyển tới /',replacement)
    case.steps[2].args['expected'] = text
    context.testcase['steps'][2]['args']['expected'] = text
    result = validate_resolution_proposal(proposal,context,case,fixture_store=store)
    assert not any(c.step_seq == 3 for c in result.valid_changes)


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

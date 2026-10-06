"""Bounded empty-login proof: recorded source evidence and local Chromium only."""
from copy import deepcopy
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest

from qctool.apply_resolution import apply_validated_resolution
from qctool.proposal_validation import validate_resolution_proposal
from qctool.executability import analyze_executability
from qctool.testcase import Step, StepKind, TestCase, ValidationError
from qctool.execute.browser import BrowserSession
from qctool.execute.runner import HttpSession, run_cases
from scripts.run_salonhub_002 import resolution_inputs as build_inputs
from qctool.ui.crawl import UIMap, PageMap, Element
from pathlib import Path


def resolution_inputs():
    # Repository fixture docs are local; no generated artifacts or application
    # checkout are required by offline tests. Source snippet is explicitly fake.
    base = 'https://salonhub-soe.vercel.app'
    case = TestCase('TC_SALON_AUTH_002','SALON_AUTH','Empty form','Complete source obligation',
        traces_to=['AC-salonhub-smoke-001-2'], source_quote='Empty form validation',
        steps=[Step(1,StepKind.WHEN,'ui.click',{'target':'nav-login-btn'})])
    ui = UIMap(base,'offline',[PageMap(base+'/login','Login',elements=[
        Element('email','input','Email hoặc Số điện thoại','input',test_id='login-email-input',input_type='text'),
        Element('password','input','Nhập mật khẩu','input',test_id='login-password-input',input_type='password'),
        Element('submit','button','Đăng nhập','button',test_id='login-submit-btn'),
    ])])
    source = "setValidationMessage('Vui lòng điền đầy đủ thông tin');\n" + '<p role="alert" data-testid="login-validation-message">'
    return build_inputs(previous=case.to_dict(),ui=ui,source_code=source,source_file=Path('fixture/Login.jsx'))


def test_full_empty_form_is_validated_without_fixtures_or_model_and_inputs_unchanged():
    case, context, proposal, _ = resolution_inputs()
    before = deepcopy((case, context, proposal))
    validation = validate_resolution_proposal(proposal, context, case)
    assert len(validation.valid_changes) == 3 and not validation.issues
    applied = apply_validated_resolution(case, validation)
    assert applied.after.executable and not applied.issues
    assert applied.case.test_data == case.test_data
    assert [s.action for s in applied.case.steps] == ['ui.session','ui.goto','assert.value','assert.value',
        'ui.click','assert.visible','assert.text','assert.json_field','assert.url_matches']
    assert all(s.args['expected']=='^$' for s in applied.case.steps[2:4])
    assert (case, context, proposal) == before


@pytest.mark.parametrize('problem', ['drop_validation','drop_network','drop_url','wrong_count',
    'fake_button','foreign_origin','wrong_path','no_observer','unknown_given'])
def test_every_clause_and_selector_must_be_proven(problem):
    case, context, proposal, _ = resolution_inputs()
    changes = list(proposal.changes)
    if problem.startswith('drop_') or problem == 'wrong_count':
        atoms = list(changes[2].expansion)
        if problem == 'drop_validation': atoms = atoms[2:]
        if problem == 'drop_network': atoms.pop(2)
        if problem == 'drop_url': atoms.pop(3)
        if problem == 'wrong_count': atoms[2] = replace(atoms[2], args={**atoms[2].args,'expected':1})
        changes[2] = replace(changes[2], expansion=tuple(atoms))
    elif problem == 'unknown_given':
        case.steps[0].args['description'] += '; other precondition'
        context = replace(context, testcase={**context.testcase,'steps':[s.to_dict() for s in case.steps]})
    else:
        args = deepcopy(changes[1].args)
        if problem == 'fake_button':args['target']='invented'
        if problem == 'foreign_origin':args['capture_requests']['origin']='https://foreign.test'
        if problem == 'wrong_path':args['capture_requests']['path']='/api/invented'
        if problem == 'no_observer':args.pop('capture_requests')
        changes[1] = replace(changes[1],args=args)
    result = validate_resolution_proposal(replace(proposal, changes=tuple(changes)),context,case)
    assert result.rejected_changes
    assert not apply_validated_resolution(case,result).after.executable


def test_request_count_does_not_masquerade_as_http_response_and_capture_modes_are_exclusive():
    selector={'method':'POST','path':'/api/auth/login','origin':'https://test.invalid','save_as':'requests','timeout_ms':200}
    click = Step(1,StepKind.WHEN,'ui.click',{'target':'submit','capture_requests':selector})
    count = Step(2,StepKind.THEN,'assert.json_field',{'source':'requests','path':'$.request_count','expected':0})
    case = TestCase('TC_EMPTY_001','EMPTY','Empty form','No request',traces_to=['FR-EMPTY'],source_quote='No login request',steps=[click,count])
    assert analyze_executability(case).executable
    case.steps[1] = Step(2,StepKind.THEN,'assert.http_status',{'source':'requests','expected':200})
    assert any(g.code=='MISSING_RESPONSE' for g in analyze_executability(case).gaps)
    with pytest.raises(ValidationError):
        Step(1,StepKind.WHEN,'ui.click',{'target':'submit','capture_requests':selector,'capture_response':selector}).validate()


@pytest.fixture(scope='module')
def site():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            mode=self.path.split('/')[-1]
            html=f'''<button data-testid="submit">Submit</button><script>
            document.querySelector('button').onclick=()=>{{
             fetch('/noise'); fetch('/api/other',{{method:'POST'}});
             if('{mode}'==='one'||'{mode}'==='two') fetch('/api/auth/login',{{method:'POST',body:'SECRET_DO_NOT_CAPTURE'}});
             if('{mode}'==='two') fetch('/api/auth/login',{{method:'POST',body:'SECRET_DO_NOT_CAPTURE'}});
             if('{mode}'==='delayed')setTimeout(()=>fetch('/api/auth/login',{{method:'POST'}}),80);
            }};</script>'''.encode()
            self.send_response(200);self.end_headers();self.wfile.write(html)
        def do_POST(self):
            self.send_response(200);self.end_headers();self.wfile.write(b'{"token":"SECRET_DO_NOT_CAPTURE"}')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown();server.server_close()


@pytest.mark.playwright
@pytest.mark.parametrize('mode,count,status',[('none',0,'Pass'),('one',1,'Fail'),('two',2,'Fail'),('delayed',1,'Fail')])
def test_real_bounded_absence_counts_all_matches_and_never_persists_secrets(site,tmp_path,mode,count,status):
    selector={'method':'POST','path':'/api/auth/login','origin':site,'save_as':'observed','timeout_ms':350}
    case=TestCase('TC_EMPTY_001','EMPTY','No login POST','Negative network window',traces_to=['FR-EMPTY'],source_quote='No login request',steps=[
        Step(1,StepKind.WHEN,'ui.goto',{'url':'/login/'+mode}),
        Step(2,StepKind.WHEN,'ui.click',{'target':'submit','capture_requests':selector}),
        Step(3,StepKind.THEN,'assert.json_field',{'source':'observed','path':'$.request_count','expected':0})])
    browser=BrowserSession(site,evidence_dir=tmp_path,trace=True)
    try:
        browser.start()
        result=run_cases([case],HttpSession(site),browser=browser)
        assert result.cases[0].status==status,result.to_dict()
        assert f'{count} requests in 350ms' in result.cases[0].steps[1].detail
        assert 'SECRET_DO_NOT_CAPTURE' not in json.dumps(result.to_dict())
        assert not list(tmp_path.glob('*.trace.zip'))
    finally:browser.close()


@pytest.mark.playwright
def test_missing_submit_is_blocked_not_zero_count_success(site):
    case=TestCase('TC_EMPTY_001','EMPTY','Missing submit','Cannot observe',traces_to=['FR-EMPTY'],source_quote='No login request',steps=[
        Step(1,StepKind.WHEN,'ui.goto',{'url':'/login/none'}),
        Step(2,StepKind.WHEN,'ui.click',{'target':'missing','capture_requests':{
            'method':'POST','path':'/api/auth/login','origin':site,'save_as':'observed','timeout_ms':150}}),
        Step(3,StepKind.THEN,'assert.json_field',{'source':'observed','path':'$.request_count','expected':0})])
    browser=BrowserSession(site)
    try:
        browser.start();result=run_cases([case],HttpSession(site),browser=browser)
        assert result.cases[0].status=='Blocked'
        assert result.cases[0].steps[-1].issue_code=='UI_REQUEST_OBSERVATION_FAILED'
    finally:browser.close()

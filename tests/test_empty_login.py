"""Bounded empty-login proof: recorded source evidence and local Chromium only."""
from copy import deepcopy
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest

from qctool.core.executability import analyze_executability
from qctool.core.testcase import Step, StepKind, TestCase, ValidationError
from qctool.execute.browser import BrowserSession
from qctool.execute.runner import HttpSession, run_cases
from qctool.ui.crawl import UIMap, PageMap, Element
from pathlib import Path


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

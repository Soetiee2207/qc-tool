"""Resolve the complete source AC for TC002; optionally execute only it.

uv run python scripts/run_salonhub_002.py --run
No account fixture, model calls, or production mutations.
"""
from copy import deepcopy
from datetime import datetime
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit, urlunsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yaml
from qctool.ingest import ingest_one
from qctool.resolution_evaluation import _case_from_dict
from qctool.resolution_context import build_resolution_context
from qctool.executability import analyze_executability
from qctool.generate.loader import load_endpoints
from qctool.generate import write_cases
from qctool.ui.crawl import UIMap
from qctool.llm_resolution import parse_resolution_proposal
from qctool.proposal_validation import validate_resolution_proposal
from qctool.apply_resolution import apply_validated_resolution
from qctool.execute.browser import BrowserSession
from qctool.execute.runner import HttpSession, run_cases
from qctool.testcase import Step, StepKind
from qctool import report

BASE = 'https://salonhub-soe.vercel.app'
ORIGIN = 'https://salonhub-3cg8.onrender.com'
SOURCE = Path('/home/soetie/Documents/2026_Document/SalonHub/frontend/src/pages/auth/Login.jsx')
MESSAGE = 'Vui lòng điền đầy đủ thông tin'


def resolution_inputs(*, previous=None, ui=None, source_code=None, source_file=SOURCE):
    if previous is None:
        raw = yaml.safe_load(Path('artifacts/salonhub-smoke/testcases.yaml').read_text())
        previous = next(c for c in raw['testcases'] if c['id'] == 'TC_SALON_AUTH_002')
    case = _case_from_dict(previous)
    manifest = ingest_one(Path('samples/smoke'), 'salonhub-smoke')
    ac = next(r for r in manifest['requirements'] if r['id'] == 'AC-salonhub-smoke-001-2')
    # Restore the complete original logical AC lost by the legacy mapper; do
    # not validate opportunistic edits to its already-mapped incomplete steps.
    case.steps = [Step(1, StepKind.GIVEN, 'perform.unmapped', {'description': ac['given']}),
                  Step(2, StepKind.WHEN, 'perform.unmapped', {'description': ac['when']}),
                  Step(3, StepKind.THEN, 'assert.unmapped', {'expected': ac['then']})]
    case.execution = 'manual'
    if ui is None:
        ui = UIMap.load(Path('artifacts/salonhub-smoke/ui-map.yaml'))
    endpoints, _, _ = load_endpoints(Path('samples/smoke/openapi.yaml'))
    context = build_resolution_context(case, analyze_executability(case).gaps,
                                      requirements=manifest['requirements'], ui_map=ui, endpoints=endpoints)
    # The alert is conditional and absent from the initial UIMap. Ground its
    # exact locator in inspected JSX, explicitly labelled SOURCE, not live DOM.
    source = source_file.read_text() if source_code is None else source_code
    declaration = '<p role="alert" data-testid="login-validation-message"'
    assert declaration in source and "setValidationMessage('"+MESSAGE+"')" in source
    page = next(p for p in context.observations['ui_pages'] if p['url'] == BASE+'/login')
    assert not any(e.get('test_id') == 'login-validation-message' for e in page['elements'])
    page['elements'].append({'id':'login-validation-message','test_id':'login-validation-message',
        'role':'alert','name':MESSAGE,'evidence':{'type':'source-code','file':str(source_file),
        'line':source[:source.index(declaration)].count('\n')+1,'conditional':True,'observed':False}})
    def ref(target=None):
        return {'source':'ui-map','ref':{'page':BASE+'/login',**({'test_id':target} if target else {})}}
    op = {'source':'openapi','ref':{'operation_id':'login','method':'POST','path':'/api/auth/login'}}
    def atom(action,args,evidence):return {'action':action,'args':args,'evidence':evidence}
    def change(seq,proposed):
        return {'step_seq':seq,'from_action':case.steps[seq-1].action,'gap_codes':['UNMAPPED_ACTION'],
                'proposed':proposed,'reason':'Preserve the complete explicit source clause; inspect only the submit window.',
                'evidence':[{'source':'testcase-step','ref':{'step_seq':seq}},ref(),op]}
    proposal = {'testcase_id':case.id,'changes':[
        change(1,{'steps':[
            atom('ui.session',{'mode':'anonymous'},[{'source':'testcase-step','ref':{'step_seq':1}}]),
            atom('ui.goto',{'url':BASE+'/login'},[ref()]),
            atom('assert.value',{'target':'login-email-input','expected':'^$','operator':'matches'},[ref('login-email-input')]),
            atom('assert.value',{'target':'login-password-input','expected':'^$','operator':'matches'},[ref('login-password-input')])]}),
        change(2,{'action':'ui.click','args':{'target':'login-submit-btn','capture_requests':{
            'method':'POST','path':'/api/auth/login','origin':ORIGIN,'save_as':'login_requests','timeout_ms':2000}}}),
        change(3,{'steps':[
            atom('assert.visible',{'target':'login-validation-message'},[ref('login-validation-message')]),
            atom('assert.text',{'target':'login-validation-message','expected':MESSAGE,'exact':True},[ref('login-validation-message')]),
            atom('assert.json_field',{'source':'login_requests','path':'$.request_count','expected':0},[op]),
            atom('assert.url_matches',{'pattern':'/login$'},[ref()])]})], 'unresolved':[]}
    proposal['changes'][1]['evidence'].append(ref('login-submit-btn'))
    return case, context, parse_resolution_proposal(json.dumps(proposal)), previous


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args()
    case,context,proposal,previous=resolution_inputs()
    snapshot=deepcopy((case,context,proposal))
    validation=validate_resolution_proposal(proposal,context,case)
    application=apply_validated_resolution(case,validation)
    assert (case,context,proposal)==snapshot
    if len(validation.valid_changes)!=3 or application.issues or not application.after.executable:
        print(json.dumps({'validation':validation.status,'issues':[i.__dict__ for i in validation.issues],
                          'application_issues':[i.__dict__ for i in application.issues]},ensure_ascii=False))
        return 1
    print(json.dumps({'validation':validation.status,'applied':len(application.applied_changes),
                      'executable':True,'steps':[s.action for s in application.case.steps]},ensure_ascii=False),flush=True)
    if not args.run:return 0
    out=Path('artifacts/salonhub-002-execution')/datetime.now().strftime('%Y%m%d-%H%M%S');out.mkdir(parents=True)
    observed={'llm_used':False,'request_observation':None,'final_browser_url':None,'validation_message':None,
              'validation_locator_source':str(SOURCE),'observation_window_ms':2000}
    class ObservedBrowser(BrowserSession):
        def click_and_observe_requests(self,arguments,step_seq):
            result=super().click_and_observe_requests(arguments,step_seq)
            observed['request_observation']=deepcopy(result)
            return result
        def end_case(self,status=''):
            if self._page is not None and self.case_id==case.id:
                parts=urlsplit(self.page.url)
                observed['final_browser_url']=urlunsplit((parts.scheme,parts.netloc,parts.path,'',''))
                alert=self.page.get_by_test_id('login-validation-message')
                if alert.count()==1 and alert.is_visible():
                    # Project a known source message only; never log arbitrary DOM text.
                    observed['validation_message']=MESSAGE if alert.inner_text()==MESSAGE else 'UNEXPECTED_MESSAGE'
            return super().end_case(status)
    browser=ObservedBrowser(BASE,authenticated=False,headless=True,evidence_dir=out/'evidence',trace=True)
    try:
        browser.start()
        result=run_cases([application.case],HttpSession(ORIGIN),browser=browser,retry=0,
                         environment='SalonHub real Chromium; empty form, no account fixture')
    finally:browser.close()
    report.write_json(result,out/'results.json');report.write_csv(result,out/'results.csv')
    report.write_junit(result,out/'junit.xml');report.render_markdown(result,out/'report.md')
    write_cases([application.case],out/'testcases.yaml',{'sources':['samples/smoke/URD.md'],'unverifiable':[],'warnings':[]})
    (out/'resolution.json').write_text(json.dumps({'original_mapped_case':previous,'logical_case':case.to_dict(),
        'context':context.to_dict(),'proposal':proposal.to_dict(),'validation_status':validation.status,
        'applied_changes':[c.to_dict() for c in application.applied_changes]},ensure_ascii=False,indent=2)+'\n')
    (out/'runtime-observations.json').write_text(json.dumps(observed,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'artifacts':str(out),'observed':observed,'result':result.cases[0].to_dict()},ensure_ascii=False))
    return 0 if result.cases[0].status=='Pass' else 1

if __name__=='__main__':raise SystemExit(main())

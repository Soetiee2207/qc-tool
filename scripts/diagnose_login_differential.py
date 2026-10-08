"""Compare a human UI login with the unchanged QC runner; never save secrets.

Run from repo root. The manual window starts empty: type the intended account
yourself. Only an observed successful response qualifies as MANUAL SUCCESS.
HMAC keys and all digests are runtime-only, shared by the two isolated contexts.
No model, provisioning, account verification or engine configuration changes.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from qctool.execute.browser import BrowserSession
from qctool.execute.runner import HttpSession, run_case
from qctool.pipeline import PipelineConfig
from qctool.executability import ExecutionGap
from qctool.exploration_plan import validate_exploration_plan
from qctool.exploration_execution import execute_validated_exploration
from qctool.llm_exploration import parse_exploration_plan
from qctool.resolution_context import ResolutionContext
from qctool.resolution_evaluation import _case_from_dict
from qctool.response_capture import matches_request, origin_of, validate_capture
from qctool.ui.explore import _safe_url


MAX_EVENTS = 100
PUBLIC_FIELDS = frozenset({
    'email', 'password', 'username', 'phone', 'credentials', 'data', 'success',
    'message', 'error', 'code', 'user', 'token', 'access_token', 'refresh_token',
    'csrf', 'csrfToken', '_csrf', 'id', 'name', 'role', 'isActive', 'isEmailVerified',
})


def body_shape(value, depth=0):
    """Only public field names/types, never scalar values or arbitrary key names."""
    if isinstance(value, dict):
        if depth >= 3:
            return {'type': 'object'}
        result = {k: body_shape(v, depth + 1) for k, v in value.items() if k in PUBLIC_FIELDS}
        if len(result) != len(value):
            result['omitted_field_count'] = len(value) - len(result)
        return result
    if isinstance(value, list):
        return {'type': 'array', 'count': len(value)}
    return 'null' if value is None else 'boolean' if type(value) is bool else 'number' if isinstance(value, (float, int)) else 'string'


class Comparison:
    def __init__(self, store, aliases):
        self.store, self.aliases = store, aliases
        self.key = os.urandom(32)

    def digest(self, value):
        return hmac.new(self.key, str(value).encode(), hashlib.sha256).hexdigest()

    def equal(self, left, right):
        return hmac.compare_digest(self.digest(left), self.digest(right))

    def safe_name(self, name):
        # Arbitrary header/cookie/key names can also contain secrets.
        clean = self.store.redact(name)
        return clean if clean == name and re.fullmatch(r'[A-Za-z_][\w.-]{0,63}', clean) else '[OMITTED_NAME]'

    def safe_url(self, url):
        return self.store.redact(_safe_url(url))


class Observation:
    def __init__(self, browser, comparison, spec, controls, label):
        self.browser, self.comparison, self.spec, self.controls = browser, comparison, spec, controls
        self.data = {'label': label, 'fresh_context': True, 'events': [], 'login_requests': [],
                     'issues': [], 'event_limit': MAX_EVENTS, 'events_truncated': False}
        self.raw_logins = []  # Request identities and HMACs, never serialized.
        self.pre_cookies = {}
        self.context = browser._context
        self.data['initial_session'] = self.session()
        self.snapshot = {'cookies': self.cookies(), 'form': {}, 'focus': {}}
        browser.page.on('request', self.on_request)
        browser.page.on('response', self.on_response)
        browser.page.on('framenavigated', self.on_navigation)

    def cookies(self):
        result = {}
        for c in self.context.cookies():
            identity = (self.comparison.safe_name(c['name']), self.comparison.safe_url('https://' + c['domain'].lstrip('.')), self.comparison.safe_url(c['path']))
            result[identity] = {'name': identity[0], 'domain': identity[1], 'path': identity[2],
                                'secure': c['secure'], 'httpOnly': c['httpOnly'], 'sameSite': c['sameSite'],
                                '_hmac': self.comparison.digest(c['value'])}
        return result

    def session(self):
        page = self.browser.page
        try:
            state = page.evaluate("""() => ({local: ['token','user','access_token','csrf'].filter(k => localStorage.getItem(k) !== null),
                session: ['token','user','access_token','csrf'].filter(k => sessionStorage.getItem(k) !== null)})""")
        except Exception:
            state = {'local': [], 'session': []}
        return {'url': self.comparison.safe_url(page.url), 'cookies': [{k:v for k,v in c.items() if not k.startswith('_')} for c in self.cookies().values()],
                'local_storage_known_keys': state['local'], 'session_storage_known_keys': state['session']}

    def form(self):
        out = []
        for field, args in self.controls.items():
            locator = self.browser.locate(args)
            record = {'field': field, 'target': args['target'], 'count': locator.count()}
            if locator.count() == 1:
                record.update({'tag': locator.evaluate('e => e.tagName.toLowerCase()'),
                               'name': self.comparison.safe_name(locator.get_attribute('name') or ''),
                               'type': locator.get_attribute('type'),
                               'value_matches_fixture': self.comparison.equal(locator.input_value(), self.comparison.store.resolve(self.comparison.aliases[field]))})
            out.append(record)
        hidden = self.browser.page.locator('input[type=hidden]')
        return {'fields': out, 'hidden_fields': [{'name': self.comparison.safe_name(hidden.nth(i).get_attribute('name') or ''),
                'has_value': bool(hidden.nth(i).input_value())} for i in range(min(hidden.count(), 10))],
                'omitted_hidden_fields': max(0, hidden.count()-10)}

    def event(self, value):
        if len(self.data['events']) < MAX_EVENTS:
            self.data['events'].append(value)
        else:
            self.data['events_truncated'] = True

    def on_navigation(self, frame):
        if frame == self.browser.page.main_frame:
            self.event({'kind': 'navigation', 'url': self.comparison.safe_url(frame.url)})

    def on_request(self, request):
        # No synchronous Playwright RPC here: nested dispatch can deliver the
        # response before the real runner's request listener registers it.
        public = {'kind': 'request', 'method': request.method, 'url': self.comparison.safe_url(request.url), 'resource_type': request.resource_type}
        self.event(public)
        # Exact selected operation, plus human-selected sibling auth operations
        # observed at the trusted backend (e.g. a different login mechanism).
        auth_prefix = self.spec['path'].rsplit('/', 1)[0] + '/'
        if not (origin_of(request.url) == self.spec['origin'] and urlsplit(request.url).path.startswith(auth_prefix) and request.method == 'POST'):
            return
        headers = request.headers  # cached initializer metadata, no RPC
        content_type = headers.get('content-type', '')
        try:
            body = request.post_data_json if 'json' in content_type else {k:v[0] for k,v in parse_qs(request.post_data or '').items()}
        except Exception:
            body = None
        csrf = {k:self.comparison.digest(v) for k,v in headers.items() if 'csrf' in k.lower() or 'xsrf' in k.lower()}
        credential_hmacs = {field:self.comparison.digest(body[field]) for field in self.comparison.aliases if isinstance(body,dict) and field in body}
        cookies = deepcopy(self.snapshot['cookies'])
        record = {'request_index': len(self.raw_logins), 'event_index': len(self.data['events'])-1,
                  'method': request.method, 'url': public['url'], 'matches_expected_capture': matches_request(request,self.spec),
                  'content_type': content_type, 'body_shape': body_shape(body),
                  'credentials_match_fixture': {field: field in credential_hmacs and hmac.compare_digest(credential_hmacs[field],self.comparison.digest(self.comparison.store.resolve(alias))) for field,alias in self.comparison.aliases.items()},
                  'cookie_header_present': bool(headers.get('cookie')), 'cookies_before': [{k:v for k,v in c.items() if not k.startswith('_')} for c in cookies.values()],
                  'authorization_present': bool(headers.get('authorization')), 'csrf_header_names': [self.comparison.safe_name(k) for k in csrf],
                  'origin': self.comparison.safe_url(headers.get('origin','')), 'referer': self.comparison.safe_url(headers.get('referer','')),
                  'user_agent': self.comparison.store.redact(headers.get('user-agent','')), 'form_before_submit_snapshot':deepcopy(self.snapshot['form'])}
        focus=self.snapshot['focus']
        record['focused_control_at_submit']={k:self.comparison.safe_name(v) if v else None for k,v in focus.items()}
        self.raw_logins.append({'request':request,'record':record,'credentials':credential_hmacs,'csrf':csrf,'cookies':cookies,'processed':False})
        self.data['login_requests'].append(record)

    def on_response(self, response):
        self.event({'kind':'response','method':response.request.method,'url':self.comparison.safe_url(response.url),'status':response.status})
        item = next((r for r in self.raw_logins if r['request'] == response.request),None)
        if item is None:
            return
        record = item['record']; record['response_status'] = response.status
        record['redirected_from'] = self.comparison.safe_url(response.request.redirected_from.url) if response.request.redirected_from else None
        item['response']=response

    def capture_snapshot(self):
        """Poll outside callbacks; a manual snapshot may precede the actual click."""
        self.snapshot = {'cookies':self.cookies(),'form':self.form(),
            'focus':self.browser.page.evaluate("""() => ({tag:document.activeElement?.tagName.toLowerCase(),
                test_id:document.activeElement?.getAttribute('data-testid'),type:document.activeElement?.getAttribute('type')})""")}

    def process(self):
        """Read full headers/body outside event callbacks, after native attribution."""
        for item in self.raw_logins:
            if item['processed'] or 'response' not in item:continue
            record=item['record']
            headers=item['request'].all_headers()
            record['cookie_header_present']=bool(headers.get('cookie'))
            record['authorization_present']=bool(headers.get('authorization'))
            item['authorization']=self.comparison.digest(headers.get('authorization',''))
            item['csrf']={k:self.comparison.digest(v) for k,v in headers.items() if 'csrf' in k.lower() or 'xsrf' in k.lower()}
            record['csrf_header_names']=[self.comparison.safe_name(k) for k in item['csrf']]
            record['origin']=self.comparison.safe_url(headers.get('origin',''))
            record['referer']=self.comparison.safe_url(headers.get('referer',''))
            record['user_agent']=self.comparison.store.redact(headers.get('user-agent',''))
            try:
                body=item['response'].json()
                record['response_body_shape']=body_shape(body)
                record['success']=body.get('success') if isinstance(body,dict) and type(body.get('success')) is bool else None
            except Exception:
                record['response_body_shape']='non_json_or_unavailable'
            item['processed']=True

    def finish(self):
        self.process()
        self.data['final_session'] = self.session()
        final = self.cookies()
        for item in self.raw_logins:
            previous = item['cookies']
            item['record']['cookie_changes'] = {'added':[final[k]['name'] for k in final.keys()-previous.keys()],
                'removed':[previous[k]['name'] for k in previous.keys()-final.keys()],
                'changed':[final[k]['name'] for k in final.keys()&previous.keys() if final[k]['_hmac']!=previous[k]['_hmac']]}
        return deepcopy(self.data)


def differential(manual, automated):
    """A missing successful reference is never converted into MANUAL SUCCESS."""
    successful = [x for x in manual.raw_logins if x['record'].get('response_status') == 200 and x['record'].get('success') is True]
    target = [x for x in automated.raw_logins if x['record']['matches_expected_capture']]
    if len(successful) != 1 or len(target) != 1:
        return {'status':'INCOMPLETE_REFERENCE' if len(successful)!=1 else 'AMBIGUOUS_CAPTURE',
                'manual_success_count':len(successful),'qctool_capture_count':len(target),
                'root_cause':'UNKNOWN','differences':[]}
    left,right = successful[0],target[0]; checks=[]
    def compare(field,category,lv,rv):
        checks.append({'field':field,'classification':category,'equal':lv==rv})
    for key,category in [('method','request construction'),('url','endpoint/capture mismatch'),('content_type','request construction'),
                         ('body_shape','request construction'),('cookie_header_present','session/cookie/CSRF state'),
                         ('cookies_before','session/cookie/CSRF state'),('cookie_changes','session/cookie/CSRF state'),
                         ('authorization_present','session/cookie/CSRF state'),('csrf_header_names','session/cookie/CSRF state'),
                         ('origin','request construction'),('referer','request construction'),('user_agent','request construction'),
                         ('response_status','application behavior'),('response_body_shape','application behavior'),('success','application behavior')]:
        compare(key,category,left['record'].get(key),right['record'].get(key))
    credential_equal = set(left['credentials'])==set(right['credentials'])=={'email','password'} and all(
        hmac.compare_digest(left['credentials'][k],right['credentials'][k]) for k in left['credentials'])
    checks.append({'field':'email/password runtime HMAC','classification':'credential resolution','equal':credential_equal})
    csrf_equal = left['csrf']==right['csrf']
    checks.append({'field':'CSRF runtime HMAC','classification':'session/cookie/CSRF state','equal':csrf_equal})
    compare('Authorization runtime HMAC','session/cookie/CSRF state',left.get('authorization'),right.get('authorization'))
    cookies_equal = {k:v['_hmac'] for k,v in left['cookies'].items()}=={k:v['_hmac'] for k,v in right['cookies'].items()}
    checks.append({'field':'cookie runtime HMAC','classification':'session/cookie/CSRF state','equal':cookies_equal})
    compare('final_session','session/cookie/CSRF state',manual.data.get('final_session'),automated.data.get('final_session'))
    compare('bootstrap request sequence','unknown',[(e['method'],e['url']) for e in manual.data['events'][:left['record']['event_index']] if e['kind']=='request'],
            [(e['method'],e['url']) for e in automated.data['events'][:right['record']['event_index']] if e['kind']=='request'])
    return {'status':'COMPARED','manual_success_count':1,'qctool_capture_count':1,
            'root_cause':('LOGIN_METHOD_OR_ENDPOINT_DIFFERENCE' if not left['record']['matches_expected_capture'] else
                          'CREDENTIAL_DIFFERENCE' if not credential_equal else 'NOT_DEMONSTRATED'),
            'differences':checks}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--testcases',type=Path,required=True)
    parser.add_argument('--case-id',required=True)
    parser.add_argument('--manual-wait-seconds',type=int,default=300)
    parser.add_argument('--exploration-audit',type=Path)
    parser.add_argument('--exploration-trace',help='Exact requirement trace identifying an already-approved recorded prerequisite.')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if not 1<=args.manual_wait_seconds<=600:parser.error('Manual wait must be 1–600 seconds.')
    cfg=PipelineConfig.from_file(args.config)
    if cfg.fixture_store is None:parser.error('Configured trusted fixtures are required.')
    raw=yaml.safe_load(args.testcases.read_text())
    rows=raw.get('testcases',raw.get('cases',[])) if isinstance(raw,dict) else raw
    case=_case_from_dict(next(c for c in rows if c['id']==args.case_id));case.validate()
    capture=next(s for s in case.steps if s.action=='ui.click' and s.args.get('capture_response'))
    spec=capture.args['capture_response'];validate_capture(spec)
    fills=[s for s in case.steps if s.action=='ui.fill' and s.seq<capture.seq]
    if len(fills)!=2:parser.error('Diagnostic requires exactly two existing credential fills before capture.')
    aliases={s.args['value'].rsplit('.',1)[-1]:s.args['value'] for s in fills}
    if set(aliases)!={'email','password'}:parser.error('Existing fills must use trusted email/password aliases.')
    if not all(cfg.fixture_store.trusts(alias,case.test_data.get('_fixture_refs',{})) for alias in aliases.values()):
        parser.error('Case aliases must match the current trusted fixture metadata.')
    comparison=Comparison(cfg.fixture_store,aliases)
    controls={s.args['value'].rsplit('.',1)[-1]:s.args for s in fills}
    entry=next(s.args['url'] for s in case.steps if s.action=='ui.goto' and s.seq<capture.seq)
    manual=None;automated=None;report={'llm_calls':0,'case_unchanged':True,'credential_comparison':'ephemeral HMAC-SHA256; key/digests never persisted'}
    class DiagnosticBrowser(BrowserSession):
        def start_case(self,case_id):
            nonlocal automated
            super().start_case(case_id)
            self._capture_private=True
            automated=Observation(self,comparison,spec,controls,'QCTOOL')
        def fill(self,step_args):
            detail=super().fill(step_args)
            alias=step_args.get('_fixture_alias')
            automated.data.setdefault('fills',[]).append({'alias':alias,'target':step_args['target'],
                'runtime_value_matches_fixture':alias in aliases.values() and comparison.equal(step_args['value'],cfg.fixture_store.resolve(alias)),
                'dom_value_matches_runtime':comparison.equal(self.locate(step_args).input_value(),step_args['value'])})
            automated.capture_snapshot()
            return detail
        def note_submit(self,step_args,step_seq):
            automated.capture_snapshot()
            automated.data['submit']={'step_seq':step_seq,'target':step_args['target'],
                                      'count':self.locate(step_args).count(), 'tag':self.locate(step_args).evaluate('e => e.tagName.toLowerCase()')}
            return len(automated.raw_logins)
        def click_and_capture(self,step_args,step_seq):
            first=self.note_submit(step_args,step_seq)
            result=super().click_and_capture(step_args,step_seq)
            automated.data['captured_response']={'status':result['status'],'body':result['body'],'trigger':result['_ui_trigger']}
            matching=[r for r in automated.raw_logins[first:] if r['record']['matches_expected_capture']]
            automated.data['capture_belongs_to_submit']=len(matching)==1 and matching[0]['record'].get('response_status')==result['status']
            return result
        def click_and_observe_requests(self,step_args,step_seq):
            first=self.note_submit(step_args,step_seq)
            result=super().click_and_observe_requests(step_args,step_seq)
            matching=[r for r in automated.raw_logins[first:] if r['record']['matches_expected_capture']]
            automated.data['capture_belongs_to_submit']=len(matching)==result['body']['request_count']
            return result
        def end_case(self,status=''):
            if automated is not None and self._context is automated.context:automated.finish()
            super().end_case(status)
        def close(self):
            if automated is not None and self._context is automated.context:
                try:automated.finish()
                except Exception:automated.data['issues'].append('FINAL_SESSION_UNAVAILABLE')
            super().close()
    try:
        with BrowserSession(cfg.web_url,headless=False,timeout_ms=cfg.timeout_seconds*1000,trace=False) as browser:
            browser.start_case('MANUAL_LOGIN_REFERENCE');browser._capture_private=True
            manual=Observation(browser,comparison,spec,controls,'MANUAL_PENDING')
            browser.goto(entry)
            browser.page.bring_to_front()
            print('MANUAL WINDOW READY: type intended active account and submit once. Credentials will not be printed.',flush=True)
            deadline=time.monotonic()+args.manual_wait_seconds
            while time.monotonic()<deadline:
                browser.page.wait_for_timeout(200)
                manual.process()
                if any(r['record'].get('response_status')==200 and r['record'].get('success') is True for r in manual.raw_logins):
                    browser.page.wait_for_timeout(2000);break
                manual.capture_snapshot()
            manual.data['label']='MANUAL SUCCESS' if any(r['record'].get('response_status')==200 and r['record'].get('success') is True for r in manual.raw_logins) else 'MANUAL SUCCESS NOT CAPTURED'
            report['manual']=manual.finish()
        original=deepcopy(case)
        with DiagnosticBrowser(cfg.web_url,headless=False,timeout_ms=cfg.timeout_seconds*1000,trace=False) as browser:
            result=run_case(case,HttpSession(cfg.base_url,timeout=cfg.timeout_seconds,verify_ssl=cfg.verify_ssl),browser,retry=0,fixture_store=cfg.fixture_store)
            report['qctool']=deepcopy(automated.data) if automated else {'issues':['NO_BROWSER_CONTEXT']}
            report['runner']=result.to_dict()
        report['case_unchanged']=case==original
        report['contexts_distinct']=manual.context is not automated.context if automated else None
        report['comparison']=differential(manual,automated) if automated else {'status':'INCOMPLETE_REFERENCE','root_cause':'UNKNOWN'}
        if args.exploration_audit:
            if not args.exploration_trace:parser.error('--exploration-trace is required with --exploration-audit.')
            audit=json.loads(args.exploration_audit.read_text())
            found=[]
            for history in audit['coverage_loop']['history']:
                for item in history['resolution']['case_results']:
                    loop=item.get('resolution') or {}
                    if args.exploration_trace not in loop.get('case',{}).get('traces_to',[]):continue
                    for cycle in loop.get('cycles',[]):
                        if cycle.get('exploration_plan') and (cycle.get('exploration_validation') or {}).get('valid_requests'):
                            found.append((item,cycle))
            if not found:raise ValueError('No recorded approved prerequisite exists.')
            item,cycle=found[0];d=cycle['context']
            context=ResolutionContext(d['testcase'],tuple(ExecutionGap(**x) for x in d['gaps']),d['specification'],d['interface_contract'],d['observations'],d['allowed_actions'],tuple(d['constraints']),d.get('data_acquisition',{}),d.get('semantics',{}),tuple(d.get('evidence_needs',[])))
            prerequisite=_case_from_dict(item['case'])
            from qctool.testcase import Step,StepKind
            for key,value in d['testcase'].items():
                if key=='steps':value=[Step(**{**s,'kind':StepKind(s['kind'])}) for s in value]
                setattr(prerequisite,key,deepcopy(value))
            plan=parse_exploration_plan(json.dumps(cycle['exploration_plan']))
            validation=validate_exploration_plan(plan,context,prerequisite,cfg.web_url,fixture_store=cfg.fixture_store)
            report['prerequisite_validation']={'status':validation.status,'issues':[i.code for i in validation.issues]}
            if validation.valid_requests:
                # Instrument only, retaining the existing explorer/validator unchanged.
                automated=None
                import qctool.ui.explore as explorer
                with patch.object(explorer,'BrowserSession',DiagnosticBrowser):
                    execution=execute_validated_exploration(validation,context,base_url=cfg.web_url,fixture_store=cfg.fixture_store)
                report['prerequisite']=deepcopy(automated.data) if automated else {'issues':['NO_BROWSER_CONTEXT']}
                report['prerequisite_issues']=[i.code for i in execution.issues]
                report['prerequisite_comparison']=differential(manual,automated) if automated else {'status':'INCOMPLETE_REFERENCE','root_cause':'UNKNOWN'}
    except Exception as exc:
        # Neither repr(exception) nor tracebacks may contain user credentials.
        report['issue']={'code':'DIAGNOSTIC_FAILED','category':type(exc).__name__}
        if manual is not None:report['manual']=manual.data
        if automated is not None:report['qctool']=automated.data
    payload=cfg.fixture_store.redact(report)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'report':str(args.out),'manual':report.get('manual',{}).get('label'),
                      'qctool_result':report.get('runner',{}).get('status'),'comparison':report.get('comparison'),
                      'issue':report.get('issue')},ensure_ascii=False),flush=True)
    return 0 if report.get('comparison',{}).get('status')=='COMPARED' else 2


if __name__=='__main__':
    raise SystemExit(main())

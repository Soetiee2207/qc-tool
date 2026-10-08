"""Offline assertions for the diagnostic trust/redaction boundaries."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

from scripts.diagnose_login_differential import Comparison, Observation, body_shape, differential
from qctool.test_fixtures import FixtureStore
from qctool.execute.browser import BrowserSession
from qctool.execute.runner import HttpSession, run_case
from tests.test_ui_response_capture import capture_site, runtime_case, capture, SECRET


def comparison():
    store=FixtureStore({'person':{'email':{'env':'EMAIL'},'password':{'env':'PASSWORD'}}},
                       environ={'EMAIL':'private@example.test','PASSWORD':'PRIVATE_PASSWORD'})
    return Comparison(store,{'email':'person.email','password':'person.password'})


def observation(cmp, *, success, email='private@example.test', password='PRIVATE_PASSWORD', matches=True):
    record={'method':'POST','url':'https://app.test/api/auth/login','content_type':'application/json',
            'body_shape':{'email':'string','password':'string'},'response_status':200 if success else 401,
            'success':success,'matches_expected_capture':matches,'event_index':0}
    login={'record':record,'credentials':{'email':cmp.digest(email),'password':cmp.digest(password)},'csrf':{},'cookies':{}}
    return SimpleNamespace(raw_logins=[login],data={'events':[],'final_session':{'url':'https://app.test/' if success else 'https://app.test/login'}})


def test_shape_never_serializes_values_or_secret_key_names():
    body={'email':'private@example.test','password':'PRIVATE_PASSWORD','data':{'token':'PRIVATE_TOKEN'},'SECRET_AS_KEY':'secret'}
    result=body_shape(body)
    assert result=={'email':'string','password':'string','data':{'token':'string'},'omitted_field_count':1}
    assert not any(secret in json.dumps(result) for secret in ('private@example.test','PRIVATE_PASSWORD','PRIVATE_TOKEN','SECRET_AS_KEY'))


def test_ephemeral_key_and_fingerprints_never_enter_report():
    cmp=comparison();manual=observation(cmp,success=True);qc=observation(cmp,success=False)
    before=deepcopy((manual.data,qc.data))
    report=differential(manual,qc)
    assert report['status']=='COMPARED' and report['root_cause']=='NOT_DEMONSTRATED'
    assert next(x for x in report['differences'] if x['field']=='email/password runtime HMAC')['equal']
    serialized=json.dumps(report)
    assert cmp.digest('PRIVATE_PASSWORD') not in serialized and cmp.key.hex() not in serialized
    assert (manual.data,qc.data)==before


def test_different_intended_manual_account_demonstrates_credential_difference():
    cmp=comparison()
    report=differential(observation(cmp,success=True,password='OTHER_PASSWORD'),observation(cmp,success=False))
    assert report['root_cause']=='CREDENTIAL_DIFFERENCE'
    assert 'OTHER_PASSWORD' not in json.dumps(report)


def test_unsuccessful_manual_attempt_is_not_successful_reference():
    cmp=comparison()
    report=differential(observation(cmp,success=False),observation(cmp,success=False))
    assert report['status']=='INCOMPLETE_REFERENCE' and report['root_cause']=='UNKNOWN'


def test_duplicate_matching_requests_are_not_attributed_arbitrarily():
    cmp=comparison();qc=observation(cmp,success=False);qc.raw_logins.append(qc.raw_logins[0])
    assert differential(observation(cmp,success=True),qc)['status']=='AMBIGUOUS_CAPTURE'


def test_different_login_mechanism_is_not_misreported_as_bad_fixture():
    cmp=comparison()
    report=differential(observation(cmp,success=True,matches=False),observation(cmp,success=False))
    assert report['root_cause']=='LOGIN_METHOD_OR_ENDPOINT_DIFFERENCE'


def test_secret_names_are_omitted_and_names_only_are_public():
    cmp=comparison()
    assert cmp.safe_name('PRIVATE_PASSWORD')=='[OMITTED_NAME]'
    assert cmp.safe_name('csrf-token')=='csrf-token'
    assert cmp.safe_url('https://app.test/login?token=PRIVATE_TOKEN#secret')=='https://app.test/login'


def test_observer_keeps_headers_cookies_and_response_values_private():
    cmp=comparison();browser=Mock()
    browser.page.url='https://app.test/login'
    browser.page.evaluate.side_effect=lambda script: {'local':[], 'session':[]} if 'localStorage' in script else {'tag':'button','test_id':'submit','type':'submit'}
    browser.page.locator.return_value.count.return_value=0
    browser._context.cookies.return_value=[{'name':'session','domain':'app.test','path':'/',
        'secure':True,'httpOnly':True,'sameSite':'Lax','value':'PRIVATE_COOKIE'}]
    spec={'method':'POST','path':'/api/auth/login','origin':'https://app.test'}
    obs=Observation(browser,cmp,spec,{},'UNIT_REFERENCE')
    req=Mock(method='POST',url='https://app.test/api/auth/login',resource_type='xhr',redirected_from=None)
    req.all_headers.return_value={'content-type':'application/json','origin':'https://app.test',
        'referer':'https://app.test/login?token=PRIVATE_URL_TOKEN','authorization':'Bearer PRIVATE_AUTH',
        'x-csrf-token':'PRIVATE_CSRF','cookie':'session=PRIVATE_COOKIE'}
    req.headers=req.all_headers.return_value
    req.post_data_json={'email':'private@example.test','password':'PRIVATE_PASSWORD'}
    obs.on_request(req)
    req.all_headers.assert_not_called()
    response=Mock(request=req,status=200,url=req.url)
    response.json.return_value={'success':True,'data':{'token':'PRIVATE_RESPONSE','user':{'email':'private@example.test'}}}
    obs.on_response(response)
    response.json.assert_not_called()
    record=obs.finish()
    assert record['login_requests'][0]['credentials_match_fixture']=={'email':True,'password':True}
    assert record['login_requests'][0]['authorization_present']
    assert record['login_requests'][0]['csrf_header_names']==['x-csrf-token']
    assert record['login_requests'][0]['success'] is True
    assert 'PRIVATE' not in json.dumps(record) and 'private@example.test' not in json.dumps(record)


def test_different_cookie_and_csrf_proofs_are_reported_without_values():
    cmp=comparison();manual=observation(cmp,success=True);qc=observation(cmp,success=False)
    manual.raw_logins[0]['csrf']={'x-csrf-token':cmp.digest('PRIVATE_CSRF')}
    manual.raw_logins[0]['cookies']={('session',):{'_hmac':cmp.digest('PRIVATE_COOKIE')}}
    result=differential(manual,qc)
    changed=[d for d in result['differences'] if not d['equal']]
    assert {d['field'] for d in changed}>={'cookie runtime HMAC','CSRF runtime HMAC'}
    assert all(d['classification']=='session/cookie/CSRF state' for d in changed if d['field'].endswith('HMAC'))
    assert 'PRIVATE' not in json.dumps(result)
    assert result['root_cause']=='NOT_DEMONSTRATED'


@pytest.mark.playwright
@pytest.mark.parametrize('mode,status', [('single','Pass'), ('negative','Fail')])
def test_observer_does_not_interfere_with_native_response_capture(capture_site, mode, status):
    cmp=comparison()
    class ObservedBrowser(BrowserSession):
        def start_case(self, case_id):
            super().start_case(case_id)
            self.observer=Observation(self,cmp,capture(capture_site),{},'LOCAL_UNIT_REFERENCE')
        def end_case(self, status=''):
            if hasattr(self,'observer') and self._context is self.observer.context:
                self.observed=self.observer.finish()
            super().end_case(status)
    with ObservedBrowser(capture_site, timeout_ms=3000, trace=False) as browser:
        result=run_case(runtime_case(capture_site,mode),HttpSession(capture_site),browser,retry=0)
        assert result.status==status, result.to_dict()
        requests=browser.observed['login_requests']
        assert len(requests)==1
        assert requests[0]['response_status']==(200 if mode=='single' else 401)
        assert requests[0]['success']==(mode=='single')
        assert SECRET not in json.dumps(browser.observed)

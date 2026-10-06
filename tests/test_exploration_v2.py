"""Bounded source/fixture-grounded interactions on a local app only."""
from copy import deepcopy
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest
from qctool.executability import analyze_executability
from qctool.exploration_plan import ExplorationPlan, PlannedExploration, ExplorationPurpose, validate_exploration_plan
from qctool.exploration_execution import execute_validated_exploration
from qctool.generate.from_openapi import IdAllocator
from qctool.generate.from_requirements import generate_from_acceptance
from qctool.llm_exploration import parse_exploration_plan, build_exploration_prompt
from qctool.llm_resolution import LLMResponseError
from qctool.resolution_context import build_resolution_context
from qctool.test_fixtures import FixtureStore
from qctool.ui.crawl import UIMap, PageMap, Element
from qctool.ui.explore import ExplorationAction, explore_page


@pytest.fixture
def local_app():
    counts = {'click': 0, 'write': 0}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            counts['write'] += 1
            self.rfile.read(int(self.headers.get('Content-Length', '0')))
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Set-Cookie', 'session=HIDDEN_COOKIE')
            self.end_headers()
            self.wfile.write(b'{"success":true,"token":"HIDDEN_RESPONSE_TOKEN"}')
        def do_GET(self):
            if self.path == '/clicked':
                counts['click'] += 1
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'''<title>Explore</title>
              <label>Email<input data-testid="email" type="email"></label>
              <label>Password<input data-testid="password" type="password"></label>
              <label>Theme<select data-testid="theme"><option value="light">Light</option><option value="dark">Dark</option></select></label>
              <button type="button" data-testid="validate">Validate</button>
              <button type="button" data-testid="login">Login</button>
              <p role="alert" data-testid="alert"></p>
              <script>
                const email=document.querySelector('[data-testid=email]');
                email.oninput=()=>{
                  if(location.search.includes('stale'))document.querySelector('[data-testid=validate]').outerHTML='<button data-testid="validate">Validate</button>';
                  if(location.search.includes('redirect'))history.pushState({},'', '/other');
                  if(location.search.includes('unsafe'))fetch('/delete', {method:'POST'});
                };
                document.querySelector('[data-testid=validate]').onclick=()=>{
                  fetch('/clicked');document.querySelector('[data-testid=alert]').textContent='Password required';
                };
                document.querySelector('[data-testid=login]').onclick=()=>{
                  document.querySelector('[data-testid=alert]').textContent='Echo: '+document.querySelector('[data-testid=password]').value;
                  fetch('/api/auth/login',{method:'POST',body:document.querySelector('[data-testid=password]').value});
                };
                document.querySelector('[data-testid=theme]').onchange=e=>document.querySelector('[data-testid=alert]').textContent='Theme: '+e.target.value;
              </script>''')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
    yield f'http://127.0.0.1:{server.server_port}', counts
    server.shutdown();server.server_close();thread.join()


def inputs(base='https://app.test', mode='literal', suffix=''):
    source = {'literal': 'fill "sample@example.test" into Email; click Validate',
              'fixture': 'fill active_user.email into Email; fill active_user.password into Password; click Login',
              'select': 'select dark in Theme'}[mode]
    req = {'id': 'AC-FORM', 'kind': 'acceptance_criterion', 'given': 'Open /form',
           'when': source, 'then': 'Observe validation; POST /api/auth/login'}
    case = generate_from_acceptance([req], IdAllocator(), 'FORM').cases[0]
    store = FixtureStore({'active_user': {'email': {'env': 'EMAIL'}, 'password': {'env': 'PASSWORD'}}},
                         {'AC-FORM': {'email': 'active_user.email', 'password': 'active_user.password'}},
                         environ={'EMAIL': 'private-EMAIL@example.test', 'PASSWORD': 'private-PASSWORD-' * 20})
    if mode == 'fixture':
        case = store.bind(case)
    ui = UIMap(base, 'recorded', [PageMap(base+'/form'+suffix, 'Explore', elements=[
        Element('email', 'input', 'Email', 'input', input_type='email', test_id='email'),
        Element('password', 'input', 'Password', 'input', input_type='password', test_id='password'),
        Element('theme', 'combobox', 'Theme', 'select', test_id='theme', options=[{'value':'light','label':'Light'}, {'value':'dark','label':'Dark'}]),
        Element('validate', 'button', 'Validate', 'button', test_id='validate'),
        Element('login', 'button', 'Login', 'button', test_id='login'),
    ])])
    context = build_resolution_context(case, analyze_executability(case).gaps, requirements=[req], ui_map=ui)
    # Selected UI evidence is supplied exactly, not synthesized browser state.
    context.observations['ui_pages'] = [ui.pages[0].to_dict()]
    context.interface_contract['api_operations'] = [{'method':'POST','path':'/api/auth/login','servers':[base]}]
    actions = {'literal': (ExplorationAction('email',2,'ui.fill','sample@example.test'), ExplorationAction('validate',2)),
               'fixture': (ExplorationAction('email',2,'ui.fill','active_user.email'), ExplorationAction('password',2,'ui.fill','active_user.password'), ExplorationAction('login',2)),
               'select': (ExplorationAction('theme',2,'ui.select','dark'),)}[mode]
    plan = ExplorationPlan(case.id, (PlannedExploration('/form'+suffix, (ExplorationPurpose('UNMAPPED_ACTION',2,'Observe explicit source sequence','observe_network'),), actions=actions),))
    return case, context, ui, store, plan


def approve(case, context, ui, store, plan):
    result = validate_exploration_plan(plan, context, case, ui.base_url, fixture_store=store)
    assert result.status == 'VALID', result.issues
    return result


def test_literal_fixture_select_grounding_and_inputs_unchanged():
    for mode in ('literal','fixture','select'):
        case,context,ui,store,plan=inputs(mode=mode)
        before=deepcopy((case,context,ui,plan))
        result=approve(case,context,ui,store,plan)
        assert len(result.valid_requests[0].request.actions)==len(plan.requests[0].actions)
        assert (case,context,ui,plan)==before
        public=json.dumps(result.to_dict())+build_exploration_prompt(context)
        assert store.resolve('active_user.password') not in public
        assert store.resolve('active_user.email') not in public


@pytest.mark.parametrize('mutation', ['target','ambiguous','foreign','alias','literal_secret','file','destructive','option','budget','unordered','unrelated'])
def test_reject_unsafe(mutation):
    case,context,ui,store,plan=inputs(mode='fixture' if mutation in {'alias','literal_secret'} else 'select' if mutation=='option' else 'literal')
    actions=list(plan.requests[0].actions)
    if mutation=='target': actions[0]=replace(actions[0],target='fake')
    if mutation=='ambiguous': context.observations['ui_pages'][0]['elements'].append(deepcopy(context.observations['ui_pages'][0]['elements'][0]))
    if mutation=='foreign': context.observations['ui_pages'][0]['url']=ui.base_url+'/other'
    if mutation=='alias': actions[0]=replace(actions[0],value='invented.email')
    if mutation=='literal_secret': actions[1]=replace(actions[1],value=store.resolve('active_user.password'))
    if mutation=='file': context.observations['ui_pages'][0]['elements'][0]['input_type']='file'
    if mutation=='destructive': actions[-1]=replace(actions[-1],target='delete')
    if mutation=='option': actions[0]=replace(actions[0],value='invented')
    if mutation=='budget': actions=actions*3
    if mutation=='unordered': actions.reverse()
    if mutation=='unrelated': actions[0]=replace(actions[0],step_seq=1)
    plan=replace(plan,requests=(replace(plan.requests[0],actions=tuple(actions)),))
    result=validate_exploration_plan(plan,context,case,ui.base_url,fixture_store=store)
    assert result.status=='REJECTED' and not result.valid_requests
    assert store.resolve('active_user.password') not in json.dumps(result.to_dict())


def test_strict_action_schema():
    case,context,ui,store,plan=inputs(mode='fixture')
    raw=plan.to_dict()
    assert parse_exploration_plan(json.dumps(raw))==plan
    for key in ('javascript','args','selector'):
        bad=deepcopy(raw);bad['requests'][0]['actions'][0][key]='ignored'
        with pytest.raises(LLMResponseError):parse_exploration_plan(json.dumps(bad))
    raw['requests'][0]['actions'][0].pop('value')
    with pytest.raises(LLMResponseError):parse_exploration_plan(json.dumps(raw))


def test_missing_fixture_store_is_not_trusted():
    case,context,ui,store,plan=inputs(mode='fixture')
    result=validate_exploration_plan(plan,context,case,ui.base_url)
    assert result.status=='REJECTED'


def test_five_explicit_actions_are_accepted():
    case,context,ui,store,plan=inputs()
    clause='fill "sample@example.test" into Email'
    source='; '.join([clause]*5)
    case.steps[1].args['description']=source
    context.testcase['steps'][1]['args']['description']=source
    context.specification['requirements'][0]['when']=source
    actions=(plan.requests[0].actions[0],)*5
    plan=replace(plan,requests=(replace(plan.requests[0],actions=actions),))
    assert len(approve(case,context,ui,store,plan).valid_requests[0].request.actions)==5


@pytest.mark.playwright
def test_changed_approved_action_is_not_executed(local_app):
    base,counts=local_app
    case,context,ui,store,plan=inputs(base)
    approved=approve(case,context,ui,store,plan).valid_requests[0]
    actions=(replace(approved.request.actions[0],value='changed@example.test'),*approved.request.actions[1:])
    tampered=replace(approved,request=replace(approved.request,actions=actions))
    result=explore_page(tampered,base_url=base,fixture_store=store,render_wait_ms=0)
    assert [i.code for i in result.issues]==['ACTION_NOT_VALIDATED']
    assert not result.action_observations and counts=={'click':0,'write':0}


@pytest.mark.playwright
def test_runtime_fixture_unavailable_stops_sequence(local_app):
    base,counts=local_app
    case,context,ui,store,plan=inputs(base,'fixture')
    approved=approve(case,context,ui,store,plan).valid_requests[0]
    result=explore_page(approved,base_url=base,render_wait_ms=0)
    assert [i.code for i in result.issues]==['FIXTURE_UNAVAILABLE']
    assert not result.action_observations and counts=={'click':0,'write':0}


@pytest.mark.playwright
@pytest.mark.parametrize('mode', ['literal','fixture','select'])
def test_real_ordered_sequence_and_redaction(local_app, mode):
    base,counts=local_app
    case,context,ui,store,plan=inputs(base,mode)
    snapshot=deepcopy((case,context,ui,plan))
    validation=approve(case,context,ui,store,plan)
    result=execute_validated_exploration(validation,context,base_url=base,fixture_store=store,render_wait_ms=0)
    assert not result.issues, result.to_dict()
    observed=result.exploration_results[0]
    assert len(observed.action_observations)==len(plan.requests[0].actions)
    assert [a['action'] for a in observed.action_observations]==[a.action for a in plan.requests[0].actions]
    assert observed.action_observations[0]['source_clause']
    assert observed.final_url==base+'/form'
    assert counts['click']==(1 if mode=='literal' else 0)
    assert counts['write']==(1 if mode=='fixture' else 0)
    if mode=='literal': assert any(e.name=='Password required' for e in observed.page.elements)
    if mode=='select': assert any(e.name=='Theme: dark' for e in observed.page.elements)
    public=json.dumps(result.to_dict())+json.dumps(validation.to_dict())+build_exploration_prompt(context)
    for secret in (store.resolve('active_user.email'),store.resolve('active_user.password'),'HIDDEN_COOKIE','HIDDEN_RESPONSE_TOKEN'):
        assert secret not in public
    assert result.context.specification==context.specification and result.context.interface_contract==context.interface_contract
    assert (case,context,ui,plan)==snapshot


@pytest.mark.playwright
@pytest.mark.parametrize('suffix,code', [('?stale','ACTION_PRECONDITION_FAILED'),('?redirect','UNEXPECTED_TRANSITION'),('?unsafe','UNSAFE_NETWORK_REQUEST')])
def test_later_action_stops_after_invalidated_grounding(local_app,suffix,code):
    base,counts=local_app
    case,context,ui,store,plan=inputs(base,suffix=suffix)
    validation=approve(case,context,ui,store,plan)
    observed=explore_page(validation.valid_requests[0],base_url=base,fixture_store=store,render_wait_ms=0)
    assert code in [i.code for i in observed.issues]
    assert counts=={'click':0,'write':0}
    assert len(observed.action_observations)<=1

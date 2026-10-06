"""Local-only two-page workflow and deterministic state/transition safety."""
from copy import deepcopy
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest

from qctool.executability import analyze_executability
from qctool.exploration_execution import execute_validated_exploration
from qctool.exploration_plan import ExplorationPlan, PlannedExploration, ExplorationPurpose, validate_exploration_plan
from qctool.generate.from_openapi import IdAllocator
from qctool.generate.from_requirements import generate_from_acceptance
from qctool.llm_exploration import parse_exploration_plan, build_exploration_prompt
from qctool.llm_resolution import EvidenceReference, _evidence_catalog, _evidence_fields, ProposedChange, AtomicProposal, ResolutionProposal
from qctool.proposal_validation import _resolve_references, _ground_action, validate_resolution_proposal
from qctool.resolution_context import build_resolution_context
from qctool.resolution_cycle import _refresh_context
from qctool.resolution_loop import _evidence_facts
from qctool.test_fixtures import FixtureStore
from qctool.ui.crawl import UIMap, PageMap, Element
from qctool.ui.explore import ExplorationAction, explore_page


@pytest.fixture
def workflow_app():
    counts = {'clicked': 0, 'posts': 0, 'wrong': 0}
    state = {'redirect': None, 'stale': False, 'entry_redirect': False}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            counts['posts'] += 1
            self.rfile.read(int(self.headers.get('Content-Length', '0')))
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(b'{"success":true,"token":"HIDDEN_TOKEN"}')
        def do_GET(self):
            if self.path == '/a' and state['entry_redirect']:
                self.send_response(302); self.send_header('Location', '/wrong'); self.end_headers(); return
            if self.path == '/b' and state['redirect']:
                self.send_response(302); self.send_header('Location', state['redirect']); self.end_headers(); return
            if self.path == '/clicked': counts['clicked'] += 1
            if self.path == '/wrong': counts['wrong'] += 1
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
            if self.path == '/a':
                html = '''<title>Page A</title><a data-testid="search" href="/b">Search</a>
                <label>Email<input data-testid="email" type="email"></label>
                <button data-testid="login" type="button">Login</button>
                <script>document.querySelector('[data-testid=login]').onclick=async()=>{
                  await fetch('/api/auth/login',{method:'POST',body:document.querySelector('input').value});
                  location.href='/b'; };</script>'''
            else:
                html = '''<title>Page B</title><h1>Results</h1>
                <label>Email<input data-testid="email" type="email"></label>
                <button data-testid="validate" type="button">Validate</button><p role="alert" data-testid="alert"></p>
                <script>document.querySelector('[data-testid=validate]').onclick=()=>{
                  fetch('/clicked');document.querySelector('[data-testid=alert]').textContent='Validation observed';};</script>'''
                if state['stale']:
                    html += '''<script>document.querySelector('input').oninput=()=>{
                    document.querySelector('button').outerHTML='<button data-testid="validate">Validate</button>';};</script>'''
            self.wfile.write(html.encode())
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield f'http://127.0.0.1:{server.server_port}', counts, state
    server.shutdown(); server.server_close(); thread.join()


def inputs(base='https://app.test', login=False, fill=False):
    source = ('fill active_user.email into Email; click Login' if login else
              'click Search; fill "public@example.test" into Email; click Validate' if fill else
              'click Search; click Validate')
    req = {'id':'AC-WORKFLOW', 'kind':'acceptance_criterion', 'given':'Open /a',
           'when':source, 'then':'URL /b; validation appears'}
    case = generate_from_acceptance([req], IdAllocator(), 'WORKFLOW').cases[0]
    store = FixtureStore({'active_user': {'email': {'env':'EMAIL'}}},
                         {'AC-WORKFLOW': {'email':'active_user.email'}},
                         environ={'EMAIL':'runtime-private@example.test'})
    if login: case = store.bind(case)
    ui = UIMap(base,'recorded',[
        PageMap(base+'/a','Page A',elements=[Element('search','link','Search','a',test_id='search',href='/b'),
            Element('email','input','Email','input',test_id='email',input_type='email'),
            Element('login','button','Login','button',test_id='login')]),
        PageMap(base+'/b','Page B',elements=[Element('email','input','Email','input',test_id='email',input_type='email'),
            Element('validate','button','Validate','button',test_id='validate')])])
    context = build_resolution_context(case,analyze_executability(case).gaps,requirements=[req],ui_map=ui)
    context.observations['ui_pages']=[p.to_dict() for p in ui.pages]
    context.interface_contract['api_operations']=[{'method':'POST','path':'/api/auth/login','servers':[base]}]
    if login:
        actions=(ExplorationAction('email',2,'ui.fill','active_user.email',page='/a'),
                 ExplorationAction('login',2,page='/a',expected_url='/b'))
    else:
        actions=(ExplorationAction('search',2,page='/a',expected_url='/b'),)
        if fill: actions += (ExplorationAction('email',2,'ui.fill','public@example.test',page='/b'),)
        actions += (ExplorationAction('validate',2,page='/b'),)
    plan=ExplorationPlan(case.id,(PlannedExploration('/a',(ExplorationPurpose('UNMAPPED_ACTION',2,'Inspect source workflow','observe_network'),),actions=actions),))
    return case,context,ui,store,plan


def approve(case,context,ui,store,plan):
    validation=validate_exploration_plan(plan,context,case,ui.base_url,fixture_store=store)
    assert validation.status=='VALID', validation.to_dict()
    return validation


def test_plan_parser_prompt_and_mutation_safety():
    case,context,ui,store,plan=inputs()
    before=deepcopy((case,context,ui,plan))
    assert parse_exploration_plan(json.dumps(plan.to_dict()))==plan
    approved=approve(case,context,ui,store,plan)
    assert approved.valid_requests[0].grounding[-1]['page']==ui.base_url+'/b'
    assert 'expected_url' in build_exploration_prompt(context)
    assert (case,context,ui,plan)==before


@pytest.mark.parametrize('bad', ['old_page','guessed','foreign','foreign_href','fill_transition','unobserved_destination'])
def test_transition_or_state_not_grounded(bad):
    case,context,ui,store,plan=inputs()
    actions=list(plan.requests[0].actions)
    if bad=='old_page': actions[1]=replace(actions[1],page='/a',target='search')
    if bad=='guessed': actions[0]=replace(actions[0],expected_url='/guessed')
    if bad=='foreign': actions[0]=replace(actions[0],expected_url='https://foreign.test/b')
    if bad=='foreign_href': context.observations['ui_pages'][0]['elements'][0]['href']='https://foreign.test/b'
    if bad=='fill_transition': actions[0]=replace(actions[0],action='ui.fill',value='public',expected_url='/b')
    if bad=='unobserved_destination': context.observations['ui_pages'].pop()
    plan=replace(plan,requests=(replace(plan.requests[0],actions=tuple(actions)),))
    result=validate_exploration_plan(plan,context,case,ui.base_url,fixture_store=store)
    assert result.status=='REJECTED'


def test_state_scoped_grounding_cannot_use_other_page_control():
    case,context,ui,store,plan=inputs()
    state={'state_id':'trusted-state-b','valid':True,'page':deepcopy(context.observations['ui_pages'][1])}
    context.observations['page_states']=[state]
    ref=EvidenceReference('ui-map',{'page':ui.base_url+'/b','state_id':'trusted-state-b'})
    repair=ProposedChange(2,'perform.unmapped',('UNMAPPED_ACTION',),'ui.click',
                          {'target':'search'},'Untrusted reason',(ref,))
    assert _ground_action(repair,_resolve_references((ref,),context),context)=='UI_EVIDENCE_NOT_FOUND'
    state['valid']=False
    assert _resolve_references((ref,),context) is None


def test_rejected_state_fields_redact_known_fixture_values():
    case,context,ui,store,plan=inputs(login=True)
    private=store.resolve('active_user.email')
    actions=(replace(plan.requests[0].actions[0],page='/'+private),plan.requests[0].actions[1])
    plan=replace(plan,requests=(replace(plan.requests[0],actions=actions),))
    before=deepcopy(plan)
    rejected=validate_exploration_plan(plan,context,case,ui.base_url,fixture_store=store)
    assert rejected.status=='REJECTED'
    assert private not in json.dumps(rejected.to_dict())
    assert plan==before


def test_normal_validator_can_reuse_specific_state_without_global_locator_collision():
    case,context,ui,store,plan=inputs(login=True)
    context.observations['page_states']=[{'state_id':'recorded-a','valid':True,'page':deepcopy(context.observations['ui_pages'][0])}]
    def ref(target):
        return EvidenceReference('ui-map',{'page':ui.base_url+'/a','state_id':'recorded-a','test_id':target})
    change=ProposedChange(2,'perform.unmapped',('UNMAPPED_ACTION',),'',{},'Preserve both source actions',
                          (EvidenceReference('testcase-step',{'step_seq':2}),),
                          (AtomicProposal('ui.fill',{'target':'email','value':'active_user.email'},(ref('email'),)),
                           AtomicProposal('ui.click',{'target':'login'},(ref('login'),))))
    result=validate_resolution_proposal(ResolutionProposal(case.id,(change,),()),context,case,fixture_store=store)
    assert result.valid_changes==(change,), result.issues
    # A forged state cannot acquire the authority of an actual recorded snapshot.
    bad=replace(change,expansion=(replace(change.expansion[0],evidence=(replace(ref('email'),ref={'page':ui.base_url+'/a','state_id':'invented','test_id':'email'}),)),change.expansion[1]))
    rejected=validate_resolution_proposal(ResolutionProposal(case.id,(bad,),()),context,case,fixture_store=store)
    assert not rejected.valid_changes


@pytest.mark.playwright
@pytest.mark.parametrize('login', [False,True])
def test_two_page_workflow_and_history(workflow_app,login):
    base,counts,state=workflow_app
    case,context,ui,store,plan=inputs(base,login)
    before=deepcopy((case,context,ui,plan))
    validation=approve(case,context,ui,store,plan)
    result=execute_validated_exploration(validation,context,base_url=base,fixture_store=store,render_wait_ms=0)
    assert not result.issues, result.to_dict()
    observed=result.exploration_results[0]
    assert observed.explored and observed.final_url==base+'/b'
    assert len(observed.states)==len(plan.requests[0].actions)+1
    assert observed.states[0]['page']['url']==base+'/a'
    assert observed.states[-1]['page']['url']==base+'/b'
    assert any(e['test_id']=='validate' for e in observed.states[-1]['page']['elements'])
    for i,record in enumerate(observed.action_observations):
        assert record['from_state_id']==observed.states[i]['state_id']
        assert record['state_id']==observed.states[i+1]['state_id']
        assert record['source_clause'] and record['source']['observed_at']
        assert all(set(n)<={'method','url','status','resource_type','action_index'} for n in record['network'])
    enriched=result.context
    assert enriched.observations['current_state_id']==observed.states[-1]['state_id']
    assert len(enriched.observations['page_states'])==len(observed.states)
    assert enriched.specification==context.specification and enriched.interface_contract==context.interface_contract
    assert (case,context,ui,plan)==before
    assert store.resolve('active_user.email') not in json.dumps(result.to_dict())
    assert 'HIDDEN_TOKEN' not in json.dumps(result.to_dict())
    ref=EvidenceReference('ui-map',{'page':base+'/b','state_id':observed.states[-1]['state_id'],'test_id':'validate','role':'button','name':'Validate'})
    _evidence_fields('ui-map',ref.ref,'ref')
    assert _resolve_references((ref,),enriched) is not None
    assert ref.to_dict() in _evidence_catalog(enriched.to_dict())
    repair=ProposedChange(2,'perform.unmapped',('UNMAPPED_ACTION',),'ui.click',
                          {'target':'validate'},'Source-required control in this state',(ref,))
    assert _ground_action(repair,_resolve_references((ref,),enriched),enriched) is None
    assert _resolve_references((replace(ref,ref={**ref.ref,'state_id':'invented'}),),enriched) is None
    refreshed=_refresh_context(case,enriched,analyze_executability(case),ui_map=ui,endpoints=None)
    assert len(refreshed.observations['ui_pages'])==2
    assert refreshed.observations['page_states']==enriched.observations['page_states']
    # Replaying identical state content, with different timestamps/IDs, is not progress.
    changed=deepcopy(enriched)
    changed.observations['page_states'][0]['state_id']='different-id'
    assert _evidence_facts(changed)==_evidence_facts(enriched)
    print('LOCAL WORKFLOW:', json.dumps({'timeline':[{'url':s['page']['url'],'trigger':s['triggering_action'],'valid':s['valid']} for s in observed.states], 'issues':[],'counts':counts}))


@pytest.mark.playwright
@pytest.mark.parametrize('mode,code', [('entry','UNEXPECTED_TRANSITION'),('unexpected','UNEXPECTED_TRANSITION'),('foreign','CROSS_ORIGIN_REDIRECT'),('stale','ACTION_PRECONDITION_FAILED')])
def test_stop_on_unexpected_or_stale_state(workflow_app,mode,code):
    base,counts,state=workflow_app
    state['redirect']='/wrong' if mode=='unexpected' else 'https://foreign.invalid/b' if mode=='foreign' else None
    state['stale']=mode=='stale'
    state['entry_redirect']=mode=='entry'
    case,context,ui,store,plan=inputs(base,fill=mode=='stale')
    validation=approve(case,context,ui,store,plan)
    result=execute_validated_exploration(validation,context,base_url=base,fixture_store=store,render_wait_ms=0)
    observed=result.exploration_results[0]
    assert code in [i.code for i in observed.issues], result.to_dict()
    assert not observed.explored and counts['clicked']==0 and counts['wrong']==0
    assert result.failed_requests and result.context.observations['page_states']
    if mode!='stale':
        assert observed.states[-1]['valid'] is False
        assert result.context.observations.get('current_state_id')!=observed.states[-1]['state_id']
        ref=EvidenceReference('ui-map',{'page':observed.states[-1]['page']['url'],'state_id':observed.states[-1]['state_id']})
        assert _resolve_references((ref,),result.context) is None


@pytest.mark.playwright
def test_modified_workflow_does_not_execute(workflow_app):
    base,counts,state=workflow_app
    case,context,ui,store,plan=inputs(base)
    approved=approve(case,context,ui,store,plan).valid_requests[0]
    actions=(replace(approved.request.actions[0],expected_url=base+'/wrong'),*approved.request.actions[1:])
    approved=replace(approved,request=replace(approved.request,actions=actions))
    result=explore_page(approved,base_url=base,render_wait_ms=0)
    assert [i.code for i in result.issues]==['ACTION_NOT_VALIDATED']
    assert not result.states and not result.action_observations and counts['clicked']==0

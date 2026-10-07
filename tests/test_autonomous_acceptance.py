"""Generic source proofs, opt-in generation plumbing and isolated local contract."""
from copy import deepcopy
from dataclasses import fields, is_dataclass, replace
import json
from pathlib import Path
import threading
from urllib.request import Request, urlopen

import pytest

from qctool.apply_resolution import apply_validated_resolution
from qctool.proposal_validation import validate_resolution_proposal
from qctool.source_grounding import empty_form_contract
from qctool.step_expansion import expected_expansion
from qctool.testcase import Step, StepKind
from qctool.generation import run_generation
from scripts.autonomous_acceptance_app import create_server
from tests.test_empty_login import resolution_inputs


def generic(value):
    if isinstance(value,str):
        for before,after in (
            ('salonhub-soe.vercel.app','generic.example.test'),('/api/auth/login','/api/session'),
            ('/login','/entry'),('Vui lòng điền đầy đủ thông tin','Both fields are required'),
            ('Đăng nhập','Login'),('login-submit-btn','session-submit'),
            ('login-email-input','account-email'),('login-password-input','account-password'),
        ):value=value.replace(before,after)
        return value
    if is_dataclass(value):return replace(value,**{f.name:generic(getattr(value,f.name)) for f in fields(value)})
    if isinstance(value,dict):return {k:generic(v) for k,v in value.items()}
    if isinstance(value,tuple):return tuple(map(generic,value))
    if isinstance(value,list):return list(map(generic,value))
    return value


def test_generic_form_full_source_semantics_and_immutability():
    case,context,proposal,_=generic(resolution_inputs())
    original=deepcopy((case,context,proposal))
    validated=validate_resolution_proposal(proposal,context,case)
    assert len(validated.valid_changes)==3 and not validated.issues
    applied=apply_validated_resolution(case,validated)
    assert applied.after.executable
    assert applied.case.steps[1].args['url'].endswith('/entry')
    assert applied.case.steps[4].args['capture_requests']['path']=='/api/session'
    assert applied.case.steps[6].args['expected']=='Both fields are required'
    assert (case,context,proposal)==original


@pytest.mark.parametrize('change',['different_route','extra_business_clause','destructive_button','destructive_operation'])
def test_generic_contract_abstains_when_source_not_exact(change):
    requirement={'given':'Phiên anonymous ở /entry; cả hai ô email và mật khẩu trống',
        'when':'Bấm Login','then':'Hiển thị Both fields are required; không gửi POST /api/session; URL vẫn ở /entry'}
    if change=='different_route':requirement['then']=requirement['then'].replace('vẫn ở /entry','vẫn ở /other')
    if change=='extra_business_clause':requirement['then']+='; unknown outcome'
    if change=='destructive_button':requirement['when']='Bấm Delete'
    if change=='destructive_operation':requirement['then']=requirement['then'].replace('/api/session','/api/delete-account')
    assert empty_form_contract(requirement) is None


def test_negative_request_grammar_uses_explicit_operation_not_product_path():
    atoms=expected_expansion(Step(1,StepKind.THEN,'assert.unmapped',{'expected':'không gửi POST /api/session'}),{},min_atoms=1)
    assert atoms[0]['no_request']==('POST','/api/session')
    assert expected_expansion(Step(1,StepKind.THEN,'assert.unmapped',{'expected':'URL not /wrong'}),{},min_atoms=1) is None


def test_generation_provisioning_option_is_explicit_and_forwarded(monkeypatch):
    import qctool.generation as module
    from tests.test_generation import executable_case
    original=module.run_coverage_loop
    seen=[]
    def capture(*args,**kwargs):
        seen.append((kwargs['allow_provisioning'],kwargs['environment']))
        return original(*args,**kwargs)
    monkeypatch.setattr(module,'run_coverage_loop',capture)
    requirement={'id':'FR-local','kind':'acceptance_criterion','given':'Open /page',
                 'when':'Open /page','then':'URL /page'}
    run_generation([requirement])
    run_generation([requirement],allow_provisioning=True,environment='local')
    assert seen==[(False,None),(True,'local')]


def test_local_app_fresh_database_and_supported_creation_contract():
    server=create_server();thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        assert server.users=={}
        body=json.dumps({'email':'unit@example.test','password':'ephemeral-unit-only','role':'customer'}).encode()
        with urlopen(Request(base+'/api/customers',data=body,headers={'Content-Type':'application/json'})) as response:
            assert response.status==201 and json.load(response)=={'success':True}
        body=json.dumps({'email':'unit@example.test','password':'ephemeral-unit-only'}).encode()
        with urlopen(Request(base+'/api/session',data=body,headers={'Content-Type':'application/json'})) as response:
            assert response.status==200 and json.load(response)=={'success':True}
        assert all(set(call)=={'method','path','status'} for call in server.calls)
    finally:server.shutdown();server.server_close();thread.join(timeout=5)


def recorded_completion(prompt):
    """Offline contract completion; used ONLY by marked localhost tests."""
    def section(name):return json.loads(prompt.split(name+'\n',1)[1].split('\n\n',1)[0])
    if prompt.startswith('Propose an UNTRUSTED exploration plan'):
        case=section('TESTCASE — EXPLICIT ROUTES AND SESSION REQUIREMENTS')
        gaps=section('UNRESOLVED EXECUTION GAPS')
        pages=section('CURRENT UI OBSERVATION — GROUNDED PAGE/LINK EVIDENCE')['ui_pages']
        # Source-clause-derived target and exact visible controls, never browser commands.
        if any('cả hai ô' in s.get('note','') for s in case['steps']):
            gap=next(g for g in gaps if g['code']=='UNMAPPED_ACTION' and any(s['seq']==g['step_seq'] and s['action']=='assert.unmapped' for s in case['steps']))
            page=next(p for p in pages if p['url'].endswith('/entry'))
            actions=[{'action':'ui.click','target':'session-submit','step_seq':gap['step_seq'],'page':page['url'],'expected_url':page['url']}]
        else:
            step=next((s for s in case['steps'] if s['action']=='perform.unmapped' and 'Preview' in s['args'].get('description','')),None)
            if step is None:return json.dumps({'testcase_id':case['id'],'requests':[]})
            gap=next(g for g in gaps if g['code']=='UNMAPPED_ACTION' and g['step_seq']==step['seq'])
            page=next(p for p in pages if p['url'].endswith('/start'))
            actions=[{'action':'ui.click','target':'preview-link','step_seq':step['seq'],'page':'/start','expected_url':'/review'},
                     {'action':'ui.fill','target':'search-field','step_seq':step['seq'],'value':'orchid','page':'/review'},
                     {'action':'ui.click','target':'check-preview','step_seq':step['seq'],'page':'/review'}]
        requests=[{'target':page['url'],'session':'anonymous',
            'purposes':[{'gap_code':gap['code'],'step_seq':gap['step_seq'],'reason':'Exact source state inspection','intent':'observe_network'}],
            'actions':actions}]
        if page['url'].endswith('/entry'):
            # Regression: a later fresh-session inspection must not erase the
            # prior action's state-scoped validation evidence.
            requests.append({'target':page['url'],'session':'anonymous','purposes':requests[0]['purposes']})
        return json.dumps({'testcase_id':case['id'],'requests':requests})
    case=section('TESTCASE');gaps=section('EXECUTION GAPS');pages=section('CURRENT UI OBSERVATION — UI MAP')['ui_pages']
    requirements=section('SPECIFICATION — REQUIREMENTS')['requirements']
    operations=section('INTERFACE CONTRACT — OPENAPI')['api_operations']
    changes=[]
    for step in case['steps']:
        if step['action'] not in {'perform.unmapped','assert.unmapped'}:continue
        # Empty-form actions/outcomes are resolved through existing deterministic proofs.
        if any('cả hai ô' in s.get('note','') for s in case['steps']):continue
        meanings=expected_expansion(Step(step['seq'],StepKind(step['kind']),step['action'],step['args']),case['test_data'],min_atoms=1)
        if not meanings:continue
        atoms=[]
        requirement=next(r for r in requirements if r['id'] in case['traces_to'])
        refs=[{'source':'requirement','ref':{'id':requirement['id']}}]
        for meaning in meanings:
            args=deepcopy(meaning.get('args',{}));evidence=deepcopy(refs)
            if 'hint' in meaning:
                matches=[(p,e) for p in pages for e in p['elements'] if e.get('name','').lower()==meaning['hint'].lower()]
                if len(matches)!=1:break
                page,element=matches[0];args['target']=element['test_id']
                evidence.append({'source':'ui-map','ref':{'page':page['url'],'test_id':element['test_id']}})
            if 'value' in meaning:args['value']=meaning['value']
            if meaning['action']=='ui.click' and any('POST ' in r.get('then','') for r in requirements):
                operation=next(o for o in operations if o['operation_id']=='establishSession')
                args['capture_response']={'method':operation['method'],'path':operation['path'],'origin':operation['servers'][0], 'save_as':'res','timeout_ms':10000}
                evidence.append({'source':'openapi','ref':{'operation_id':operation['operation_id']}})
            if 'operation' in meaning:
                evidence.append({'source':'openapi','ref':{'method':meaning['operation'][0],'path':meaning['operation'][1]}})
            if 'route' in meaning:
                matches=[p for p in pages if p['url'].endswith(meaning['route'])]
                if len(matches)!=1:break
                evidence.append({'source':'ui-map','ref':{'page':matches[0]['url']}})
            atoms.append({'action':meaning['action'],'args':args,'evidence':evidence})
        if len(atoms)!=len(meanings):continue
        codes=[g['code'] for g in gaps if g['step_seq']==step['seq']]
        changes.append({'step_seq':step['seq'],'from_action':step['action'],'gap_codes':codes,
            'proposed':{'steps':atoms} if len(atoms)>1 else {'action':atoms[0]['action'],'args':atoms[0]['args']},
            'reason':'Recorded exact source grammar','evidence':refs if len(atoms)>1 else atoms[0]['evidence']})
    return json.dumps({'testcase_id':case['id'],'changes':changes,'unresolved':[] if changes else [{'code':g['code'],'step_seq':g['step_seq'],'reason':'Insufficient selected evidence'} for g in gaps]})


@pytest.mark.playwright
def test_fresh_docs_to_real_local_runner_without_provider_network(tmp_path,monkeypatch):
    from qctool.llm_provider import OpenAICompatibleLLM
    from scripts.run_autonomous_acceptance import run_acceptance
    def complete(self,prompt):return recorded_completion(prompt)
    monkeypatch.setattr(OpenAICompatibleLLM,'complete',complete)
    private_values=iter(('LOCAL-PRIVATE-CORRECT-123','LOCAL-PRIVATE-WRONG-456'))
    monkeypatch.setattr('scripts.run_autonomous_acceptance.secrets.token_urlsafe',lambda _:next(private_values))
    result=run_acceptance(tmp_path,OpenAICompatibleLLM('https://unused.example.test','offline-test','UNIT-KEY'))
    assert result['status']=='PASSED', (result.get('error_frames'),result.get('scenario_results'))
    assert result['fresh_account_count']==0
    assert result['provisioning_executed'] and result['validated_exploration_executed']
    assert result['scenario_results']['AC-autonomous-001-1']=='Pass'
    assert result['scenario_results']['AC-autonomous-001-2']=='Pass'
    packet=json.loads((tmp_path/'generation.json').read_text())
    assert packet['coverage_loop']['history']
    assert all(c['steps'] for c in result['results']['results'] if c['status']=='Pass')
    assert 'UNIT-KEY' not in (tmp_path/'acceptance.json').read_text()

    assert all(status=='Pass' for status in result['scenario_results'].values())
    for path in tmp_path.rglob('*'):
        if path.is_file():
            assert b'LOCAL-PRIVATE-CORRECT-123' not in path.read_bytes()
            assert b'LOCAL-PRIVATE-WRONG-456' not in path.read_bytes()


def test_compact_resolution_example_uses_generic_source_ids_routes_and_aliases():
    from qctool.llm_resolution import build_resolution_prompt, parse_resolution_proposal
    from qctool.resolution_context import build_resolution_context
    from qctool.executability import analyze_executability
    from qctool.test_fixtures import FixtureStore
    from qctool.ui.crawl import UIMap,PageMap,Element
    from qctool.testcase import TestCase
    from qctool.generate.loader import load_endpoints
    base='https://generic.example.test'
    case=TestCase('TC_GENERIC_001','GENERIC','Sign in','Source only',traces_to=['AC-GENERIC'],execution='manual',source_quote='Explicit generic sign-in obligation',
        steps=[Step(1,StepKind.GIVEN,'ui.goto',{'url':'/entry'}),
               Step(2,StepKind.WHEN,'perform.unmapped',{'description':'fill email; fill password; click Login'}),
               Step(3,StepKind.THEN,'assert.unmapped',{'expected':'POST /api/session trả 200 với success=true; URL chuyển tới /workspace'})])
    requirement={'id':'AC-GENERIC','when':case.steps[1].args['description'],'then':case.steps[2].args['expected']}
    store=FixtureStore({'actor':{'email':{'env':'EMAIL'},'password':{'env':'PASSWORD'}}},
        {'AC-GENERIC':{'email':'actor.email','password':'actor.password'}},environ={'EMAIL':'unit-private@example.test','PASSWORD':'UNIT-PRIVATE'})
    case=store.bind(case)
    ui=UIMap(base,'offline',[PageMap(base+'/entry','Entry',elements=[
        Element('email','input','Email','input',test_id='account-email',input_type='email'),
        Element('password','input','Password','input',test_id='account-password',input_type='password'),
        Element('submit','button','Login','button',test_id='session-submit')]),PageMap(base+'/workspace','Workspace')])
    endpoints=load_endpoints(Path('samples/acceptance/autonomous/openapi.yaml'))[0]
    endpoints=[replace(e,contract_servers=[base]) for e in endpoints]
    context=build_resolution_context(case,analyze_executability(case).gaps,requirements=[requirement],ui_map=ui,endpoints=endpoints)
    prompt=build_resolution_prompt(context)
    example=json.loads(prompt.split('COMPACT LOGIN EXAMPLE — partial proposal from this context only\n')[1])
    proposal=parse_resolution_proposal(json.dumps(example))
    validation=validate_resolution_proposal(proposal,context,case,fixture_store=store)
    assert len(validation.valid_changes)==2 and not validation.issues
    assert apply_validated_resolution(case,validation).after.executable
    assert '/api/auth/login' not in prompt and 'UNIT-PRIVATE' not in prompt
    assert proposal.changes[0].expansion[-1].args['capture_response']['path']=='/api/session'
    assert proposal.changes[1].expansion[-1].args=={'pattern':'/workspace$'}

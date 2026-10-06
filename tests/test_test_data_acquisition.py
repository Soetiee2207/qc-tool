"""Offline acquisition classification; no browser, model or backend calls."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from qctool.config import ConfigError
from qctool.executability import analyze_executability
from qctool.generate.loader import load_endpoints
from qctool.llm_exploration import build_exploration_prompt
from qctool.llm_resolution import build_resolution_prompt
from qctool.resolution_context import build_resolution_context
from qctool.resolution_cycle import run_resolution_cycle
from qctool.test_data_acquisition import DATA_REQUIREMENTS, DataRequirement, DataStatus, acquire_test_data
from qctool.test_fixtures import FixtureStore, load_fixture_store
from qctool.testcase import TestCase, Step, StepKind

FACTS={'account_exists':True,'role':'customer','account_state':'active','password_valid':True}
GIVENS=[
 'Phiên anonymous ở /login; tài khoản customer đang hoạt động và mật khẩu đúng do người vận hành cung cấp',
 'Phiên anonymous ở /login; email của tài khoản hoạt động và mật khẩu sai đã xác nhận',
 'Phiên anonymous ở /login; tài khoản có isActive=false đã được chuẩn bị bởi người vận hành',
]


def inputs(facts=None, env=None, acquisition=None):
    config={'fixtures':{'active_user':{'email':{'env':'EMAIL'},'password':{'env':'PASSWORD'}}},
            'bindings':{'AC-LOGIN':{'email':'active_user.email','correct_password':'active_user.password'}}}
    if facts: config['fixtures']['active_user']['facts']=facts
    if acquisition is not None: config['acquisition']=acquisition
    store=FixtureStore(config['fixtures'],config['bindings'],
                       environ=env if env is not None else {'EMAIL':'private@example.test','PASSWORD':'PRIVATE-PASSWORD'},
                       acquisition=acquisition)
    case=TestCase('TC_GENERIC_007','AUTH','Login','Login',traces_to=['AC-LOGIN'],execution='manual',
                  steps=[Step(1,StepKind.GIVEN,'perform.unmapped',{'description':GIVENS[0]}),
                         Step(2,StepKind.THEN,'assert.url_matches',{'pattern':'/$'})])
    return case,store,config


def need():
    return DataRequirement('active_user',('active_user.email','active_user.password'),FACTS,step_seq=1)


def declarations():
    return {'evidence':[{'fixture':'active_user','facts':FACTS,'assurance':'DECLARED','source_ref':'operator-check-001'}]}


def test_existing_fixture_available_without_claiming_account_state():
    case,store,config=inputs()
    requirement=DataRequirement('active_user',('active_user.email','active_user.password'))
    result=acquire_test_data(case,fixture_store=store,requirements=[requirement])
    assert result.status==DataStatus.AVAILABLE
    assert result.case.test_data['email']=='active_user.email'
    assert not result.to_dict()['live_verification_performed']
    assert result.findings[0].facts==()


def test_missing_alias_is_missing_fixture():
    case,store,config=inputs(env={})
    result=acquire_test_data(case,fixture_store=store)
    assert result.status==DataStatus.MISSING_TEST_DATA
    assert result.issues[0]['code']=='MISSING_FIXTURE'
    assert all(not alias['available'] for alias in result.findings[0].aliases)


def test_unknown_alias_is_not_created_or_guessed():
    case,_,_=inputs()
    store=FixtureStore({},environ={})
    result=acquire_test_data(case,fixture_store=store,
                             requirements=[DataRequirement('unknown_user',('unknown_user.password',))])
    assert result.status==DataStatus.MISSING_TEST_DATA
    assert result.issues[0]['code']=='MISSING_FIXTURE'
    assert not result.findings[0].aliases[0]['available']
    assert 'unknown_user.password' not in store.to_dict()['aliases']


def test_credentials_are_not_account_proof_and_config_is_declaration_only():
    case,store,config=inputs({'role':'customer','account_state':'active'})
    result=acquire_test_data(case,fixture_store=store)
    assert result.status==DataStatus.MISSING_TEST_DATA
    assert result.issues[0]['code']=='UNVERIFIED_TEST_DATA'
    facts={f.fact:f.status for f in result.findings[0].facts}
    assert facts=={'account_exists':'UNVERIFIED','role':'DECLARED','account_state':'DECLARED','password_valid':'UNVERIFIED'}


def test_declared_fact_policy_is_explicit_and_never_claims_live_verification():
    case,store,config=inputs(acquisition=declarations())
    result=acquire_test_data(case,fixture_store=store,requirements=[replace(need(),require_verified=False)])
    assert result.status==DataStatus.AVAILABLE
    assert all(f.status=='DECLARED' for f in result.findings[0].facts)
    assert not result.to_dict()['live_verification_performed']


def test_public_requirement_literal_id_is_not_proof_of_entity_existence():
    case,store,config=inputs()
    case.test_data={'entity_id':'ORDER-001'}
    result=acquire_test_data(case,requirements=[DataRequirement(None,facts={'entity_id':'ORDER-001'})])
    assert result.status==DataStatus.AVAILABLE and result.findings[0].facts[0].status=='LITERAL'
    absent=acquire_test_data(case,requirements=[DataRequirement(None,facts={'entity_id':'ORDER-001','entity_exists':True})])
    assert absent.status==DataStatus.MISSING_TEST_DATA


@pytest.mark.parametrize('unsafe', [None,'admin','seed','delete','external','auth'])
def test_creation_contract_is_a_candidate_only_never_called(unsafe,monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**kw:pytest.fail('No network permitted'))
    op=load_endpoints(Path('samples/smoke/openapi.yaml'))[0][0]
    op=replace(op,operation_id='createCustomer',method='POST',path='/users',requires_auth=False,responses={'201':{}})
    if unsafe in {'admin','seed','delete'}: op=replace(op,path='/'+unsafe+'/users')
    if unsafe=='auth': op=replace(op,requires_auth=True)
    config={'provisioning':[{'fixture':'active_user','operation_id':'createCustomer','provides':FACTS,'external_interaction':unsafe=='external'}]}
    case,store,_=inputs(env={})
    result=acquire_test_data(case,fixture_store=store,sources=config,endpoints=[op])
    assert result.status==(DataStatus.PROVISIONABLE if unsafe is None else DataStatus.UNSAFE_TO_PROVISION)
    assert result.findings[0].provisioning[0]['execution_allowed'] is False
    assert not result.to_dict()['provisioning_performed']
    context=replace(build_resolution_context(result.case,()),data_acquisition=result.to_dict())
    assert not analyze_executability(result.case,context=context).executable


def test_no_fuzzy_endpoint_guessing_or_incomplete_creation_contract():
    case,store,_=inputs(env={})
    op=replace(load_endpoints(Path('samples/smoke/openapi.yaml'))[0][0],operation_id='createCustomer',method='POST',path='/users',requires_auth=False,responses={'201':{}})
    assert acquire_test_data(case,fixture_store=store,endpoints=[op]).status==DataStatus.MISSING_TEST_DATA
    sources={'provisioning':[{'fixture':'active_user','operation_id':'createCustomer','provides':FACTS,'external_interaction':False}]}
    assert acquire_test_data(case,fixture_store=store,sources=sources,endpoints=[replace(op,responses={'200':{}})]).status==DataStatus.MISSING_TEST_DATA
    assert acquire_test_data(case,fixture_store=store,sources=sources,endpoints=[op,op]).status==DataStatus.MISSING_TEST_DATA


def test_conflicting_seed_and_fixture_facts_ambiguous():
    case,store,_=inputs({'account_state':'active'})
    sources={'evidence':[{'fixture':'active_user','facts':{'account_state':'locked'},'assurance':'DECLARED','source_ref':'seed-manifest-001'}]}
    result=acquire_test_data(case,fixture_store=store,sources=sources)
    assert result.status==DataStatus.AMBIGUOUS
    assert next(f for f in result.findings[0].facts if f.fact=='account_state').status=='CONFLICT'


def test_conflicting_bindings_are_structured_ambiguity():
    case,store,_=inputs()
    case.test_data['email']='other_user.email'
    result=acquire_test_data(case,fixture_store=store)
    assert result.status==DataStatus.AMBIGUOUS and result.case==case


def test_secrets_not_serialized_and_all_inputs_unchanged():
    case,store,config=inputs(acquisition=declarations())
    context=build_resolution_context(case,())
    before=deepcopy((case,context,config)); store_before=store.to_dict()
    result=acquire_test_data(case,fixture_store=store)
    packet=replace(context,data_acquisition=result.to_dict())
    public=json.dumps(result.to_dict())+build_resolution_prompt(packet)+build_exploration_prompt(packet)+repr(result)
    assert 'PRIVATE-PASSWORD' not in public and 'private@example.test' not in public
    assert (case,context,config)==before and store.to_dict()==store_before


def test_opt_in_resolution_integration_and_gap_types():
    case,store,config=inputs()
    # Nonempty acquisition config enables the gate without changing legacy facts validation.
    store=FixtureStore(config['fixtures'],config['bindings'],environ={'EMAIL':'private@example.test','PASSWORD':'PRIVATE-PASSWORD'},acquisition={'requirements':{'AC-LOGIN':[{'fixture':'active_user','aliases':['active_user.email','active_user.password'],'facts':FACTS,'step_seq':1}]}})
    context=build_resolution_context(case,())
    before=deepcopy((case,context))
    cycle=run_resolution_cycle(case,context,fixture_store=store)
    assert cycle.context.data_acquisition['status']=='MISSING_TEST_DATA'
    assert 'UNVERIFIED_TEST_DATA' in {g.code for g in cycle.after.gaps}
    assert not cycle.after.executable
    assert (case,context)==before


@pytest.mark.parametrize('index,name,password_key', [(0,'active_user','correct_password'),(1,'invalid_user','wrong_password'),(2,'locked_user','non_empty_password')])
def test_login_source_shapes_not_testcase_id_special_cases(index,name,password_key):
    case,_,_=inputs()
    case.id='TC_ARBITRARY_100'
    case.steps[0].args['description']=GIVENS[index]
    definitions={name:{'email':{'env':'EMAIL'},'password':{'env':'PASSWORD'}}}
    store=FixtureStore(definitions,{'AC-LOGIN':{'email':name+'.email',password_key:name+'.password'}},environ={'EMAIL':'private@example.test','PASSWORD':'PRIVATE-PASSWORD'})
    result=acquire_test_data(case,fixture_store=store)
    assert result.status==DataStatus.MISSING_TEST_DATA
    facts={f.fact:f.expected for f in result.findings[0].facts}
    assert facts['account_exists'] is True
    if index==0: assert facts['role']=='customer' and facts['password_valid'] is True
    if index==1: assert facts['password_valid'] is False and facts['account_state']=='active'
    if index==2: assert facts['account_state']=='locked' and 'password_valid' not in facts


def test_unbound_account_is_missing_data_not_invented_alias():
    case,_,_=inputs()
    result=acquire_test_data(case)
    assert result.status==DataStatus.MISSING_TEST_DATA
    assert result.findings[0].requirement.fixture is None
    assert result.findings[0].aliases==()


def test_mapping_given_does_not_erase_unverified_data_obligation():
    case,store,_=inputs({'role':'customer','account_state':'active'},acquisition={'evidence':[]})
    first=acquire_test_data(case,fixture_store=store)
    mapped=deepcopy(first.case)
    mapped.steps[0].action='ui.goto'; mapped.steps[0].args={'url':'/login'}
    again=acquire_test_data(mapped,fixture_store=store)
    assert again.case.test_data[DATA_REQUIREMENTS]==first.case.test_data[DATA_REQUIREMENTS]
    assert again.status==DataStatus.MISSING_TEST_DATA
    assert again.issues[0]['code']=='UNVERIFIED_TEST_DATA'


@pytest.mark.parametrize('marker', ['source-clause','mapper-clause','resolution-expansion'])
def test_source_provenance_recovers_need_from_already_mapped_given(marker):
    case,store,_=inputs()
    original=case.steps[0].to_dict()
    record={'source-clause':{'field':'given','text':GIVENS[0]},
            'mapper-clause':{'testcase_id':case.id,'source_step_seq':1,'source_text':GIVENS[0]},
            'resolution-expansion':{'testcase_id':case.id,'source_step':original}}[marker]
    case.steps[0]=Step(1,StepKind.GIVEN,'ui.goto',{'url':'/login'},f'[{marker}] '+json.dumps(record))
    result=acquire_test_data(case,fixture_store=store)
    assert result.status==DataStatus.MISSING_TEST_DATA
    assert result.findings[0].requirement.facts==FACTS


def test_config_cannot_claim_it_performed_backend_verification():
    with pytest.raises(ConfigError):
        FixtureStore({},acquisition={'evidence':[{'fixture':'active_user','facts':{'account_exists':True},'assurance':'RECORDED_VERIFICATION','source_ref':'claimed-live-check'}]})


def test_credentials_from_different_accounts_do_not_prove_one_account():
    case,_,_=inputs()
    store=FixtureStore({'first':{'email':{'env':'EMAIL'}},'second':{'password':{'env':'PASSWORD'}}},
                       {'AC-LOGIN':{'email':'first.email','correct_password':'second.password'}},
                       environ={'EMAIL':'private@example.test','PASSWORD':'PRIVATE-PASSWORD'})
    result=acquire_test_data(case,fixture_store=store)
    assert result.status==DataStatus.MISSING_TEST_DATA
    assert result.findings[0].requirement.fixture is None


def test_requirement_budget_has_structured_abstention():
    case,store,_=inputs()
    result=acquire_test_data(case,fixture_store=store,requirements=[need()]*9)
    assert result.status==DataStatus.MISSING_TEST_DATA
    assert result.issues[0]['code']=='MISSING_TEST_DATA'


def test_config_extension_and_malformed_metadata_rejected():
    store=load_fixture_store({'fixtures':{},'acquisition':{'evidence':[]}})
    assert store.acquisition_config=={'evidence':[]}
    with pytest.raises(ConfigError):
        FixtureStore({},acquisition={'evidence':[{'fixture':'active_user','facts':{'password':'secret'},'assurance':'DECLARED','source_ref':'seed'}]})

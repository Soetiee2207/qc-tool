"""One preparation phase, through normal resolution/generation, all offline."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

import qctool.test_data_preparation as preparation
import qctool.test_data_verification as verification_module
from qctool.test_data_acquisition import acquire_test_data, DataRequirement, DataStatus
from qctool.test_data_preparation import prepare_test_data, PreparationStatus
from qctool.test_data_verification import VerificationResult, VerificationStatus
from qctool.test_fixtures import FixtureStore
from qctool.generation import run_generation
from qctool.executability import analyze_executability
from qctool.testcase import Step, StepKind
from tests.test_test_data_verification import setup, rule, BASE, verify
from tests.test_test_data_acquisition import inputs, FACTS, need
from tests.test_generation import executable_case


def success(*args):
    return {'status':200, 'body':{'success':True,'token':'SECRET-RESPONSE'}}


def test_verified_receipt_is_reused_without_network():
    case,store,config,op,acquired=setup()
    receipt=verify(store,op,acquired)
    result=prepare_test_data(acquired.case,fixture_store=store,endpoints=[op],verification=receipt,
                             transport=lambda *a:pytest.fail('already verified'))
    assert result.available and result.final.status==DataStatus.AVAILABLE
    assert not result.verification_attempted
    assert result.verification_reason=='RECEIPT_REUSED'


def test_aliases_alone_never_trigger_verification():
    case,store,config,op,_=setup()
    case.steps=[Step(1,StepKind.THEN,'assert.url_matches',{'pattern':'/login$'})]
    result=prepare_test_data(case,fixture_store=store,endpoints=[op],base_url=BASE,
                             transport=lambda *a:pytest.fail('credentials are not a trigger'))
    assert result.available and result.verification is None
    assert result.verification_reason=='ALREADY_AVAILABLE'


def test_401_precise_invalid_blocker_not_missing_fixture():
    case,store,config,op,_=setup()
    result=prepare_test_data(case,fixture_store=store,endpoints=[op],base_url=BASE,
                             transport=lambda *a:{'status':401,'body':{'success':False,'message':'private error'}})
    assert result.status==PreparationStatus.INVALID_TEST_DATA
    assert not result.available
    assert {b['code'] for b in result.blockers}=={'INVALID_TEST_DATA'}
    assert result.case.execution=='manual'
    assert all(f.status=='UNVERIFIED' for f in result.final.findings[0].facts)
    assert 'private error' not in json.dumps(result.to_dict())


@pytest.mark.parametrize('failure',['unreviewed','admin','ambiguous','bad_contract'])
def test_unsafe_or_ambiguous_rules_never_call_verifier_or_resolve(failure,monkeypatch):
    record=rule()
    if failure=='unreviewed':record['policy']['approved']=False
    case,store,config,op,_=setup(record)
    endpoints=[op]
    if failure=='admin':endpoints=[replace(op,path='/admin/users')]
    if failure=='ambiguous':endpoints=[op,op]
    if failure=='bad_contract':endpoints=[replace(op,request_required=['invented'])]
    monkeypatch.setattr(preparation,'verify_test_data',lambda *a,**kw:pytest.fail('unsafe verification phase'))
    monkeypatch.setattr(store,'resolve',lambda *a:pytest.fail('unsafe alias resolution'))
    result=prepare_test_data(case,fixture_store=store,endpoints=endpoints,base_url=BASE)
    assert not result.verification_attempted
    assert result.verification is None
    assert result.status==(PreparationStatus.AMBIGUOUS if failure=='ambiguous' else PreparationStatus.UNSAFE_TO_VERIFY)


def test_missing_fixture_with_creation_candidate_is_provisionable_never_provisioned():
    config={'provisioning':[{'fixture':'active_user','operation_id':'createCustomer',
                            'provides':FACTS,'external_interaction':False}],
            'verification':[rule()]}
    case,store,_=inputs(env={},acquisition=config)
    _,_,_,login,_=setup()
    create=replace(login,operation_id='createCustomer',path='/users',responses={'201':{}},contract_servers=[])
    result=prepare_test_data(case,fixture_store=store,endpoints=[login,create],base_url=BASE,
                             transport=lambda *a:pytest.fail('missing fixture'))
    assert result.status==PreparationStatus.PROVISIONABLE
    assert result.final.status==DataStatus.PROVISIONABLE
    assert not result.verification_attempted
    assert not result.final.to_dict()['provisioning_performed']
    assert any(b['code']=='PROVISIONABLE' for b in result.blockers)


def test_stale_or_fake_receipt_is_explicit_blocker_no_fallback_call():
    case,store,config,op,acquired=setup()
    receipt=verify(store,op,acquired)
    for fake in [receipt.to_dict(),VerificationResult(receipt.observations)]:
        result=prepare_test_data(acquired.case,fixture_store=store,endpoints=[op],verification=fake,
                                 transport=lambda *a:pytest.fail('no repair for bad receipt'))
        assert not result.available
        assert result.verification is None
        assert result.final.status!=DataStatus.AVAILABLE
        assert result.verification_reason=='RECEIPT_REJECTED'
        assert any(i['code']=='VERIFICATION_RECEIPT_REJECTED' for i in result.blockers)
    store._values['active_user.password']='NEW-SECRET'
    assert not prepare_test_data(acquired.case,fixture_store=store,verification=receipt).available


def test_rule_selection_skips_verified_facts_and_preserves_maximum_calls():
    records=[]
    for field in ['account_exists','role','account_state']:
        record=rule({field:FACTS[field]}); record['operation_id']='verify_'+field
        records.append(record)
    case,_,config,op,_=setup()
    store=FixtureStore(config['fixtures'],config['bindings'],environ={'EMAIL':'private@example.test','PASSWORD':'PRIVATE-PASSWORD'},
                       acquisition={'verification':records})
    endpoints=[replace(op,operation_id=r['operation_id']) for r in records]
    calls=[]
    result=prepare_test_data(case,fixture_store=store,endpoints=endpoints,base_url=BASE,
                             transport=lambda *a:(calls.append(a) or success()))
    assert len(calls)==3
    assert not result.available  # password_valid was never proven.
    assert result.status==PreparationStatus.UNVERIFIED_TEST_DATA


@pytest.mark.parametrize('fixture,facts,status',[
    ('active_user',FACTS,200),
    ('invalid_user',{'account_exists':True,'account_state':'active','password_valid':False},401),
    ('locked_user',{'account_exists':True,'account_state':'locked'},401),
])
def test_generic_login_regressions(fixture,facts,status):
    case,_,config,op,_=setup()
    aliases=[fixture+'.email',fixture+'.password']
    record=rule(facts); record.update(fixture=fixture,body_aliases=dict(zip(('email','password'),aliases)))
    store=FixtureStore({fixture:config['fixtures']['active_user']},
                       {'AC-LOGIN':dict(zip(('email','correct_password'),aliases))},
                       environ={'EMAIL':'private@example.test','PASSWORD':'PRIVATE-PASSWORD'},
                       acquisition={'verification':[record]})
    result=prepare_test_data(case,fixture_store=store,endpoints=[op],base_url=BASE,
                             requirements=[DataRequirement(fixture,tuple(aliases),facts)],
                             transport=lambda *a:{'status':status,'body':{'success':status==200}})
    assert result.status==(PreparationStatus.AVAILABLE if status==200 else PreparationStatus.INVALID_TEST_DATA)


def test_unavailable_without_rule_is_unverified_not_invalid():
    case,store,_=inputs()
    result=prepare_test_data(case,fixture_store=store)
    assert result.status==PreparationStatus.UNVERIFIED_TEST_DATA
    assert result.verification_reason=='NO_REVIEWED_RULE'
    assert not result.verification_attempted


def test_missing_values_are_distinct_from_invalid_or_unverified_state():
    case,store,_=inputs(env={},acquisition={'verification':[rule()]})
    _,_,_,op,_=setup()
    result=prepare_test_data(case,fixture_store=store,endpoints=[op],base_url=BASE,
                             transport=lambda *a:pytest.fail('missing credentials'))
    assert result.status==PreparationStatus.MISSING_FIXTURE
    assert result.verification_reason=='MISSING_VALUES'
    assert any(i['code']=='MISSING_FIXTURE' for i in result.blockers)


def test_unsafe_alternative_does_not_block_safe_independent_rule():
    bad=rule(); bad['operation_id']='unsafeProbe'; bad['policy']['approved']=False
    good=rule()
    case,_,config,op,_=setup()
    store=FixtureStore(config['fixtures'],config['bindings'],environ={'EMAIL':'private@example.test','PASSWORD':'PRIVATE-PASSWORD'},
                       acquisition={'verification':[bad,good]})
    unsafe=replace(op,operation_id='unsafeProbe',contract_servers=['https://foreign.example.test'])
    calls=[]
    result=prepare_test_data(case,fixture_store=store,endpoints=[unsafe,op],base_url='https://frontend.example.test',
                             transport=lambda *a:(calls.append(a) or success()))
    assert result.available
    assert len(calls)==1 and calls[0][1]==BASE+'/api/auth/login'
    assert result.rule_decisions[0]['code']=='UNAPPROVED_EFFECTS'


def test_two_approved_backend_origins_are_ambiguous_without_any_call():
    first=rule({'account_exists':True}); second=rule({'password_valid':True}); second['operation_id']='checkPassword'
    case,_,config,op,_=setup()
    store=FixtureStore(config['fixtures'],config['bindings'],environ={'EMAIL':'private@example.test','PASSWORD':'PRIVATE-PASSWORD'},
                       acquisition={'verification':[first,second]})
    other=replace(op,operation_id='checkPassword',contract_servers=['https://other.example.test'])
    result=prepare_test_data(case,fixture_store=store,endpoints=[op,other],transport=lambda *a:pytest.fail('ambiguous backend'))
    assert result.status==PreparationStatus.AMBIGUOUS
    assert not result.verification_attempted

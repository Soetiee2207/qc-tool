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
from qctool.resolution_context import build_resolution_context
from qctool.resolution_cycle import run_resolution_cycle
from qctool.resolution_loop import run_resolution_loop
from qctool.generation import run_generation
from qctool.executability import analyze_executability
from qctool.testcase import Step, StepKind
from tests.test_test_data_verification import setup, rule, BASE, verify
from tests.test_test_data_acquisition import inputs, FACTS, need
from tests.test_generation import executable_case, flows


def success(*args):
    return {'status':200, 'body':{'success':True,'token':'SECRET-RESPONSE'}}


def test_safe_reviewed_rule_prepares_all_facts_and_keeps_inputs_unchanged():
    case,store,config,op,_=setup()
    context=build_resolution_context(case,())
    before=deepcopy((case,context,config,store.to_dict()))
    calls=[]
    def transport(*args):
        calls.append(args)
        return success()
    result=prepare_test_data(case,fixture_store=store,endpoints=[op],base_url=BASE,transport=transport)
    assert result.status==PreparationStatus.AVAILABLE and result.available
    assert result.initial.status==DataStatus.MISSING_TEST_DATA
    assert result.final.status==DataStatus.AVAILABLE
    assert result.verification.status==VerificationStatus.VERIFIED
    assert result.verification_attempted and len(calls)==1
    assert [stage.stage for stage in result.stages]==['acquisition','verification','reacquisition']
    assert not result.blockers
    assert before==(case,context,config,store.to_dict())
    packet=json.dumps(result.to_dict())
    assert all(secret not in packet for secret in ['PRIVATE-PASSWORD','private@example.test','SECRET-RESPONSE'])


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


def test_no_data_case_does_zero_acquisition_or_verification_work(monkeypatch):
    case=executable_case()
    monkeypatch.setattr(preparation,'acquire_test_data',lambda *a,**kw:pytest.fail('no acquisition needed'))
    monkeypatch.setattr(preparation,'verify_test_data',lambda *a,**kw:pytest.fail('no verification needed'))
    result=prepare_test_data(case)
    assert result.status==PreparationStatus.NO_DATA_REQUIRED
    assert result.available and result.case==case and result.case is not case
    assert result.initial is result.final is result.verification is None
    context=build_resolution_context(case,())
    assert run_resolution_loop(case,context).executable


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


def test_prepare_once_per_loop_no_new_probe_on_later_cycles(monkeypatch):
    case,store,config,op,_=setup()
    calls=[]
    monkeypatch.setattr(verification_module,'_once',lambda *a:(calls.append(a) or success()))
    # Force cycles by leaving logical steps unmapped; data acquisition completes first.
    context=build_resolution_context(case,())
    result=run_resolution_loop(case,context,fixture_store=store,endpoints=[op],base_url=BASE,max_cycles=5)
    assert len(calls)==1
    assert result.test_data_preparation.available
    assert result.context.data_acquisition['status']=='AVAILABLE'
    assert all(c.context.data_acquisition['status']=='AVAILABLE' for c in result.cycles)


def test_standalone_cycle_automatically_prepares_before_model_work(monkeypatch):
    case,store,config,op,_=setup()
    calls=[]
    monkeypatch.setattr(verification_module,'_once',lambda *a:(calls.append(a) or success()))
    result=run_resolution_cycle(case,build_resolution_context(case,()),fixture_store=store,endpoints=[op],base_url=BASE)
    assert len(calls)==1
    assert result.test_data_preparation.available
    assert result.audit[0].stage=='test_data_preparation'


def test_invalid_data_stops_resolution_before_model_or_browser(monkeypatch):
    case,store,config,op,_=setup()
    calls=[]
    def invalid(*args):
        calls.append(args)
        return {'status':401,'body':{'success':False}}
    monkeypatch.setattr(verification_module,'_once',invalid)
    class ForbiddenLLM:
        def complete(self,prompt):pytest.fail('data blocker must not reach LLM')
    result=run_resolution_loop(case,build_resolution_context(case,()),fixture_store=store,endpoints=[op],
                               base_url=BASE,resolution_llm=ForbiddenLLM(),exploration_llm=ForbiddenLLM(),max_cycles=10)
    assert len(calls)==1 and result.cycle_count==0
    assert result.stop_reason=='NO_MORE_WORK'
    assert not result.executable
    assert any(i.code=='INVALID_TEST_DATA' for i in result.issues)
    assert any(g.code=='INVALID_TEST_DATA' for g in result.executability.gaps)


def test_generation_existing_mapped_case_is_not_executable_with_invalid_data(monkeypatch):
    _,store,config,op,_=setup()
    case=executable_case(); case.traces_to.append('AC-LOGIN')
    requirement={'fixture':'active_user','aliases':['active_user.email','active_user.password'], 'facts':FACTS}
    # Trusted config needs are explicit even for already mapped cases.
    store=FixtureStore(config['fixtures'],config['bindings'],
                       environ={'EMAIL':'private@example.test','PASSWORD':'PRIVATE-PASSWORD'},
                       acquisition={'verification':[rule()],'requirements':{'AC-LOGIN':[requirement]}})
    calls=[]
    monkeypatch.setattr(verification_module,'_once',lambda *a:(calls.append(a) or {'status':401,'body':{'success':False}}))
    result=run_generation([], [case], fixture_store=store,endpoints=[op],base_url=BASE,flows=flows(),max_passes=1)
    assert calls and result.test_data_preparations[0].status==PreparationStatus.INVALID_TEST_DATA
    assert case.id not in {c.id for c in result.executable_cases}
    assert any(i.code=='INVALID_TEST_DATA' for i in result.issues)
    assert case.execution=='auto'
    assert all(c.execution=='manual' for c in result.unresolved_cases)
    assert 'PRIVATE-PASSWORD' not in json.dumps(result.to_dict())


def test_coverage_generated_case_preserves_data_blocker_with_real_resolution_loop(monkeypatch):
    from qctool.coverage_resolution import run_coverage_resolution_pass
    from tests.test_coverage_resolution import report, contexts_for, ui_map
    _,_,config,op,_=setup()
    # The planner's FLOW-1 is the exact trusted requirement binding, no ID special case.
    store=FixtureStore(config['fixtures'],{'FLOW-1':{'email':'active_user.email','correct_password':'active_user.password'}},
                       environ={'EMAIL':'private@example.test','PASSWORD':'PRIVATE-PASSWORD'},
                       acquisition={'verification':[rule()], 'requirements':{'FLOW-1':[{
                           'fixture':'active_user','aliases':['active_user.email','active_user.password'],'facts':FACTS}]}})
    calls=[]
    monkeypatch.setattr(verification_module,'_once',lambda *a:(calls.append(a) or {'status':401,'body':{'success':False}}))
    result=run_coverage_resolution_pass(report(),contexts=contexts_for(report()),requirements=[],ui_map=ui_map(),
                                        fixture_store=store,endpoints=[op],base_url=BASE)
    assert len(calls)==1
    assert not result.accepted_cases and result.unresolved_cases
    candidate=result.case_results[0]
    assert any(g.code=='INVALID_TEST_DATA' for g in candidate.executability.gaps)
    assert candidate.resolution.test_data_preparation.status==PreparationStatus.INVALID_TEST_DATA


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


def test_requirements_registry_roundtrips_json_and_matches_context():
    case,store,config,op,_=setup()
    result=prepare_test_data(case,fixture_store=store,endpoints=[op],base_url=BASE,transport=success)
    context=build_resolution_context(result.case,())
    assert context.testcase['test_data']==result.case.test_data
    assert json.loads(json.dumps(result.case.test_data))==result.case.test_data


def test_resolution_data_blocker_updates_context_snapshot():
    case,store,config,op,_=setup()
    result=run_resolution_loop(case,build_resolution_context(case,()),fixture_store=store,endpoints=[op],
                               data_verification=VerificationResult(()))
    assert result.context.testcase['execution']==result.case.execution=='manual'
    assert result.context.testcase['test_data']==result.case.test_data
    assert result.context.gaps==result.executability.gaps

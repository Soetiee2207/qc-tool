"""Approved fixture creation/verification using fake transports only."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from qctool.config import ConfigError
from qctool.data.fixtures import FixtureStore
from qctool.data.acquisition import acquire_test_data, DataStatus
from qctool.data.preparation import prepare_test_data, PreparationStatus
from qctool.data.provisioning import (
    provision_test_data, ProvisioningStatus, ProvisioningResult, ProvisioningObservation,
)
from tests.test_data_verification import setup as verification_setup, rule as verification_rule, BASE
from tests.test_data_acquisition import FACTS
from tests.test_generation import executable_case


def rule(verification_required=True):
    return {'fixture':'active_user', 'operation_id':'createCustomer',
            'inputs':{'email':{'alias':'active_user.email'},'password':{'alias':'active_user.password'},'role':{'literal':'customer'}},
            'expected':{'status':201,'json':{'$.success':True}},
            'establishes':deepcopy(FACTS), 'verification_required':verification_required,
            'cleanup':{'operation_id':'deleteFixture','source_ref':'test-contract:cleanup'},
            'policy':{'approved':True,'allowed_environment':'test','allowed_base_urls':[BASE],
                      'mutation_type':'create_fixture','external_interaction':False,'whitelisted_operations':[]},
            'source_ref':'reviewed-test-contract:createCustomer'}


def setup(record=None, verify=True, paths=None):
    case,_,config,login,_=verification_setup()
    record=record or rule()
    metadata=paths if paths is not None else [{'fixture':'active_user','operation_id':record['operation_id'],
                                             'provides':deepcopy(FACTS),'external_interaction':False}]
    acquisition={'provisioning':metadata,'provisioning_rules':[record]}
    if verify:acquisition['verification']=[verification_rule()]
    store=FixtureStore(config['fixtures'],config['bindings'],
                       environ={'EMAIL':'private@example.test','PASSWORD':'PRIVATE-PASSWORD'},acquisition=acquisition)
    create=replace(login,operation_id=record['operation_id'],path='/customers',responses={'201':{}},
                    request_body={'type':'object','properties':{'email':{'type':'string'},'password':{'type':'string'},
                                                              'role':{'type':'string','enum':['customer']}}},
                    request_required=['email','password','role'])
    acquired=acquire_test_data(case,fixture_store=store,endpoints=[login,create])
    return case,store,login,create,acquired


def created(*args):return {'status':201,'body':{'success':True,'token':'PRIVATE-RESPONSE-TOKEN'}}
def verified(*args):return {'status':200,'body':{'success':True}}


def prepare(case,store,login,create,**kwargs):
    return prepare_test_data(case,fixture_store=store,endpoints=[login,create],base_url=BASE,
                             allow_provisioning=True,environment='test',provisioning_transport=created,
                             transport=verified,**kwargs)


def test_safe_provision_verify_available_and_every_input_unchanged():
    case,store,login,create,initial=setup()
    assert initial.status==DataStatus.PROVISIONABLE
    before=deepcopy((case,store.to_dict(),login,create))
    calls=[]
    def mutate(*args):calls.append(('provision',args));return created()
    def check(*args):calls.append(('verify',args));return verified()
    result=prepare_test_data(case,fixture_store=store,endpoints=[login,create],base_url=BASE,
                             allow_provisioning=True,environment='test',provisioning_transport=mutate,transport=check)
    assert result.available and result.final.status==DataStatus.AVAILABLE
    assert result.provisioning.status==ProvisioningStatus.PROVISIONED
    assert result.provisioning_attempted
    assert result.provisioning.observation.facts=={}  # No proof from creation alone.
    assert [name for name,_ in calls]==['provision','verify']
    assert [s.stage for s in result.stages]==['acquisition','provisioning','verification','reacquisition']
    assert all(f.status=='VERIFIED' for f in result.final.findings[0].facts)
    assert result.final.to_dict()['provisioning_performed']
    assert result.provisioning.observation.cleanup['operation_id']=='deleteFixture'
    assert before==(case,store.to_dict(),login,create)
    output=json.dumps(result.to_dict())+repr(result)
    assert all(secret not in output for secret in ['PRIVATE-PASSWORD','private@example.test','PRIVATE-RESPONSE-TOKEN'])


def test_provisioning_success_but_verification_401_remains_invalid():
    case,store,login,create,_=setup()
    result=prepare_test_data(case,fixture_store=store,endpoints=[login,create],base_url=BASE,
                             allow_provisioning=True,environment='test',provisioning_transport=created,
                             transport=lambda *a:{'status':401,'body':{'success':False}})
    assert result.provisioning.status==ProvisioningStatus.PROVISIONED
    assert result.status==PreparationStatus.INVALID_TEST_DATA and not result.available
    assert all(f.status=='UNVERIFIED' for f in result.final.findings[0].facts)
    assert result.case.execution=='manual'


def test_success_without_required_verification_is_unverified_not_available():
    case,store,login,create,_=setup(verify=False)
    result=prepare(case,store,login,create)
    assert result.status==PreparationStatus.UNVERIFIED_TEST_DATA
    assert result.provisioning.status==ProvisioningStatus.PROVISIONED
    assert not result.available


def test_explicit_creation_implication_can_establish_only_named_facts():
    record=rule(False);record['establishes']={'account_exists':True}
    case,store,login,create,_=setup(record,verify=False)
    result=prepare(case,store,login,create)
    statuses={f.fact:f.status for f in result.final.findings[0].facts}
    assert statuses['account_exists']=='VERIFIED'
    assert statuses['role']==statuses['account_state']==statuses['password_valid']=='UNVERIFIED'
    assert not result.available
    case,store,login,create,_=setup(rule(False),verify=False)
    result=prepare(case,store,login,create)
    assert result.available and result.verification is None


@pytest.mark.parametrize('change',['unapproved','environment','production','backend','mutation','admin','upload','alias','literal','method','auth'])
def test_unsafe_rules_never_resolve_or_call(change,monkeypatch):
    record=rule()
    if change=='unapproved':record['policy']['approved']=False
    if change=='environment':record['policy']['allowed_environment']='staging'
    if change=='production':record['policy']['allowed_environment']='production'
    if change=='backend':record['policy']['allowed_base_urls']=['https://other.example.test']
    if change=='mutation':record['policy']['mutation_type']='delete_record'
    if change=='alias':record['inputs']['password']['alias']='active_user.unknown'
    if change=='literal':record['inputs']['role']['literal']='admin'
    case,store,login,create,acquired=setup(record)
    if change in {'admin','upload'}:create=replace(create,path='/'+change+'/customers')
    if change=='method':create=replace(create,method='DELETE')
    if change=='auth':create=replace(create,requires_auth=True)
    monkeypatch.setattr(store,'resolve',lambda *a:pytest.fail('unsafe alias resolution'))
    result=provision_test_data(acquired,fixture_store=store,endpoints=[login,create],base_url=BASE,
                               environment='test',enabled=True,transport=lambda *a:pytest.fail('unsafe mutation'))
    assert result.status==ProvisioningStatus.UNSAFE_TO_PROVISION
    assert result.to_dict()['calls']==0


def test_disabled_is_default_even_with_approved_policy():
    case,store,login,create,acquired=setup()
    result=prepare_test_data(case,fixture_store=store,endpoints=[login,create],base_url=BASE,
                             provisioning_transport=lambda *a:pytest.fail('default disabled'),transport=lambda *a:verified())
    assert result.provisioning is None
    assert provision_test_data(acquired,fixture_store=store).observation.code=='PROVISIONING_DISABLED'


@pytest.mark.parametrize('external',['flag','route','operation'])
def test_registration_otp_requires_external_interaction(external):
    record=rule()
    if external=='flag':record['policy']['external_interaction']=True
    if external=='operation':record['operation_id']='registerCustomer'
    case,store,login,create,acquired=setup(record)
    if external=='route':create=replace(create,path='/api/otp/register')
    result=provision_test_data(acquired,fixture_store=store,endpoints=[login,create],base_url=BASE,
                               environment='test',enabled=True,transport=lambda *a:pytest.fail('OTP mutation'))
    assert result.status==ProvisioningStatus.NEEDS_EXTERNAL_INTERACTION
    assert not result.observation.attempted
    result=prepare(case,store,login,create)
    assert result.status==PreparationStatus.NEEDS_EXTERNAL_INTERACTION


def test_ambiguous_matching_rules_never_mutate():
    case,store,login,create,_=setup()
    store.acquisition_config['provisioning_rules'].append(deepcopy(rule()))
    result=prepare_test_data(case,fixture_store=store,endpoints=[login,create],base_url=BASE,
                             allow_provisioning=True,environment='test',provisioning_transport=lambda *a:pytest.fail('ambiguous'))
    assert result.status==PreparationStatus.AMBIGUOUS
    assert result.provisioning.observation.code=='MULTIPLE_RULES'


@pytest.mark.parametrize('response',[{'status':302,'body':{'success':True}}, {'status':500,'body':{}},
                                      {'status':409,'body':{}}, {'status':201,'body':{'success':False}}])
def test_failure_no_retry_or_verification(response):
    case,store,login,create,_=setup()
    calls=[]
    result=prepare_test_data(case,fixture_store=store,endpoints=[login,create],base_url=BASE,
                             allow_provisioning=True,environment='test',
                             provisioning_transport=lambda *a:(calls.append(a) or response),
                             transport=lambda *a:pytest.fail('verify after failed mutation'))
    assert len(calls)==1
    assert result.status==PreparationStatus.PROVISIONING_FAILED
    assert result.provisioning.observation.facts=={}


def test_transport_error_redacted_and_called_once():
    case,store,login,create,_=setup()
    calls=[]
    def error(*args):calls.append(args);raise TimeoutError('PRIVATE-PASSWORD Bearer PRIVATE-TOKEN')
    result=prepare_test_data(case,fixture_store=store,endpoints=[login,create],base_url=BASE,
                             allow_provisioning=True,environment='test',provisioning_transport=error,
                             transport=lambda *a:pytest.fail('failed mutation'))
    assert len(calls)==1
    assert result.provisioning.observation.code=='TRANSPORT_FAILED'
    assert 'PRIVATE-' not in json.dumps(result.to_dict())


def test_stale_fake_receipts_cannot_establish_data_or_trigger_new_calls():
    case,store,login,create,acquired=setup(rule(False))
    receipt=provision_test_data(acquired,fixture_store=store,endpoints=[login,create],base_url=BASE,
                                environment='test',enabled=True,transport=created)
    fake=ProvisioningResult(receipt.observation)
    for bad in [fake,receipt.to_dict(),replace(receipt,observation=replace(receipt.observation,facts={'role':'admin'}))]:
        with pytest.raises(ConfigError):acquire_test_data(acquired.case,fixture_store=store,provisioning=bad)
        result=prepare_test_data(acquired.case,fixture_store=store,endpoints=[login,create],base_url=BASE,
                                 allow_provisioning=True,environment='test',provisioning_receipt=bad,
                                 provisioning_transport=lambda *a:pytest.fail('bad receipt retry'))
        assert not result.available
        assert result.provisioning_reason=='PROVISIONING_RECEIPT_REJECTED'
    store._values['active_user.password']='NEW-PASSWORD'
    with pytest.raises(ConfigError):acquire_test_data(acquired.case,fixture_store=store,provisioning=receipt)


def test_explicit_valid_receipt_reuse_requires_same_environment():
    case,store,login,create,acquired=setup(rule(False))
    receipt=provision_test_data(acquired,fixture_store=store,endpoints=[login,create],base_url=BASE,
                                environment='test',enabled=True,transport=created)
    result=prepare_test_data(acquired.case,fixture_store=store,endpoints=[login,create],base_url=BASE,
                             allow_provisioning=True,environment='test',provisioning_receipt=receipt,
                             provisioning_transport=lambda *a:pytest.fail('receipt reused'))
    assert result.available and result.provisioning_reason=='PROVISIONING_RECEIPT_REUSED'
    assert not result.provisioning_attempted
    result=prepare_test_data(acquired.case,fixture_store=store,allow_provisioning=True,environment='staging',provisioning_receipt=receipt)
    assert not result.available


def test_no_data_and_available_are_unchanged_even_when_enabled():
    case,store,login,create,_=setup()
    plain=executable_case()
    result=prepare_test_data(plain,fixture_store=store,endpoints=[login,create],base_url=BASE,
                             allow_provisioning=True,environment='test',provisioning_transport=lambda *a:pytest.fail('no data'))
    assert result.case==plain and result.initial is None
    case.steps=[Step for Step in plain.steps]
    result=prepare_test_data(case,fixture_store=store,endpoints=[login,create],base_url=BASE,
                             allow_provisioning=True,environment='test',provisioning_transport=lambda *a:pytest.fail('available'))
    assert result.available and result.provisioning is None


def test_admin_creation_only_with_explicit_whitelist_in_test_environment():
    record=rule();record['policy']['whitelisted_operations']=['createCustomer']
    case,store,login,create,_=setup(record)
    create=replace(create,path='/admin/customers')
    acquired=acquire_test_data(case,fixture_store=store,endpoints=[login,create])
    assert acquired.status==DataStatus.PROVISIONABLE
    result=prepare(case,store,login,create)
    assert result.available


def test_receipt_cannot_be_reused_after_contract_or_backend_change():
    case,store,login,create,acquired=setup(rule(False))
    receipt=provision_test_data(acquired,fixture_store=store,endpoints=[login,create],base_url=BASE,
                                environment='test',enabled=True,transport=created)
    assert acquire_test_data(acquired.case,fixture_store=store,endpoints=[login,create],provisioning=receipt).status==DataStatus.AVAILABLE
    with pytest.raises(ConfigError):
        acquire_test_data(acquired.case,fixture_store=store,endpoints=[login,replace(create,path='/other')],provisioning=receipt)
    result=prepare_test_data(acquired.case,fixture_store=store,endpoints=[login,create],base_url='https://other.example.test',
                             allow_provisioning=True,environment='test',provisioning_receipt=receipt)
    assert result.provisioning_reason=='PROVISIONING_RECEIPT_REJECTED'


def test_two_distinct_reviewed_creation_candidates_are_ambiguous():
    case,store,login,create,_=setup()
    other=deepcopy(rule());other['operation_id']='createAlternate'
    store.acquisition_config['provisioning_rules'].append(other)
    store.acquisition_config['provisioning'].append({'fixture':'active_user','operation_id':'createAlternate','provides':FACTS,'external_interaction':False})
    other_op=replace(create,operation_id='createAlternate',path='/alternate-customers')
    result=prepare_test_data(case,fixture_store=store,endpoints=[login,create,other_op],base_url=BASE,
                             allow_provisioning=True,environment='test',provisioning_transport=lambda *a:pytest.fail('ambiguous candidates'))
    assert result.status==PreparationStatus.AMBIGUOUS


def test_timeout_is_bounded_and_never_provisions_with_unbounded_setting():
    case,store,login,create,acquired=setup()
    with pytest.raises(ConfigError):
        provision_test_data(acquired,fixture_store=store,endpoints=[login,create],base_url=BASE,
                            environment='test',enabled=True,timeout=11,transport=lambda *a:pytest.fail('timeout gate'))


def test_conflicting_required_facts_do_not_mutate():
    from qctool.data.acquisition import DataRequirement
    case,store,login,create,_=setup()
    store.acquisition_config['provisioning'].append({'fixture':'active_user','operation_id':'createCustomer',
                                                   'provides':{'account_state':'locked'},'external_interaction':False})
    acquired=acquire_test_data(case,fixture_store=store,endpoints=[login,create],requirements=[
        DataRequirement('active_user',('active_user.email','active_user.password'),{'account_state':'active'}),
        DataRequirement('active_user',('active_user.email','active_user.password'),{'account_state':'locked'})])
    result=provision_test_data(acquired,fixture_store=store,endpoints=[login,create],base_url=BASE,
                               environment='test',enabled=True,transport=lambda *a:pytest.fail('conflicting states'))
    assert result.status==ProvisioningStatus.AMBIGUOUS

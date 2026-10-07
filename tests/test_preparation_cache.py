"""Exact state reuse is runtime-only; no weaker/stale/fabricated proof accepted."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from qctool.config import ConfigError
from qctool.preparation_cache import PreparationCache, preparation_identity
from qctool.test_data_acquisition import acquire_test_data
from qctool.test_data_preparation import prepare_test_data
from qctool.test_data_verification import VerificationResult
from tests.test_test_data_provisioning import setup, created, verified, BASE


def attempt(case,store,ops,cache,calls):
    return prepare_test_data(case,fixture_store=store,endpoints=ops,base_url=BASE,
        environment='test',allow_provisioning=True,preparation_cache=cache,
        provisioning_transport=lambda *a:(calls.append('create') or created()),
        transport=lambda *a:(calls.append('verify') or verified()))


def test_identical_second_case_reuses_provision_and_verification_without_mutation():
    case,store,login,create,_=setup();cache=PreparationCache();calls=[]
    second=deepcopy(case);second.id='TC_OTHER_001'
    snapshot=deepcopy((case,second,store.to_dict(),login,create))
    first=attempt(case,store,[login,create],cache,calls)
    reused=attempt(second,store,[login,create],cache,calls)
    assert first.available and reused.available
    assert calls==['create','verify']
    assert first.preparation_mode=='EXECUTED' and reused.preparation_mode=='REUSED'
    assert first.preparation_identity==reused.preparation_identity
    assert reused.reused_from_testcase==case.id and reused.case.id==second.id
    assert not reused.provisioning_attempted and not reused.verification_attempted
    assert snapshot==(case,second,store.to_dict(),login,create)
    encoded=json.dumps(reused.to_dict())+repr(cache)
    assert all(s not in encoded for s in ('private@example.test','PRIVATE-PASSWORD','PRIVATE-RESPONSE-TOKEN'))
    # Public observations are not sufficient to construct an accepted receipt.
    fake=replace(reused.verification,_receipt=None)
    rejected=prepare_test_data(reused.case,fixture_store=store,endpoints=[login,create],
                              verification=fake,preparation_cache=cache)
    assert not rejected.available and rejected.verification_reason=='RECEIPT_REJECTED'


@pytest.mark.parametrize('change',['fixture','aliases','facts','stronger','assurance','credential','config',
                                   'provision_rule','policy','verification_rule','contract','backend','environment','enabled'])
def test_every_trust_input_changes_identity(change):
    case,store,login,create,acquired=setup()
    ops=[login,create];backend=BASE;env='test';enabled=True
    before=preparation_identity(acquired,store,ops,backend,env,enabled)
    changed=deepcopy(acquired)
    req=changed.findings[0].requirement
    if change=='fixture':req=replace(req,fixture='another_user')
    if change=='aliases':req=replace(req,aliases=req.aliases+('active_user.other',))
    if change=='facts':req=replace(req,facts={**req.facts,'account_state':'locked'})
    if change=='assurance':req=replace(req,require_verified=not req.require_verified)
    if change=='stronger':req=replace(req,facts={**req.facts,'entity_exists':True})
    if change in ('fixture','aliases','facts','stronger','assurance'):
        changed=replace(changed,findings=(replace(changed.findings[0],requirement=req),))
    if change=='credential':store._values['active_user.password']='CHANGED-PRIVATE'
    if change=='config':store._metadata['active_user.email']['source']['name']='OTHER_ENV'
    if change=='provision_rule':store.acquisition_config['provisioning_rules'][0]['expected']['status']=200
    if change=='policy':store.acquisition_config['provisioning_rules'][0]['policy']['approved']=False
    if change=='verification_rule':store.acquisition_config['verification'][0]['expected']['status']=201
    if change=='contract':ops=[replace(login,responses={'401':{}}),create]
    if change=='backend':backend='https://different.test'
    if change=='environment':env='local'
    if change=='enabled':enabled=False
    assert before!=preparation_identity(changed,store,ops,backend,env,enabled)


@pytest.mark.parametrize('tamper',['receipt','observation','container','changed_store','fake_result','timestamp','fake_verification','fake_provisioning'])
def test_stale_or_fake_cache_entry_is_rejected_without_new_calls(tamper,monkeypatch):
    case,store,login,create,_=setup();cache=PreparationCache();calls=[]
    original=attempt(case,store,[login,create],cache,calls)
    entry=cache._entries[original.preparation_identity]
    if tamper=='fake_result':entry.result={'status':'AVAILABLE'}
    if tamper=='receipt':entry.result=replace(entry.result,verification=VerificationResult(entry.result.verification.observations))
    if tamper=='observation':entry.result.verification.observations[0].facts['role']='admin'
    if tamper=='container':cache._entries[original.preparation_identity]={'status':'AVAILABLE'}
    if tamper=='changed_store':entry.store=deepcopy(store)
    if tamper=='timestamp':entry.created=None
    if tamper=='fake_verification':entry.result=replace(entry.result,verification={'status':'VERIFIED'})
    if tamper=='fake_provisioning':entry.result=replace(entry.result,provisioning={'status':'PROVISIONED'})
    second=deepcopy(case);second.id='TC_OTHER_002'
    result=attempt(second,store,[login,create],cache,calls)
    assert not result.available and result.preparation_mode=='REJECTED'
    assert result.blockers[0]['code']=='PREPARATION_RECEIPT_REJECTED'
    assert calls==['create','verify']


@pytest.mark.parametrize('failed_phase',['create','verify'])
def test_failed_proof_is_not_available_but_creation_history_survives(failed_phase):
    case,store,login,create,_=setup();cache=PreparationCache()
    result=prepare_test_data(case,fixture_store=store,endpoints=[login,create],base_url=BASE,
        environment='test',allow_provisioning=True,preparation_cache=cache,
        provisioning_transport=lambda *a:created() if failed_phase=='verify' else {'status':409,'body':{'success':False}},
        transport=lambda *a:{'status':401,'body':{'success':False}})
    assert not result.available
    assert bool(cache._entries) == (failed_phase == "verify")
    if failed_phase == "verify":
        again = attempt(case, store, [login, create], cache, [])
        assert not again.available and not again.verification_attempted and not again.provisioning_attempted


def test_serialized_cache_is_not_trusted():
    case,store,login,create,_=setup()
    with pytest.raises(ConfigError):attempt(case,store,[login,create],{'status':'AVAILABLE'},[])


def test_generation_shares_preparation_between_existing_and_generated_candidates(monkeypatch):
    import qctool.test_data_provisioning as provisioning
    import qctool.test_data_verification as verification
    from qctool.generation import run_generation
    from qctool.ui.crawl import UIMap, PageMap
    from tests.test_test_data_acquisition import GIVENS
    case,store,login,create,_=setup();calls=[]
    case.source_quote=GIVENS[0]
    monkeypatch.setattr(provisioning,'_once',lambda *a:(calls.append('create') or created()))
    monkeypatch.setattr(verification,'_once',lambda *a:(calls.append('verify') or verified()))
    row={'id':'AC-LOGIN','kind':'acceptance_criterion','given':GIVENS[0],
         'when':'Open /login','then':'URL /login'}
    result=run_generation([row],[case],fixture_store=store,endpoints=[login,create],
        ui_map=UIMap(BASE,'recorded',[PageMap(BASE+'/login','Login')]),base_url=BASE,
        allow_provisioning=True,environment='test',max_passes=1)
    assert calls==['create','verify']
    assert result.test_data_preparations[0].preparation_mode=='EXECUTED'
    generated=result.history[0].resolution.case_results[0].resolution.test_data_preparation
    assert generated.preparation_mode=='REUSED' and generated.available
    assert generated.reused_from_testcase==case.id
    assert generated.to_dict()['executed_calls']==0


def test_partial_requirement_proof_is_not_reused_for_stronger_facts():
    case,store,login,create,acquired=setup();cache=PreparationCache();calls=[]
    requirement=acquired.findings[0].requirement
    weak=replace(requirement,facts={'account_exists':True,'password_valid':True})
    store.acquisition_config['verification'][0]['proves']=dict(weak.facts)
    kwargs=dict(fixture_store=store,endpoints=[login,create],base_url=BASE,
                preparation_cache=cache,environment='test',allow_provisioning=False,
                transport=lambda *a:(calls.append('verify') or verified()))
    first=prepare_test_data(case,requirements=[weak],**kwargs)
    assert first.available
    second=deepcopy(case);second.id='TC_STRONGER_001'
    result=prepare_test_data(second,requirements=[requirement],**kwargs)
    assert result.preparation_identity!=first.preparation_identity
    assert result.preparation_mode=='EXECUTED' and not result.available
    assert calls==['verify','verify']


def test_expired_assurance_reverifies_without_recreating_and_preserves_inputs():
    case,store,login,create,_=setup(); calls=[]; now=[0]
    cache=PreparationCache(freshness_seconds=10,clock=lambda:now[0])
    first=attempt(case,store,[login,create],cache,calls)
    second=deepcopy(case);second.id='TC_LATER_001'
    snapshot=deepcopy((case,second,first.to_dict(),store.to_dict(),login,create))
    now[0]=11
    result=attempt(second,store,[login,create],cache,calls)
    assert result.available and result.preparation_mode=='REVERIFIED'
    assert calls==['create','verify','verify']
    assert result.verification_attempted and not result.provisioning_attempted
    assert result.reused_from_testcase==case.id
    assert {'STALE','REUSED','REVERIFIED'} <= {s.status for s in result.stages}
    assert snapshot==(case,second,first.to_dict(),store.to_dict(),login,create)
    now[0]=12
    reused=attempt(second,store,[login,create],cache,calls)
    assert reused.available and reused.preparation_mode=='REUSED'
    assert calls==['create','verify','verify']
    encoded=json.dumps(result.to_dict())
    assert all(s not in encoded for s in ('private@example.test','PRIVATE-PASSWORD','PRIVATE-RESPONSE-TOKEN'))


@pytest.mark.parametrize('verifier',['missing','unsafe','failed','partial'])
def test_expired_proof_without_successful_verifier_never_recreates(verifier):
    case,store,login,create,acquired=setup();calls=[];now=[0]
    if verifier=='missing': store.acquisition_config.pop('verification')
    if verifier=='unsafe': store.acquisition_config['verification'][0]['policy']['approved']=False
    if verifier=='partial': store.acquisition_config['verification'][0]['proves']={'account_exists':True}
    cache=PreparationCache(freshness_seconds=10,clock=lambda:now[0])
    # An authentic earlier receipt with the same current identity. Configuration
    # remains unchanged between admission and expiry (no identity bypass).
    original=prepare_test_data(case,fixture_store=store,endpoints=[login,create],base_url=BASE,
        environment='test',allow_provisioning=True,provisioning_transport=created,
        transport=verified)
    if not original.available:
        # Creation was authentic; absent/unsafe/partial proof cannot be AVAILABLE
        # even before expiry. Retaining this event prevents duplicate creation.
        assert original.provisioning.status.value=='PROVISIONED'
    identity=preparation_identity(acquired,store,[login,create],BASE,'test',True)
    cache._remember(identity,original,store,[login,create])
    now[0]=11
    result=prepare_test_data(case,fixture_store=store,endpoints=[login,create],base_url=BASE,
        environment='test',allow_provisioning=True,preparation_cache=cache,
        provisioning_transport=lambda *a:(calls.append('create') or created()),
        transport=lambda *a:(calls.append('verify') or {'status':401,'body':{'success':False}}))
    assert not result.available and 'create' not in calls
    assert calls==(['verify'] if verifier in ('failed','partial') else [])
    again=attempt(case,store,[login,create],cache,calls)
    assert not again.available and 'create' not in calls


def test_no_verifier_after_expiry_drops_even_creation_fact_proof():
    from tests.test_test_data_provisioning import rule
    case,store,login,create,_=setup(rule(False),verify=False);now=[0];calls=[]
    cache=PreparationCache(freshness_seconds=10,clock=lambda:now[0])
    first=attempt(case,store,[login,create],cache,calls)
    assert first.available and first.verification is None
    now[0]=11
    result=attempt(case,store,[login,create],cache,calls)
    assert not result.available and calls==['create']
    assert result.provisioning.observation.facts=={}
    assert result.preparation_mode=='UNVERIFIED'
    assert 'STALE' in {s.status for s in result.stages}


def test_operator_declarations_do_not_expire_as_live_assurance():
    case,store,login,create,acquired=setup(); now=[0];calls=[]
    # Existing trusted config declarations with no requirement for live proof.
    store.acquisition_config['evidence']=[{
        'fixture':'active_user','facts':dict(acquired.findings[0].requirement.facts),
        'assurance':'DECLARED','source_ref':'reviewed-operator-declaration'}]
    need=replace(acquired.findings[0].requirement,require_verified=False)
    cache=PreparationCache(freshness_seconds=10,clock=lambda:now[0])
    options=dict(fixture_store=store,endpoints=[login,create],requirements=[need],
                 preparation_cache=cache,base_url=BASE,environment='test',
                 transport=lambda *a:calls.append('verify'))
    first=prepare_test_data(case,**options)
    assert first.available and first.verification is None
    now[0]=10000
    result=prepare_test_data(case,**options)
    assert result.available and result.preparation_mode=='REUSED' and not calls


@pytest.mark.parametrize('seconds',[0,-1,True,float('inf'),float('nan'),'300'])
def test_invalid_freshness_rejected(seconds):
    with pytest.raises(ConfigError):PreparationCache(freshness_seconds=seconds)


def test_expired_tampered_receipt_is_rejected_before_reverification():
    case,store,login,create,_=setup();calls=[];now=[0]
    cache=PreparationCache(freshness_seconds=10,clock=lambda:now[0])
    first=attempt(case,store,[login,create],cache,calls)
    entry=cache._entries[first.preparation_identity]
    entry.result=replace(entry.result,verification=replace(entry.result.verification,_receipt=None))
    now[0]=11
    result=attempt(case,store,[login,create],cache,calls)
    assert not result.available and result.preparation_mode=='REJECTED'
    assert calls==['create','verify']


def test_fresh_cache_does_not_import_another_runs_history():
    case,store,login,create,_=setup();calls=[]
    first=attempt(case,store,[login,create],PreparationCache(),calls)
    second=attempt(case,store,[login,create],PreparationCache(),calls)
    assert first.available and second.available
    assert first.preparation_mode==second.preparation_mode=='EXECUTED'
    assert calls==['create','verify','create','verify']

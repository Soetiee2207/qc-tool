"""Deterministic verification policy and runtime receipts; no external calls."""
from copy import deepcopy
from dataclasses import replace, asdict
import json
from pathlib import Path

import pytest

from qctool.config import ConfigError
from qctool.generate.loader import load_endpoints
from qctool.data.acquisition import acquire_test_data, DataRequirement, DataStatus
from qctool.data.verification import (
    verify_test_data, VerificationStatus as Status, VerificationResult,
    MAX_VERIFICATION_CALLS, _once,
)
from tests.test_data_acquisition import inputs, need, FACTS

BASE = 'https://verification.example.test'


def rule(proves=None):
    return {'fixture': 'active_user', 'operation_id': 'login',
            'body_aliases': {'email': 'active_user.email', 'password': 'active_user.password'},
            'expected': {'status': 200, 'json': {'$.success': True}},
            'proves': deepcopy(proves or FACTS),
            'policy': {'approved': True, 'test_data_mutation': False, 'side_effects': ['session_creation']},
            'source_ref': 'operator-policy:login-session-only'}


def setup(record=None, facts=None, requirements=None):
    case, store, config = inputs(facts=facts, acquisition={'verification': [record or rule()]})
    op = replace(load_endpoints(Path('tests/fixtures/smoke/openapi.yaml'))[0][0],
                 servers=[], contract_servers=[BASE])
    acquired = acquire_test_data(case, fixture_store=store, requirements=requirements or [need()])
    return case, store, config, op, acquired


def verify(store, op, acquired, response=None, transport=None):
    return verify_test_data(acquired, fixture_store=store, endpoints=[op], base_url=BASE,
                            transport=transport or (lambda *args: response or {'status': 200, 'body': {'success': True}}))


def test_success_proves_only_explicit_facts_and_acquisition_becomes_available():
    case, store, config, op, acquired = setup()
    result = verify(store, op, acquired)
    assert result.status == Status.VERIFIED
    assert result.to_dict()['calls'] == 1
    after = acquire_test_data(acquired.case, fixture_store=store, verification=result)
    assert after.status == DataStatus.AVAILABLE
    assert all(f.status == 'VERIFIED' for f in after.findings[0].facts)
    assert after.to_dict()['live_verification_performed']
    assert result.observations[0].source['path'] == '/api/auth/login'


def test_partial_proof_does_not_verify_sibling_facts():
    case, store, config, op, acquired = setup(rule({'account_exists': True, 'password_valid': True}))
    result = verify(store, op, acquired)
    after = acquire_test_data(acquired.case, fixture_store=store, verification=result)
    assert after.status == DataStatus.MISSING_TEST_DATA
    assert {f.fact: f.status for f in after.findings[0].facts} == {
        'account_exists': 'VERIFIED', 'password_valid': 'VERIFIED', 'role': 'UNVERIFIED', 'account_state': 'UNVERIFIED'}


@pytest.mark.parametrize('state', ['active', 'locked'])
def test_401_invalid_probe_never_diagnoses_password_or_account_state(state):
    request = DataRequirement('active_user', ('active_user.email', 'active_user.password'),
                              {'account_exists': True, 'account_state': state})
    case, store, config, op, acquired = setup(rule({'account_exists': True}), requirements=[request])
    result = verify(store, op, acquired, {'status': 401, 'body': {'success': False, 'message': 'locked or nonexistent'}})
    assert result.status == Status.INVALID
    assert result.observations[0].facts == {}
    assert 'locked or nonexistent' not in json.dumps(result.to_dict())
    after = acquire_test_data(acquired.case, fixture_store=store, verification=result)
    assert all(f.status == 'UNVERIFIED' for f in after.findings[0].facts)
    assert after.status == DataStatus.MISSING_TEST_DATA


def test_success_flag_false_does_not_prove_negative_facts():
    case, store, config, op, acquired = setup()
    result = verify(store, op, acquired, {'status': 200, 'body': {'success': False}})
    assert result.status == Status.INVALID
    assert result.observations[0].facts == {}


@pytest.mark.parametrize('change', ['unapproved', 'mutation', 'external', 'admin', 'register', 'seed', 'requires_auth', 'wrong_server', 'delete_method'])
def test_unsafe_probe_never_resolves_aliases_or_calls_transport(change, monkeypatch):
    record = rule()
    if change == 'unapproved': record['policy']['approved'] = False
    if change == 'mutation': record['policy']['test_data_mutation'] = True
    if change == 'external': record['policy']['side_effects'] = ['mailbox']
    case, store, config, op, acquired = setup(record)
    if change in {'admin', 'register', 'seed'}: op = replace(op, path='/api/' + change)
    if change == 'requires_auth': op = replace(op, requires_auth=True)
    if change == 'wrong_server': op = replace(op, contract_servers=['https://different.example.test'])
    if change == 'delete_method': op = replace(op, method='DELETE')
    monkeypatch.setattr(store, 'resolve', lambda *a: pytest.fail('unsafe alias resolution'))
    result = verify(store, op, acquired, transport=lambda *a: pytest.fail('unsafe network call'))
    assert result.status == Status.UNSAFE_TO_VERIFY
    assert result.to_dict()['calls'] == 0


def test_readonly_still_needs_explicit_policy_and_no_secret_query():
    record = rule()
    record['body_aliases'] = {}
    record['policy']['side_effects'] = []
    case, store, config, op, acquired = setup(record)
    op = replace(op, method='GET', path='/fixture-state', operation_id='login', request_required=[], request_body=None)
    result = verify(store, op, acquired)
    assert result.status == Status.VERIFIED


def test_conflicting_live_and_declared_facts_are_ambiguous():
    case, store, config, op, acquired = setup(facts={'account_state': 'locked'})
    result = verify(store, op, acquired)
    assert result.status == Status.AMBIGUOUS
    after = acquire_test_data(acquired.case, fixture_store=store, verification=result)
    assert after.status == DataStatus.AMBIGUOUS
    state = next(f for f in after.findings[0].facts if f.fact == 'account_state')
    assert state.status == 'CONFLICT'
    assert {i['value'] for i in state.evidence} == {'locked', 'active'}


@pytest.mark.parametrize('response', [
    {'status': 500, 'body': {'success': True}},
    {'status': 302, 'body': {'success': True}},
    {'status': 200, 'body': {}},
    {'status': 200, 'body': None},
    {'status': 200, 'body': {'success': 1}},
])
def test_inconclusive_or_wrong_type_never_proves_facts(response):
    case, store, config, op, acquired = setup()
    result = verify(store, op, acquired, response)
    assert result.status in {Status.UNVERIFIED, Status.INVALID}
    assert result.observations[0].facts == {}


def test_bounded_transport_failure_no_retry_and_secret_exception_redacted():
    case, store, config, op, acquired = setup()
    calls = []
    def transport(*args):
        calls.append(args)
        raise TimeoutError('PRIVATE-PASSWORD private@example.test Bearer hidden-token')
    result = verify(store, op, acquired, transport=transport)
    assert len(calls) == 1
    assert result.status == Status.UNVERIFIED
    assert result.observations[0].code == 'TRANSPORT_FAILED'
    payload = json.dumps(result.to_dict()) + repr(result)
    assert all(v not in payload for v in ['PRIVATE-PASSWORD', 'private@example.test', 'hidden-token'])


def test_bound_is_enforced_before_network():
    with pytest.raises(ConfigError):
        inputs(acquisition={'verification': [rule()] * (MAX_VERIFICATION_CALLS + 1)})
    case, store, config, op, acquired = setup()
    with pytest.raises(ConfigError):
        verify_test_data(acquired, fixture_store=store, base_url=BASE, timeout=11)


def test_missing_or_ambiguous_operation_never_guessed():
    case, store, config, op, acquired = setup()
    for endpoints, status in [([], Status.UNVERIFIED), ([op, op], Status.AMBIGUOUS)]:
        result = verify_test_data(acquired, fixture_store=store, endpoints=endpoints, base_url=BASE,
                                  transport=lambda *a: pytest.fail('unexpected call'))
        assert result.status == status


def test_forged_dict_tampered_receipt_or_changed_credentials_cannot_prove_facts():
    case, store, config, op, acquired = setup()
    result = verify(store, op, acquired)
    for forged in [result.to_dict(), VerificationResult(result.observations),
                   replace(result, observations=(replace(result.observations[0], facts={'account_state':'locked'}),))]:
        with pytest.raises(ConfigError):
            acquire_test_data(acquired.case, fixture_store=store, verification=forged)
    store._values['active_user.password'] = 'NEW-PRIVATE-PASSWORD'
    with pytest.raises(ConfigError):
        acquire_test_data(acquired.case, fixture_store=store, verification=result)


def test_receipt_cannot_transfer_to_another_case_or_fixture_store():
    case, store, config, op, acquired = setup()
    result = verify(store, op, acquired)
    another = deepcopy(acquired.case); another.id = 'OTHER'
    with pytest.raises(ConfigError):
        acquire_test_data(another, fixture_store=store, verification=result)
    _, other_store, _, _, _ = setup()
    with pytest.raises(ConfigError):
        acquire_test_data(acquired.case, fixture_store=other_store, verification=result)


@pytest.mark.parametrize('index,required,proof,expected_status', [
    ('007', FACTS, FACTS, DataStatus.AVAILABLE),
    ('008', {'account_exists': True, 'account_state': 'active', 'password_valid': False}, {'account_exists': True}, DataStatus.MISSING_TEST_DATA),
    ('009', {'account_exists': True, 'account_state': 'locked'}, {'account_exists': True}, DataStatus.MISSING_TEST_DATA),
])
def test_regression_login_roles_offline_without_id_specific_rules(index, required, proof, expected_status):
    from qctool.data.fixtures import FixtureStore
    fixture = {'007':'active_user', '008':'invalid_user', '009':'locked_user'}[index]
    aliases = (fixture+'.email', fixture+'.password')
    requirement = DataRequirement(fixture, aliases, required)
    case, _, config, op, _ = setup()
    record = rule(proof)
    record.update(fixture=fixture, body_aliases=dict(zip(('email','password'), aliases)))
    store = FixtureStore({fixture:config['fixtures']['active_user']},
                         {'AC-LOGIN':dict(zip(('email','correct_password'),aliases))},
                         environ={'EMAIL':'private@example.test','PASSWORD':'PRIVATE-PASSWORD'},
                         acquisition={'verification':[record]})
    acquired = acquire_test_data(case,fixture_store=store,requirements=[requirement])
    # IDs intentionally generic; semantics and required facts decide the result.
    result = verify(store, op, acquired, {'status': 200 if index == '007' else 401, 'body': {'success': index == '007'}})
    after = acquire_test_data(acquired.case, fixture_store=store, verification=result)
    assert after.status == expected_status


def test_real_transport_one_send_no_retry_and_does_not_export_raw_payload(monkeypatch):
    calls = []
    class Socket:
        def settimeout(self, value): pass
    class Response:
        status = 200
        chunks = [b'{"success":true,"token":"secret-token"}', b'']
        def read1(self, amount): return self.chunks.pop(0)
    class Connection:
        def __init__(self, *a, **kw): self.sock = Socket()
        def request(self, *a, **kw): calls.append(a)
        def getresponse(self): return Response()
        def close(self): calls.append('closed')
    monkeypatch.setattr('http.client.HTTPSConnection', Connection)
    case, store, config, op, acquired = setup()
    result = verify_test_data(acquired, fixture_store=store, endpoints=[op], base_url=BASE)
    assert result.status == Status.VERIFIED
    assert len(calls) == 2 and calls[-1] == 'closed'
    assert 'secret-token' not in json.dumps(result.to_dict())
    def fail(*a, **kw):
        calls.append('failed-send'); raise OSError('private transport error')
    monkeypatch.setattr(Connection, 'request', fail)
    calls.clear()
    result = verify_test_data(acquired, fixture_store=store, endpoints=[op], base_url=BASE)
    assert result.status == Status.UNVERIFIED
    assert calls == ['failed-send', 'closed']


def test_readonly_is_preferred_and_duplicate_implications_do_not_amplify_calls():
    from qctool.data.fixtures import FixtureStore
    login = rule()
    readonly = rule()
    readonly.update(operation_id='fixtureState', body_aliases={})
    readonly['policy']['side_effects'] = []
    case, old_store, config, op, _ = setup()
    store = FixtureStore(config['fixtures'], config['bindings'],
                         environ={'EMAIL': 'private@example.test', 'PASSWORD': 'PRIVATE-PASSWORD'},
                         acquisition={'verification': [login, readonly, readonly]})
    acquired = acquire_test_data(case, fixture_store=store, requirements=[need()])
    state_op = replace(op, method='GET', path='/fixture-state', operation_id='fixtureState',
                       request_body=None, request_required=[])
    calls = []
    def transport(method, url, body, timeout):
        calls.append((method, url, body))
        return {'status': 200, 'body': {'success': True}}
    result = verify_test_data(acquired, fixture_store=store, endpoints=[op, state_op], base_url=BASE, transport=transport)
    assert calls == [('GET', BASE + '/fixture-state', {})]
    assert result.status == Status.VERIFIED
    assert result.to_dict()['calls'] == 1
    assert acquire_test_data(acquired.case, fixture_store=store, verification=result).status == DataStatus.AVAILABLE


def test_partial_fact_proof_can_be_combined_from_two_exact_operations():
    from qctool.data.fixtures import FixtureStore
    login = rule({'account_exists': True, 'password_valid': True})
    state = rule({'account_state': 'active', 'role': 'customer'})
    state.update(operation_id='fixtureState', body_aliases={}, expected={'status': 200, 'json': {'$.role':'customer', '$.account_state':'active'}})
    state['policy']['side_effects'] = []
    case, _, config, op, _ = setup()
    store = FixtureStore(config['fixtures'], config['bindings'], environ={'EMAIL':'private@example.test', 'PASSWORD':'PRIVATE-PASSWORD'}, acquisition={'verification':[login,state]})
    acquired = acquire_test_data(case, fixture_store=store, requirements=[need()])
    state_op = replace(op, method='GET', path='/fixture-state', operation_id='fixtureState', request_body=None, request_required=[])
    calls = []
    def transport(method,url,body,timeout):
        calls.append(method)
        return {'status':200,'body':{'role':'customer','account_state':'active'} if method=='GET' else {'success':True}}
    result = verify_test_data(acquired, fixture_store=store, endpoints=[op,state_op], base_url=BASE, transport=transport)
    assert calls == ['GET', 'POST']
    assert acquire_test_data(acquired.case,fixture_store=store,verification=result).status == DataStatus.AVAILABLE


@pytest.mark.parametrize('base', ['file:///tmp/foo', 'https://user:password@host.test', BASE+'?token=x', BASE+'/../api', BASE+':invalid'])
def test_invalid_origins_never_call_transport(base):
    case, store, config, op, acquired = setup()
    result = verify_test_data(acquired,fixture_store=store,endpoints=[op],base_url=base,transport=lambda *a:pytest.fail('unsafe target'))
    assert result.status == Status.UNSAFE_TO_VERIFY


def test_runtime_cannot_claim_facts_when_store_changed_during_call():
    case,store,config,op,acquired = setup()
    def transport(*args):
        store._values['active_user.password'] = 'DIFFERENT-PASSWORD'
        return {'status':200,'body':{'success':True}}
    result = verify(store,op,acquired,transport=transport)
    assert result.status == Status.UNVERIFIED
    assert result.observations[0].code == 'FIXTURE_CHANGED'
    assert not result.observations[0].facts


def test_config_cannot_embed_literals_or_private_response_predicates():
    for alteration in ('literal','token','extra'):
        record = rule()
        if alteration=='literal': record['body_aliases']['password']='PRIVATE-PASSWORD'
        elif alteration=='token': record['expected']['json']['$.token']='secret'
        else: record['unexpected']='field'
        with pytest.raises(ConfigError):
            setup(record)


@pytest.mark.parametrize('status', [408,429])
def test_transient_http_failure_is_unverified_and_not_retried(status):
    case,store,config,op,acquired = setup()
    calls=[]
    def transport(*args):
        calls.append(args)
        return {'status':status,'body':{'success':False}}
    result=verify(store,op,acquired,transport=transport)
    assert result.status==Status.UNVERIFIED
    assert len(calls)==1


def test_creation_contract_and_camelcase_provisioning_operation_are_denied():
    case,store,config,op,acquired = setup()
    result=verify(store,replace(op,responses={'200':{},'201':{}}),acquired,
                  transport=lambda *a:pytest.fail('creation endpoint'))
    assert result.status==Status.UNSAFE_TO_VERIFY
    record=rule(); record['operation_id']='createUser'
    case,store,config,op,acquired=setup(record)
    result=verify(store,replace(op,operation_id='createUser',path='/users'),acquired,
                  transport=lambda *a:pytest.fail('creation operation'))
    assert result.status==Status.UNSAFE_TO_VERIFY

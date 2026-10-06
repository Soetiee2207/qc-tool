"""Trusted public fixture facts: no inference from credentials or model metadata."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from qctool.apply_resolution import apply_validated_resolution
from qctool.config import ConfigError
from qctool.executability import analyze_executability
from qctool.llm_resolution import AtomicProposal, EvidenceReference, ProposedChange, ResolutionProposal, build_resolution_prompt
from qctool.proposal_validation import validate_resolution_proposal
from qctool.resolution_context import build_resolution_context
from qctool.step_expansion import expected_expansion
from qctool.test_fixtures import FACT_REGISTRY, FixtureStore, load_fixture_store
from qctool.testcase import Step, StepKind
from tests.test_step_expansion import fixture, BASE, ACTION, HAPPY

GIVEN = ('Phiên anonymous ở /login; tài khoản customer đang hoạt động '
         'và mật khẩu đúng do người vận hành cung cấp')
SECRETS = {'EMAIL': 'fact-fixture@example.test', 'PASSWORD': 'FICTIONAL_FACT_SECRET_123'}


def inputs(facts=None, *, missing_credentials=False, url='/login', text=GIVEN):
    definitions = {'active_user': {'email': {'env': 'EMAIL'}, 'password': {'env': 'PASSWORD'}}}
    if facts is not None:
        definitions['active_user']['facts'] = facts
    store = FixtureStore(definitions, {'FR-LOGIN': {'email': 'active_user.email',
                                                 'correct_password': 'active_user.password'}},
                         environ={} if missing_credentials else SECRETS)
    case, context = fixture(data={}, expected=HAPPY)
    case.steps[0] = Step(1, StepKind.GIVEN, 'perform.unmapped', {'description': text})
    bound = store.bind(case)
    context = replace(context, testcase={**context.testcase, 'steps': [s.to_dict() for s in bound.steps],
                                        'test_data': deepcopy(bound.test_data)},
                      gaps=analyze_executability(bound).gaps)
    page = EvidenceReference('ui-map', {'page': BASE + '/login'})
    origin = EvidenceReference('testcase-step', {'step_seq': 1})
    change = ProposedChange(1, 'perform.unmapped', ('UNMAPPED_ACTION',), '', {},
                            'Preserve source setup; account facts come from trusted config',
                            (origin, page), (
                                AtomicProposal('ui.session', {'mode': 'anonymous'}, (origin,)),
                                AtomicProposal('ui.goto', {'url': url}, (page,))))
    return bound, context, store, change


def validate(case, context, store, change):
    return validate_resolution_proposal(ResolutionProposal(case.id, (change,), ()), context, case,
                                        fixture_store=store)


@pytest.mark.parametrize('url', ['/login', BASE + '/login'])
def test_active_customer_proves_given_and_applies_detached_expansion(url):
    case, context, store, change = inputs({'role': 'customer', 'account_state': 'active'}, url=url)
    snapshot = deepcopy((case, context, store.to_dict(), change))
    result = validate(case, context, store, change)
    assert result.valid_changes == (change,)
    assert not result.issues
    applied = apply_validated_resolution(case, result)
    assert not applied.issues
    assert applied.case.steps[0].action == 'ui.session'
    assert applied.case.steps[1].action == 'ui.goto'
    assert [s.seq for s in applied.case.steps] == [1, 2, 3, 4]
    assert [s.action for s in applied.case.steps[2:]] == ['perform.unmapped', 'assert.unmapped']
    assert applied.case.preconditions == case.preconditions
    assert applied.case.test_data[FACT_REGISTRY] == case.test_data[FACT_REGISTRY]
    assert GIVEN in applied.case.steps[0].note
    assert not applied.after.executable
    assert (case, context, store.to_dict(), change) == snapshot


@pytest.mark.parametrize('facts', [None, {}, {'role': 'customer'}, {'account_state': 'active'},
    {'role': 'staff', 'account_state': 'active'}, {'role': 'customer', 'account_state': 'locked'},
    {'role': 'customer', 'account_state': 'inactive'}])
def test_missing_or_conflicting_facts_do_not_prove_account_state(facts):
    case, context, store, change = inputs(facts)
    result = validate(case, context, store, change)
    assert not result.valid_changes
    assert any(i.code == 'EXPANSION_SEMANTICS_UNPROVEN' for i in result.issues)
    assert apply_validated_resolution(case, result).case == case


def test_metadata_without_private_trusted_store_is_not_proof():
    case, context, _, change = inputs({'role': 'customer', 'account_state': 'active'})
    assert not validate(case, context, None, change).valid_changes


def test_forged_fact_packet_rejected_against_config():
    case, context, store, change = inputs({'role': 'staff', 'account_state': 'locked'})
    case.test_data[FACT_REGISTRY]['active_user']['values'] = {'role': 'customer', 'account_state': 'active'}
    context = replace(context, testcase={**context.testcase, 'test_data': deepcopy(case.test_data)})
    assert not validate(case, context, store, change).valid_changes


def test_missing_credentials_do_not_prove_operator_provided_password():
    case, context, store, change = inputs({'role': 'customer', 'account_state': 'active'}, missing_credentials=True)
    assert not validate(case, context, store, change).valid_changes
    assert any(g.code == 'MISSING_FIXTURE' for g in analyze_executability(case).gaps)


@pytest.mark.parametrize('text', [GIVEN + '; thêm quyền admin', GIVEN.replace('customer', 'staff'),
                                GIVEN.replace('anonymous', 'authenticated')])
def test_unknown_extra_clause_or_different_precondition_not_discarded(text):
    case, context, store, change = inputs({'role': 'customer', 'account_state': 'active'}, text=text)
    assert not validate(case, context, store, change).valid_changes


@pytest.mark.parametrize('url', ['/admin', 'https://foreign.test/login'])
def test_given_route_still_requires_exact_source_and_context_grounding(url):
    case, context, store, change = inputs({'role': 'customer', 'account_state': 'active'}, url=url)
    assert not validate(case, context, store, change).valid_changes


def test_public_facts_reach_context_with_provenance_but_secrets_do_not():
    case, context, store, _ = inputs({'role': 'customer', 'account_state': 'active'})
    rebuilt = build_resolution_context(case, analyze_executability(case).gaps)
    record = rebuilt.testcase['test_data'][FACT_REGISTRY]['active_user']
    assert record == {'values': {'role': 'customer', 'account_state': 'active'},
                      'source': {'type': 'config', 'fixture': 'active_user', 'field': 'facts'}}
    payload = json.dumps({'case': case.to_dict(), 'context': rebuilt.to_dict(), 'store': store.to_dict()})
    prompt = build_resolution_prompt(context)
    for secret in SECRETS.values():
        assert secret not in payload and secret not in prompt and secret not in repr(store)
    assert 'customer' in prompt and 'account_state' in prompt


@pytest.mark.parametrize('facts', [{'password': 'secret'}, {'role': 'FICTIONAL_SECRET'},
                                 {'account_state': {'env': 'PASSWORD'}}, {'role': ['customer']}])
def test_fact_channel_rejects_secrets_unknown_names_and_env_references(facts):
    with pytest.raises(ConfigError) as caught:
        inputs(facts)
    assert 'FICTIONAL_SECRET' not in str(caught.value)


def test_facts_for_unbound_account_are_not_selected_and_mixed_accounts_not_proven():
    case, context, _, change = inputs({'role': 'customer', 'account_state': 'active'})
    store = FixtureStore({'active_user': {'email': {'env': 'EMAIL'}, 'password': {'env': 'PASSWORD'},
                                          'facts': {'role': 'customer', 'account_state': 'active'}},
                          'other': {'password': {'env': 'PASSWORD'}, 'facts': {'role': 'staff'}}}, environ=SECRETS)
    bound = store.bind(case)
    assert set(bound.test_data[FACT_REGISTRY]) == {'active_user'}
    bound.test_data['correct_password'] = 'other.password'
    bound = store.bind(bound)
    assert not store.proves_account_precondition(bound.test_data, role='customer', account_state='active')


def test_facts_do_not_change_when_or_then_expansion_rules():
    case, _, store, _ = inputs({'role': 'customer', 'account_state': 'active'})
    for step in case.steps[1:]:
        assert expected_expansion(step, case.test_data, fixture_store=store) == expected_expansion(step, case.test_data)
    assert case.steps[1].args['description'] == ACTION
    assert expected_expansion(case.steps[2], case.test_data, fixture_store=store) is None


def test_config_loader_and_fact_definition_inputs_unchanged():
    raw = {'fixtures': {'active_user': {'facts': {'role': 'customer', 'account_state': 'active'}}}}
    before = deepcopy(raw)
    store = load_fixture_store(raw)
    assert store.to_dict()['facts']['active_user']['values']['role'] == 'customer'
    assert raw == before


def test_fact_value_equal_to_credential_is_rejected_without_echo():
    with pytest.raises(ConfigError, match='must not contain credential values'):
        FixtureStore({'active_user': {'facts': {'role': 'customer'},
                                      'password': {'env': 'PASSWORD'}}}, environ={'PASSWORD': 'customer'})


@pytest.mark.parametrize('name', ['bad-name', 123, 'Bearer secret'])
def test_facts_only_fixture_name_is_validated(name):
    with pytest.raises(ConfigError, match='lowercase identifier'):
        FixtureStore({name: {'facts': {'role': 'customer'}}})

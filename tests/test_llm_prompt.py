"""Prompt views cannot replace the full trusted validator context."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from qctool.executability import analyze_executability
from qctool.llm_prompt import (PromptBudgetError, describe_prompt, select_prompt_context,
                               current_prompt_composition)
from qctool.llm_resolution import build_resolution_prompt, propose_resolution
from qctool.llm_exploration import build_exploration_prompt
from qctool.outcome_grounding import outcome_state
from qctool.proposal_validation import validate_resolution_proposal
from qctool.llm_resolution import ResolutionProposal
from qctool.resolution_cycle import run_resolution_cycle
from qctool.test_fixtures import FixtureStore
from tests.test_resolution_cycle import _inputs, FakeLLM, _proposal, BASE
from tests.test_outcome_grounding import api_inputs, workflow_inputs


def materialized_observations(view):
    result = deepcopy(view['observations'])
    for state in result['page_states']:
        if 'action_chain' in state:
            state.update(deepcopy(result['action_chains'][state.pop('action_chain')]))
    return result


def test_irrelevant_api_pages_and_controls_excluded():
    case, context, _, operation = api_inputs()
    original = deepcopy(context)
    context.interface_contract['api_operations'].append({**operation, 'path': '/unrelated', 'operation_id': 'unrelated'})
    context.observations['ui_pages'].append({'url': BASE+'/admin', 'elements': [{'test_id': 'admin', 'name': 'Admin'}]})
    context.observations['ui_pages'][0]['elements'].append({'test_id': 'advertisement', 'name': 'Advertisement', 'role': 'link'})
    snapshot = deepcopy(context)
    view = select_prompt_context(context)
    assert view['interface_contract']['api_operations'] == [operation]
    assert [p['url'] for p in view['observations']['ui_pages']] == [original.observations['ui_pages'][0]['url']]
    assert [e['test_id'] for e in view['observations']['ui_pages'][0]['elements']] == ['submit-control']
    assert context == snapshot
    assert case.steps[-1].args['expected'] in json.dumps(view, ensure_ascii=False)


def test_required_source_and_expected_negative_outcome_remain_verbatim():
    case, context, _, _ = api_inputs()
    view = select_prompt_context(context)
    assert view['specification']['requirements'] == context.specification['requirements']
    assert view['testcase']['steps'][-1]['args'] == case.steps[-1].args
    assert '401' in build_resolution_prompt(context)
    assert 'success=false' in build_resolution_prompt(context)
    assert [s['note'] for s in view['testcase']['steps']] == [s.note for s in case.steps]


def test_conflicting_relevant_api_and_locator_evidence_not_hidden():
    _, context, _, op = api_inputs()
    conflicting = {**op, 'response_codes': ['500']}
    context.interface_contract['api_operations'].append(conflicting)
    element = context.observations['ui_pages'][0]['elements'][0]
    context.observations['ui_pages'][0]['elements'].append({**element, 'name': 'Different action', 'disabled': True})
    view = select_prompt_context(context)
    assert view['interface_contract']['api_operations'] == [op, conflicting]
    assert len(view['observations']['ui_pages'][0]['elements']) == 2
    assert view['observations']['ui_pages'][0]['elements'][1]['disabled'] is True


def test_exact_evidence_dedup_never_merges_distinct_states():
    _, context, _ = workflow_inputs()
    context.observations['ui_pages'].append(deepcopy(context.observations['ui_pages'][0]))
    view = select_prompt_context(context)
    assert len(view['observations']['ui_pages']) == 2
    assert len(view['observations']['page_states']) == 4
    assert len(view['observations']['action_chains']) == 1


def test_v3_current_ancestry_remains_sufficient_but_obsolete_history_excluded():
    case, context, change = workflow_inputs()
    obsolete = deepcopy(context.observations['page_states'][0])
    obsolete['state_id'] = 'unrelated-old-state'
    obsolete['page']['url'] = BASE+'/unrelated'
    context.observations['page_states'].insert(0, obsolete)
    original = deepcopy(context)
    view = select_prompt_context(context)
    assert [s['state_id'] for s in view['observations']['page_states']] == ['state-0', 'state-1', 'state-2', 'state-3']
    packet = replace(context, observations=materialized_observations(view))
    assert outcome_state(case.steps[-1], case, packet)['state_id'] == 'state-3'
    # Actual validation still receives the original context, not the view.
    result = validate_resolution_proposal(ResolutionProposal(case.id, (change,), ()), context, case)
    assert result.valid_changes == (change,)
    assert context == original


def test_conflicting_current_state_variants_and_ancestors_retained():
    _, context, _ = workflow_inputs()
    variant = deepcopy(context.observations['page_states'][-1])
    variant['valid'] = False
    context.observations['page_states'].append(variant)
    view = select_prompt_context(context)
    assert len([s for s in view['observations']['page_states'] if s['state_id']=='state-3']) == 2
    assert any(not s['valid'] for s in view['observations']['page_states'])


def test_unknown_source_cannot_filter_away_potential_controls():
    _, context, _ = _inputs()
    context.testcase['steps'][1]['args']['description'] = 'An explicitly documented novel business interaction'
    assert select_prompt_context(context)['observations']['ui_pages'][0]['elements'] == context.observations['ui_pages'][0]['elements']


def test_fixtures_stay_aliases_public_facts_and_secrets_never_sent():
    case, context, _ = _inputs()
    store = FixtureStore({'operator': {'password': {'env': 'PRIVATE_PASSWORD'},
        'facts': {'role': 'customer', 'account_state': 'active'}}},
        {case.id: {'password': 'operator.password'}}, environ={'PRIVATE_PASSWORD': 'SECRET-NOT-FOR-MODEL'})
    bound = store.bind(case)
    context = replace(context, testcase={**context.testcase, 'test_data': bound.test_data})
    before = deepcopy(context)
    prompt = build_resolution_prompt(context)
    assert 'SECRET-NOT-FOR-MODEL' not in prompt
    assert 'operator.password' in prompt and 'active' in prompt
    assert context == before


def test_prompt_selection_and_accounting_are_stable_and_content_free():
    _, context, _ = _inputs()
    prompt = build_resolution_prompt(context)
    assert prompt == build_resolution_prompt(deepcopy(context))
    counts = describe_prompt(prompt)
    assert sum(v['bytes'] for v in counts['components'].values()) == len(prompt.encode('utf-8'))
    assert counts['estimated_prompt_tokens'] == (len(prompt.encode('utf-8'))+3)//4
    serialized = json.dumps(counts)
    assert 'btn-login' not in serialized and 'TC_LOGIN_001' not in serialized
    assert all(v['estimated_tokens'] >= 0 for v in counts['components'].values())


@pytest.mark.parametrize('builder', [build_resolution_prompt, build_exploration_prompt])
def test_budget_blocks_required_evidence_without_dropping_source(builder):
    _, context, _ = _inputs()
    before = deepcopy(context)
    with pytest.raises(PromptBudgetError):
        builder(context, max_prompt_tokens=1)
    assert context == before


def test_budget_failure_is_audited_and_never_calls_adapter():
    case, context, _ = _inputs()
    context.specification['requirements'] = [{'id': case.traces_to[0], 'statement': 'SOURCE ' * 16000}]
    adapter = FakeLLM(AssertionError('No request when authority cannot fit'))
    result = run_resolution_cycle(case, context, resolution_llm=adapter, base_url=BASE)
    assert not adapter.prompts and result.case == case
    assert any(i.code == 'PROMPT_BUDGET_EXCEEDED' for i in result.issues)
    assert result.context.specification == context.specification


def test_call_scope_accounts_prompt_without_retaining_it():
    case, context, _ = _inputs()
    class InspectAdapter:
        def complete(self, prompt):
            self.counts = current_prompt_composition()
            assert self.counts == describe_prompt(prompt)
            return _proposal()
    adapter = InspectAdapter()
    proposal = propose_resolution(context, adapter)
    assert proposal.testcase_id == case.id
    assert current_prompt_composition() is None
    assert 'btn-login' not in json.dumps(adapter.counts)


def test_different_original_source_authority_is_not_discarded_with_audit():
    case, context, _ = _inputs()
    origin = {'source_step': case.steps[1].to_dict(), 'source_quote': 'Explicit second outcome must also hold',
              'source_ref': 'source:prior', 'traces_to': ['FR-ORIGINAL'], 'reason': 'AUDIT-ONLY-REASON'}
    step = context.testcase['steps'][1]
    step['note'] = step.get('note', '') + '\n[resolution-expansion] ' + json.dumps(origin)
    prompt = build_resolution_prompt(context)
    assert 'Explicit second outcome must also hold' in prompt
    assert 'source:prior' in prompt and 'FR-ORIGINAL' in prompt
    assert 'AUDIT-ONLY-REASON' not in prompt


def test_provider_records_actual_usage_and_only_composition_counts(monkeypatch):
    from tests.test_llm_provider import client, http, envelope, KEY
    from qctool.llm_provider import capture_provider_attempts
    _, context, _ = _inputs()
    body = envelope(_proposal())
    body['usage'] = {'prompt_tokens': 123, 'completion_tokens': 17, 'total_tokens': 140,
                     'untrusted_detail': 'PRIVATE-RESPONSE-SECRET'}
    http(monkeypatch, body)
    with capture_provider_attempts() as records:
        propose_resolution(context, client())
    counts = records[0]['prompt_composition']
    assert counts['actual_prompt_tokens'] == 123 and counts['actual_completion_tokens'] == 17
    assert counts['estimated_prompt_tokens'] > 0
    audit = json.dumps(records)
    assert KEY not in audit and 'PRIVATE-RESPONSE-SECRET' not in audit
    assert 'btn-login' not in audit and 'User submits' not in audit


def test_live_bad_envelopes_are_not_corrected():
    from qctool.llm_resolution import LLMResponseError, parse_resolution_proposal
    from qctool.llm_exploration import parse_exploration_plan
    raw = json.loads(_proposal())
    change = raw['changes'][0]
    change['proposed']['reason'] = change.pop('reason')
    with pytest.raises(LLMResponseError):
        parse_resolution_proposal(json.dumps(raw))
    with pytest.raises(LLMResponseError):
        parse_exploration_plan('{"requests":[]}')


def test_comparison_never_exports_historical_prompt_completion_or_secrets():
    from scripts.compare_llm_usage import summarize_calls
    packet = {'calls': [{'stage': 'resolution', 'prompt': 'PRIVATE-HISTORICAL-PROMPT',
                        'response': 'PRIVATE-COMPLETION',
                        'usage': {'prompt_tokens': 9, 'completion_tokens': 2, 'total_tokens': 11}}]}
    result = summarize_calls(packet)
    assert result['usage'] == {'prompt_tokens': 9, 'completion_tokens': 2, 'total_tokens': 11}
    assert 'PRIVATE' not in json.dumps(result)
    assert result['calls'][0]['components']['protocol_schema']['bytes'] == len(packet['calls'][0]['prompt'])

"""Only prefix organization/telemetry changes; no response cache or network."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from qctool.llm_prompt import DYNAMIC_MARKER, PROTOCOL_VERSIONS, prompt_cache_diagnostics
from qctool.llm_resolution import build_resolution_prompt
from qctool.llm_exploration import build_exploration_prompt
from qctool.llm_provider import capture_provider_attempts
from tests.test_resolution_cycle import _inputs
from tests.test_outcome_grounding import api_inputs, workflow_inputs
from tests.test_llm_provider import client, http, envelope, KEY


def prefix(prompt):
    return prompt.split(DYNAMIC_MARKER+'\n\n', 1)[0]


@pytest.mark.parametrize('builder', [build_resolution_prompt, build_exploration_prompt])
def test_stable_same_project_different_case_and_cycle(builder):
    _, context, _ = _inputs()
    original = deepcopy(context)
    a = builder(context)
    other = deepcopy(context)
    other.testcase['id'] = 'TC_ANOTHER_009'
    other.testcase['title'] = 'Another testcase'
    other.testcase['steps'][1]['note'] = 'Different source action'
    b = builder(other)
    assert prefix(a) == prefix(b) and a != b
    changed = deepcopy(context)
    changed.observations['ui_pages'][0]['evidence'] = {'observed_at':'2030-01-01', 'audit_id':'different'}
    c = builder(changed)
    assert prefix(a) == prefix(c) and a != c
    assert prompt_cache_diagnostics(a)['dynamic_tail_fingerprint'] != prompt_cache_diagnostics(c)['dynamic_tail_fingerprint']
    assert builder(deepcopy(context)) == a
    assert context == original


@pytest.mark.parametrize('builder', [build_resolution_prompt, build_exploration_prompt])
def test_authority_provenance_volatility_moves_to_tail_not_removed(builder):
    _, context, _, _ = api_inputs()
    a = builder(context)
    other = deepcopy(context)
    other.specification['requirements'][0].update(observed_at='2099', audit_id='new-audit', source={'file':'source.md','line':77})
    b = builder(other)
    assert prefix(a) == prefix(b)
    assert '2099' not in prefix(b) and 'new-audit' not in prefix(b)
    assert '2099' in b and 'new-audit' in b and 'source.md' in b


@pytest.mark.parametrize('builder', [build_resolution_prompt, build_exploration_prompt])
def test_source_contract_change_invalidates_project_not_family_protocol(builder):
    _, context, _, _ = api_inputs()
    a = builder(context)
    requirement = deepcopy(context)
    requirement.specification['requirements'][0]['statement'] = 'Different explicit obligation'
    assert prefix(a) != prefix(builder(requirement))
    api = deepcopy(context)
    api.interface_contract['api_operations'][0]['response_codes'] = ['999']
    assert prefix(a) != prefix(builder(api))
    assert prompt_cache_diagnostics(a)['protocol_fingerprint'] == prompt_cache_diagnostics(builder(api))['protocol_fingerprint']


def test_origin_bindings_are_dynamic_but_still_exact_available_evidence():
    _, context, _, _ = api_inputs()
    a = build_resolution_prompt(context)
    other = deepcopy(context)
    other.interface_contract['api_operations'][0]['servers'] = ['http://127.0.0.1:59999']
    b = build_resolution_prompt(other)
    assert prefix(a) == prefix(b)
    assert 'http://127.0.0.1:59999' in b


def test_families_separate_and_version_invalidates_protocol(monkeypatch):
    _, context, _ = _inputs()
    r = build_resolution_prompt(context)
    e = build_exploration_prompt(context)
    rd, ed = prompt_cache_diagnostics(r), prompt_cache_diagnostics(e)
    assert rd['cache_family'] == 'resolution' and ed['cache_family'] == 'exploration'
    assert rd['stable_prefix_fingerprint'] != ed['stable_prefix_fingerprint']
    monkeypatch.setitem(PROTOCOL_VERSIONS, 'resolution', '3-test')
    assert prefix(r) != prefix(build_resolution_prompt(context))
    assert prefix(e) == prefix(build_exploration_prompt(context))
    assert rd['stable_prefix_fingerprint'] not in r  # diagnostic hashes not model input


def test_map_order_canonical_but_source_steps_actions_state_chains_preserved():
    _, context, _ = workflow_inputs()
    a = build_resolution_prompt(context)
    other = deepcopy(context)
    other = replace(other, testcase=dict(reversed(list(other.testcase.items()))))
    assert build_resolution_prompt(other) == a
    case_section = json.loads(a.split('TESTCASE\n',1)[1].split('\n\n',1)[0])
    assert [s['seq'] for s in case_section['steps']] == [s['seq'] for s in context.testcase['steps']]
    obs = json.loads(a.split('CURRENT UI OBSERVATION — UI MAP\n',1)[1].split('\n\n',1)[0])
    assert [s['state_id'] for s in obs['page_states']] == [s['state_id'] for s in context.observations['page_states']]
    assert obs['action_chains'][0]['validated_actions'] == context.observations['page_states'][0]['validated_actions']
    other.testcase['steps'].reverse()
    assert prefix(build_resolution_prompt(other)) == prefix(a)
    assert build_resolution_prompt(other) != a


@pytest.mark.parametrize('usage,expected', [
    ({'prompt_tokens':100,'prompt_cache_hit_tokens':80,'prompt_cache_miss_tokens':20,'completion_tokens':5}, .8),
    ({'prompt_tokens':100,'completion_tokens':5}, None),
    ({'prompt_tokens':100,'prompt_cache_hit_tokens':True,'prompt_cache_miss_tokens':'20'}, None),
    ({'prompt_tokens':100,'prompt_cache_hit_tokens':150,'prompt_cache_miss_tokens':0}, None),
    ({'prompt_tokens':100,'prompt_cache_hit_tokens':80,'prompt_cache_miss_tokens':30}, None),
])
def test_cache_usage_whitelist_safe_present_absent_or_malformed(monkeypatch,usage,expected):
    payload = envelope('{}')
    payload['usage'] = {**usage, 'private_response':KEY}
    http(monkeypatch,payload)
    _, context, _ = _inputs()
    prompt = build_resolution_prompt(context)
    with capture_provider_attempts() as records:
        assert client().complete(prompt) == '{}'
    record = records[0]
    assert record['cache_usage']['hit_ratio'] == expected
    assert record['cache_family'] == record['capability'] == 'resolution'
    assert KEY not in json.dumps(record) and prompt not in json.dumps(record)
    assert 'private_response' not in record['usage']


def test_cache_report_weighted_ratios_without_content_or_fake_missing_counts():
    from scripts.report_cache_usage import summarize_cache
    packet = {'calls':[
        {'stage':'resolution','prompt':'PRIVATE PROMPT','response':KEY,'usage':{
            'prompt_tokens':100,'prompt_cache_hit_tokens':80,'prompt_cache_miss_tokens':20,'completion_tokens':10}},
        {'stage':'exploration','usage':{
            'prompt_tokens':300,'prompt_cache_hit_tokens':60,'prompt_cache_miss_tokens':240,'completion_tokens':20}}]}
    report = summarize_cache(packet)
    assert report['overall']['hit_ratio'] == 140/400
    assert report['resolution']['hit_ratio'] == .8 and report['exploration']['hit_ratio'] == .2
    assert 'PRIVATE PROMPT' not in json.dumps(report) and KEY not in json.dumps(report)
    packet['calls'][1]['usage'].pop('prompt_cache_hit_tokens')
    report = summarize_cache(packet)
    assert report['overall']['hit_tokens'] is None and report['overall']['hit_ratio'] is None

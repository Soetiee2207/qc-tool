"""Operation/state-specific source proofs, with deliberately corrupted evidence."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from qctool.executability import analyze_executability
from qctool.llm_resolution import AtomicProposal, EvidenceReference, ProposedChange, ResolutionProposal
from qctool.outcome_grounding import outcome_state, response_binding
from qctool.proposal_validation import validate_resolution_proposal
from qctool.resolution_context import build_resolution_context
from qctool.resolve import resolve_deterministically
from qctool.testcase import Step, StepKind, TestCase
from qctool.ui.crawl import Element, PageMap, UIMap

BASE = 'https://unit.example.test'


def note(req, field):
    return '[source-clause] ' + json.dumps({'requirement_id': req['id'], 'field': field, 'text': req[field]})


def api_inputs():
    req = {'id': 'AC-REJECT', 'when': 'Click Login',
           'then': 'POST /api/session-check trả 401 với success=false; URL vẫn ở /entry-point'}
    capture = {'method': 'POST', 'path': '/api/session-check', 'origin': BASE,
               'save_as': 'attempt', 'timeout_ms': 1000}
    case = TestCase('TC_GENERIC_010', 'UNIT', 'Negative response', 'Source contract',
        traces_to=[req['id']], source_quote=req['then'], execution='manual', steps=[
            Step(1, StepKind.GIVEN, 'ui.goto', {'url': '/entry-point'}),
            Step(2, StepKind.WHEN, 'ui.click', {'target': 'submit-control', 'capture_response': capture}, note(req, 'when')),
            Step(3, StepKind.THEN, 'assert.unmapped', {'expected': req['then']}, note(req, 'then'))])
    ui = UIMap(BASE, 'offline', [PageMap(BASE+'/entry-point', 'Entry', elements=[
        Element('submit', 'button', 'Login', 'button', test_id='submit-control')])])
    context = build_resolution_context(case, analyze_executability(case).gaps, requirements=[req], ui_map=ui)
    operation = {'method': 'POST', 'path': '/api/session-check', 'operation_id': 'checkSession',
                 'servers': [BASE], 'response_codes': ['200', '401']}
    context.interface_contract['api_operations'] = [operation]
    requirement = EvidenceReference('requirement', {'id': req['id']})
    api = EvidenceReference('openapi', {'operation_id': operation['operation_id']})
    page = EvidenceReference('ui-map', {'page': BASE+'/entry-point'})
    # Real failure shape: contract at parent/status level, requirement at JSON atom.
    change = ProposedChange(3, 'assert.unmapped', ('UNMAPPED_ACTION',), '', {}, 'Untrusted reason',
        (requirement, api), (
            AtomicProposal('assert.http_status', {'expected': 401, 'source': 'attempt'}, (api,)),
            AtomicProposal('assert.json_field', {'path': '$.success', 'expected': False, 'source': 'attempt'}, (requirement,)),
            AtomicProposal('assert.url_matches', {'pattern': '/entry\\-point$'}, (page,))))
    return case, context, change, operation


def test_parent_contract_grounds_body_only_with_exact_response_writer():
    case, context, change, _ = api_inputs()
    before = deepcopy((case, context, change))
    result = validate_resolution_proposal(ResolutionProposal(case.id, (change,), ()), context, case)
    assert result.valid_changes == (change,) and not result.issues
    assert (case, context, change) == before
    resolved = resolve_deterministically(case, context=context)
    assert resolved.after.executable
    assert [s.action for s in resolved.case.steps[-3:]] == ['assert.http_status', 'assert.json_field', 'assert.url_matches']
    assert resolved.case.steps[-2].args == {'path': '$.success', 'expected': False, 'source': 'attempt'}


@pytest.mark.parametrize('bad', ['wrong_operation', 'wrong_origin', 'missing_capture', 'wrong_source', 'overwrite', 'counter_overwrite', 'fabricated_contract', 'undocumented_status', 'ambiguous_operation'])
def test_api_false_or_stale_response_link_rejected(bad):
    case, context, change, operation = api_inputs()
    if bad == 'wrong_operation': case.steps[1].args['capture_response']['path'] = '/api/unrelated'
    if bad == 'wrong_origin': case.steps[1].args['capture_response']['origin'] = 'https://foreign.example.test'
    if bad == 'missing_capture': del case.steps[1].args['capture_response']
    if bad == 'wrong_source':
        change = replace(change, expansion=(change.expansion[0], replace(change.expansion[1], args={**change.expansion[1].args, 'source': 'other'}), change.expansion[2]))
    if bad in {'overwrite', 'counter_overwrite'}:
        writer = (Step(3, StepKind.WHEN, 'http.request', {'method': 'GET', 'path': '/other', 'save_as': 'attempt'})
                  if bad == 'overwrite' else Step(3, StepKind.WHEN, 'ui.click', {'target': 'submit-control', 'capture_requests': case.steps[1].args['capture_response']}))
        case.steps.insert(2, writer); case.steps[-1].seq = 4; change = replace(change, step_seq=4)
    if bad == 'fabricated_contract': change = replace(change, evidence=(EvidenceReference('openapi', {'operation_id': 'invented'}),))
    if bad == 'undocumented_status': operation['response_codes'] = ['200']
    if bad == 'ambiguous_operation': context.interface_contract['api_operations'].append({**operation, 'operation_id': 'otherOperation'})
    context = replace(context, testcase=build_resolution_context(case, ()).testcase, gaps=analyze_executability(case).gaps)
    result = validate_resolution_proposal(ResolutionProposal(case.id, (change,), ()), context, case)
    assert not result.valid_changes and result.issues


def workflow_inputs():
    req = {'id': 'AC-WORKFLOW', 'when': 'Click Preview; fill "public" into Search; Click Check',
           'then': 'Hiển thị Item ready; URL vẫn ở /details'}
    case = TestCase('TC_GENERIC_020', 'UNIT', 'Preview result', 'Exact source', traces_to=[req['id']], source_quote=req['then'], execution='manual', steps=[
        Step(1, StepKind.GIVEN, 'ui.goto', {'url': '/catalog'}),
        Step(2, StepKind.WHEN, 'ui.click', {'target': 'preview'}, note(req, 'when')),
        Step(3, StepKind.WHEN, 'ui.fill', {'target': 'search', 'value': 'public'}, note(req, 'when')),
        Step(4, StepKind.WHEN, 'ui.click', {'target': 'check'}, note(req, 'when')),
        Step(5, StepKind.THEN, 'assert.unmapped', {'expected': req['then']}, note(req, 'then'))])
    pages = [
        {'url': BASE+'/catalog', 'elements': [{'test_id': 'preview', 'name': 'Preview', 'role': 'link'}]},
        {'url': BASE+'/details', 'elements': [{'test_id': 'search', 'name': 'Search', 'role': 'input'}, {'test_id': 'check', 'name': 'Check', 'role': 'button'}]},
    ]
    bindings = [
        {'action': 'ui.click', 'target': 'preview', 'name': 'Preview', 'role': 'link', 'page': pages[0]['url'], 'expected_url': pages[1]['url'], 'source_clause': 'Click Preview'},
        {'action': 'ui.fill', 'target': 'search', 'name': 'Search', 'role': 'input', 'value': 'public', 'page': pages[1]['url'], 'expected_url': pages[1]['url'], 'source_clause': 'fill "public" into Search'},
        {'action': 'ui.click', 'target': 'check', 'name': 'Check', 'role': 'button', 'page': pages[1]['url'], 'expected_url': pages[1]['url'], 'source_clause': 'Click Check'},
    ]
    for index, binding in enumerate(bindings):
        binding.update(source='validated_action', action_index=index, step_seq=2, requirement_ids=[req['id']])
    states = []
    for index in range(4):
        page = deepcopy(pages[0 if index == 0 else 1])
        if index == 3: page['elements'].append({'test_id': 'feedback', 'name': 'Item ready', 'role': 'alert'})
        state = {'state_id': f'state-{index}', 'valid': True, 'page': page,
                 'triggering_action': None if index == 0 else index-1,
                 'source': {'type': 'playwright_exploration', 'observed_at': '2026-10-07T12:00:00+07:00'},
                 'testcase_id': case.id, 'session': 'anonymous', 'request': {'target': pages[0]['url']},
                 'validated_actions': deepcopy(bindings)}
        if index: state.update(from_state_id=f'state-{index-1}', source_step_seq=2, source_clause=bindings[index-1]['source_clause'])
        states.append(state)
    context = build_resolution_context(case, analyze_executability(case).gaps, requirements=[req])
    context.observations.update(page_states=states, current_state_id='state-3', ui_pages=[pages[0], {**deepcopy(states[-1]['page']), 'state_id': 'state-3'}])
    reference = EvidenceReference('ui-map', {'page': pages[1]['url'], 'state_id': 'state-3', 'test_id': 'feedback'})
    change = ProposedChange(5, 'assert.unmapped', ('UNMAPPED_ACTION',), '', {}, 'Untrusted reason',
        (EvidenceReference('requirement', {'id': req['id']}),), (
            AtomicProposal('assert.visible', {'target': 'feedback'}, (reference,)),
            AtomicProposal('assert.text', {'target': 'feedback', 'expected': 'Item ready', 'exact': True}, (reference,)),
            AtomicProposal('assert.url_matches', {'pattern': '/details$'}, (EvidenceReference('ui-map', {'page': pages[1]['url'], 'state_id': 'state-3'}),))))
    return case, context, change


def test_final_state_source_chain_grounds_all_visible_outcome_atoms():
    case, context, change = workflow_inputs()
    original = deepcopy((case, context, change))
    assert outcome_state(case.steps[-1], case, context)['state_id'] == 'state-3'
    validation = validate_resolution_proposal(ResolutionProposal(case.id, (change,), ()), context, case)
    assert validation.valid_changes == (change,) and not validation.issues
    resolved = resolve_deterministically(case, context=context)
    assert resolved.after.executable
    assert [s.action for s in resolved.case.steps[-3:]] == ['assert.visible', 'assert.text', 'assert.url_matches']
    assert (case, context, change) == original


@pytest.mark.parametrize('bad', ['stale', 'invalid', 'wrong_case', 'wrong_clause', 'wrong_step', 'broken_chain', 'wrong_route', 'wrong_target', 'wrong_value', 'unapproved', 'duplicate_state', 'changed_source', 'unrelated_requirement', 'wrong_initial_navigation', 'wrong_initial_request'])
def test_workflow_wrong_or_stale_state_cannot_prove_outcome(bad):
    case, context, change = workflow_inputs()
    state = context.observations['page_states'][-1]
    if bad == 'stale': context.observations['current_state_id'] = 'state-2'
    if bad == 'invalid': state['valid'] = False
    if bad == 'wrong_case': state['testcase_id'] = 'OTHER'
    if bad == 'wrong_clause': state['source_clause'] = 'Click Unrelated'
    if bad == 'wrong_step': state['source_step_seq'] = 99
    if bad == 'broken_chain': state['from_state_id'] = 'state-0'
    if bad == 'wrong_route': state['page']['url'] = BASE+'/unrelated'
    if bad == 'wrong_target': case.steps[3].args['target'] = 'unrelated'
    if bad == 'wrong_value': case.steps[2].args['value'] = 'invented'
    if bad == 'unapproved': state['validated_actions'] = []
    if bad == 'duplicate_state': context.observations['page_states'].append(deepcopy(state))
    if bad == 'changed_source': context.specification['requirements'][0]['when'] = 'Click Check'
    if bad == 'unrelated_requirement': state['validated_actions'][-1]['requirement_ids'] = ['OTHER']
    if bad == 'wrong_initial_navigation': case.steps[0].args['url'] = '/unrelated'
    if bad == 'wrong_initial_request': state['request'] = {'target': BASE+'/unrelated'}
    context = replace(context, testcase=build_resolution_context(case, ()).testcase, gaps=analyze_executability(case).gaps)
    assert outcome_state(case.steps[-1], case, context) is None
    validation = validate_resolution_proposal(ResolutionProposal(case.id, (change,), ()), context, case)
    assert not validation.valid_changes
    assert not resolve_deterministically(case, context=context).after.executable


def test_observed_text_cannot_replace_source_expected_text_or_drop_text_check():
    case, context, change = workflow_inputs()
    dropped = replace(change, expansion=(change.expansion[0], change.expansion[2]))
    broad = replace(change, expansion=(*change.expansion[:2], replace(change.expansion[2], args={'pattern': '.*details.*'})))
    wrong = replace(change, expansion=(change.expansion[0], replace(change.expansion[1], args={'target': 'feedback', 'expected': 'Observed bug', 'exact': True}), change.expansion[2]))
    for proposed in (dropped, broad, wrong):
        result = validate_resolution_proposal(ResolutionProposal(case.id, (proposed,), ()), context, case)
        assert not result.valid_changes


def test_observed_response_does_not_redefine_negative_contract_expectation():
    case, context, change, _ = api_inputs()
    context.observations['network'] = [{'method': 'POST', 'path': '/api/session-check', 'status': 200, 'success': True}]
    for index, args in ((0, {'expected': 200, 'source': 'attempt'}),
                        (1, {'path': '$.success', 'expected': True, 'source': 'attempt'})):
        atoms = list(change.expansion)
        atoms[index] = replace(atoms[index], args=args)
        proposed = replace(change, expansion=tuple(atoms))
        assert not validate_resolution_proposal(ResolutionProposal(case.id, (proposed,), ()), context, case).valid_changes
    resolved = resolve_deterministically(case, context=context)
    assert resolved.case.steps[-3].args['expected'] == 401
    assert resolved.case.steps[-2].args['expected'] is False


def test_matching_operation_in_context_without_cited_contract_is_not_enough():
    case, context, change, _ = api_inputs()
    req = change.evidence[0]
    proposed = replace(change, evidence=(req,), expansion=(
        change.expansion[0], change.expansion[1], change.expansion[2]))
    # Status atom has the operation, but unrelated sibling evidence is not an
    # implicit parent reference; the JSON atom must still bind to the contract.
    assert not validate_resolution_proposal(ResolutionProposal(case.id, (proposed,), ()), context, case).valid_changes


def test_workflow_cannot_bypass_state_chain_with_flat_page_references():
    case, context, change = workflow_inputs()
    for index in (0, 1, 2):
        atoms = list(change.expansion)
        atoms[index] = replace(atoms[index], evidence=tuple(
            replace(ref, ref={k: v for k, v in ref.ref.items() if k != 'state_id'})
            for ref in atoms[index].evidence))
        proposed = replace(change, expansion=tuple(atoms))
        result = validate_resolution_proposal(ResolutionProposal(case.id, (proposed,), ()), context, case)
        assert not result.valid_changes
        assert result.issues[0].code == 'OUTCOME_STATE_UNPROVEN'


def test_mapper_sibling_clause_provenance_is_equivalent_to_compound_source():
    case, context, change = workflow_inputs()
    requirement = context.specification['requirements'][0]
    for step, clause in zip(case.steps[1:4], requirement['when'].split(';')):
        step.note += '\n[mapper-clause] ' + json.dumps({'text': clause.strip()})
    context = replace(context, testcase=build_resolution_context(case, ()).testcase)
    assert outcome_state(case.steps[-1], case, context)
    assert resolve_deterministically(case, context=context).after.executable

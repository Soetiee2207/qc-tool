"""Source-grounded repair across validated post-action observation and retry."""
from copy import deepcopy
from dataclasses import replace
import json

from qctool.apply_resolution import apply_validated_resolution
from qctool.executability import analyze_executability
from qctool.exploration_plan import ExplorationPlan, ExplorationPurpose, PlannedExploration, validate_exploration_plan
from qctool.generate.mapper import map_testcases
from qctool.llm_resolution import EvidenceReference, ProposedChange, ResolutionProposal
from qctool.proposal_validation import validate_resolution_proposal
from qctool.resolution_context import build_resolution_context
from qctool.llm_exploration import build_exploration_prompt, parse_exploration_plan
from qctool.resolution_loop import run_resolution_loop
from qctool.resolve import resolve_deterministically
from qctool.source_grounding import SEMANTIC_GAP, semantic_repair_arguments
from qctool.testcase import Step, StepKind
from qctool.ui.crawl import Element
from qctool.ui.explore import ExplorationAction, ExplorationResult
from tests.test_interaction_exploration import setup


def pipeline_case():
    case, ui, context, _ = setup()
    ui.pages[0].elements.insert(0, Element('nav', 'link', 'Đăng nhập', 'a', test_id='nav-login-btn', href='/login'))
    map_testcases([case], ui, ui.base_url, {'/api/auth/login'})
    refreshed = build_resolution_context(case, analyze_executability(case).gaps,
        requirements=context.specification['requirements'], ui_map=ui)
    refreshed.interface_contract.update(deepcopy(context.interface_contract))
    # Add contract after selection, then derive context-sensitive gaps.
    refreshed = replace(refreshed, gaps=analyze_executability(case, context=refreshed).gaps)
    return case, ui, refreshed


class RecordedPlanner:
    calls = 0

    def complete(self, prompt):
        self.calls += 1
        # The real prompt supplies the current renumbered source step.
        testcase = json.loads(prompt.split('TESTCASE — EXPLICIT ROUTES AND SESSION REQUIREMENTS\n')[1].split('\n\n')[0])
        step = next(s for s in testcase['steps'] if s['action'] == 'assert.unmapped'
                    and s['args']['expected'] == 'Hiển thị Vui lòng điền đầy đủ thông tin')
        return json.dumps(ExplorationPlan(testcase['id'], (PlannedExploration('/login', (
            ExplorationPurpose('UNMAPPED_ACTION', step['seq'], 'Observe explicit empty-submit validation', 'observe_network'),),
            actions=(ExplorationAction('login-submit-btn', step['seq']),)),)).to_dict())


def observation(approved, count=0):
    _, ui, _ = pipeline_case()
    page = deepcopy(ui.pages[0])
    page.elements.extend([
        Element('status', 'status', 'Vui lòng điền đầy đủ thông tin', 'div'),
        Element('alert', 'alert', 'Vui lòng điền đầy đủ thông tin', 'p', test_id='login-validation-message')])
    page.text = ['Vui lòng điền đầy đủ thông tin']
    action = {'action_index': 0, 'action': 'ui.click', 'target': 'login-submit-btn',
              'source_step_seq': approved.request.actions[0].step_seq,
              'credential_inputs_empty': True, 'request_count': count,
              'selector': {'method': 'POST', 'path': '/api/auth/login', 'origin': ui.base_url, 'window_ms': 2000},
              'final_url': page.url, 'page': {'url': page.url, 'elements': [e.to_dict() for e in page.elements]},
              'source': {'type': 'playwright_exploration', 'observed_at': 'recorded'}}
    return ExplorationResult(approved.request, page.url, page, (), (), (), 'recorded',
                             truncated=('network',), action_observations=(action,))


def test_semantic_gap_and_unrelated_steps_stay_closed():
    case, ui, context = pipeline_case()
    wrong = next(s for s in case.steps if s.action == 'ui.click')
    assert wrong.args['target'] == 'nav-login-btn'
    assert (SEMANTIC_GAP, wrong.seq) in {(g.code, g.step_seq) for g in context.gaps}
    case.steps.append(Step(99, StepKind.WHEN, 'ui.click', {'target': 'nav-login-btn'}))
    assert not any(g.step_seq == 99 for g in analyze_executability(case, context=context).gaps)
    wrong.args = semantic_repair_arguments(wrong, case, context)
    assert not any(g.code == SEMANTIC_GAP and g.step_seq == wrong.seq
                   for g in analyze_executability(case, context=context).gaps)


def test_semantic_replacement_requires_exact_proof_and_evidence():
    case, ui, context = pipeline_case()
    step = next(s for s in case.steps if s.action == 'ui.click')
    page = context.observations['ui_pages'][0]['url']
    refs = (EvidenceReference('requirement', {'id': 'AC-EMPTY'}),
            EvidenceReference('ui-map', {'page': page, 'test_id': 'login-submit-btn'}),
            EvidenceReference('openapi', {'method': 'POST', 'path': '/api/auth/login'}))
    change = ProposedChange(step.seq, step.action, (SEMANTIC_GAP,), 'ui.click',
                            semantic_repair_arguments(step, case, context), 'Exact source', refs)
    original = deepcopy((case, context))
    validation = validate_resolution_proposal(ResolutionProposal(case.id, (change,), ()), context, case)
    assert validation.valid_changes == (change,)
    applied = apply_validated_resolution(case, validation)
    assert not applied.issues
    assert next(s for s in applied.case.steps if s.seq == step.seq).args['target'] == 'login-submit-btn'
    for bad in (replace(change, args={'target': 'login-submit-btn'}),
                replace(change, args={**change.args, 'target': 'fabricated'}),
                replace(change, evidence=refs[1:])):
        assert not validate_resolution_proposal(ResolutionProposal(case.id, (bad,), ()), context, case).valid_changes
    altered = deepcopy(validation)
    altered.analysis_context.observations['ui_pages'][0]['elements'].clear()
    assert apply_validated_resolution(case, altered).issues
    assert (case, context) == original


def test_missing_source_provenance_never_reopens_concrete_steps():
    case, ui, context = pipeline_case()
    for step in case.steps:
        step.note = ''
    assert not any(g.code == SEMANTIC_GAP for g in analyze_executability(case, context=context).gaps)


def test_interaction_enrichment_retry_preserves_all_outcomes(monkeypatch):
    case, ui, context = pipeline_case()
    original = deepcopy((case, ui, context))
    calls = []
    def explorer(approved, **kwargs):
        calls.append(approved)
        return observation(approved, count=1)  # Product behavior must not change expected count=0.
    monkeypatch.setattr('qctool.exploration_execution.explore_page', explorer)
    planner = RecordedPlanner()
    result = run_resolution_loop(case, context, ui_map=ui, exploration_llm=planner, base_url=ui.base_url)
    assert result.executable, [(c.issues, c.after.gaps) for c in result.cycles]
    assert result.cycle_count == 2 and len(calls) == planner.calls == 1
    assert len(result.case.steps) == 9
    assert [s.action for s in result.case.steps] == ['ui.session', 'ui.goto', 'assert.value', 'assert.value',
        'ui.click', 'assert.visible', 'assert.text', 'assert.json_field', 'assert.url_matches']
    assert result.case.steps[4].args['target'] == 'login-submit-btn'
    assert result.case.steps[6].args['expected'] == 'Vui lòng điền đầy đủ thông tin'
    assert result.case.steps[7].args['expected'] == 0
    assert result.case.steps[8].args['pattern'] == '/login$'
    pages = result.context.observations['ui_pages']
    assert len(pages) == 1
    assert sum(e.get('test_id') == 'login-submit-btn' for e in pages[0]['elements']) == 1
    source = pages[0]['explorations'][0]
    assert source['action_observations'][0]['request_count'] == 1
    assert source['action_observations'][0]['target'] == 'login-submit-btn'
    assert source['truncated'] == ['network'] and source['previous_snapshot']
    assert result.context.specification == context.specification
    assert result.context.interface_contract == context.interface_contract
    assert (case, ui, context) == original


def test_alert_without_action_provenance_remains_unresolved():
    case, ui, context = pipeline_case()
    context.observations['ui_pages'][0]['elements'].append(
        Element('alert', 'alert', 'Vui lòng điền đầy đủ thông tin', 'p', test_id='login-validation-message').to_dict())
    result = resolve_deterministically(case, context=context)
    assert any(s.action == 'assert.unmapped' for s in result.case.steps)


def test_wrong_navigation_is_a_gap_even_when_contract_is_missing():
    case, _, context = pipeline_case()
    context.interface_contract['api_operations'] = []
    click = next(s for s in case.steps if s.action == 'ui.click')
    assert any(g.code == SEMANTIC_GAP and g.step_seq == click.seq
               for g in analyze_executability(case, context=context).gaps)
    result = resolve_deterministically(case, context=context)
    assert next(s for s in result.case.steps if s.action == 'ui.click').args['target'] == 'nav-login-btn'


def test_refresh_deduplicates_reordered_map_elements():
    from qctool.resolution_cycle import _refresh_context
    case, ui, context = pipeline_case()
    # Context builder changes ranking when mapped targets change. Order is not
    # independent locator evidence and must not create a second page snapshot.
    context.observations['ui_pages'][0]['elements'].reverse()
    result = _refresh_context(case, context, analyze_executability(case, context=context), ui_map=ui, endpoints=None)
    assert len(result.observations['ui_pages']) == 1


def test_observation_request_count_is_meaningful_not_timestamp_progress():
    from qctool.resolution_loop import _evidence_facts
    case, ui, context = pipeline_case()
    result = resolve_deterministically(case, context=context)
    from qctool.resolution_cycle import _refresh_context
    context = _refresh_context(result.case, context, result.after, ui_map=None, endpoints=None)
    raw = RecordedPlanner().complete(build_exploration_prompt(context))
    approved = validate_exploration_plan(parse_exploration_plan(raw), context, result.case, ui.base_url).valid_requests[0]
    from qctool.exploration_execution import _enrich
    _enrich(context.observations, observation(approved), approved)
    facts = _evidence_facts(context)
    changed = deepcopy(context)
    source = changed.observations['ui_pages'][0]['explorations'][0]
    source['source']['observed_at'] = 'different time'
    source['action_observations'][0]['source']['observed_at'] = 'different time'
    assert _evidence_facts(changed) == facts
    source['action_observations'][0]['request_count'] = 1
    assert _evidence_facts(changed) != facts

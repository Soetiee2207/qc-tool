"""Capability selection cannot approve a repair or browser action."""
from copy import deepcopy
from dataclasses import replace

import pytest

from qctool.executability import analyze_executability, ExecutionGap
from qctool.gap_routing import route_gaps
from qctool.resolution_cycle import run_resolution_cycle
from qctool.resolution_context import build_resolution_context
from qctool.resolution_loop import run_resolution_loop
from qctool.testcase import Step, StepKind
from tests.test_resolution_cycle import BASE, FakeLLM, _inputs, _proposal, _unresolved
from tests.test_interaction_resolution import RecordedPlanner, observation, pipeline_case


def test_missing_controls_route_directly_to_exploration():
    case, context, _ = _inputs(evidence=False)
    original = deepcopy((case, context))
    result = route_gaps(case, context, base_url=BASE)
    assert result.selected_capability == 'exploration'
    assert result.llm_call_skipped == ('resolution',)
    assert result.gap_classification[0].classification == 'NEEDS_EXPLORATION'
    assert (case, context) == original


def test_existing_controls_route_only_to_resolution():
    case, context, _ = _inputs()
    forbidden = FakeLLM(AssertionError('Browser capability must not be requested'))
    result = run_resolution_cycle(case, context, resolution_llm=FakeLLM(_unresolved()),
                                  exploration_llm=forbidden, base_url=BASE)
    assert all(d.selected_capability == 'resolution' for d in result.decisions)
    assert not forbidden.prompts and result.exploration_plan is None


def test_deterministic_repair_audits_resolved_work_without_model():
    case, context, ui = _inputs(missing_locator=True)
    forbidden = FakeLLM(AssertionError('Must not call'))
    result = run_resolution_cycle(case, context, ui_map=ui, resolution_llm=forbidden,
                                  exploration_llm=forbidden, base_url=BASE)
    assert result.after.executable and not forbidden.prompts
    assert result.decisions[0].selected_capability == 'none'
    assert {g.classification for g in result.decisions[0].gap_classification} == {'DETERMINISTIC'}
    assert result.decisions[0].llm_call_skipped == ('resolution', 'exploration')


@pytest.mark.parametrize('code', ['MISSING_FIXTURE', 'INVALID_TEST_DATA', 'UNVERIFIED_TEST_DATA',
                                  'MISSING_PRECONDITION', 'UNSUPPORTED_ACTION', 'INVALID_ACTION'])
def test_blocked_gaps_do_not_request_models(code):
    case, context, _ = _inputs()
    context = replace(context, gaps=(ExecutionGap(code, 'Unavailable trusted input', 2),))
    result = route_gaps(case, context, base_url=BASE)
    assert result.selected_capability == 'none'
    assert result.gap_classification[0].classification == 'BLOCKED'


def test_missing_source_authority_has_no_safe_capability():
    case, context, _ = _inputs(evidence=False)
    case.steps[1] = Step(2, StepKind.THEN, 'assert.unmapped', {'expected': 'TBC'})
    context = build_resolution_context(case, analyze_executability(case).gaps)
    assert route_gaps(case, context, base_url=BASE).selected_capability == 'none'


def test_missing_contract_is_not_replaced_by_live_product_observation():
    case, context, _ = _inputs()
    case.steps[1] = Step(2, StepKind.THEN, 'assert.unmapped', {'expected': 'POST /absent trả 401 với success=false'})
    context = build_resolution_context(case, analyze_executability(case).gaps)
    decision = route_gaps(case, context, base_url=BASE)
    assert decision.selected_capability == 'none'
    assert all(g.classification == 'BLOCKED' for g in decision.gap_classification)


def test_mixed_post_action_and_mapping_gaps_inspect_first_then_use_deterministic(monkeypatch):
    import qctool.resolution_cycle as cycle
    case, ui, context = pipeline_case()
    original = deepcopy((case, ui, context))
    resolution = FakeLLM(AssertionError('Post-action evidence should enable deterministic repair'))
    planner = RecordedPlanner()
    calls = []
    from qctool.exploration_execution import execute_validated_exploration
    def execute(approved, packet, **kwargs):
        import qctool.exploration_execution as execution
        request = approved.valid_requests[0]
        calls.append(request)
        monkeypatch.setattr(execution, 'explore_page', lambda *a, **kw: observation(request))
        return execute_validated_exploration(approved, packet, **kwargs)
    monkeypatch.setattr(cycle, 'execute_validated_exploration', execute)
    result = run_resolution_loop(case, context, ui_map=ui, base_url=ui.base_url,
                                 resolution_llm=resolution, exploration_llm=planner, max_cycles=3)
    assert result.executable and result.cycle_count == 2
    assert len(calls) == planner.calls == 1 and not resolution.prompts
    assert result.cycles[0].decisions[0].selected_capability == 'exploration'
    assert result.cycles[1].deterministic.changes
    assert result.cycles[1].decisions[0].selected_capability == 'none'
    assert (case, ui, context) == original


def test_rejected_mapping_does_not_ping_pong_between_capabilities():
    case, context, _ = _inputs()
    resolution, exploration = FakeLLM(_proposal(target='invented')), FakeLLM(AssertionError('No missing evidence'))
    result = run_resolution_loop(case, context, resolution_llm=resolution,
                                 exploration_llm=exploration, base_url=BASE, max_cycles=20)
    assert result.stop_reason == 'REPEATED_STATE' and result.cycle_count == 1
    assert len(resolution.prompts) == 1 and not exploration.prompts
    assert result.cycles[0].validation.rejected_changes


def test_preparation_blocks_all_capabilities_even_with_other_mapping_gaps():
    case, context, _ = _inputs()
    decision = route_gaps(case, context, base_url=BASE, blocked=True)
    assert decision.selected_capability == 'none'
    assert all(g.classification == 'BLOCKED' for g in decision.gap_classification)
    assert decision.llm_call_skipped == ('resolution', 'exploration')

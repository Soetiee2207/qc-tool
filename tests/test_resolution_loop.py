"""Bounded orchestration, with fake adapters and no live browser/model calls."""

from copy import deepcopy
from dataclasses import replace

import pytest

import qctool.exploration_execution as execution
import qctool.resolution_loop as loop
from qctool.executability import analyze_executability
from qctool.resolution_cycle import run_resolution_cycle
from tests.test_resolution_cycle import (
    BASE, FakeLLM, _fake_explorer, _inputs, _plan, _proposal, _unresolved,
)


class SequenceLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        assert self.responses, "Unexpected extra model call"
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_executable_after_first_cycle_skips_exploration():
    case, context, _ = _inputs()
    adapter = SequenceLLM(_proposal())
    result = loop.run_resolution_loop(case, context, resolution_llm=adapter)
    assert result.executable
    assert result.executability == analyze_executability(result.case)
    assert result.stop_reason == "EXECUTABLE"
    assert result.cycle_count == 1
    assert len(adapter.prompts) == 1
    assert result.cycles[0].exploration_plan is None


def test_already_executable_runs_zero_cycles(monkeypatch):
    case, context, _ = _inputs()
    case.steps[1].action, case.steps[1].args = "ui.click", {"target": "btn-login"}
    monkeypatch.setattr(loop, "run_resolution_cycle", lambda *a, **kw: pytest.fail("Already executable"))
    result = loop.run_resolution_loop(case, context)
    assert result.executable and result.cycle_count == 0
    assert result.stop_reason == "EXECUTABLE"


def test_exploration_enables_second_cycle_repair_and_preserves_history(monkeypatch):
    case, context, _ = _inputs(evidence=False)
    resolution = SequenceLLM(_proposal())
    exploration = SequenceLLM(_plan())
    monkeypatch.setattr(execution, "explore_page", _fake_explorer)
    result = loop.run_resolution_loop(case, context, resolution_llm=resolution,
                                      exploration_llm=exploration, base_url=BASE)
    assert result.cycle_count == 2 and result.executable
    assert result.stop_reason == "EXECUTABLE"
    first, second = result.cycles
    assert first.case.steps[1].action == "perform.unmapped"
    assert first.exploration_execution.successful_requests
    assert second.case.steps[1].action == "ui.click"
    assert first.context.observations["ui_pages"][0]["url"] == BASE + "/login"
    assert "btn-login" in resolution.prompts[0]
    assert len(exploration.prompts) == len(resolution.prompts) == 1
    assert [(event.cycle, event.stage, event.status) for event in result.audit] == [
        (index, event.stage, event.status)
        for index, cycle in enumerate(result.cycles, 1) for event in cycle.audit]


def test_identical_state_stops_after_one_cycle():
    case, context, _ = _inputs()
    result = loop.run_resolution_loop(case, context, max_cycles=50)
    assert result.stop_reason == "REPEATED_STATE"
    assert result.cycle_count == 1
    assert result.cycles[0].issues  # Missing adapters are not a reason to spin.


def test_repeated_evidence_with_new_timestamp_is_not_progress(monkeypatch):
    case, context, _ = _inputs(evidence=False)
    observations = []

    def inspect(request, **kwargs):
        observations.append(request)
        return replace(_fake_explorer(request), observed_at=f"time-{len(observations)}")

    monkeypatch.setattr(execution, "explore_page", inspect)
    result = loop.run_resolution_loop(case, context, max_cycles=20,
                                      resolution_llm=FakeLLM(_unresolved()),
                                      exploration_llm=FakeLLM(_plan()), base_url=BASE)
    assert result.stop_reason == "REPEATED_STATE" and result.cycle_count == 2
    assert len(observations) == 1
    assert len(result.context.observations["ui_pages"]) == 1
    # Once selected evidence exists, repeated exploration is skipped.
    assert len(result.context.observations["ui_pages"][0]["explorations"]) == 1


def test_budget_caps_cycles_even_when_new_evidence_keeps_arriving(monkeypatch):
    case, context, _ = _inputs(evidence=False)
    template = run_resolution_cycle(case, context)
    count = []

    def run(candidate, packet, **kwargs):
        count.append(1)
        packet.observations['ui_pages'].append({
            'url': BASE + '/login', 'text': [f'New text {len(count)}'], 'elements': []})
        return replace(template, case=candidate, context=packet)

    monkeypatch.setattr(loop, 'run_resolution_cycle', run)
    result = loop.run_resolution_loop(case, context, max_cycles=3)
    assert result.stop_reason == 'MAX_CYCLES' and result.cycle_count == 3
    assert not result.executable and len(count) == 3


def test_partial_repairs_progress_across_cycles_without_exploration():
    case, context, _ = _inputs(extra_step=True)
    adapter = SequenceLLM(_proposal(), _proposal(seq=3, target="btn-save"))
    result = loop.run_resolution_loop(case, context, resolution_llm=adapter)
    assert result.cycle_count == 2 and result.executable
    assert len(result.cycles[0].after.gaps) == 1
    assert result.cycles[0].case.steps[2].action == "perform.unmapped"
    assert result.cycles[1].case.steps[2].action == "ui.click"
    assert result.cycles[0].application.applied_changes
    assert result.cycles[1].application.applied_changes


def test_stage_failure_without_new_progress_stops_with_last_repairs():
    case, context, _ = _inputs(extra_step=True)
    adapter = SequenceLLM(_proposal(), RuntimeError("password=PRIVATE"))
    result = loop.run_resolution_loop(case, context, resolution_llm=adapter)
    assert result.stop_reason == "REPEATED_STATE" and result.cycle_count == 2
    assert result.case.steps[1].action == "ui.click"
    assert result.case.steps[2].action == "perform.unmapped"
    assert any(issue.stage == "resolution_llm" and issue.code == "STAGE_FAILED"
               for issue in result.cycles[-1].issues)
    assert "PRIVATE" not in repr(result.cycles[-1].issues)
    assert len(adapter.prompts) == 2


def test_unexpected_cycle_exception_discards_private_candidate(monkeypatch):
    case, context, _ = _inputs(extra_step=True)
    calls = []

    def run(candidate, packet, **kwargs):
        calls.append(candidate)
        if len(calls) == 1:
            return run_resolution_cycle(candidate, packet, resolution_llm=FakeLLM(_proposal()))
        candidate.steps[1].action = "ui.magic"
        packet.specification["requirements"] = [{"statement": "Wrong expectation"}]
        raise RuntimeError("token=PRIVATE")

    monkeypatch.setattr(loop, "run_resolution_cycle", run)
    result = loop.run_resolution_loop(case, context)
    assert result.stop_reason == "CYCLE_FAILED"
    assert result.cycle_count == 1 and len(calls) == 2
    assert result.issues[0].cycle == 2
    assert result.case.steps[1].action == "ui.click"
    assert result.context.specification == context.specification
    assert "PRIVATE" not in repr(result.issues)
    assert (result.audit[-1].cycle, result.audit[-1].stage, result.audit[-1].status) == (
        2, "cycle", "FAILED")


def test_oscillation_detected_before_budget(monkeypatch):
    case, context, _ = _inputs(evidence=False)
    titles = iter(["State A", "State B", "State A"])
    template = run_resolution_cycle(case, context)

    def run(candidate, packet, **kwargs):
        candidate.title = next(titles)
        packet.testcase["title"] = candidate.title
        return replace(template, case=candidate, context=packet,
                       after=analyze_executability(candidate))

    monkeypatch.setattr(loop, "run_resolution_cycle", run)
    result = loop.run_resolution_loop(case, context, max_cycles=20)
    assert result.stop_reason == "REPEATED_STATE" and result.cycle_count == 3


def test_non_evidence_context_change_is_no_progress(monkeypatch):
    case, context, _ = _inputs()
    template = run_resolution_cycle(case, context)

    def run(candidate, packet, **kwargs):
        return replace(template, context=replace(packet, constraints=("New constraint",)))

    monkeypatch.setattr(loop, "run_resolution_cycle", run)
    result = loop.run_resolution_loop(case, context)
    assert result.stop_reason == "NO_PROGRESS" and result.cycle_count == 1


def test_duplicate_evidence_and_reordering_do_not_change_state(monkeypatch):
    case, context, _ = _inputs()
    template = run_resolution_cycle(case, context)

    def run(candidate, packet, **kwargs):
        page = packet.observations["ui_pages"][0]
        page["elements"].reverse()
        packet.observations["ui_pages"].append(deepcopy(page))
        return replace(template, context=packet)

    monkeypatch.setattr(loop, "run_resolution_cycle", run)
    result = loop.run_resolution_loop(case, context)
    assert result.stop_reason == "REPEATED_STATE" and result.cycle_count == 1


def test_no_more_work_for_structural_error_without_execution_gaps():
    case, context, _ = _inputs()
    case.steps[1].action, case.steps[1].args = "ui.click", {"target": "btn-login"}
    case.traces_to = []  # Invalid provenance, no execution gap to repair.
    result = loop.run_resolution_loop(case, context)
    assert not result.executable
    assert result.executability.validation_error
    assert result.stop_reason == "NO_MORE_WORK" and result.cycle_count == 1


def test_originals_and_earlier_history_remain_detached(monkeypatch):
    case, context, ui_map = _inputs(evidence=False)
    originals = deepcopy((case, context, ui_map))
    monkeypatch.setattr(execution, "explore_page", _fake_explorer)
    result = loop.run_resolution_loop(case, context, resolution_llm=SequenceLLM(_proposal()),
                                      exploration_llm=SequenceLLM(_plan()), base_url=BASE)
    assert (case, context, ui_map) == originals
    result.case.steps[1].args["target"] = "changed"
    result.context.observations["ui_pages"][0]["title"] = "changed"
    assert result.cycles[0].case.steps[1].action == "perform.unmapped"
    assert result.cycles[1].case.steps[1].args["target"] == "btn-login"
    assert result.cycles[0].context.observations["ui_pages"][0]["title"] == "Login"
    assert (case, context, ui_map) == originals


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "3", None])
def test_invalid_budget_rejected_before_running(monkeypatch, limit):
    case, context, _ = _inputs()
    monkeypatch.setattr(loop, "run_resolution_cycle", lambda *a, **kw: pytest.fail("Invalid budget"))
    with pytest.raises(ValueError, match="positive integer"):
        loop.run_resolution_loop(case, context, max_cycles=limit)

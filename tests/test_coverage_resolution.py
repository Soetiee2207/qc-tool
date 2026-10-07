"""Standalone coverage pass: real loop, fake model completions, no browser."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

import qctool.coverage_resolution as coverage_pass
from qctool.coverage import analyze_coverage
from qctool.coverage_plan import plan_coverage
from qctool.executability import analyze_executability
from qctool.resolution_context import build_resolution_context
from qctool.resolution_loop import run_resolution_loop
from qctool.testcase import Step, StepKind, TestCase
from qctool.ui.crawl import PageMap, UIMap, Element

BASE = "https://app.test"


def flows(*ids):
    return {"flow": [{"id": id, "source_file": "flows.md", "source_line": 8,
                      "steps": [{"action": "Open /login", "expected": "URL /login"}]}
                     for id in ids or ("FLOW-1",)]}


def report(*ids):
    return analyze_coverage([], [], flows=flows(*ids))


def ui_map():
    return UIMap(BASE, "now", [PageMap(BASE + "/login", "Login")])


def contexts_for(source_report, existing=(), requirements=None):
    """Caller supplies trusted evidence for an explicit known route."""
    contexts = {}
    for logical in plan_coverage(source_report, existing_cases=existing).cases:
        context = build_resolution_context(logical, analyze_executability(logical).gaps,
                                           requirements=requirements)
        probe = deepcopy(logical)
        probe.steps[0] = Step(1, StepKind.WHEN, "ui.goto", {"url": "/login"})
        selected = build_resolution_context(probe, (), ui_map=ui_map())
        contexts[logical.id] = replace(context, observations=selected.observations)
    return contexts


class RepairLLM:
    def __init__(self):
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return json.dumps({"testcase_id": "TC_COV_001", "changes": [
            {"step_seq": seq, "from_action": before, "gap_codes": ["UNMAPPED_ACTION"],
             "proposed": {"action": action, "args": args}, "reason": "Explicit source route",
             "evidence": [{"source": "ui-map", "ref": {"page": BASE + "/login"}}]}
            for seq, before, action, args in [
                (1, "perform.unmapped", "ui.goto", {"url": "/login"}),
                (2, "assert.unmapped", "assert.url_matches", {"pattern": "/login"})]],
            "unresolved": []})


class MustNotCall:
    def complete(self, prompt):
        pytest.fail("No exploration is needed after a fully executable repair")


def test_candidate_evidence_and_safe_provider_failure_survive_real_coverage_stack():
    from qctool.generate.loader import load_endpoints
    from qctool.llm_provider import LLMProviderError
    from pathlib import Path
    requirements = [{"id": "AC-LOGIN", "kind": "acceptance_criterion",
                     "given": "Anonymous at /login; existing account supplied",
                     "when": "Click Login", "then": "POST /projects returns 201"}]
    source = analyze_coverage(requirements, [])
    saved = deepcopy(source)
    endpoints = load_endpoints(Path("samples/openapi/task-manager-sample.yaml"))[0]
    class FailedProvider:
        def complete(self, prompt):
            assert BASE + "/login" in prompt
            assert '"operation_id": "createProject"' in prompt
            raise LLMProviderError("TIMEOUT", "PRIVATE transport payload")
    result = coverage_pass.run_coverage_resolution_pass(source, requirements=requirements,
        ui_map=UIMap(BASE, "now", [PageMap(BASE + "/login", "Login", elements=[
            Element("login", "button", "Login", "button", test_id="btn-login")])]),
        endpoints=endpoints, resolution_llm=FailedProvider(), base_url=BASE)
    assert source == saved
    record = result.case_results[0]
    context = record.resolution.cycles[0].context
    assert len(context.observations["ui_pages"]) == 1
    assert len(context.interface_contract["api_operations"]) == 1
    assert record.case.steps == result.plan.cases[0].steps
    assert any(issue.code == "TIMEOUT" and "timed out" in issue.message for issue in result.issues)
    assert "PRIVATE" not in repr(result.issues)


def test_real_loop_resolves_logical_case_and_accepts_only_executable():
    adapter = RepairLLM()
    result = coverage_pass.run_coverage_resolution_pass(
        report(), resolution_llm=adapter, exploration_llm=MustNotCall(),
        ui_map=ui_map(), base_url=BASE, contexts=contexts_for(report()))
    assert len(result.accepted_cases) == 1
    assert not result.unresolved_cases
    assert analyze_executability(result.accepted_cases[0]).executable
    assert result.planned_cases[0].steps[0].action == "perform.unmapped"
    assert result.accepted_cases[0].steps[0].action == "ui.goto"
    assert result.accepted_cases[0].execution == "auto"
    assert result.case_results[0].resolution.cycle_count == 1
    cycle = result.case_results[0].resolution.cycles[0]
    assert len(cycle.deterministic.changes) == 2
    assert cycle.application is None
    assert not adapter.prompts
    assert result.accepted_obligation_to_testcase == {"FLOW-1:steps[0].expected": "TC_COV_001"}
    assert result.audit[0].obligation.source.file == "flows.md"


def test_unresolved_logical_case_is_not_successful_coverage():
    result = coverage_pass.run_coverage_resolution_pass(report())
    assert not result.accepted_cases
    assert len(result.unresolved_cases) == 1
    assert not result.case_results[0].executability.executable
    assert not result.accepted_obligation_to_testcase
    assert result.obligation_to_testcase == {"FLOW-1:steps[0].expected": "TC_COV_001"}
    assert result.case_results[0].resolution.cycles
    assert result.issues


def test_partial_resolution_keeps_last_progress_and_full_history():
    class PartialLLM:
        def __init__(self):
            self.calls = 0

        def complete(self, prompt):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("Model unavailable")
            response = json.loads(RepairLLM().complete(prompt))
            response["changes"] = response["changes"][:1]
            return json.dumps(response)

    result = coverage_pass.run_coverage_resolution_pass(
        report(), resolution_llm=PartialLLM(), contexts=contexts_for(report()))
    assert not result.accepted_cases
    assert result.unresolved_cases[0].steps[0].action == "ui.goto"
    assert result.unresolved_cases[0].steps[1].action == "assert.unmapped"
    resolution = result.case_results[0].resolution
    assert resolution.cycle_count == 2
    assert resolution.cycles[0].application.applied_changes
    assert any(i.stage == "resolution_llm" and i.code == "STAGE_FAILED"
               and i.cycle == 2 for i in result.issues)


def test_supplied_context_identity_mismatch_is_not_accepted():
    contexts = contexts_for(report())
    contexts["TC_COV_001"].testcase["id"] = "TC_OTHER_001"
    result = coverage_pass.run_coverage_resolution_pass(report(), contexts=contexts,
                                                        resolution_llm=RepairLLM())
    assert not result.accepted_cases
    assert result.case_results[0].resolution.cycles[0].proposal is None
    assert any(i.code == "TESTCASE_MISMATCH" for i in result.issues)


def test_shared_candidate_resolves_only_once(monkeypatch):
    calls = []

    def run(case, context, **kwargs):
        calls.append(case.id)
        return run_resolution_loop(case, context, **kwargs)

    monkeypatch.setattr(coverage_pass, "run_resolution_loop", run)
    result = coverage_pass.run_coverage_resolution_pass(
        report("FLOW-1", "FLOW-2"), resolution_llm=RepairLLM(), ui_map=ui_map(),
        contexts=contexts_for(report("FLOW-1", "FLOW-2")))
    assert calls == ["TC_COV_001"]
    assert len(result.planned_cases) == len(result.accepted_cases) == 1
    assert result.accepted_cases[0].traces_to == ["FLOW-1", "FLOW-2"]
    assert len(result.accepted_obligation_to_testcase) == 2
    assert len(result.audit) == 2


def test_one_case_failure_does_not_stop_others_or_leak_exception(monkeypatch):
    source = {"flow": [
        {"id": "FLOW-1", "steps": [{"action": "Open /broken", "expected": "Broken page"}]},
        flows("FLOW-2")["flow"][0]]}
    calls = []

    def run(case, context, **kwargs):
        calls.append(case.id)
        if len(calls) == 1:
            case.steps[0].args["description"] = "Corrupted"
            raise RuntimeError("password=PRIVATE")
        # Real loop for the second candidate; adjust completion's identity only.
        adapter = RepairLLM()

        class SecondLLM:
            def complete(self, prompt):
                return adapter.complete(prompt).replace("TC_COV_001", "TC_COV_002")

        kwargs["resolution_llm"] = SecondLLM()
        return run_resolution_loop(case, context, **kwargs)

    monkeypatch.setattr(coverage_pass, "run_resolution_loop", run)
    result = coverage_pass.run_coverage_resolution_pass(
        analyze_coverage([], [], flows=source), ui_map=ui_map(),
        contexts=contexts_for(analyze_coverage([], [], flows=source)))
    assert calls == ["TC_COV_001", "TC_COV_002"]
    assert [c.id for c in result.accepted_cases] == ["TC_COV_002"]
    assert result.unresolved_cases[0].steps[0].args == {"description": "Open /broken"}
    assert result.case_results[0].resolution is None
    assert result.issues[0].code == "CASE_RESOLUTION_FAILED"
    assert "PRIVATE" not in repr(result.issues)


def test_context_failure_is_isolated(monkeypatch):
    original = coverage_pass.build_resolution_context
    calls = []

    def build(case, gaps, **kwargs):
        calls.append(case.id)
        if len(calls) == 1:
            raise RuntimeError("context unavailable")
        return original(case, gaps, **kwargs)

    monkeypatch.setattr(coverage_pass, "build_resolution_context", build)
    requirements = [{"id": "FR-1", "kind": "functional", "acceptance": ["Saved", "Notification sent"]}]
    result = coverage_pass.run_coverage_resolution_pass(analyze_coverage(requirements, []))
    assert len(result.unresolved_cases) == 2
    assert result.issues[0].stage == "context"
    assert result.case_results[0].resolution is None
    assert result.case_results[1].resolution is not None


def test_already_covered_and_reused_cases_are_not_resolved(monkeypatch):
    source_report = report()
    existing = plan_coverage(source_report).cases
    monkeypatch.setattr(coverage_pass, "run_resolution_loop",
                        lambda *a, **kw: pytest.fail("Existing cases must not be resolved"))
    covered_report = analyze_coverage([], existing, flows=flows())
    result = coverage_pass.run_coverage_resolution_pass(covered_report, existing)
    assert not result.planned_cases and not result.case_results
    # Stale report: planner reuses existing intent, pass still must not resolve it.
    result = coverage_pass.run_coverage_resolution_pass(source_report, existing)
    assert not result.case_results and not result.accepted_cases
    assert result.skipped_obligations[0].code == "EXISTING_INTENT"
    assert result.obligation_to_testcase
    assert not result.accepted_obligation_to_testcase


def test_acceptance_is_reanalyzed_instead_of_trusting_loop_flag(monkeypatch):
    logical = plan_coverage(report()).cases[0]
    template = run_resolution_loop(logical, build_resolution_context(
        logical, analyze_executability(logical).gaps))
    false_claim = replace(template.executability, executable=True)
    monkeypatch.setattr(coverage_pass, "run_resolution_loop",
                        lambda *a, **kw: replace(template, executability=false_claim))
    result = coverage_pass.run_coverage_resolution_pass(report())
    assert not result.accepted_cases
    assert not result.case_results[0].accepted


def test_input_and_result_snapshots_remain_detached():
    source_report, evidence = report(), ui_map()
    existing = [TestCase("TC_OTHER_001", "OTHER", "Existing", "Existing")]
    requirements = [{"id": "FLOW-1", "kind": "functional", "statement": "Open /login"}]
    contexts = contexts_for(source_report, existing, requirements)
    snapshot = deepcopy((source_report, existing, evidence, requirements, contexts))
    result = coverage_pass.run_coverage_resolution_pass(
        source_report, existing, resolution_llm=RepairLLM(), ui_map=evidence,
        requirements=requirements, contexts=contexts)
    assert (source_report, existing, evidence, requirements, contexts) == snapshot
    assert result.case_results[0].resolution.context.specification["requirements"][0]["id"] == "FLOW-1"
    result.accepted_cases[0].steps[0].args["url"] = "/changed"
    assert result.planned_cases[0].steps[0].args == {"description": "Open /login"}
    assert result.case_results[0].resolution.case.steps[0].args == {"url": "/login"}
    assert (source_report, existing, evidence, requirements, contexts) == snapshot


@pytest.mark.parametrize("budget", [0, -1, True])
def test_invalid_budget_rejected_before_planning(budget):
    with pytest.raises(ValueError, match="positive integer"):
        coverage_pass.run_coverage_resolution_pass(report(), max_cycles=budget)

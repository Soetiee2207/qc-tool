"""Evaluate the real loop with local recordings; no browser or model provider."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import socket
import urllib.request

import pytest

import qctool.resolution_evaluation as evaluation
from qctool.executability import analyze_executability
from qctool.resolution_evaluation import (
    ExplorationReplay, ResolutionEvaluationCase, StepGroundTruth,
    evaluate_resolution_loop, load_evaluation_suite, main,
)
from qctool.resolution_loop import ResolutionLoopStopReason, run_resolution_loop
from qctool.ui.explore import ExplorationRequest
from tests.test_resolution_cycle import BASE, _fake_explorer, _inputs, _plan, _proposal, _unresolved

SAMPLE = Path(__file__).resolve().parents[1] / "samples/evaluation/resolution-replay.yaml"
CLICK = {"action": "ui.click", "args": {"target": "btn-login"}}


@pytest.fixture(autouse=True)
def prohibit_live_calls(monkeypatch):
    from qctool.execute.browser import BrowserSession
    import playwright.sync_api

    def forbidden(*args, **kwargs):
        pytest.fail("Offline evaluation attempted network/browser access")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(BrowserSession, "start", forbidden)
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", forbidden)


def _entry(*, label=None, extra_step=False, missing_locator=False):
    case, context, ui_map = _inputs(extra_step=extra_step, missing_locator=missing_locator)
    return ResolutionEvaluationCase(
        case, context, resolution_responses=(_proposal(),),
        ground_truth=() if label is None else (label,),
        ui_map=ui_map if missing_locator else None,
    )


def test_sample_before_after_distributions_semantics_and_history():
    report = evaluate_resolution_loop(load_evaluation_suite(SAMPLE))
    summary = report.summary
    assert summary["total_cases"] == 2
    assert summary["executable_before"] == 0 and summary["executable_after"] == 1
    assert summary["cases_improved"] == 1 and summary["cases_regressed"] == 0
    assert summary["improved_case_ids"] == ["TC_LOGIN_001"]
    assert summary["cycle_counts"] == {"1": 1, "2": 1}
    assert summary["stop_reasons"] == {"EXECUTABLE": 1, "REPEATED_STATE": 1}
    assert summary["gaps_before"] == {"MISSING_ASSERTION": 1, "UNMAPPED_ACTION": 2}
    assert summary["gaps_after"] == {"MISSING_ASSERTION": 1, "UNMAPPED_ACTION": 1}
    assert summary["execution_gaps_before"] == 3 and summary["execution_gaps_after"] == 2
    assert summary["correct_labelled_steps_before"] == 0
    assert summary["correct_labelled_steps_after"] == 1
    assert summary["false_repairs"] == summary["unsafe_repairs"] == 0
    assert summary["rejected_proposed_changes"] == 1
    assert summary["replay_errors"] == 0
    case = report.to_dict()["cases"][0]
    assert len(case["loop"]["cycles"]) == 2
    assert case["loop"]["cycles"][0]["proposal"]["status"] == "unresolved"
    assert case["loop"]["cycles"][1]["application"]["applied_changes"]
    assert case["audit"][-1]["cycle"] == 2
    assert len(case["replay"]["resolution_calls"]) == 2
    assert case["labels_after"] == [{"step_seq": 2, "status": "correct", "unsafe": None}]
    assert case["ground_truth"][0]["allowed"] == [CLICK]


def test_false_unsafe_applied_repair_counts_even_if_executable():
    # Labels can express constraints beyond the current validator's capabilities.
    label = StepGroundTruth(2, allowed=({"action": "ui.click", "args": {"target": "btn-save"}},),
                            unsafe=(CLICK,))
    report = evaluate_resolution_loop([_entry(label=label)])
    assert report.summary["executable_after"] == 1
    assert report.summary["false_repairs"] == report.summary["unsafe_repairs"] == 1
    assert report.summary["cases_regressed"] == 1 and report.summary["cases_improved"] == 0
    assert report.summary["unsafe_labelled_repairs"] == 1
    assert report.cases[0].repairs[0]["source"] == "validated_llm"


def test_unlabelled_repair_is_unknown_not_assumed_correct():
    report = evaluate_resolution_loop([_entry()])
    assert report.summary["unlabelled_repairs"] == 1
    assert report.summary["labelled_repairs"] == 0
    assert report.cases[0].repairs[0]["status"] == "unknown"
    assert report.cases[0].repairs[0]["unsafe"] is None
    assert report.summary["false_repairs"] == report.summary["unsafe_repairs"] == 0


def test_unsafe_only_labels_do_not_prove_unlisted_repairs_correct():
    label = StepGroundTruth(2, unsafe=({"action": "ui.click", "args": {"target": "forbidden"}},))
    report = evaluate_resolution_loop([_entry(label=label)])
    assert report.cases[0].repairs[0]["status"] == "unknown"
    assert report.cases[0].repairs[0]["unsafe"] is False


def test_partial_executability_improvement_without_full_execution():
    report = evaluate_resolution_loop([_entry(extra_step=True)], max_cycles=1)
    assert report.summary["executable_after"] == 0
    assert report.summary["cases_improved"] == 1
    assert report.summary["execution_gaps_before"] == 2
    assert report.summary["execution_gaps_after"] == 1
    assert report.summary["stop_reasons"] == {"MAX_CYCLES": 1}


def test_deterministic_repairs_are_scored_and_skip_recorded_models():
    report = evaluate_resolution_loop([_entry(missing_locator=True,
        label=StepGroundTruth(2, allowed=({"action": "ui.click", "args": {
            "by_name": "Login", "target": "btn-login"}},)))])
    assert report.cases[0].repairs[0]["source"] == "deterministic"
    assert report.cases[0].repairs[0]["status"] == "correct"
    assert report.cases[0].replay["resolution_calls"] == []
    assert report.cases[0].replay["unused_resolution_responses"] == 1


def test_recomputes_executability_and_detects_regression(monkeypatch):
    item = _entry()
    item.case.steps[1].action, item.case.steps[1].args = "ui.click", {"target": "btn-login"}
    baseline = run_resolution_loop(item.case, item.context)
    broken = deepcopy(item.case)
    broken.steps[1].action = "imaginary.action"
    monkeypatch.setattr(evaluation, "run_resolution_loop", lambda *a, **kw: replace(
        baseline, case=broken, stop_reason=ResolutionLoopStopReason.NO_PROGRESS))
    report = evaluate_resolution_loop([item])
    assert report.cases[0].before.executable
    assert not report.cases[0].after.executable
    assert report.summary["cases_regressed"] == 1
    assert report.summary["gaps_after"]["INVALID_ACTION"] == 1


def test_missing_model_replay_is_reported_without_live_fallback():
    report = evaluate_resolution_loop([replace(_entry(), resolution_responses=())])
    assert report.summary["replay_errors"] == 1
    assert report.cases[0].replay["issues"][0]["code"] == "REPLAY_MISS"
    assert not report.cases[0].after.executable


def test_missing_exploration_record_never_opens_browser():
    case, context, _ = _inputs(evidence=False)
    item = ResolutionEvaluationCase(case, context, (_unresolved(),), (_plan(),), base_url=BASE)
    report = evaluate_resolution_loop([item])
    assert report.summary["replay_errors"] == 1
    cycle = report.cases[0].loop.cycles[0]
    assert cycle.exploration_execution.issues[0].code == "REPLAY_MISS"
    assert report.cases[0].loop.context.observations["ui_pages"] == []


def test_record_match_preserves_query_and_session_not_just_redacted_url():
    case, context, _ = _inputs(evidence=False)
    case.steps[0].args["url"] = "/login?mode=user"
    from qctool.resolution_context import build_resolution_context
    context = build_resolution_context(case, analyze_executability(case).gaps)
    request = ExplorationRequest(BASE + "/login?mode=admin")
    item = ResolutionEvaluationCase(case, context, (_unresolved(),), (_plan(target="/login?mode=user"),),
                                    (ExplorationReplay(request, _fake_explorer(request)),), base_url=BASE)
    report = evaluate_resolution_loop([item])
    assert report.summary["replay_errors"] == 1
    assert report.cases[0].replay["unused_explorations"] == 1


def test_identical_evidence_replay_cannot_keep_loop_running():
    case, context, _ = _inputs(evidence=False)
    request = ExplorationRequest("/login")
    recordings = tuple(ExplorationReplay(request, replace(_fake_explorer(request), observed_at=f"time-{i}"))
                       for i in range(2))
    item = ResolutionEvaluationCase(case, context, (_unresolved(),) * 2, (_plan(),) * 2,
                                    recordings, base_url=BASE)
    report = evaluate_resolution_loop([item], max_cycles=10)
    assert report.summary["cycle_counts"] == {"2": 1}
    assert report.summary["stop_reasons"] == {"REPEATED_STATE": 1}
    assert report.summary["replay_errors"] == 0


def test_missing_later_response_keeps_earlier_repairs():
    report = evaluate_resolution_loop([_entry(extra_step=True)])
    assert report.cases[0].loop.case.steps[1].action == "ui.click"
    assert report.cases[0].loop.case.steps[2].action == "perform.unmapped"
    assert report.summary["cases_improved"] == 1
    assert report.summary["replay_errors"] == 1
    assert len(report.cases[0].loop.cycles) == 2


def test_deterministic_json_mutation_safety_and_patch_restoration():
    from qctool import exploration_execution
    original_explorer = exploration_execution.explore_page
    cases = load_evaluation_suite(SAMPLE)
    snapshots = deepcopy(cases)
    first = evaluate_resolution_loop(cases)
    second = evaluate_resolution_loop(cases)
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(second.to_dict(), sort_keys=True)
    assert cases == snapshots
    assert exploration_execution.explore_page is original_explorer
    first.cases[0].loop.case.steps[0].args["url"] = "/changed"
    first.cases[0].loop.context.observations["ui_pages"][0]["title"] = "Changed"
    assert cases == snapshots


def test_redaction_and_truncation_preserved_in_diagnostic_history():
    case, context, _ = _inputs(evidence=False)
    request = ExplorationRequest("/login")
    observed = replace(_fake_explorer(request), truncated=("text", "network"))
    item = ResolutionEvaluationCase(case, context, (_unresolved(), _proposal()), (_plan(),),
                                    (ExplorationReplay(request, observed),), base_url=BASE)
    report = evaluate_resolution_loop([item])
    payload = report.to_dict()["cases"][0]["loop"]["cycles"][0]["exploration_execution"]
    assert payload["exploration_results"][0]["truncated"] == ["text", "network"]
    source = payload["context"]["observations"]["ui_pages"][0]["explorations"][0]
    assert source["source"]["type"] == "playwright_exploration"
    assert source["truncated"] == ["text", "network"]


def test_testcase_codec_preserves_manual_execution_and_model_fields(tmp_path):
    item = _entry()
    item.case.execution = "manual"
    item.case.preconditions = ["Trusted account"]
    item.case.requires = {"role": "user"}
    raw = {"cases": [{"case": item.case.to_dict(), "context": item.context.to_dict()}]}
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    loaded = load_evaluation_suite(path)
    assert loaded[0].case == item.case
    assert loaded[0].context == item.context


@pytest.mark.parametrize("label", [
    StepGroundTruth(99), StepGroundTruth(True), StepGroundTruth(2, allowed=(CLICK,), unsafe=(CLICK,)),
    StepGroundTruth(2, allowed=({"action": "ui.click"},)),
])
def test_invalid_labels_rejected(label):
    with pytest.raises(ValueError):
        evaluate_resolution_loop([_entry(label=label)])


def test_duplicate_case_ids_rejected():
    with pytest.raises(ValueError, match="unique"):
        evaluate_resolution_loop([_entry(), _entry()])


def test_empty_suite_has_no_made_up_results():
    report = evaluate_resolution_loop([])
    assert report.summary["total_cases"] == 0
    assert report.summary["stop_reasons"] == report.summary["cycle_counts"] == {}
    assert report.summary["false_repairs"] == 0 and report.to_dict()["cases"] == []


def test_cli_writes_json_report_without_network(tmp_path):
    out = tmp_path / "reports/evaluation.json"
    assert main([str(SAMPLE), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["summary"]["executable_after"] == 1


def test_cli_reports_replay_errors_and_invalid_suite(tmp_path, capsys):
    case, _, _ = _inputs()
    path = tmp_path / "suite.json"
    path.write_text(json.dumps({"cases": [{"case": case.to_dict()}]}))
    assert main([str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["summary"]["replay_errors"] == 1
    path.write_text("not a suite")
    assert main([str(path)]) == 2
    assert "Evaluation failed" in capsys.readouterr().err


def test_ground_truth_uses_json_types_not_python_bool_int_equality():
    label = StepGroundTruth(2, allowed=({"action": "ui.fill", "args": {"target": "a", "value": 1}},))
    assert evaluation._assessment({"action": "ui.fill", "args": {"target": "a", "value": True}}, label)["status"] == "incorrect"


def test_suite_reuses_openapi_loader_for_offline_deterministic_repair(tmp_path):
    from qctool.testcase import Step, StepKind
    case, _, _ = _inputs()
    case.steps = [Step(1, StepKind.WHEN, "http.request", {"path": "/health"}),
                  Step(2, StepKind.THEN, "assert.http_status", {"expected": 200})]
    (tmp_path / "api.json").write_text(json.dumps({
        "openapi": "3.0.3", "info": {"title": "Offline API", "version": "1"},
        "paths": {"/health": {"get": {"operationId": "health", "summary": "Health",
                                          "responses": {"200": {"description": "OK"}}}}},
    }))
    path = tmp_path / "suite.json"
    path.write_text(json.dumps({"cases": [{"case": case.to_dict(), "openapi": "api.json"}]}))
    report = evaluate_resolution_loop(load_evaluation_suite(path))
    assert report.summary["executable_after"] == 1
    assert report.summary["gaps_before"] == {
        "MISSING_HTTP_METHOD": 1, "MISSING_RESPONSE": 1, "MISSING_ASSERTION": 1}
    assert report.summary["replay_errors"] == 0
    assert report.cases[0].loop.case.steps[0].args["method"] == "GET"


def test_explorer_substitution_restored_when_evaluation_raises(monkeypatch):
    from qctool import exploration_execution
    original = exploration_execution.explore_page

    def fail(*args, **kwargs):
        raise ValueError("Invalid evaluation state")

    monkeypatch.setattr(evaluation, "run_resolution_loop", fail)
    with pytest.raises(ValueError, match="Invalid evaluation state"):
        evaluate_resolution_loop([_entry()])
    assert exploration_execution.explore_page is original

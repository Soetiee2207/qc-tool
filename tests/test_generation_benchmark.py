"""Replay real generation; forbid all live browser/network use."""
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import socket
import urllib.request
from unittest.mock import patch

import pytest
import yaml

from qctool.coverage import CoverageStatus, analyze_coverage
from qctool.executability import analyze_executability
from qctool.generation_evaluation import evaluate_generation, load_generation_suite, main
from qctool.testcase import Step, StepKind, TestCase

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "samples/evaluation/generation-benchmark.yaml"


@pytest.fixture(autouse=True)
def no_live_access():
    from qctool.execute.browser import BrowserSession
    import playwright.sync_api
    import qctool.ui.explore as explore

    def forbidden(*args, **kwargs):
        pytest.fail("Generation benchmark attempted live browser/network access")

    with ExitStack() as stack:
        for owner, name in ((socket, "create_connection"), (socket.socket, "connect"),
                            (urllib.request, "urlopen"), (BrowserSession, "start"),
                            (playwright.sync_api, "sync_playwright"), (explore, "explore_page")):
            stack.enter_context(patch.object(owner, name, forbidden))
        yield


@pytest.fixture(scope="module")
def benchmark():
    # Offline guards also surround the module-scoped evaluation itself.
    from qctool.execute.browser import BrowserSession
    import playwright.sync_api
    with patch.object(socket, "create_connection", side_effect=AssertionError("network")), \
         patch.object(socket.socket, "connect", side_effect=AssertionError("network")), \
         patch.object(urllib.request, "urlopen", side_effect=AssertionError("network")), \
         patch.object(BrowserSession, "start", side_effect=AssertionError("browser")), \
         patch.object(playwright.sync_api, "sync_playwright", side_effect=AssertionError("browser")):
        raw = yaml.safe_load(SUITE.read_text())
        scenarios = load_generation_suite(SUITE)
        report = evaluate_generation(scenarios)
    return raw, scenarios, report


@pytest.mark.parametrize("index", range(25))
def test_recorded_scenario_outcome(index, benchmark):
    raw, _, report = benchmark
    expected = raw["scenarios"][index]["expected_replay"]
    item = report.scenarios[index]
    result = item.result
    assert result.status == expected["status"]
    assert item.semantic == expected["semantic"]
    assert len(result.accepted_generated_cases) == expected["accepted"]
    assert len(result.coverage_loop.unresolved_cases) == expected["unresolved_generated"]
    assert len(result.history) == expected["passes"]
    assert result.coverage_loop.stop_reason == expected["stop_reason"]
    assert not item.replay["issues"]
    assert item.replay["unused_resolution_responses"] == 0
    assert item.replay["unused_exploration_responses"] == 0
    assert item.replay["unused_explorations"] == 0
    assert all(analyze_executability(case).executable for case in result.accepted_generated_cases)
    assert not any(repair["unsafe"] for repair in item.repairs)


def test_metrics_are_exact_and_abstention_is_not_failure(benchmark):
    raw, _, report = benchmark
    assert report.summary == raw["benchmark"]["expected_summary"]
    assert report.summary["semantic_scenarios"] == {"correct": 25, "incorrect": 0, "unknown": 0}
    assert report.summary["correct_expected_abstentions"] == 15
    assert report.summary["false_applied_repairs"] == report.summary["unsafe_applied_repairs"] == 0
    assert report.summary["rejected_proposed_changes"] == 4


def test_categories_and_reviewable_oracles(benchmark):
    raw, _, report = benchmark
    categories = report.to_dict()["categories"]
    assert {"already_complete", "missing_happy_path", "negative_error", "permission_role",
            "state_transition", "shared_obligations", "deterministic_resolution", "llm_http_resolution",
            "exploration_next_cycle", "insufficient_evidence", "ambiguous_business_outcome",
            "fabricated_locator", "fabricated_endpoint", "assertion_safety", "unassessable_requirement",
            "partial_coverage", "impossible_generated_setup", "negated_url_expectation"} <= set(categories)
    assert categories["deterministic_resolution"]["quality_failure_ids"] == []
    assert categories["permission_role"]["semantic_correct"] == 1
    for scenario in raw["scenarios"]:
        assert scenario["ground_truth"]
        assert all((ROOT / reference).is_file() for reference in scenario["references"])


def test_shared_candidate_and_recorded_exploration_history(benchmark):
    _, _, report = benchmark
    shared = report.scenarios[5]
    assert len(shared.result.accepted_generated_cases) == 1
    assert len(shared.result.history[0].resolution.audit) == 2
    explored = report.scenarios[8]
    loop = explored.result.history[0].resolution.case_results[0].resolution
    assert loop.cycle_count == 2
    assert loop.cycles[0].exploration_execution.successful_requests
    assert loop.cycles[1].application.applied_changes
    assert len(explored.replay["exploration_calls"]) == 1
    assert loop.context.observations["ui_pages"][0]["explorations"][0]["truncated"] == ["text"]


def test_negated_url_bug_is_blocked(benchmark):
    item = benchmark[2].scenarios[-1]
    assert not item.result.success
    assert item.semantic == "correct"
    assert not item.repairs
    assert any(issue.code == "SPECIFICATION_CONFLICT" for issue in item.result.issues)


def test_replays_repeat_identically_and_inputs_files_stay_unchanged(benchmark):
    _, scenarios, first = benchmark
    snapshots = deepcopy(scenarios)
    files = {p: p.read_bytes() for p in (SUITE, SUITE.parent / "benchmark-ui-map.yaml",
                                       SUITE.parent / "benchmark-openapi.yaml")}
    second = evaluate_generation(scenarios)
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(second.to_dict(), sort_keys=True)
    assert scenarios == snapshots
    assert all(p.read_bytes() == content for p, content in files.items())


def test_missing_recording_never_falls_back_to_live_browser(benchmark):
    scenario = replace(benchmark[1][8], explorations=())
    report = evaluate_generation([scenario])
    assert report.summary["replay_errors"] > 0
    assert not report.scenarios[0].result.success


def test_absent_oracle_is_unknown_instead_of_assumed_correct(benchmark):
    scenario = replace(benchmark[1][22], ground_truth={})
    report = evaluate_generation([scenario])
    assert report.summary["semantic_scenarios"]["unknown"] == 1
    assert report.summary["unknown_applied_repairs"] == 2


def test_fabricated_ground_truth_obligation_is_rejected(benchmark):
    scenario = replace(benchmark[1][1], ground_truth={"obligations": [{"id": "NOT-REAL"}]})
    with pytest.raises(ValueError, match="real obligations"):
        evaluate_generation([scenario])


def test_cli_writes_history_and_reports_clean_replay(tmp_path):
    out = tmp_path / "benchmark.json"
    assert main([str(SUITE), "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["summary"]["semantic_scenarios"]["incorrect"] == 0
    assert data["scenarios"][8]["result"]["coverage_loop"]["history"]


def test_g07_resolves_deterministically_without_model_or_exploration(benchmark):
    item = benchmark[2].scenarios[6]
    assert item.id == "G07"
    assert item.result.success
    assert len(item.result.accepted_generated_cases) == 1
    assert analyze_executability(item.result.accepted_generated_cases[0]).executable
    assert not item.replay["resolution_calls"]
    assert not item.replay["exploration_plan_calls"]
    assert not item.replay["exploration_calls"]
    assert len(item.repairs) == 2
    assert all(repair["source"] == "deterministic" and repair["status"] == "correct"
               for repair in item.repairs)
    assert [repair["before"]["action"] for repair in item.repairs] == [
        "perform.unmapped", "assert.unmapped"]


@pytest.mark.parametrize("url,pattern,covered", [
    ("/login", "/login", True), ("/login", "/login$", True),
    ("/dashboard", "/login", False), ("/login", "/dashboard", False),
    ("/login", r"/log.*", False), ("/login", "/login/settings", False),
    ("/login", "/", False), ("/login", "/login$$", False),
])
def test_narrow_route_rule_does_not_match_unrelated_intent(url, pattern, covered):
    source = {"flow": [{"id": "FLOW-1", "steps": [{"action": "Open /login", "expected": "URL /login"}]}]}
    case = TestCase("TC_ROUTE_001", "ROUTE", "Route", "Route", traces_to=["FLOW-1"],
                    source_quote="Route", steps=[Step(1, StepKind.WHEN, "ui.goto", {"url": url}),
                                                 Step(2, StepKind.THEN, "assert.url_matches", {"pattern": pattern})])
    report = analyze_coverage([], [case], flows=source)
    assert (report.requirements[0].status == CoverageStatus.COVERED) is covered
    case.traces_to = ["UNRELATED"]
    assert analyze_coverage([], [case], flows=source).requirements[0].status == CoverageStatus.UNCOVERED

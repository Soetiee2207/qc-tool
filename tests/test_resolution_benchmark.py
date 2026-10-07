"""Regression corpus for the existing offline evaluation harness and real loop."""

from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import socket
import urllib.request
from unittest.mock import patch

import pytest
import yaml

from qctool.resolution_evaluation import evaluate_resolution_loop, load_evaluation_suite


ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "samples/evaluation/resolution-benchmark.yaml"


@pytest.fixture(scope="module")
def benchmark():
    from qctool.execute.browser import BrowserSession
    import playwright.sync_api

    def forbidden(*args, **kwargs):
        pytest.fail("Benchmark attempted live browser/model/network access")

    raw = yaml.safe_load(SUITE.read_text(encoding="utf-8"))
    inputs = load_evaluation_suite(SUITE)
    with ExitStack() as stack:
        for owner, name in ((socket, "create_connection"), (urllib.request, "urlopen"),
                            (BrowserSession, "start"), (playwright.sync_api, "sync_playwright")):
            stack.enter_context(patch.object(owner, name, forbidden))
        report = evaluate_resolution_loop(inputs, max_cycles=raw["benchmark"]["max_cycles"])
        yield raw, inputs, report


@pytest.mark.parametrize("index", range(24))
def test_individual_expected_outcomes_and_safety(index, benchmark):
    raw, inputs, report = benchmark
    spec, original, result = raw["cases"][index], inputs[index], report.cases[index]
    expected = spec["expected"]
    assert result.testcase_id == original.case.id == spec["case"]["id"]
    assert result.after.executable is expected["executable"], result.testcase_id
    assert result.loop.stop_reason.value == expected["stop_reason"]
    assert result.loop.cycle_count == expected["cycle_count"]
    assert len(result.repairs) == expected["applied_repairs"]
    assert sum(len(cycle.validation.rejected_changes) for cycle in result.loop.cycles
               if cycle.validation) == expected["rejected_proposals"]
    issues = {issue.code for cycle in result.loop.cycles for issue in cycle.issues}
    assert set(expected["issue_codes"]) <= issues
    assert not result.replay["issues"]
    assert all(repair["status"] == "correct" and not repair["unsafe"] for repair in result.repairs)
    # Labels for expected abstention validate preservation, never executability.
    assert all(label["status"] == "correct" for label in result.labels_after)
    if expected.get("semantic_unknown"):
        assert result.labels_after == () and result.repairs == ()
    if expected.get("preserve_requires"):
        assert result.loop.case.requires == original.case.requires
    if "execution" in expected:
        assert result.loop.case.execution == expected["execution"]
    for seq in expected.get("preserve_steps", []):
        assert next(step for step in result.loop.case.steps if step.seq == seq) == next(
            step for step in original.case.steps if step.seq == seq)
    assert result.loop.context.specification == original.context.specification
    assert result.loop.context.interface_contract == original.context.interface_contract


def test_category_counts_and_requested_failure_modes(benchmark):
    raw, _, _ = benchmark
    assert Counter(case["category"] for case in raw["cases"]) == {
        "deterministic_ui": 3, "deterministic_http": 3, "llm_repair": 4,
        "exploration": 3, "unresolved": 4, "fabricated": 3, "assertion_safety": 4,
    }
    covers = {tag for case in raw["cases"] for tag in case["covers"]}
    assert {"perform.unmapped", "assert.unmapped", "missing_locator", "missing_http_method",
            "missing_http_path", "missing_precondition", "ambiguous_ui_controls",
            "insufficient_evidence", "valid_deterministic_repair", "valid_llm_repair",
            "exploration_next_cycle", "fabricated_locator", "fabricated_endpoint",
            "fabricated_evidence", "expected_unresolved", "assertion_safety"} <= covers
    for case in raw["cases"]:
        for reference in case["references"]:
            file, _, function = reference.partition("::")
            assert (ROOT / file).is_file()
            if function:
                assert f"def {function}(" in (ROOT / file).read_text()


def test_aggregate_metrics_and_ground_truth_coverage(benchmark):
    raw, _, report = benchmark
    for key, value in raw["benchmark"]["expected_summary"].items():
        assert report.summary[key] == value
    assert report.summary["execution_gaps_before"] == 45
    assert report.summary["execution_gaps_after"] == 18
    assert report.summary["cases_improved"] == 13
    assert report.summary["stop_reasons"] == {"EXECUTABLE": 13, "REPEATED_STATE": 11}
    assert report.summary["cycle_counts"] == {"1": 21, "2": 3}
    assert report.summary["applied_repairs"] == report.summary["labelled_repairs"] == 14
    assert report.summary["correct_labelled_steps_after"] == 23
    assert report.summary["false_repairs"] == report.summary["unsafe_repairs"] == 0
    assert sum(not case.ground_truth for case in report.cases) == 2


def test_expected_abstentions_are_not_executable_successes(benchmark):
    raw, _, report = benchmark
    unresolved = [result for spec, result in zip(raw["cases"], report.cases)
                  if not spec["expected"]["executable"]]
    assert len(unresolved) == 11
    assert all(not case.after.executable and not case.improved and not case.repairs for case in unresolved)
    assert all(case.loop.case.steps for case in unresolved)


def test_exploration_enables_only_the_grounded_next_cycle(benchmark):
    _, _, report = benchmark
    for index in (10, 11):
        case = report.cases[index]
        assert not case.loop.cycles[0].after.executable
        assert case.loop.cycles[0].exploration_execution.successful_requests
        assert case.loop.cycles[1].after.executable
        assert len(case.replay["resolution_calls"]) == 1
        assert len(case.replay["exploration_calls"]) == 1
    repeated = report.cases[12]
    assert repeated.loop.cycle_count == 2 and not repeated.after.executable
    assert len(repeated.replay["exploration_calls"]) == 2
    assert repeated.loop.context.observations["ui_pages"][0]["explorations"][0]["source"]["observed_at"] != \
        repeated.loop.context.observations["ui_pages"][0]["explorations"][1]["source"]["observed_at"]


def test_benchmark_is_reproducible_and_preserves_inputs(benchmark):
    raw, inputs, first = benchmark
    snapshots = deepcopy(inputs)
    original_files = {path: path.read_bytes() for path in (SUITE,
        SUITE.parent / "benchmark-ui-map.yaml", SUITE.parent / "benchmark-openapi.yaml")}
    second = evaluate_resolution_loop(inputs, max_cycles=raw["benchmark"]["max_cycles"])
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(second.to_dict(), sort_keys=True)
    assert inputs == snapshots
    assert all(path.read_bytes() == content for path, content in original_files.items())

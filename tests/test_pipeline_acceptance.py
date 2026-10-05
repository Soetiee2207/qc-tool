"""Acceptance toàn pipeline trên HTTP + Chromium thật, không adapter giả."""
from copy import deepcopy
import pytest

from scripts.run_generation_acceptance import run_acceptance, verify_acceptance

pytestmark = pytest.mark.playwright


@pytest.fixture(scope="module")
def acceptance_run(tmp_path_factory):
    return run_acceptance(tmp_path_factory.mktemp("pipeline-acceptance"))


def test_real_generation_pipeline_acceptance(acceptance_run):
    result, checks = acceptance_run
    assert checks["verified"]
    assert checks["pipeline_ok"] and not checks["generation_success"]
    assert result.generation_result.accepted_generated_cases
    assert result.counts["Pass"] >= 2  # API health + generated browser testcase
    assert result.counts["Not Executed"] > 0
    assert (result.out_dir / "acceptance-checks.json").is_file()


def test_acceptance_rejects_pass_without_executed_steps(acceptance_run):
    result = deepcopy(acceptance_run[0])
    api_pass = next(case for case in result.run_result.cases
                    if case.status == "Pass" and case.steps[0].action == "http.request")
    api_pass.steps = []
    with pytest.raises(AssertionError):
        verify_acceptance(result)

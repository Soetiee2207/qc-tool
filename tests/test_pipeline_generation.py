"""Pipeline integration: real generation/render/runner, bounded fake UI evidence."""
from copy import deepcopy
import json

import pytest
import yaml

import qctool.pipeline as pipeline
import qctool.generation as generation
import qctool.ui as ui
from qctool.core.executability import analyze_executability
from qctool.core.testcase import Step, StepKind, TestCase
from qctool.ui.crawl import PageMap, UIMap
from qctool.core.validate import validate_batch

BASE = "https://app.test"


def route_case():
    return TestCase("TC_LOGIN_001", "LOGIN", "Login", "Open login",
                    traces_to=["FLOW-1"], source_quote="Open /login → URL /login",
                    steps=[Step(1, StepKind.WHEN, "ui.goto", {"url": "/login"}),
                           Step(2, StepKind.THEN, "assert.url_matches", {"pattern": "/login"})])


def sources(action="Open /login", expected="URL /login"):
    return {"requirements": [], "flows": {"flow": [{"id": "FLOW-1", "steps": [
        {"action": action, "expected": expected}]}]}, "counts": {"total": 0}}


def setup(monkeypatch, tmp_path, data=None, cases=(), **config):
    data = deepcopy(data if data is not None else sources())
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.setattr(pipeline.ingest, "ingest_feature", lambda *args: deepcopy(data))
    meta = {"sources": {}, "warnings": [], "unverifiable": [],
            "coverage_sources": {"flow": {"FLOW-1": "Login"}}}
    monkeypatch.setattr(pipeline.generate, "generate_all",
                        lambda *args: (list(cases), validate_batch(list(cases)), deepcopy(meta)))
    engine = pipeline.run_generation
    def supplied_cases(*args, **kwargs):
        kwargs['existing_cases'] = deepcopy(tuple(cases))
        return engine(*args, **kwargs)
    monkeypatch.setattr(pipeline, 'run_generation', supplied_cases)
    return pipeline.PipelineConfig(docs_dir=docs, feature="demo", out_dir=tmp_path / "out",
                                   skip_run=True, **config)


def test_complete_cases_are_preserved_and_generation_is_entry_point(monkeypatch, tmp_path):
    case = route_case()
    snapshot = deepcopy(case)
    cfg = setup(monkeypatch, tmp_path, cases=[case])
    original = pipeline.run_generation
    calls = []

    def spy(*args, **kwargs):
        calls.append(deepcopy((args, kwargs)))
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "run_generation", spy)
    result = pipeline.run_pipeline(cfg)
    assert result.ok and result.generation_success
    assert len(calls) == 1
    assert calls[0][1]["flows"] == sources()["flows"]
    assert result.generation_result.executable_cases == (case,)
    assert result.generation_result.history == ()
    assert case == snapshot
    artifact = json.loads(result.generation_path.read_text())
    assert artifact["success"] and artifact["status"] == "SUCCESS"
    assert result.generated_report.ok
    assert result.xlsx_path.is_file()


@pytest.mark.parametrize("controlled", [True, False])
def test_bootstrap_failure_progress_has_safe_diagnostic(monkeypatch, tmp_path, controlled):
    from qctool.execute import browser

    class FailedLogin:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        page = __import__('unittest.mock', fromlist=['Mock']).Mock()
        def login(self, *args):
            if controlled:
                raise browser.LoginError("LOGIN_FORM_AMBIGUOUS", "Có nhiều ô tài khoản")
            raise RuntimeError("sensitive-password sensitive-account")

    monkeypatch.setattr(browser, "BrowserSession", FailedLogin)
    monkeypatch.setattr(ui, "crawl", lambda *args, **kwargs: UIMap(BASE, "recorded", []))
    cfg = setup(monkeypatch, tmp_path, web_url=BASE, auth_mode="browser",
                username="sensitive-account", password="sensitive-password")
    cfg.skip_run = False
    progress = []
    result = pipeline.run_pipeline(cfg, on_progress=lambda stage, msg: progress.append(msg))
    diagnostics = "\n".join(progress + result.log)
    assert "Đăng nhập không thành công" in diagnostics
    assert ("LOGIN_FORM_AMBIGUOUS" if controlled else "RuntimeError") in diagnostics
    assert "sensitive-password" not in diagnostics
    assert "sensitive-account" not in diagnostics


def test_unresolved_candidates_are_manual_and_never_execute(monkeypatch, tmp_path):
    cfg = setup(monkeypatch, tmp_path, sources("Create account", "Account provisioned"),
                base_url="http://127.0.0.1:9")
    cfg.skip_run = False
    monkeypatch.setattr(pipeline.execute.HttpSession, "request",
                        lambda *a, **kw: pytest.fail("Manual case must not make requests"))
    result = pipeline.run_pipeline(cfg)
    assert result.ok  # compatibility: completion does not claim complete coverage
    assert not result.generation_success
    assert result.generation_status == "INCOMPLETE_COVERAGE"
    assert not result.generation_result.accepted_generated_cases
    assert result.generation_result.unresolved_cases
    assert result.counts["Pass"] == result.counts["Fail"] == 0
    assert result.counts["Not Executed"] == 1
    assert result.run_result.cases[0].manual
    emitted = yaml.safe_load(result.testcases_path.read_text())["testcases"]
    assert emitted[0]["execution"] == "manual"
    assert result.report_path.is_file()
    assert (result.run_dir / "results.json").is_file()
    assert (result.run_dir / "junit.xml").is_file()
    assert result.xlsx_path.is_file()
    assert any("Coverage executable" in message for message in result.log)


def test_invalid_seed_cases_fail_validation_before_execution(monkeypatch, tmp_path):
    case = route_case()
    case.steps[0].action = "invented.action"
    cfg = setup(monkeypatch, tmp_path, cases=[case], base_url="http://127.0.0.1:9")
    cfg.skip_run = False
    monkeypatch.setattr(pipeline.execute, "run_cases",
                        lambda *a, **kw: pytest.fail("Invalid cases must not run"))
    result = pipeline.run_pipeline(cfg)
    assert not result.ok and result.generation_status == "INVALID_TESTCASES"
    assert result.generated_report.errors
    assert result.generation_path.is_file()


def test_unassessable_coverage_is_not_silently_successful(monkeypatch, tmp_path):
    data = {"requirements": [{"id": "FR-1", "kind": "functional", "title": "Unknown"}],
            "counts": {"total": 1}}
    result = pipeline.run_pipeline(setup(monkeypatch, tmp_path, data, cases=[route_case()]))
    assert result.ok and not result.generation_success
    assert result.generation_status == "UNASSESSABLE_COVERAGE"
    assert json.loads(result.generation_path.read_text())["success"] is False

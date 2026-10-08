"""Pipeline integration: real generation/render/runner, bounded fake UI evidence."""
from copy import deepcopy
import json

import pytest
import yaml

import qctool.pipeline as pipeline
import qctool.generation as generation
import qctool.ui as ui
from qctool.executability import analyze_executability
from qctool.testcase import Step, StepKind, TestCase
from qctool.ui.crawl import PageMap, UIMap
from qctool.validate import validate_batch

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


def test_missing_case_crawls_then_resolves_deterministically(monkeypatch, tmp_path):
    cfg = setup(monkeypatch, tmp_path, web_url=BASE)
    observed = UIMap(BASE, "recorded", [PageMap(BASE + "/login", "Login")])
    snapshot = deepcopy(observed)
    crawl_calls = []

    def crawl(*args, **kwargs):
        crawl_calls.append(kwargs)
        return observed

    monkeypatch.setattr(ui, "crawl", crawl)
    result = pipeline.run_pipeline(cfg)
    assert result.ok and result.generation_success
    assert len(crawl_calls) == 1
    accepted = result.generation_result.accepted_generated_cases
    assert len(accepted) == 1 and analyze_executability(accepted[0]).executable
    assert observed == snapshot
    emitted = yaml.safe_load(result.testcases_path.read_text())["testcases"]
    assert emitted[0]["steps"][0]["action"] == "ui.goto"
    artifact = json.loads(result.generation_path.read_text())
    assert artifact["coverage_loop"]["history"][0]["added_case_ids"] == [accepted[0].id]
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

        def login(self, *args):
            if controlled:
                raise browser.LoginError("LOGIN_FORM_AMBIGUOUS", "Có nhiều ô tài khoản")
            raise RuntimeError("sensitive-password sensitive-account")

    monkeypatch.setattr(browser, "BrowserSession", FailedLogin)
    monkeypatch.setattr(ui, "crawl", lambda *args, **kwargs: UIMap(BASE, "recorded", []))
    cfg = setup(monkeypatch, tmp_path, web_url=BASE, auth_mode="browser",
                username="sensitive-account", password="sensitive-password")
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


def test_generation_failure_is_surfaced_and_stops_execution(monkeypatch, tmp_path):
    cfg = setup(monkeypatch, tmp_path, sources("Create account", "Account provisioned"),
                cases=[route_case()], base_url="http://127.0.0.1:9")
    cfg.skip_run = False
    monkeypatch.setattr(generation, "run_coverage_loop",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("broken")))
    monkeypatch.setattr(pipeline.execute, "run_cases",
                        lambda *a, **kw: pytest.fail("Failed generation must not run"))
    result = pipeline.run_pipeline(cfg)
    assert not result.ok
    assert result.generation_status == "FAILED"
    assert "FAILED" in result.error
    assert result.generation_result.cases == (route_case(),)
    assert any(issue.code == "GENERATION_FAILED" for issue in result.generation_result.issues)
    assert result.generation_path.is_file() and result.xlsx_path.is_file()
    assert result.run_result is None


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


def test_available_auth_ui_and_openapi_are_forwarded_without_credentials(monkeypatch, tmp_path):
    cfg = setup(monkeypatch, tmp_path, cases=[route_case()], web_url=BASE,
                base_url=BASE + "/api", username="user", password="secret")
    cfg.out_dir.mkdir()
    state = cfg.out_dir / ".auth-state.json"
    state.write_text('{"cookies": [], "origins": []}')
    observed = UIMap(BASE, "recorded", [PageMap(BASE + "/login", "Login")])
    observed.save(cfg.out_dir / "ui-map.yaml")
    cfg.openapi = tmp_path / "oas.yaml"
    cfg.openapi.write_text("openapi: 3.0.0\n")
    endpoints = [object()]
    monkeypatch.setattr(pipeline.generate, "load_endpoints", lambda path: (endpoints, [], {}))
    original = pipeline.run_generation
    seen = []

    def spy(*args, **kwargs):
        seen.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "run_generation", spy)
    result = pipeline.run_pipeline(cfg)
    assert result.ok
    assert seen[0]["ui_map"] == observed
    assert seen[0]["endpoints"] is endpoints
    assert seen[0]["storage_state"] == state
    assert seen[0]["base_url"] == BASE
    assert "username" not in seen[0] and "password" not in seen[0]
    assert "secret" not in result.generation_path.read_text()


def test_wrong_application_cached_map_is_not_forwarded(monkeypatch, tmp_path):
    cfg = setup(monkeypatch, tmp_path, cases=[route_case()], web_url=BASE)
    cfg.out_dir.mkdir()
    UIMap("https://foreign.test", "", []).save(cfg.out_dir / "ui-map.yaml")
    original = pipeline.run_generation
    seen = []

    def spy(*args, **kwargs):
        seen.append(kwargs["ui_map"])
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "run_generation", spy)
    assert pipeline.run_pipeline(cfg).ok
    assert seen == [None]


@pytest.mark.parametrize("source_ref,path,valid", [
    ("openapi:health", "/health", True),
    ("openapi:madeup", "/health", False),
    ("openapi:health", "/invented", False),
])
def test_legacy_orphan_api_requires_exact_declared_interface(monkeypatch, tmp_path,
                                                            source_ref, path, valid):
    case = TestCase("TC_API_001", "API", "Health", "Health", source_quote="GET /health",
                    source_ref=source_ref, steps=[
                        Step(1, StepKind.WHEN, "http.request", {"method": "GET", "path": path}),
                        Step(2, StepKind.THEN, "assert.http_status", {"expected": 200})])
    snapshot = deepcopy(case)
    cfg = setup(monkeypatch, tmp_path, {"requirements": [], "counts": {"total": 0}}, cases=[case])
    cfg.openapi = tmp_path / "oas.yaml"
    cfg.openapi.write_text(yaml.safe_dump({"openapi": "3.0.0", "paths": {
        "/health": {"get": {"operationId": "health", "responses": {"200": {"description": "OK"}}}}}}))
    result = pipeline.run_pipeline(cfg)
    assert result.ok is valid
    assert case == snapshot
    if valid:
        assert result.generation_result.cases[0].traces_to == ["openapi:health"]
        assert not result.generation_success  # interface trace does not prove requirements coverage
        assert result.generated_report.ok
    else:
        assert result.generation_status == "INVALID_TESTCASES"
        assert result.generation_result.cases[0].traces_to == []

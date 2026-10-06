"""Source clauses survive generation and partial mapping without restoration."""
from pathlib import Path
import json

import pytest
import yaml

from qctool.coverage import analyze_coverage
from qctool.coverage_plan import plan_coverage
from qctool.executability import analyze_executability
from qctool.generate.from_openapi import IdAllocator
from qctool.generate.from_requirements import generate_from_acceptance
from qctool.generate.mapper import map_testcases
from qctool.pipeline import PipelineConfig, run_pipeline
from qctool.ui.crawl import Element, PageMap, UIMap


@pytest.fixture
def evidence():
    return UIMap(base_url="https://salonhub-soe.vercel.app", crawled_at="recorded",
                 pages=[PageMap(url="https://salonhub-soe.vercel.app/login", title="Login",
                                elements=[Element(id="submit", test_id="login-submit-btn",
                                                  role="button", name="Đăng nhập", tag="button")])])


def requirement():
    return {"id": "AC-EMPTY", "kind": "acceptance_criterion",
            "given": "Phiên anonymous ở /login; cả hai ô email và mật khẩu trống",
            "when": "Bấm Đăng nhập",
            "then": "Hiển thị Vui lòng điền đầy đủ thông tin; không gửi POST /api/auth/login; URL vẫn ở /login",
            "source": {"file": "urd.md", "line": 34}}


def test_acceptance_has_all_three_source_fields():
    req = requirement()
    case = generate_from_acceptance([req], IdAllocator(), "AUTH").cases[0]
    assert [s.kind.value for s in case.steps] == ["given", "when", "then"]
    for step, field in zip(case.steps, ("given", "when", "then")):
        assert req[field] in step.note
        assert '"requirement_id": "AC-EMPTY"' in step.note


@pytest.mark.parametrize("field", ["when", "then"])
def test_partial_mapping_keeps_unmapped_siblings_in_order(evidence, field):
    req = requirement()
    req[field] = ("Bấm Đăng nhập; Unknown business action" if field == "when"
                  else "URL vẫn ở /login; Unknown business outcome")
    case = generate_from_acceptance([req], IdAllocator(), "AUTH").cases[0]
    map_testcases([case], evidence, evidence.base_url, {"/api/auth/login"})
    selected = [s for s in case.steps if s.kind.value == field]
    assert len(selected) == 2
    assert selected[0].action == ("ui.click" if field == "when" else "assert.url_matches")
    assert selected[1].action == ("perform.unmapped" if field == "when" else "assert.unmapped")
    assert "Unknown business" in str(selected[1].args)
    assert all(req[field] in s.note for s in selected)
    assert case.execution == "manual"


def test_coverage_candidate_preserves_source_and_mapping(evidence):
    req = requirement()
    report = analyze_coverage([req], [])
    candidate = plan_coverage(report).cases[0]
    assert [s.kind.value for s in candidate.steps] == ["given", "when", "then"]
    assert all('"obligation_id"' in s.note for s in candidate.steps)
    map_testcases([candidate], evidence, evidence.base_url, {"/api/auth/login"})
    assert any(s.action == "assert.unmapped" and "không gửi POST" in str(s.args)
               for s in candidate.steps)
    assert not analyze_executability(candidate).executable


@pytest.mark.parametrize("text", [
    "Mở /login, Unknown business action",
    "Bấm Đăng nhập, Unknown business action",
])
def test_comma_compound_is_not_consumed_by_a_partial_match(evidence, text):
    req = requirement()
    req["when"] = text
    case = generate_from_acceptance([req], IdAllocator(), "AUTH").cases[0]
    map_testcases([case], evidence, evidence.base_url)
    when = [s for s in case.steps if s.kind.value == "when"]
    assert len(when) == 1
    assert when[0].action == "perform.unmapped"
    assert when[0].args["description"] == text


def test_tc002_normal_pipeline_preserves_every_outcome(tmp_path, monkeypatch, evidence):
    # Exercise real ingest/generator/mapper/coverage/render path. Only browser
    # evidence acquisition is stubbed; no source-step restoration or LLM calls.
    import qctool.ui
    monkeypatch.setattr(qctool.ui, "crawl", lambda *a, **kw: evidence)
    repo = Path(__file__).resolve().parents[1]
    cfg = PipelineConfig(docs_dir=repo / "samples/smoke",
                         openapi=repo / "samples/smoke/openapi.yaml",
                         feature="salonhub-smoke", module="SALON_AUTH",
                         web_url=evidence.base_url, auth_mode="manual",
                         skip_run=True, out_dir=tmp_path, llm_enabled=False)
    result = run_pipeline(cfg)
    assert result.error is None
    payload = yaml.safe_load(result.testcases_path.read_text())
    case = next(c for c in payload["testcases"] if c["id"] == "TC_SALON_AUTH_002")
    steps = case["steps"]
    assert case["execution"] == "manual"
    assert any(s["action"] == "perform.unmapped" and
               "cả hai ô email và mật khẩu trống" in str(s["args"]) for s in steps)
    assert any(s["action"] == "assert.unmapped" and
               "Vui lòng điền đầy đủ thông tin" in str(s["args"]) for s in steps)
    assert any(s["action"] == "assert.unmapped" and
               "không gửi POST /api/auth/login" in str(s["args"]) for s in steps)
    assert any(s["action"] == "assert.url_matches" and
               "login" in s["args"]["pattern"] for s in steps)
    assert [s["seq"] for s in steps] == list(range(1, len(steps) + 1))
    sourced = [s for s in steps if "[mapper-clause]" in s.get("note", "")]
    assert len(sourced) >= 6
    assert all("AC-salonhub-smoke-001-2" in s["note"] for s in sourced)
    audit = json.loads(result.generation_path.read_text())
    assert "TC_SALON_AUTH_002" not in {c["id"] for c in audit["executable_cases"]}

"""Source clauses survive generation and partial mapping without restoration."""
from pathlib import Path
import json

import pytest
import yaml

from qctool.coverage import analyze_coverage
from qctool.executability import analyze_executability
from qctool.generate.from_openapi import IdAllocator
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
    assert any(s["action"] == "assert.unmapped" and
               "/login" in str(s["args"]) for s in steps)
    assert [s["seq"] for s in steps] == list(range(1, len(steps) + 1))
    assert case['source_intent']['req_id'] == 'AC-salonhub-smoke-001-2'
    assert 'không gửi POST /api/auth/login' in case['source_intent']['expected']
    audit = json.loads(result.generation_path.read_text())
    assert "TC_SALON_AUTH_002" not in {c["id"] for c in audit["executable_cases"]}

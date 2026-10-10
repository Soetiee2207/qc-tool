"""Test cho pipeline gộp + web UI.

Dùng HTTP thật (server trong tiến trình, cổng do hệ điều hành chọn) — không giả
lập — để test đi đúng đường đi mà trình duyệt sẽ đi.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qctool.pipeline import PipelineConfig, run_pipeline  # noqa: E402
from qctool.web.app import PAGE, Handler  # noqa: E402
from tests.mock_server import create_server  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SAMPLE_SPEC = REPO / "projects" / "demo" / "task-manager" / "openapi.yaml"
FIXTURE_DOCS = Path(__file__).parent / "fixtures" / "urd_srs"


@pytest.fixture(scope="module")
def api():
    server = create_server(0, "/api/v1")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    yield f"http://{host}:{port}/api/v1"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def ui():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    yield f"http://{host}:{port}"
    server.shutdown()
    server.server_close()


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def _post(url: str, payload: dict) -> tuple[int, str]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


# ── Pipeline ─────────────────────────────────────────────────────────────────
def test_pipeline_generates_without_running(tmp_path):
    cfg = PipelineConfig(openapi=SAMPLE_SPEC, feature="sample", module="SAMPLE",
                         skip_run=True, out_dir=tmp_path)
    result = run_pipeline(cfg)
    assert result.ok, result.error
    assert result.total_cases > 40
    assert result.testcases_path.is_file()
    assert result.xlsx_path.is_file()
    assert result.run_dir is None, "skip_run thì không được chạy"


def test_pipeline_full_run(tmp_path, api):
    cfg = PipelineConfig(openapi=SAMPLE_SPEC, feature="sample", module="SAMPLE",
                         base_url=api, bearer_token="t", timeout_seconds=10,
                         out_dir=tmp_path)
    result = run_pipeline(cfg)
    assert result.ok, result.error
    assert result.counts["Pass"] > 0
    assert result.counts["Fail"] > 0, "mock có bug cài sẵn, phải có Fail"
    assert result.report_path.is_file()
    assert (result.run_dir / "results.json").is_file()
    assert (result.run_dir / "junit.xml").is_file()
    assert (result.run_dir / "results.csv").is_file()


def test_pipeline_reports_progress():
    stages: list[str] = []
    cfg = PipelineConfig(openapi=SAMPLE_SPEC, feature="x", skip_run=True)
    run_pipeline(cfg, on_progress=lambda stage, _msg: stages.append(stage))
    assert "generate" in stages
    assert stages[-1] in ("done", "run")


def test_pipeline_with_docs_only(tmp_path):
    """Chỉ có tài liệu, không có OpenAPI — vẫn phải sinh được case."""
    if not FIXTURE_DOCS.is_dir():
        pytest.skip("thiếu fixture tài liệu")
    cfg = PipelineConfig(docs_dir=FIXTURE_DOCS, feature="demo", skip_run=True, out_dir=tmp_path)
    result = run_pipeline(cfg)
    assert result.ok, result.error
    assert result.total_cases > 0
    assert result.requirements_path.is_file()


def test_pipeline_needs_a_source():
    result = run_pipeline(PipelineConfig(feature="x", skip_run=True))
    assert not result.ok
    assert "nguồn đầu vào" in (result.error or "")


def test_pipeline_missing_docs_dir_reports_clearly():
    result = run_pipeline(PipelineConfig(docs_dir=Path("/khong/ton/tai"), feature="x"))
    assert not result.ok
    assert "Không tìm thấy thư mục tài liệu" in (result.error or "")


def test_pipeline_never_raises(tmp_path):
    """Mọi lỗi phải trả về `error`, không được ném ra ngoài — web UI phụ thuộc điều này."""
    cfg = PipelineConfig(openapi=Path("/khong/ton/tai.yaml"), feature="x", out_dir=tmp_path)
    result = run_pipeline(cfg)
    assert not result.ok
    assert result.error


def test_config_from_file(tmp_path):
    spec = tmp_path / "qctool.yaml"
    spec.write_text(yaml.safe_dump({
        "feature": "abc",
        "docs_dir": "./docs",
        "run": {"base_url": "https://x.test", "timeout_seconds": 12},
        "auth": {"mode": "token", "token": "zzz"},
        "out": {"skip_run": True, "created_by": "@me"},
    }), encoding="utf-8")
    cfg = PipelineConfig.from_file(spec)
    assert cfg.feature == "abc"
    assert cfg.docs_dir == tmp_path / "docs", "đường dẫn tương đối tính từ file cấu hình"
    assert cfg.base_url == "https://x.test"
    assert cfg.timeout_seconds == 12
    assert cfg.auth_mode == "token"
    assert cfg.skip_run is True
    assert cfg.created_by == "@me"


def test_config_reads_ui_section(tmp_path):
    """Mục `ui:` phải được đọc — trước đây khoá lạ bị bỏ qua im lặng."""
    spec = tmp_path / "qctool.yaml"
    spec.write_text(yaml.safe_dump({
        "feature": "abc",
        "openapi": "./oas.yaml",
        "ui": {"retry": 2, "evidence": "always", "trace": True,
               "soft_assert": True, "viewport": "1280x720"},
    }), encoding="utf-8")
    cfg = PipelineConfig.from_file(spec)
    assert cfg.ui_retry == 2
    assert cfg.ui_evidence == "always"
    assert cfg.ui_trace is True
    assert cfg.soft_assert is True
    assert cfg.viewport == (1280, 720)


def test_ui_retry_is_clamped(tmp_path):
    spec = tmp_path / "qctool.yaml"
    spec.write_text(yaml.safe_dump({
        "feature": "abc", "openapi": "./oas.yaml", "ui": {"retry": 99},
    }), encoding="utf-8")
    assert PipelineConfig.from_file(spec).ui_retry == 3


def test_defaults_keep_ui_off(tmp_path):
    """Không khai `ui:` thì hành vi phải y như trước — không tự bật gì."""
    spec = tmp_path / "qctool.yaml"
    spec.write_text(yaml.safe_dump({"feature": "abc", "openapi": "./oas.yaml"}),
                    encoding="utf-8")
    cfg = PipelineConfig.from_file(spec)
    assert cfg.ui_retry == 0
    assert cfg.ui_evidence == "on-fail"
    assert cfg.ui_trace is False
    assert cfg.ui_axe is False
    assert cfg.soft_assert is False
    assert cfg.viewport == (1440, 900)


def test_config_rejects_incomplete_browser_auth():
    """`browser` là chế độ duy nhất được tự đăng nhập — thiếu tài khoản phải báo ngay."""
    from qctool.config import Config, ConfigError

    with pytest.raises(ConfigError, match="browser cần"):
        Config(base_url="https://x.test", auth_mode="browser").validate()

    Config(base_url="https://x.test", auth_mode="browser",
           username="a", password="b").validate()
    Config(base_url="https://x.test", auth_mode="manual").validate()


def test_config_accepts_ui_section_keys(tmp_path):
    """`ui:` phải được đọc — trước đây khoá lạ bị bỏ qua im lặng."""
    spec = tmp_path / "qctool.yaml"
    spec.write_text(yaml.safe_dump({
        "feature": "abc", "openapi": "./oas.yaml",
        "ui": {"retry": 1, "evidence": "off", "viewport": {"width": 800, "height": 600}},
    }), encoding="utf-8")
    cfg = PipelineConfig.from_file(spec)
    assert cfg.ui_retry == 1
    assert cfg.ui_evidence == "off"
    assert cfg.viewport == (800, 600)


# ── Không tự đăng nhập ───────────────────────────────────────────────────────
def test_manual_auth_mode_never_logs_in(tmp_path, monkeypatch):
    """Hồi quy P1 (finding 2026-09-21): `.env` có tài khoản KHÔNG được làm tool tự đăng nhập.

    Lần chạy thật đầu tiên trên mock đã hỏng vì lỗi này: tool mở `/login` của một
    trang không có form đăng nhập rồi mất luôn trình duyệt. Test cũ không bắt được
    vì mọi test đều dựng config trực tiếp với `username=None`.

    Cách kiểm: giả lập `.env` có tài khoản, chạy pipeline ở `auth.mode: manual`, và
    khẳng định `BrowserSession.login` không hề được gọi.
    """
    monkeypatch.setenv("QCTOOL_USERNAME", "ai.do@example.com")
    monkeypatch.setenv("QCTOOL_PASSWORD", "matkhau")
    monkeypatch.setenv("QCTOOL_AUTH_MODE", "manual")

    from qctool.execute import browser as browser_mod

    calls: list[str] = []
    monkeypatch.setattr(browser_mod.BrowserSession, "login",
                        lambda self, u, p: calls.append(u) or "đã đăng nhập")

    docs = tmp_path / "docs"
    docs.mkdir()
    # Fixture phải sinh ra **case cần map** (`perform.unmapped`) — nếu mọi case đều
    # đã auto, nhánh đăng nhập trong chặng crawl không bao giờ chạy và test sẽ xanh
    # một cách vô nghĩa. Tài liệu dưới đây có AC dạng Given/When/Then để chắc chắn
    # có case chưa map.
    (docs / "urd.md").write_text(
        "---\ntype: urd\nfeature: demo\nstatus: draft\n---\n\n"
        "# Demo\n\n### US-001 — Đăng nhập\n\n"
        "**As a** nhân viên\n**I want** đăng nhập\n**So that** vào được portal\n\n"
        "**Acceptance Criteria**\n\n"
        "| ID | Given | When | Then |\n|---|---|---|---|\n"
        "| AC-001-1 | Chưa đăng nhập | Mở `/projects` | Redirect `/login` |\n",
        encoding="utf-8")

    cfg = PipelineConfig(
        docs_dir=docs, feature="demo", module="DEMO",
        web_url="http://127.0.0.1:9",          # không có gì lắng nghe → crawl lỗi, không sao
        base_url="http://127.0.0.1:9",
        auth_mode="manual",
        username="ai.do@example.com",           # có tài khoản, nhưng mode là manual
        password="matkhau",
        skip_run=True,
        out_dir=tmp_path / "out",
    )
    run_pipeline(cfg)
    assert calls == [], f"auth.mode=manual mà vẫn đăng nhập: {calls}"
    # Agent without opt-in LLM performs no browser work at all.
    assert (cfg.out_dir / '3-generate/testcases.yaml').is_file()
    assert not (cfg.out_dir / '2-crawl/ui-map.yaml').exists()


# ── Web UI ───────────────────────────────────────────────────────────────────
def test_ui_serves_page(ui):
    code, body = _get(ui + "/")
    assert code == 200
    assert "qc-tool" in body
    assert "Chạy QC" in body


def test_page_has_no_unrendered_placeholders():
    """Trang phải là HTML tĩnh hoàn chỉnh, không còn chỗ trống kiểu template."""
    assert "{{" not in PAGE and "}}" not in PAGE
    assert "%s" not in PAGE


def test_ui_rejects_missing_input(ui):
    code, body = _post(ui + "/api/run", {"docs_dir": "", "openapi": "", "feature": "x"})
    assert code == 400
    assert "nguồn đầu vào" in json.loads(body)["error"]


def test_ui_rejects_missing_path(ui):
    code, body = _post(ui + "/api/run",
                       {"openapi": "/khong/co/that.yaml", "feature": "x"})
    assert code == 400
    assert "Không tìm thấy" in json.loads(body)["error"]


def test_ui_rejects_token_mode_without_token(ui):
    code, body = _post(ui + "/api/run", {
        "openapi": str(SAMPLE_SPEC), "feature": "x",
        "base_url": "https://x.test", "auth_mode": "token", "bearer_token": "",
    })
    assert code == 400
    assert "token" in json.loads(body)["error"]


def test_ui_run_end_to_end(ui, api, tmp_path):
    code, body = _post(ui + "/api/run", {
        "openapi": str(SAMPLE_SPEC), "feature": "sample", "module": "SAMPLE",
        "base_url": api, "auth_mode": "token", "bearer_token": "t",
        "timeout_seconds": "10", "verify_ssl": True, "skip_run": False,
    })
    assert code == 202, body
    job_id = json.loads(body)["job_id"]

    import time
    for _ in range(40):
        _, snapshot = _get(f"{ui}/api/jobs/{job_id}")
        state = json.loads(snapshot)
        if state["done"]:
            break
        time.sleep(0.4)
    else:
        pytest.fail("job không xong sau 16 giây")

    assert state["error"] is None, state["error"]
    assert state["result"]["total_cases"] > 40
    assert state["result"]["counts"]["Fail"] > 0
    assert state["messages"], "phải có tiến trình để UI hiển thị"


def test_ui_unknown_job_returns_404(ui):
    code, _ = _get(ui + "/api/jobs/khongtontai")
    assert code == 404


def test_ui_blocks_download_outside_project(ui):
    """Không được để lộ file hệ thống qua endpoint tải file."""
    code, body = _get(ui + "/api/download?path=/etc/passwd")
    assert code == 403
    assert "thư mục dự án" in json.loads(body)["error"]


def test_ui_downloads_generated_file(ui, tmp_path):
    import shutil
    folder = REPO / "projects" / "_test_download"
    target = folder / "artifacts" / "file.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("nội dung thử", encoding="utf-8")
    try:
        code, body = _get(ui + "/api/download?path=" + str(target))
        assert code == 200
        assert body == "nội dung thử"
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_ui_config_endpoint(ui):
    code, body = _get(ui + "/api/config")
    assert code == 200
    assert "base_url" in json.loads(body)

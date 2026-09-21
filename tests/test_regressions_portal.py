"""Test hồi quy cho các lỗi tìm ra khi chạy trên portal thật (2026-09-21, đợt 2).

Lượt chạy thật sau khi tích hợp Playwright phát hiện 7 lỗi — tất cả đều thuộc loại
"tool ghi một thứ không phải kết luận về sản phẩm thành kết luận về sản phẩm".
Bộ test này khoá từng lỗi lại.

| Lỗi | Triệu chứng | Test |
|---|---|---|
| L1 | `qc.yaml` trỏ OAS không tồn tại → 0 case API, im lặng | `test_missing_openapi_is_loud` |
| L2 | `_api_paths_from` đọc sai khoá → mapper từ chối mọi endpoint | `test_api_paths_read_from_sources` |
| L3 | `base_url` thiếu `/api/v1` → 9 `Fail` giả (404) | `test_base_url_prefix_corrected_from_spec` |
| L4 | Phiên hết hạn → crawl ra 2 element, UI map rỗng, 62 case "thủ công" | `test_stale_session_is_detected` |
| L5 | `soft_failures` rò sang case API → 8 `Fail` giả dù mọi bước `[OK]` | (xem `test_ui_run.py`) |
| L6 | Câu điều kiện `refresh fail no upload` → bấm nút `Refresh` (bịa hành động) | `test_condition_text_is_not_a_button` |
| L7 | Kiểm "Users hidden" bằng tài khoản admin → `Fail` giả | `test_permission_visibility_case_needs_privileged_setup` |
| L8 | NFR hiệu năng `p95 < 100ms` bị nhánh "câu nói về API" chặn → không bao giờ kiểm | `test_perf_nfr_maps_to_http_request` |
| L9 | Ngưỡng `p95` đem so với **một** lần gọi → `Fail` giả (162ms, p95 thật 84ms) | `test_perf_threshold_measures_percentile` |
| L10 | Generator **bịa** kỳ vọng rỗng «hoàn tất đúng như tài liệu mô tả» → case không bao giờ chạy | `test_flow_case_uses_documented_destination` |
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qctool.generate.mapper import map_testcases  # noqa: E402
from qctool.pipeline import (  # noqa: E402
    PipelineConfig,
    _api_paths_from,
    _keep_better_map,
    _resolve_base_url,
    run_pipeline,
)
from qctool.testcase import Step, StepKind, TestCase  # noqa: E402
from qctool.ui.crawl import Element, PageMap, UIMap  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


# ── L2: nguồn đường dẫn API ─────────────────────────────────────────────────
def test_api_paths_read_from_sources():
    """Hồi quy: `endpoints` nằm trong `sources.openapi`, không phải ở `meta`.

    Hàm cũ đọc `meta["endpoints"]` (một **số đếm** trong file testcases.yaml) nên
    luôn trả rỗng → mapper từ chối mọi đường dẫn API có thật trong spec. Đó là
    nguyên nhân 6 case endpoint vẫn ở trạng thái "chưa map" dù đã có OpenAPI.
    """
    meta = {
        "sources": {"openapi": {"path": "oas.yaml", "endpoints": [
            {"path": "/auth/config", "method": "GET"},
            {"path": "/auth/me", "method": "GET"},
        ]}},
    }
    assert _api_paths_from(meta) == {"/auth/config", "/auth/me"}


def test_api_paths_tolerate_count_form():
    """`endpoints: 3` (số đếm) không được làm sập — chỉ là không có dữ liệu."""
    assert _api_paths_from({"endpoints": 3}) == set()
    assert _api_paths_from({"sources": {"openapi": {"endpoints": 3}}}) == set()
    assert _api_paths_from({}) == set()


def test_generate_writes_endpoints_into_sources(tmp_path):
    """Lượt chạy sau đọc `testcases.yaml` phải thấy được danh sách endpoint."""
    from qctool.generate import generate_all, write_cases

    oas = tmp_path / "oas.yaml"
    oas.write_text(yaml.safe_dump({
        "openapi": "3.0.0",
        "info": {"title": "t", "version": "1"},
        "servers": [{"url": "https://x.test/api/v1"}],
        "paths": {
            "/auth/config": {"get": {"operationId": "c",
                                     "responses": {"200": {"description": "ok"}}}},
        },
    }), encoding="utf-8")

    cases, _, meta = generate_all(None, oas, "API")
    out = tmp_path / "testcases.yaml"
    write_cases(cases, out, meta)

    loaded = yaml.safe_load(out.read_text(encoding="utf-8"))
    endpoints = loaded["sources"]["openapi"]["endpoints"]
    assert isinstance(endpoints, list) and endpoints, \
        "danh sách endpoint phải được ghi ra file, không chỉ số đếm"
    assert endpoints[0]["path"] == "/auth/config"


# ── L3: tiền tố đường dẫn của base_url ──────────────────────────────────────
def _cfg(base_url: str, web_url: str = "https://x.test") -> PipelineConfig:
    return PipelineConfig(base_url=base_url, web_url=web_url)


def test_base_url_prefix_corrected_from_spec():
    """Hồi quy: config ghi `https://host` nhưng API ở `https://host/api/v1`.

    Để nguyên thì mọi request rơi vào SPA catch-all → HTTP 404 → 9 case `Fail` giả
    trên portal thật (2026-09-21).
    """
    meta = {"sources": {"openapi": {"servers": ["https://x.test/api/v1"]}}}
    assert _resolve_base_url(_cfg("https://x.test"), meta) == "https://x.test/api/v1"

    # Và `run_pipeline` phải thật sự **dùng** giá trị đã sửa, không chỉ có hàm đúng.
    # Test chỉ kiểm hàm thì nhánh gọi sai vẫn lọt — đã mắc đúng lỗi này.
    for cfg_base, expected in (("https://x.test", "https://x.test/api/v1"),
                               ("https://x.test/api/v1", "https://x.test/api/v1"),
                               ("https://khac.test", "https://khac.test")):
        cfg = PipelineConfig(base_url=cfg_base, web_url="https://x.test",
                             skip_run=True)
        assert _resolve_base_url(cfg, meta) == expected


def test_pipeline_uses_corrected_base_url(tmp_path):
    """`run_pipeline` phải DÙNG địa chỉ đã sửa, không chỉ có hàm `_resolve_base_url` đúng.

    Cách kiểm: dựng mock API ở `/api/v1`, khai `base_url` **thiếu** tiền tố, và
    khẳng định case API **đạt**. Nếu pipeline quên áp dụng, request bay vào
    `/health` (không có) → 404 → case `Fail`.
    """
    import threading

    from tests.mock_server import create_server

    server = create_server(0, "/api/v1")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    root = f"http://{host}:{port}"

    oas = tmp_path / "oas.yaml"
    oas.write_text(yaml.safe_dump({
        "openapi": "3.0.0",
        "info": {"title": "t", "version": "1"},
        "servers": [{"url": f"{root}/api/v1"}],
        "paths": {
            "/health": {"get": {"operationId": "h", "security": [],
                                "responses": {"200": {"description": "ok"}}}},
        },
    }), encoding="utf-8")

    cfg = PipelineConfig(
        openapi=oas, feature="urlfix", module="URLFIX",
        base_url=root,                      # THIẾU `/api/v1`
        web_url=root,
        timeout_seconds=10, out_dir=tmp_path / "out",
    )
    try:
        result = run_pipeline(cfg)
    finally:
        server.shutdown()
        server.server_close()

    # Kiểm **địa chỉ thật đã dùng**, không chỉ kết quả: mock chấp nhận cả
    # `/health` lẫn `/api/v1/health`, nên nhìn vào Pass/Fail là không phân biệt được.
    used = (result.run_result.base_url if result.run_result else "")
    assert used == f"{root}/api/v1", (
        f"pipeline dùng sai địa chỉ: {used!r} — thiếu tiền tố thì trên hệ thống thật "
        "mọi request sẽ 404"
    )
    assert result.counts.get("Fail", 0) == 0, f"có Fail: {result.log[-4:]}"


def test_base_url_kept_when_path_matches():
    meta = {"sources": {"openapi": {"servers": ["https://x.test/api/v1"]}}}
    assert _resolve_base_url(_cfg("https://x.test/api/v1"), meta) == "https://x.test/api/v1"


def test_base_url_kept_for_different_host():
    """Khác tên miền ⇒ người dùng có thể cố ý trỏ môi trường khác. Không đoán."""
    meta = {"sources": {"openapi": {"servers": ["https://prod.test/api/v1"]}}}
    assert _resolve_base_url(_cfg("https://dev.test"), meta) == "https://dev.test"


def test_base_url_falls_back_to_spec_when_empty():
    meta = {"sources": {"openapi": {"servers": ["https://x.test/api/v1"]}}}
    assert _resolve_base_url(_cfg(""), meta) == "https://x.test/api/v1"


# ── L8: NFR hiệu năng phải gọi được API, không bị nhánh "câu về API" chặn ───
API_PATHS = {"/api/v1/auth/config", "/api/v1/auth/me"}


def test_perf_nfr_maps_to_http_request(ui_map):
    """Hồi quy: `/auth/config p95 < 100ms` từng ở `manual` mãi mãi.

    Câu này khớp `RE_API_HINT` (có `p95` và `ms`) nên `_looks_like_api` chặn nó
    khỏi mọi nhánh map — trong khi tool **đã có** đủ verb để kiểm
    (`http.request` + `assert.response_time`). NFR hiệu năng vì thế không bao giờ
    được kiểm, dù đó là loại yêu cầu dễ kiểm tự động nhất.

    Tài liệu viết `/auth/config` còn API thật ở `/api/v1/auth/config`; bước sinh ra
    phải dùng đường dẫn **thật** trong spec.
    """
    case = TestCase(id="TC_AUTH_900", module="AUTH", title="/auth/config p95 < 100ms",
                    objective="o", traces_to=["NFR-PERF-01"], source_quote="q")
    case.steps = [Step(1, StepKind.WHEN, "perform.unmapped",
                       {"description": "/auth/config p95 < 100ms"})]

    map_testcases([case], ui_map, "https://x.test", API_PATHS)

    assert case.execution == "auto", "NFR hiệu năng phải chạy được tự động"
    assert [s.action for s in case.steps] == ["http.request", "assert.response_time"]
    assert case.steps[0].args["path"] == "/api/v1/auth/config"
    assert case.steps[1].args["max_ms"] == 100.0
    # Phải lấy nhiều mẫu: `p95 < 100ms` cho phép 5% số lần gọi vượt ngưỡng, nên
    # so một lần gọi với ngưỡng là kiểm chặt hơn yêu cầu (xem L9).
    assert case.steps[1].args["percentile"] == 95
    assert case.steps[1].args["samples"] > 1


# ── L9: ngưỡng phân vị phải đo bằng phân vị ─────────────────────────────────
def test_perf_threshold_measures_percentile(ui_map, monkeypatch):
    """Hồi quy: `TC_NFR_001` từng báo `Fail` trên portal vì lấy **một** mẫu 162ms.

    Đo lại 30 lần trên cùng endpoint đó: p95 = 84ms — trong ngưỡng 100ms. Con số
    162ms gồm cả 109ms bắt tay TLS của một kết nối mới, và dù sao một lần gọi cũng
    không nói được gì về phân vị thứ 95.

    Test này khoá cả hai vế: (a) bước sinh ra yêu cầu lấy mẫu, (b) kết luận dựa
    trên phân vị của các mẫu, không phải mẫu đầu tiên.
    """
    from qctool.execute.runner import HttpSession, _percentile, _run_step

    case = TestCase(id="TC_AUTH_903", module="AUTH", title="/auth/config p95 < 100ms",
                    objective="o", traces_to=["NFR-PERF-01"], source_quote="q")
    case.steps = [Step(1, StepKind.WHEN, "perform.unmapped",
                       {"description": "/auth/config p95 < 100ms"})]
    map_testcases([case], ui_map, "https://x.test", API_PATHS)
    perf = next(s for s in case.steps if s.action == "assert.response_time")

    # Ngưỡng p95 của 20 mẫu: **một** mẫu chậm (900ms) vẫn nằm trong 5% cho phép,
    # nên p95 = 95.5ms < 100ms → ĐẠT. Cách đo cũ — lấy đúng mẫu đầu tiên, 900ms —
    # sẽ báo hỏng. Đây chính là chỗ sai đã gặp trên portal.
    calls = {"n": 0}

    def fake_request(self, method, path, **kw):
        calls["n"] += 1
        return {"status": 200, "body": {}, "raw": "", "duration_ms": 50.0,
                "server_ms": 50.0, "error": None, "_path": path, "_args": {"method": "GET"}}

    monkeypatch.setattr(HttpSession, "request", fake_request)
    session = HttpSession("https://x.test")
    saved = {"res": {"status": 200, "body": {}, "raw": "", "duration_ms": 900.0,
                     "server_ms": 900.0, "error": None, "_path": "/api/v1/auth/config",
                     "_args": {"method": "GET"}}}

    ok, detail = _run_step(perf, session, saved)
    # Lần gọi đầu đã xảy ra ở bước `http.request`, nên chỉ lấy thêm `samples - 1`.
    assert calls["n"] == perf.args["samples"] - 1, "phải lấy đủ số mẫu đã khai"
    assert "p95" in detail and "lần gọi" in detail, f"chi tiết phải nói rõ cách đo: {detail}"

    # Với 19/20 mẫu ở 50ms, p95 = 95.5ms < 100ms → ĐẠT (một mẫu chậm nằm trong 5%
    # mà yêu cầu p95 cho phép). Cách đo cũ lấy đúng mẫu 900ms nên báo hỏng.
    assert ok, f"p95 thật phải nằm trong ngưỡng, nhưng: {detail}"
    assert _percentile([900.0] + [50.0] * 19, 95) < 100


def test_perf_nfr_refuses_unknown_endpoint(ui_map):
    """Đường dẫn không có trong spec → không map. Đo hiệu năng một endpoint không
    tồn tại là vô nghĩa, và tệ hơn: `assert.http_status` sẽ đỏ vì lý do của tool."""
    case = TestCase(id="TC_AUTH_901", module="AUTH", title="x", objective="o",
                    traces_to=["NFR-PERF-99"], source_quote="q")
    case.steps = [Step(1, StepKind.WHEN, "perform.unmapped",
                       {"description": "/auth/khong-co-that p95 < 50ms"})]

    map_testcases([case], ui_map, "https://x.test", API_PATHS)

    assert case.needs_mapping and case.execution == "manual"


def test_perf_nfr_without_spec_stays_unmapped(ui_map):
    """Không có OpenAPI → không đoán. `ui.goto` tới một endpoint API sẽ nhận HTML
    rồi báo `Fail` sai (đúng lỗi L1 đã gặp)."""
    case = TestCase(id="TC_AUTH_902", module="AUTH", title="x", objective="o",
                    traces_to=["NFR-PERF-01"], source_quote="q")
    case.steps = [Step(1, StepKind.WHEN, "perform.unmapped",
                       {"description": "/auth/config p95 < 100ms"})]

    map_testcases([case], ui_map, "https://x.test", set())

    assert case.needs_mapping and case.execution == "manual"
    assert not any(s.action.startswith("ui.") for s in case.steps), \
        "không được mở trình duyệt tới một endpoint API"


# ── L10: kỳ vọng của case luồng chính phải là thứ kiểm được ─────────────────
def test_flow_case_uses_documented_destination():
    """Hồi quy: generator tự bịa kỳ vọng rỗng cho mọi case luồng chính.

    Câu «Chức năng X hoàn tất đúng như tài liệu mô tả» không sai, nhưng không
    kiểm gì cả — nên case mãi ở `manual` **dù tài liệu có nêu đích đến rõ ràng**
    (`Unauthenticated → /login?callback=`). Đó là tool tự làm mất thông tin mà
    chính nó vừa đọc được.
    """
    from qctool.generate.from_functions import generate_from_functions
    from qctool.generate.from_openapi import IdAllocator

    reqs = [{
        "id": "FR-x-008", "kind": "functional", "title": "Route auth guard",
        "api": {"flow": ["Unauthenticated → /login?callback=; loading spinner while isLoading"]},
        "source": {"file": "srs.md", "line": 1},
    }]
    cases = generate_from_functions(reqs, IdAllocator(), "AUTH")
    assert len(cases) == 1
    then = [s for s in cases[0].steps if s.kind is StepKind.THEN]
    assert then, "case luồng chính phải có vế THEN"
    assert then[0].args["expected"] == "Chuyển tới /login?callback=", \
        "phải dùng đích đến tài liệu đã ghi, không bịa câu mô tả rỗng"


def test_flow_case_without_destination_stays_honest():
    """Không có đích đến trong tài liệu → giữ câu mô tả, case ở lại `manual`.

    Đây là vế còn lại của nguyên tắc: không đoán. `persistReturnPath` là mô tả cơ
    chế bên trong, không quan sát được từ ngoài — sinh assertion từ nó là bịa.
    """
    from qctool.generate.from_functions import generate_from_functions
    from qctool.generate.from_openapi import IdAllocator

    reqs = [{
        "id": "FR-x-003", "kind": "functional", "title": "SSO login redirect",
        "api": {"flow": ["LoginScreen button → persistReturnPath → redirectUri = origin + safe path"]},
        "source": {"file": "srs.md", "line": 1},
    }]
    cases = generate_from_functions(reqs, IdAllocator(), "AUTH")
    expected = [s for s in cases[0].steps if s.kind is StepKind.THEN][0].args["expected"]
    assert "hoàn tất đúng như tài liệu" in expected, \
        "không có đích đến quan sát được thì phải giữ câu mô tả, không bịa assertion"


# ── L6: câu điều kiện không phải là nút ─────────────────────────────────────
@pytest.fixture
def ui_map() -> UIMap:
    return UIMap(
        base_url="https://x.test", crawled_at="now",
        pages=[PageMap(url="https://x.test/", title="t", elements=[
            Element(id="refresh", role="button", name="Refresh", tag="button"),
            Element(id="signin", role="button", name="Sign in", tag="button"),
        ])],
    )


def test_condition_text_is_not_a_button(ui_map):
    """Hồi quy: `refresh fail no upload` (điều kiện) từng khớp nút `Refresh`.

    Nhánh *nhãn trần* của mapper coi câu mô tả là tên element, nên case
    `Refreshing → Unauthenticated khi refresh fail no upload` sinh ra bước
    `ui.click «Refresh»` — hành động không ai nói tới. Bấm nút đó rồi kiểm sai chỗ
    là bịa hành động, tệ hơn là để case chưa map.
    """
    case = TestCase(id="TC_X_001", module="X", title="Refreshing → Unauthenticated",
                    objective="o", traces_to=["S-1"], source_quote="q")
    case.steps = [
        Step(1, StepKind.WHEN, "perform.unmapped",
             {"description": "refresh fail no upload"}),
        Step(2, StepKind.THEN, "assert.unmapped", {"expected": "Redirect /login"}),
    ]
    map_testcases([case], ui_map, "https://x.test")

    clicks = [s for s in case.steps if s.action == "ui.click"]
    assert not clicks, f"câu điều kiện bị map thành bấm nút: {clicks}"


def test_direct_click_command_still_maps(ui_map):
    """Ngược lại: lệnh bấm tường minh vẫn phải map — đừng siết quá tay."""
    case = TestCase(id="TC_X_002", module="X", title="t", objective="o",
                    traces_to=["S-1"], source_quote="q")
    case.steps = [
        Step(1, StepKind.WHEN, "perform.unmapped",
             {"description": "Click Sign in with Keycloak"}),
        Step(2, StepKind.THEN, "assert.unmapped", {"expected": "Redirect /login"}),
    ]
    map_testcases([case], ui_map, "https://x.test")
    assert any(s.action == "ui.click" for s in case.steps)


def test_bare_label_with_filler_maps(ui_map):
    """`Sign in button` (nhãn + loại phần tử) vẫn phải khớp."""
    case = TestCase(id="TC_X_003", module="X", title="t", objective="o",
                    traces_to=["S-1"], source_quote="q")
    case.steps = [
        Step(1, StepKind.WHEN, "perform.unmapped", {"description": "Sign in button"}),
        Step(2, StepKind.THEN, "assert.unmapped", {"expected": "Redirect /login"}),
    ]
    map_testcases([case], ui_map, "https://x.test")
    assert any(s.action == "ui.click" for s in case.steps)


# ── L4: UI map nghèo không được ghi đè bản tốt ──────────────────────────────
def _map(n: int, base: str = "https://x.test") -> UIMap:
    return UIMap(base_url=base, crawled_at="now",
                 pages=[PageMap(url=f"{base}/", title="t", elements=[
                     Element(id=f"e{i}", role="button", name=f"Nút {i}", tag="button")
                     for i in range(n)])])


def test_poor_crawl_does_not_overwrite_good_map(tmp_path):
    """Hồi quy: crawl lần này ra 8 element, bản đồ cũ có 322 — giữ bản cũ.

    Ghi đè khi đó làm mất dữ liệu đã dò hôm trước, và lần sau mọi case UI lại
    thành "chưa map" mà không rõ vì sao (phiên vừa hết hạn là đủ).
    """
    path = tmp_path / "ui-map.yaml"
    _map(322).save(path)
    kept = _keep_better_map(_map(8), path)
    assert len(kept.elements) == 322


def test_better_crawl_replaces_map(tmp_path):
    path = tmp_path / "ui-map.yaml"
    _map(8).save(path)
    assert len(_keep_better_map(_map(322), path).elements) == 322


def test_map_from_other_environment_replaces(tmp_path):
    """Khác `base_url` ⇒ bản đồ cũ vô nghĩa, luôn lấy bản mới."""
    path = tmp_path / "ui-map.yaml"
    _map(322, "https://prod.test").save(path)
    fresh = _map(8, "https://dev.test")
    assert _keep_better_map(fresh, path) is fresh


def test_missing_old_map_accepts_fresh(tmp_path):
    fresh = _map(3)
    assert _keep_better_map(fresh, tmp_path / "chua-co.yaml") is fresh


# ── L1: thiếu OpenAPI phải ồn ào ────────────────────────────────────────────
def test_missing_openapi_is_loud(tmp_path):
    """Hồi quy: `qc.yaml` trỏ `./openapi.json` không tồn tại → 0 case API, im lặng.

    Người dùng chỉ thấy "sinh được ít testcase hơn" và không biết vì sao. Pipeline
    phải cảnh báo, và cảnh báo đó phải nằm trong log để đọc lại được.
    """
    from qctool.pipeline import run_pipeline

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "urd.md").write_text(
        "---\ntype: urd\nfeature: d\nstatus: draft\n---\n\n# D\n\n"
        "### US-001 — A\n\n**As a** x\n**I want** y\n**So that** z\n\n"
        "**Acceptance Criteria**\n\n| ID | Given | When | Then |\n|---|---|---|---|\n"
        "| AC-001-1 | a | b | c |\n", encoding="utf-8")

    cfg = PipelineConfig(
        docs_dir=docs, openapi=tmp_path / "khong-ton-tai.yaml",
        feature="d", module="D", skip_run=True, out_dir=tmp_path / "out",
    )
    result = run_pipeline(cfg)
    assert any("OpenAPI" in line for line in result.log), \
        "thiếu file OpenAPI phải được ghi vào log, không im lặng"

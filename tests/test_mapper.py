"""Test cho mapper — chỗ nối giữa tài liệu và trình duyệt.

Mỗi test ứng với một bug đã gặp thật khi chạy trên portal thật. Mapper sai thì
case báo `Fail` vì lý do chẳng liên quan gì tới sản phẩm — đúng loại báo động giả
mà cả dự án này sinh ra để tránh.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qctool.generate.mapper import (  # noqa: E402
    _join,
    _looks_like_api,
    _setup_requirement,
    map_testcases,
)
from qctool.testcase import CaseType, Priority, Step, StepKind, Technique, TestCase  # noqa: E402
from qctool.ui.crawl import Element, PageMap, UIMap  # noqa: E402


@pytest.fixture
def ui_map() -> UIMap:
    return UIMap(
        base_url="https://portal.test",
        crawled_at="2026-09-21 10:00",
        pages=[PageMap(url="https://portal.test/login", title="Sign In", elements=[
            Element(id="sign_in", role="button", name="Sign in", tag="button"),
            Element(id="vi", role="button", name="VI", tag="button"),
            Element(id="username", role="textbox", name="Username", tag="input"),
            Element(id="password", role="textbox", name="Password", tag="input"),
        ])],
    )


def _ac_case(when: str, then: str, **kw) -> TestCase:
    base = dict(
        id="TC_AUTH_001", module="AUTH", title=f"{when} → {then}", objective="o",
        traces_to=["AC-1"], source_quote="q",
        steps=[
            Step(1, StepKind.WHEN, "perform.unmapped",
                 {"description": when, "expectation": then}),
            Step(2, StepKind.THEN, "assert.unmapped", {"expected": then}),
        ],
        priority=Priority.MEDIUM, case_type=CaseType.POSITIVE,
        technique=Technique.ACCEPTANCE_CRITERION,
    )
    return TestCase(**{**base, **kw})


# ── Hồi quy: bug ghép URL ────────────────────────────────────────────────────
def test_join_always_inserts_slash():
    """Bug đã gặp: `root + "users"` ra `https://host.fitusers` → case fail vì URL rác."""
    assert _join("https://portal.test", "users") == "https://portal.test/users"
    assert _join("https://portal.test/", "users") == "https://portal.test/users"
    assert _join("https://portal.test", "/users") == "https://portal.test/users"
    assert _join("https://portal.test", "https://other.test/x") == "https://other.test/x"


# ── Hồi quy: nhận nhầm đường dẫn API thành trang web ─────────────────────────
def test_api_looking_text_not_mapped_to_goto(ui_map):
    """`/auth/config p95 < 100ms` là API, không phải trang — map thành ui.goto sẽ
    mở trình duyệt tới đường dẫn API rồi nhận HTML, và báo Fail sai."""
    assert _looks_like_api("`/auth/config` p95 < 100ms")
    assert _looks_like_api("GET /auth/me 200")
    assert not _looks_like_api("Click Sign in with Keycloak")
    assert not _looks_like_api("Mở /projects")

    case = _ac_case("/auth/config p95 < 100ms", "Response dưới 100ms")
    map_testcases([case], ui_map, "https://portal.test")
    assert case.needs_mapping, "case API không có spec thì phải để chưa map"


# ── Không map HTTP khi chưa xác minh đường dẫn ───────────────────────────────
def test_http_not_mapped_without_spec(ui_map):
    """Đường dẫn trong tài liệu chưa chắc là đường dẫn API thật.

    Tài liệu ghi `/auth/me`, nhưng API thật là `/api/v1/auth/me`. Không có spec
    thì không được đoán — để case chưa map còn hơn gọi sai rồi báo Fail.
    """
    case = _ac_case("Portal load xong", "GET /auth/me 200")
    map_testcases([case], ui_map, "https://portal.test", api_paths=set())
    assert case.needs_mapping


def test_http_mapped_when_path_verified(ui_map):
    """Có spec xác nhận đường dẫn thì map được."""
    case = _ac_case("Portal load xong", "GET /api/v1/auth/me 200")
    map_testcases([case], ui_map, "https://portal.test", api_paths={"/api/v1/auth/me"})
    actions = [s.action for s in case.steps]
    assert "http.request" in actions
    assert "assert.http_status" in actions


def test_dropping_http_drops_dependent_asserts(ui_map):
    """Bug đã gặp: bỏ `http.request` nhưng giữ `assert.http_status` → assert chạy
    mà không có response, case báo Fail vì lỗi của tool."""
    case = _ac_case("Portal load xong", "GET /auth/me 200")
    map_testcases([case], ui_map, "https://portal.test", api_paths=set())
    actions = [s.action for s in case.steps]
    assert "assert.http_status" not in actions, "assert mồ côi không được giữ lại"


# ── Map được thì phải đúng ───────────────────────────────────────────────────
def test_click_mapped_when_element_exists(ui_map):
    """Bấm được nút có thật trên trang. Vế THEN map được thì cả case mới hết chưa-map."""
    case = _ac_case("Click Sign in with Keycloak", "Redirect /login")
    map_testcases([case], ui_map, "https://portal.test")
    assert any(s.action == "ui.click" for s in case.steps)
    assert not case.needs_mapping, "cả WHEN lẫn THEN đều map được thì phải hết chưa-map"


def test_case_stays_unmapped_if_expectation_cannot_map(ui_map):
    """WHEN map được nhưng THEN không → case vẫn chưa map. Không được chạy nửa vời."""
    case = _ac_case("Click Sign in with Keycloak", "Sang trang IdP")
    map_testcases([case], ui_map, "https://portal.test")
    assert case.needs_mapping


def test_click_not_mapped_when_element_missing(ui_map):
    """Không có element trên trang thì không được bịa ra selector."""
    case = _ac_case("Click nút Mua ngay", "Sang trang thanh toán")
    map_testcases([case], ui_map, "https://portal.test")
    assert case.needs_mapping


def test_goto_mapped_with_correct_url(ui_map):
    case = _ac_case("Mở /projects", "Thấy trang dự án")
    map_testcases([case], ui_map, "https://portal.test")
    goto = next((s for s in case.steps if s.action == "ui.goto"), None)
    assert goto is not None
    assert goto.args["url"] == "https://portal.test/projects"


def test_redirect_mapped_to_url_assert(ui_map):
    case = _ac_case("Mở /projects", "Redirect /login?callback=/projects")
    map_testcases([case], ui_map, "https://portal.test")
    assert any(s.action == "assert.url_matches" for s in case.steps)


def test_state_only_description_produces_no_action(ui_map):
    """«Portal load xong» không phải hành động — không sinh bước thừa."""
    case = _ac_case("Portal load xong", "Redirect /login")
    map_testcases([case], ui_map, "https://portal.test")
    actions = [s.action for s in case.steps]
    assert "ui.click" not in actions and "ui.goto" not in actions


# ── Case cần môi trường ──────────────────────────────────────────────────────
def test_denied_case_marked_as_needing_setup(ui_map):
    """Case đòi bị từ chối truy cập cần tài khoản THIẾU quyền.

    Chạy bằng tài khoản đủ quyền mà mong đợi 403 là sai tiền đề — phải `Blocked`,
    không phải `Fail`, nếu không dev sẽ đi tìm bug không tồn tại.
    """
    case = _ac_case("Navigate /users manually", "Redirect /forbidden")
    map_testcases([case], ui_map, "https://portal.test")
    assert case.requires
    assert "KHÔNG có quyền" in case.requires


def test_setup_detection_covers_common_phrasings():
    for text in ("Redirect /forbidden", "trả 403 khi không có quyền",
                 "User thiếu quyền truy cập", "Access denied"):
        assert _setup_requirement(text), f"không nhận ra: {text}"
    for text in ("GET /auth/me 200", "Nav Projects visible", "Redirect /login"):
        assert _setup_requirement(text) is None, f"nhận nhầm: {text}"


# ── Thống kê ─────────────────────────────────────────────────────────────────
def test_stats_count_mapped_correctly(ui_map):
    cases = [
        _ac_case("Click Sign in with Keycloak", "Redirect /dashboard"),
        _ac_case("Click nút không tồn tại", "Không rõ"),
    ]
    cases[1].id = "TC_AUTH_002"
    stats = map_testcases(cases, ui_map, "https://portal.test")
    assert stats.total == 2
    assert stats.mapped == 1
    assert stats.still_unmapped == 1
    assert stats.reasons


def test_mapper_is_deterministic(ui_map):
    """Cùng input phải cho cùng output — mapper chạy deterministic, không LLM."""

    def build():
        return [_ac_case("Click Sign in with Keycloak", "Sang trang IdP")]

    first, second = build(), build()
    map_testcases(first, ui_map, "https://portal.test")
    map_testcases(second, ui_map, "https://portal.test")
    assert [s.to_dict() for s in first[0].steps] == [s.to_dict() for s in second[0].steps]


# ── UI map ───────────────────────────────────────────────────────────────────
def test_ui_map_find_exact_and_partial():
    ui = UIMap(base_url="x", crawled_at="now", pages=[PageMap(url="u", title="t", elements=[
        Element(id="a", role="button", name="Sign in with Keycloak", tag="button"),
        Element(id="b", role="button", name="Cancel", tag="button"),
    ])])
    assert ui.find("Sign in with Keycloak").id == "a"
    assert ui.find("sign in with keycloak").id == "a", "phải khớp không phân biệt hoa thường"
    assert ui.find("Sign in with Keycloak button").id == "a", "tên trong tài liệu dài hơn nhãn"
    assert ui.find("Không có thứ này") is None


def test_ui_map_survives_round_trip(tmp_path):
    original = UIMap(base_url="https://x.test", crawled_at="2026-09-21 10:00",
                     pages=[PageMap(url="https://x.test/a", title="A", text=["hello"],
                                    elements=[Element(id="btn", role="button",
                                                      name="Bấm tôi", tag="button")])])
    path = tmp_path / "ui-map.yaml"
    original.save(path)
    loaded = UIMap.load(path)
    assert loaded.base_url == "https://x.test"
    assert loaded.elements[0].name == "Bấm tôi"
    assert loaded.elements[0].role == "button"

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


# ── Hồi quy: nhận nhầm đường dẫn API thành trang web ─────────────────────────


# ── Không map HTTP khi chưa xác minh đường dẫn ───────────────────────────────


# ── Map được thì phải đúng ───────────────────────────────────────────────────


# ── Case cần môi trường ──────────────────────────────────────────────────────


# ── Thống kê ─────────────────────────────────────────────────────────────────


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

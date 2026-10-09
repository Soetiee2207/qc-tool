"""Test cho phần UI/UX mới: vocabulary, mapper theo test id, nhãn UX, evidence.

Ba nhóm, và mỗi nhóm ứng với một thứ đã sai thật khi làm:

1. **Vocabulary** — mapper sinh tham số ngoài `ACTION_SPECS` (`by_name`), validator
   không thấy vì nó chạy trước mapper. Test ở đây chạy validator **sau** mapper.
2. **Mapper theo test id** — dùng nhãn hiển thị làm selector nghĩa là mỗi lần dev
   sửa chữ trong giao diện là test đỏ, dù sản phẩm vẫn đúng.
3. **Nhãn UX** — nhóm câu văn xuôi về vô hiệu hoá/lỗi JS/accessibility. Trước đây
   chúng luôn ở trạng thái chưa map, tức NFR về UX không bao giờ được kiểm.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qctool.execute.runner import UI_ASSERT_VERBS, UI_VERBS  # noqa: E402
from qctool.testcase import (  # noqa: E402
    ACTION_SPECS,
    Step,
    StepKind,
    TestCase,
    ValidationError,
)
from qctool.ui.crawl import Element, PageMap, UIMap  # noqa: E402
from qctool.validate import validate_batch  # noqa: E402


@pytest.fixture
def ui_map() -> UIMap:
    """UI map có test id — giống thứ `qctool crawl` sinh ra từ webapp thật."""
    return UIMap(
        base_url="https://portal.test",
        crawled_at="2026-09-21 10:00",
        pages=[
            PageMap(url="https://portal.test/login", title="Đăng nhập", elements=[
                Element(id="sign_in", role="button", name="Đăng nhập bằng SSO",
                        tag="button", test_id="btn-sso"),
                Element(id="username", role="textbox", name="Tên đăng nhập",
                        tag="input", test_id="input-username"),
                Element(id="save", role="button", name="Lưu", tag="button",
                        test_id="btn-save", disabled=True),
            ]),
            PageMap(url="https://portal.test/projects", title="Dự án", elements=[
                Element(id="row", role="button", name="Mở dự án", tag="button",
                        test_id="row-open"),
            ]),
        ],
    )


def _case(when: str, then: str, **kw) -> TestCase:
    case = TestCase(
        id=kw.get("id", "TC_UX_001"), module="UX", title="t", objective="o",
        traces_to=["AC-1"], source_quote="q",
    )
    case.steps = [
        Step(1, StepKind.WHEN, "perform.unmapped", {"description": when}),
        Step(2, StepKind.THEN, "assert.unmapped", {"expected": then}),
    ]
    return case


# ── 1. Vocabulary ───────────────────────────────────────────────────────────
def test_every_ui_verb_has_a_spec():
    """Verb không có trong `ACTION_SPECS` sẽ bị validator chặn ở cửa ra."""
    for verb in UI_VERBS:
        assert verb in ACTION_SPECS, f"`{verb}` thiếu trong ACTION_SPECS"


def test_ui_assert_verbs_all_start_with_assert():
    for verb in UI_ASSERT_VERBS:
        assert verb.startswith("assert."), verb


def test_by_name_is_declared_in_specs():
    for verb in ("ui.click", "ui.fill", "ui.select", "ui.hover", "ui.check",
                 "assert.visible", "assert.not_visible", "assert.text",
                 "assert.value", "assert.enabled", "assert.disabled",
                 "assert.count", "assert.focused", "assert.checked"):
        spec = ACTION_SPECS[verb]
        assert "by_name" in spec.required + spec.optional, verb


def test_unknown_arg_still_rejected():
    """Nới `by_name` không được làm mất khả năng bắt tham số lạ."""
    step = Step(1, StepKind.THEN, "assert.text",
                {"target": "x", "expected": "y", "by_nam": "z"})
    with pytest.raises(ValidationError, match="tham số lạ"):
        step.validate()


# ── 2. Mapper dùng test id ──────────────────────────────────────────────────


# ── 3. Nhãn UX ──────────────────────────────────────────────────────────────


# ── 4. Verb mới đọc được như câu (cột Test Steps) ───────────────────────────
def test_new_verbs_render_as_sentences():
    """Cột Test Steps là chỗ người QC đọc — không được lộ cú pháp máy."""
    cases = [
        (Step(1, StepKind.WHEN, "ui.hover", {"target": "menu", "by_name": "Menu"}), "Menu"),
        (Step(1, StepKind.WHEN, "ui.scroll", {"direction": "bottom"}), "cuối trang"),
        (Step(1, StepKind.WHEN, "ui.press", {"key": "Escape"}), "Escape"),
        (Step(1, StepKind.THEN, "assert.console_clean", {}), "JavaScript"),
        (Step(1, StepKind.THEN, "assert.axe", {}), "accessibility"),
    ]
    for step, needle in cases:
        text = step.describe()
        assert needle in text, f"«{step.action}» đọc ra: {text}"
        assert step.action not in text, "không được lộ tên verb ra cột người đọc"
        assert "{'" not in text and "target=" not in text


def test_new_verbs_have_human_expectation():
    for verb in sorted(UI_ASSERT_VERBS):
        args = {"target": "x", "by_name": "Nút X", "expected": "y", "pattern": "p",
                "name": "n", "max_ms": 1, "required": [], "key": "k", "url": "/",
                "mode": "anonymous", "value": "v"}.get(verb, {})
        if not args and ACTION_SPECS[verb].required:
            continue
        step = Step(1, StepKind.THEN, verb, args)
        text = step.expects()
        assert text and verb not in text, f"«{verb}» → {text}"

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
from qctool.generate.mapper import map_testcases  # noqa: E402
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


def test_mapped_step_with_by_name_passes_validation(ui_map):
    """Hồi quy: mapper sinh `by_name` mà `ACTION_SPECS` không khai.

    Validator trong `generate_all` chạy TRƯỚC mapper nên lỗi này bị che; chỉ khi
    ai đó validate sau khi map mới lộ. Test này validate đúng thứ tự đó.
    """
    case = _case("Bấm Đăng nhập bằng SSO", "Hiện Tên đăng nhập")
    map_testcases([case], ui_map, "https://portal.test")

    step = next(s for s in case.steps if s.action == "ui.click")
    assert "by_name" in step.args
    case.validate()                      # không được ném ValidationError


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
def test_mapper_prefers_test_id(ui_map):
    case = _case("Bấm Đăng nhập bằng SSO", "Hiện Tên đăng nhập")
    map_testcases([case], ui_map, "https://portal.test")

    click = next(s for s in case.steps if s.action == "ui.click")
    assert click.args["target"] == "btn-sso", "phải dùng test id, không dùng nhãn"
    assert click.args["by_name"] == "Đăng nhập bằng SSO"


def test_mapper_falls_back_to_element_id_without_test_id():
    ui = UIMap(base_url="https://x.test", crawled_at="now",
               pages=[PageMap(url="https://x.test/", title="t", elements=[
                   Element(id="nut_luu", role="button", name="Lưu", tag="button"),
               ])])
    case = _case("Bấm Lưu", "Hiện Lưu")
    map_testcases([case], ui, "https://x.test")
    click = next(s for s in case.steps if s.action == "ui.click")
    assert click.args["target"] == "nut_luu"


def test_mapped_cases_have_no_unmapped_steps(ui_map):
    case = _case("Bấm Đăng nhập bằng SSO", "Hiện Tên đăng nhập")
    map_testcases([case], ui_map, "https://portal.test")
    assert not case.needs_mapping
    assert case.execution == "auto"


def test_mapped_case_passes_batch_validator(ui_map):
    """Cả batch sau mapper phải qua được validator — cửa ra thật của tool."""
    case = _case("Bấm Đăng nhập bằng SSO", "Hiện Tên đăng nhập")
    map_testcases([case], ui_map, "https://portal.test")
    report = validate_batch([case])
    assert not report.errors, report.errors


# ── 3. Nhãn UX ──────────────────────────────────────────────────────────────
def test_disabled_label_maps_to_assert_disabled(ui_map):
    case = _case("Mở trang đăng nhập", "Nút Lưu bị vô hiệu hoá khi chưa nhập gì")
    map_testcases([case], ui_map, "https://portal.test")

    assert any(s.action == "assert.disabled" for s in case.steps), \
        "nhãn «vô hiệu hoá» phải map thành assert.disabled"
    step = next(s for s in case.steps if s.action == "assert.disabled")
    assert step.args["target"] == "btn-save"


def test_enabled_label_maps_to_assert_enabled(ui_map):
    case = _case("Mở trang đăng nhập", "Nút Lưu bấm được sau khi nhập tên")
    map_testcases([case], ui_map, "https://portal.test")
    assert any(s.action == "assert.enabled" for s in case.steps)


def test_js_error_label_maps_to_console_clean(ui_map):
    case = _case("Mở trang đăng nhập", "Không lộ stack trace ra UI khi có lỗi")
    map_testcases([case], ui_map, "https://portal.test")
    assert any(s.action == "assert.console_clean" for s in case.steps)


def test_broken_request_label_maps_to_requests_clean(ui_map):
    case = _case("Mở trang đăng nhập", "Không có request lỗi khi tải trang")
    map_testcases([case], ui_map, "https://portal.test")
    assert any(s.action == "assert.no_broken_requests" for s in case.steps)


def test_accessibility_label_maps_to_axe(ui_map):
    case = _case("Mở trang đăng nhập", "Trang đạt chuẩn WCAG AA")
    map_testcases([case], ui_map, "https://portal.test")
    assert any(s.action == "assert.axe" for s in case.steps)


def test_ux_label_without_known_element_stays_unmapped(ui_map):
    """Không có element nào trong map để trỏ tới ⇒ giữ văn xuôi, không đoán bừa."""
    case = _case("Mở trang đăng nhập", "Nút Xoá tài khoản bị vô hiệu hoá")
    map_testcases([case], ui_map, "https://portal.test")
    assert case.needs_mapping, "không được bịa selector cho element không có trong map"


def test_ux_mapping_beats_visible_mapping(ui_map):
    """«bị vô hiệu hoá» vừa khớp RE_VISIBLE vừa khớp RE_UI_UNAVAILABLE.

    Map nhầm sang `assert.visible` là bỏ mất đúng thứ cần kiểm — và test vẫn xanh
    vì nút quả thật đang hiện.
    """
    case = _case("Mở trang đăng nhập", "Nút Lưu hiện ra nhưng bị vô hiệu hoá")
    map_testcases([case], ui_map, "https://portal.test")
    assert any(s.action == "assert.disabled" for s in case.steps)
    assert not any(s.action == "assert.visible" for s in case.steps)


def test_mapper_still_deterministic_with_ux_labels(ui_map):
    def build():
        return [_case("Bấm Đăng nhập bằng SSO", "Nút Lưu bị vô hiệu hoá")]

    first, second = build(), build()
    map_testcases(first, ui_map, "https://portal.test")
    map_testcases(second, ui_map, "https://portal.test")
    assert [s.to_dict() for s in first[0].steps] == [s.to_dict() for s in second[0].steps]


def test_permission_visibility_case_needs_privileged_setup(ui_map):
    """Hồi quy: kiểm «mục X phải bị ẩn với người thiếu quyền» cần tài khoản thiếu quyền.

    Đã gặp thật trên portal: `Nav Projects visible; Users hidden` báo `Fail` vì tài
    khoản automation là platform administrator — thấy `Users` là **đúng** với quyền
    đó. Không đánh dấu `requires` thì tool gửi dev đi tìm bug không tồn tại.
    """
    from qctool.generate.mapper import _setup_requirement

    reason = _setup_requirement("Nav Projects visible; Users hidden")
    assert reason and "KHÔNG có quyền" in reason

    assert _setup_requirement("Sidebar ẩn mục Quản trị người dùng") is not None
    # Câu không liên quan quyền thì không được gắn cờ
    assert _setup_requirement("Bấm nút Đăng nhập") is None


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

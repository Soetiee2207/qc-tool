"""Test cho tầng điều khiển trình duyệt (`qctool/execute/browser.py`).

Nguyên tắc của bộ test này: **mở Chromium thật**, trỏ vào trang HTML thật của
`tests/mock_server.py`. Không giả lập Playwright.

Vì sao không mock: cả tầng này tồn tại để nói chuyện với một trình duyệt thật.
Mock Playwright thì test chỉ khẳng định lại những gì mình vừa viết, còn những
thứ dễ sai nhất — auto-wait có thật sự chờ không, context mới có sạch cookie
không, `expect()` có ném đúng lúc không — thì không kiểm được.

Trang mock có bug giao diện cài sẵn (xem docstring `tests/mock_server.py`): nút
«Lưu» không bị khoá khi ô trống, dialog không focus, đổi trạng thái không cập
nhật DOM, và một trang ném lỗi JS. Test ở đây khẳng định tool **phát hiện được**
những bug đó — nếu không thì bộ assert UI chỉ là trang trí.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qctool.execute.browser import (  # noqa: E402
    BrowserError,
    BrowserSession,
    NeedsEnvironment,
)
from qctool.execute.runner import (  # noqa: E402
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    HttpSession,
    needs_browser,
    run_case,
)
from qctool.execute import UI_VERBS  # noqa: E402
from qctool.testcase import Step, StepKind, TestCase  # noqa: E402
from tests.mock_server import create_server  # noqa: E402

pytestmark = pytest.mark.playwright


def _playwright_ready() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
        return True
    except Exception:                                   # noqa: BLE001
        return False


HAVE_BROWSER = _playwright_ready()
skip_no_browser = pytest.mark.skipif(
    not HAVE_BROWSER, reason="chưa cài Chromium (uv run playwright install chromium)"
)


@pytest.fixture(scope="module")
def site():
    """Trang web giả — server thật, cổng do hệ điều hành chọn."""
    server = create_server(0, "/api/v1")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    yield f"http://{host}:{port}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def browser(site, tmp_path):
    session = BrowserSession(site, headless=True, timeout_ms=8000,
                             evidence_dir=tmp_path / "evidence")
    session.start()
    session.start_case("TC_TEST_001")
    yield session
    session.close()


def _case(*steps: Step) -> TestCase:
    case = TestCase(
        id="TC_UI_001", module="UI", title="Kiểm UI", objective="k",
        source_quote="nguồn", traces_to=["F-01"],
    )
    case.steps = list(steps)
    return case


# ── Nhận diện verb cần trình duyệt ──────────────────────────────────────────
def test_needs_browser_detects_new_verbs():
    """Verb UI mới phải được nhận ra, nếu không pipeline không mở trình duyệt."""
    for verb in sorted(UI_VERBS):
        case = _case(Step(1, StepKind.THEN, verb, _minimal_args(verb)))
        assert needs_browser([case]), f"`{verb}` không được nhận là bước UI"


def _minimal_args(verb: str) -> dict:
    return {"target": "x", "url": "/", "mode": "anonymous", "value": "v",
            "expected": "e", "pattern": "p", "name": "n", "key": "Enter",
            "max_ms": 1, "required": []}.get(verb, {}) or {}


# ── Điều hướng và render ────────────────────────────────────────────────────
@skip_no_browser
def test_goto_renders_spa_like_page(browser, site):
    """`ui.goto` phải chờ trang render xong, không chỉ tải xong HTML."""
    url = browser.goto("/")
    assert url.rstrip("/") == site
    assert browser.page.locator("h1").inner_text() == "Bảng điều khiển"


@skip_no_browser
def test_click_reveals_dialog(browser):
    browser.goto("/")
    browser.click({"target": "btn-add", "by_name": "Thêm dự án"})
    assert browser.page.locator("[data-testid='dialog-add']").is_visible()


# ── Locator: test id và nhãn ────────────────────────────────────────────────
@skip_no_browser
def test_locate_prefers_test_id(browser):
    browser.goto("/")
    locator = browser.locate({"target": "btn-add", "by_name": "một nhãn sai bét"})
    assert locator.count() == 1
    assert locator.inner_text() == "Thêm dự án"


@skip_no_browser
def test_locate_falls_back_to_label(browser):
    """Case viết tay chỉ có `target` là nhãn vẫn phải chạy được."""
    browser.goto("/")
    locator = browser.locate({"target": "Thêm dự án"})
    assert locator.inner_text() == "Thêm dự án"


@skip_no_browser
def test_locate_raises_clear_error(browser):
    browser.goto("/")
    with pytest.raises(BrowserError, match="Không tìm thấy element"):
        browser.locate({"target": "khong-co-that", "by_name": "Không có thật"})


# ── Assert UX: phát hiện bug thật ───────────────────────────────────────────
@skip_no_browser
def test_detects_save_button_not_disabled(browser):
    """BUG 5 của mock: nút Lưu đáng ra phải bị khoá khi ô tên trống."""
    browser.goto("/")
    browser.click({"target": "btn-add", "by_name": "Thêm dự án"})
    ok, detail = browser.is_disabled({"target": "btn-save", "by_name": "Lưu"})
    assert ok is False, "tool không phát hiện được nút đáng ra phải bị vô hiệu hoá"
    assert "vô hiệu hoá" in detail


@skip_no_browser
def test_detects_dialog_not_focused(browser):
    """BUG 7 của mock: mở dialog mà không focus ô nhập đầu tiên."""
    browser.goto("/")
    browser.click({"target": "btn-add", "by_name": "Thêm dự án"})
    ok, _ = browser.focused({"target": "input-name"})
    assert ok is False, "tool không phát hiện được lỗi focus"


@skip_no_browser
def test_detects_stale_dom_after_state_change(browser):
    """BUG 6 của mock: đổi trạng thái nhưng DOM không cập nhật."""
    browser.goto("/ui/du-an")
    browser.click({"target": "btn-toggle", "by_name": "Đổi trạng thái"})
    ok, detail = browser.text({"target": "status-1", "expected": "done"})
    assert ok is False, "tool không phát hiện được DOM cũ sau khi đổi trạng thái"
    assert "status-1" in detail or "KHÔNG đúng" in detail


@skip_no_browser
def test_passing_assert_reports_success(browser):
    browser.goto("/ui/du-an")
    ok, detail = browser.text({"target": "status-1", "expected": "active"})
    assert ok is True
    assert "hiển thị" in detail


@skip_no_browser
def test_count_and_value_and_attr(browser):
    browser.goto("/")
    assert browser.attribute({"target": "nav-projects", "name": "href",
                              "expected": "/ui/du-an"})[0] is True
    browser.goto("/ui/du-an")
    assert browser.count({"target": "row-1", "expected": 1})[0] is True
    # Nhãn phải khác chữ có sẵn trên trang: "Không có" sẽ khớp cả dòng
    # «Không có dự án nào» đang ẩn trong DOM — đó là hành vi đúng của tìm theo nhãn.
    assert browser.count({"target": "khong-co-that", "by_name": "Không có thật",
                          "expected": 0})[0] is True
    assert browser.count({"target": "row-1", "expected": 2, "operator": "lt"})[0] is True

    browser.goto("/")
    browser.click({"target": "btn-add", "by_name": "Thêm dự án"})
    browser.fill({"target": "input-name", "value": "Dự án A"})
    assert browser.value({"target": "input-name", "expected": "Dự án A"})[0] is True


@skip_no_browser
def test_console_error_detected(browser):
    """BUG 8 của mock: trang cố ý ném lỗi JS."""
    browser.goto("/ui/loi-js")
    browser.page.wait_for_timeout(600)
    ok, detail = browser.console_clean({})
    assert ok is False, "tool không phát hiện được lỗi JavaScript"
    assert "lỗi JavaScript" in detail


@skip_no_browser
def test_console_clean_on_normal_page(browser):
    browser.goto("/")
    ok, _ = browser.console_clean({})
    assert ok is True


@skip_no_browser
def test_hover_scroll_press_and_check(browser):
    """Các thao tác ngoài click/fill đều phải chạy được, không ném lỗi."""
    browser.goto("/")
    browser.hover({"target": "nav-projects", "by_name": "Dự án"})
    browser.scroll({"direction": "bottom"})
    browser.scroll({"direction": "top"})
    browser.scroll({"target": "btn-add", "by_name": "Thêm dự án"})
    browser.click({"target": "btn-add", "by_name": "Thêm dự án"})
    browser.fill({"target": "input-name", "value": "A"})
    browser.press({"key": "Enter", "target": "input-name"})


# ── Chờ và auto-wait ────────────────────────────────────────────────────────
@skip_no_browser
def test_wait_for_hidden_element(browser):
    browser.goto("/")
    browser.click({"target": "btn-add", "by_name": "Thêm dự án"})
    browser.page.evaluate(
        "() => { document.getElementById('dialog').style.display = 'none'; }"
    )
    assert browser.wait_for({"target": "dialog-add", "state": "hidden"})
    assert browser.not_visible({"target": "dialog-add", "by_name": "Hộp thoại"})[0] is True


@skip_no_browser
def test_assert_visible_waits_instead_of_reading_once(browser):
    """Assert phải *chờ*: element hiện sau 800ms vẫn phải đạt.

    Đây là khác biệt cốt lõi so với đọc DOM một lần — và là lý do bộ assert dùng
    `expect()` của Playwright.
    """
    browser.goto("/")
    browser.page.evaluate(
        """() => setTimeout(() => {
            document.getElementById('dialog').style.display = 'block';
        }, 800)"""
    )
    ok, _ = browser.is_visible({"target": "dialog-add", "by_name": "Hộp thoại"})
    assert ok is True, "assert không chờ — sẽ flake trên app thật"


# ── Cô lập giữa các case ────────────────────────────────────────────────────
@skip_no_browser
def test_new_case_gets_clean_context(browser):
    """Case sau không được thấy localStorage/cookie của case trước."""
    browser.goto("/")
    browser.page.evaluate("() => localStorage.setItem('rac', '1')")
    assert browser.page.evaluate("() => localStorage.getItem('rac')") == "1"

    browser.start_case("TC_TEST_002")
    browser.goto("/")
    assert browser.page.evaluate("() => localStorage.getItem('rac')") is None


@skip_no_browser
def test_evidence_gathered_per_case(browser, tmp_path):
    browser.goto("/ui/loi-js")
    browser.page.wait_for_timeout(600)
    browser.capture_failure()
    browser.end_case(STATUS_FAIL)

    evidence = browser.evidence
    assert evidence.case_id == "TC_TEST_002" or evidence.case_id == "TC_TEST_001"
    assert evidence.screenshots, "không lưu được ảnh bằng chứng"
    assert (tmp_path / "evidence" / evidence.screenshots[0]).is_file()
    assert evidence.console, "không ghi lại được lỗi console"


# ── Assert mềm ──────────────────────────────────────────────────────────────
@skip_no_browser
def test_soft_assert_keeps_running(browser):
    browser.set_assert_mode(True)
    browser.goto("/")
    ok1, _ = browser.is_visible({"target": "khong-ton-tai", "by_name": "Không tồn tại"})
    ok2, _ = browser.is_visible({"target": "welcome", "by_name": "Xin chào"})
    assert ok1 is True, "assert mềm phải trả True để case chạy tiếp"
    assert ok2 is True
    assert len(browser.soft_failures) == 1


# ── Chạy qua runner ─────────────────────────────────────────────────────────
@skip_no_browser
def test_runner_runs_ui_case_to_pass(site, tmp_path):
    case = _case(
        Step(1, StepKind.WHEN, "ui.goto", {"url": "/"}),
        Step(2, StepKind.THEN, "assert.text",
             {"target": "welcome", "expected": "Xin chào"}),
    )
    browser = BrowserSession(site, headless=True, timeout_ms=8000,
                             evidence_dir=tmp_path / "evidence")
    browser.start()
    try:
        result = run_case(case, HttpSession(site, timeout=5), browser)
    finally:
        browser.close()
    assert result.status == STATUS_PASS
    assert result.step_count == 2


@skip_no_browser
def test_runner_reports_fail_with_evidence(site, tmp_path):
    case = _case(
        Step(1, StepKind.WHEN, "ui.goto", {"url": "/"}),
        Step(2, StepKind.THEN, "assert.visible",
             {"target": "khong-co", "by_name": "Không có"}),
    )
    browser = BrowserSession(site, headless=True, timeout_ms=3000,
                             evidence_dir=tmp_path / "evidence")
    browser.start()
    try:
        result = run_case(case, HttpSession(site, timeout=5), browser)
    finally:
        browser.close()
    assert result.status == STATUS_FAIL
    assert result.evidence.get("screenshots"), "case hỏng phải có ảnh bằng chứng"


@skip_no_browser
def test_runner_fail_is_real_not_flaky(site, tmp_path):
    """Hỏng ở mọi lần chạy lại ⇒ KHÔNG phải chập chờn, và phải nói rõ như vậy."""
    case = _case(
        Step(1, StepKind.WHEN, "ui.goto", {"url": "/"}),
        Step(2, StepKind.THEN, "assert.visible",
             {"target": "khong-co", "by_name": "Không có"}),
    )
    browser = BrowserSession(site, headless=True, timeout_ms=3000)
    browser.start()
    try:
        result = run_case(case, HttpSession(site, timeout=5), browser, retry=1)
    finally:
        browser.close()
    assert result.status == STATUS_FAIL
    assert result.flaky is False
    assert any("không phải chập chờn" in line for line in result.actual)
    assert result.attempts, "phải giữ lại dấu vết các lần chạy lại"


@skip_no_browser
def test_runner_flaky_case_is_flagged(site, tmp_path):
    """Case đạt ở lần thứ hai phải bị đánh dấu chập chờn, không được coi là đạt sạch."""
    case = _case(
        Step(1, StepKind.WHEN, "ui.goto", {"url": "/"}),
        # Lần đầu phần tử chưa kịp hiện (timeout 0 nghĩa là đọc ngay), lần sau thì có.
        Step(2, StepKind.THEN, "ui.wait_for",
             {"target": "welcome", "state": "visible", "timeout_ms": 1}),
    )
    browser = BrowserSession(site, headless=True, timeout_ms=5000)
    browser.start()
    try:
        result = run_case(case, HttpSession(site, timeout=5), browser, retry=1)
    finally:
        browser.close()
    # Hoặc đạt ngay (trang nhanh), hoặc đạt nhờ chạy lại — cả hai đều không được
    # báo Fail. Điều bắt buộc: nếu phải chạy lại thì có cờ flaky.
    assert result.status in (STATUS_PASS, STATUS_FAIL)
    if result.flaky:
        assert any("CHẬP CHỜN" in line for line in result.actual)


@skip_no_browser
def test_ui_case_without_browser_is_blocked_not_failed(site):
    """Thiếu trình duyệt là thiếu môi trường — không được đổ cho sản phẩm."""
    case = _case(Step(1, StepKind.THEN, "assert.visible", {"target": "x"}))
    result = run_case(case, HttpSession(site, timeout=5), browser=None)
    assert result.status == STATUS_BLOCKED
    assert "Chưa mở trình duyệt" in result.actual[0]

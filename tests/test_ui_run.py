"""Test cho retry / phân loại chập chờn / bằng chứng.

Không cần trình duyệt: dùng một `BrowserSession` giả chỉ trả kết quả theo kịch bản.
Điều cần khẳng định không phải "Playwright chạy được" (đã có `test_browser.py`),
mà là **cách tool kể lại kết quả**: hỏng rồi đạt ở lần sau thì phải bị gọi là chập
chờn, chứ không được tính là đạt sạch. Đây là chuyện trung thực của báo cáo, không
phải chuyện kỹ thuật của trình duyệt.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qctool.execute import (  # noqa: E402
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    HttpSession,
    run_case,
)
from qctool.report import build_markdown  # noqa: E402
from qctool.execute.runner import RunResult  # noqa: E402
from qctool.testcase import Step, StepKind, TestCase  # noqa: E402


class FakeEvidence:
    def __init__(self) -> None:
        self.case_id = ""
        self.screenshots: list[str] = []
        self.trace = None
        self.console: list[str] = []
        self.network: list[str] = []
        self.axe: list[str] = []
        self.note = ""

    def is_empty(self) -> bool:
        return not (self.screenshots or self.trace or self.console
                    or self.network or self.axe or self.note)

    def to_dict(self) -> dict:
        out: dict = {}
        if self.screenshots:
            out["screenshots"] = list(self.screenshots)
        if self.trace:
            out["trace"] = self.trace
        if self.console:
            out["console"] = list(self.console)
        if self.network:
            out["network"] = list(self.network)
        if self.note:
            out["note"] = self.note
        return out


class FakeBrowser:
    """Trình duyệt giả: `visible_after` lần gọi đầu thì báo không thấy.

    Bộ đếm **không** reset theo `start_case`: mỗi case thật sự mở context mới,
    nhưng ở đây ta muốn mô phỏng "lần đầu không thấy, lần sau thấy" — tức là một
    điều kiện của sản phẩm, không phải trạng thái của trình duyệt.
    """

    def __init__(self, visible_after: int = 0, evidence: bool = False) -> None:
        self.calls = 0
        self.visible_after = visible_after
        self.evidence = FakeEvidence()
        self.soft_failures: list[str] = []
        self.cases: list[str] = []

    # vòng đời
    def start_case(self, case_id: str) -> None:
        self.evidence = FakeEvidence()
        self.evidence.case_id = case_id
        self.cases.append(case_id)

    def end_case(self, status: str = "") -> None:
        pass

    def set_assert_mode(self, soft: bool) -> None:
        self.soft_failures = []

    def capture_failure(self) -> None:
        self.evidence.screenshots.append("TC_X_001-fail.png")
        self.evidence.note = "URL lúc fail: https://x.test/login"

    # bước
    def goto(self, url: str) -> str:
        return f"https://x.test{url}"

    def is_visible(self, args: dict) -> tuple[bool, str]:
        self.calls += 1
        if self.calls > self.visible_after:
            return True, "«Xin chào» hiện trên màn hình"
        return False, "«Xin chào» KHÔNG hiện trên màn hình"


def _case() -> TestCase:
    case = TestCase(id="TC_X_001", module="X", title="Kiểm UI", objective="o",
                    source_quote="q", traces_to=["F-1"])
    case.steps = [
        Step(1, StepKind.WHEN, "ui.goto", {"url": "/"}),
        Step(2, StepKind.THEN, "assert.visible", {"target": "welcome",
                                                  "by_name": "Xin chào"}),
    ]
    return case


# ── Chập chờn ───────────────────────────────────────────────────────────────
def test_retry_recovers_and_marks_flaky():
    """Đạt ở lần thứ hai KHÔNG phải là đạt — phải mang cờ chập chờn."""
    browser = FakeBrowser(visible_after=1)
    result = run_case(_case(), HttpSession("https://x.test"), browser, retry=1)

    assert result.status == STATUS_PASS
    assert result.flaky is True
    assert result.attempts, "phải giữ lại dấu vết lần hỏng đầu"
    assert any("CHẬP CHỜN" in line for line in result.actual)


def test_no_retry_means_no_flaky_flag():
    browser = FakeBrowser(visible_after=0)
    result = run_case(_case(), HttpSession("https://x.test"), browser)
    assert result.status == STATUS_PASS
    assert result.flaky is False
    assert result.attempts == []


def test_real_failure_stays_failed_and_says_so():
    browser = FakeBrowser(visible_after=99)
    result = run_case(_case(), HttpSession("https://x.test"), browser, retry=2)

    assert result.status == STATUS_FAIL
    assert result.flaky is False
    assert len(result.attempts) >= 2
    assert any("không phải chập chờn" in line for line in result.actual)


def test_retry_does_not_mask_blocked():
    """Case thiếu môi trường thì chạy lại bao nhiêu lần cũng vô nghĩa."""
    case = _case()
    case.requires = "Cần tài khoản không có quyền"
    browser = FakeBrowser()
    result = run_case(case, HttpSession("https://x.test"), browser, retry=2)
    assert result.status == "Blocked"
    assert browser.calls == 0, "không được chạm vào trình duyệt"


# ── Bằng chứng ──────────────────────────────────────────────────────────────
def test_failure_carries_evidence():
    browser = FakeBrowser(visible_after=99)
    result = run_case(_case(), HttpSession("https://x.test"), browser)

    assert result.status == STATUS_FAIL
    assert result.evidence.get("screenshots"), "case hỏng phải có ảnh"
    assert result.evidence.get("note"), "phải ghi lại URL lúc hỏng"


def test_each_case_gets_its_own_browser_context():
    browser = FakeBrowser()
    run_case(_case(), HttpSession("https://x.test"), browser)
    run_case(_case(), HttpSession("https://x.test"), browser)
    assert browser.cases == ["TC_X_001", "TC_X_001"], \
        "mỗi case phải mở context riêng, không dùng chung"


def test_environment_problem_is_blocked_not_failed():
    """Không nạp được axe-core (mạng chập) là thiếu môi trường, không phải bug sản phẩm."""
    from qctool.execute.browser import NeedsEnvironment

    class BrokenAxe(FakeBrowser):
        def axe_scan(self, args: dict):
            raise NeedsEnvironment("Không nạp được axe-core để quét accessibility")

    case = TestCase(id="TC_X_002", module="X", title="Kiểm a11y", objective="o",
                    source_quote="q", traces_to=["F-2"])
    case.steps = [
        Step(1, StepKind.WHEN, "ui.goto", {"url": "/"}),
        Step(2, StepKind.THEN, "assert.axe", {}),
    ]
    result = run_case(case, HttpSession("https://x.test"), BrokenAxe())
    assert result.status == STATUS_BLOCKED
    assert "axe-core" in (result.blocked_reason or "")


def test_page_unreachable_is_blocked_not_failed():
    """Hồi quy lượt chạy thật trên portal: trang không tải được vì mạng của máy
    test (`ERR_NETWORK_CHANGED`) từng bị ghi thành `Fail` — tức là đổ lỗi cho sản
    phẩm trong khi chưa hề chạm được vào nó."""
    from qctool.execute.browser import NeedsEnvironment

    class Unreachable(FakeBrowser):
        def goto(self, url: str) -> str:
            raise NeedsEnvironment(
                "Không mở được https://x.test/ sau 3 lần thử vì lỗi mạng của máy "
                "chạy test (ERR_NETWORK_CHANGED)."
            )

    case = TestCase(id="TC_X_003", module="X", title="Mở trang", objective="o",
                    source_quote="q", traces_to=["F-3"])
    case.steps = [
        Step(1, StepKind.WHEN, "ui.goto", {"url": "/"}),
        Step(2, StepKind.THEN, "assert.visible", {"target": "welcome"}),
    ]
    result = run_case(case, HttpSession("https://x.test"), Unreachable())
    assert result.status == STATUS_BLOCKED
    assert "ERR_NETWORK_CHANGED" in (result.blocked_reason or "")
    assert any("Chưa chạy" in line for line in result.actual)


def test_env_error_markers_cover_real_cases():
    """Các mã lỗi mạng phải được nhận diện — thiếu một mã là một lần báo Fail sai."""
    from qctool.execute.browser import ENV_ERROR_MARKERS, _is_env_problem

    for marker in ("ERR_NETWORK_CHANGED", "ERR_NAME_NOT_RESOLVED",
                   "ERR_CONNECTION_REFUSED", "ERR_INTERNET_DISCONNECTED"):
        assert marker in ENV_ERROR_MARKERS
        assert _is_env_problem(Exception(f"net::{marker}"), [])
    # Lỗi thật của sản phẩm thì KHÔNG được coi là lỗi môi trường
    assert _is_env_problem(Exception("Locator expected to be visible"), []) is False


def test_retry_stops_when_rerun_is_blocked():
    """Chạy lại mà **không chạy được** (thiếu đăng nhập) thì không phải chập chờn.

    Chập chờn nghĩa là đạt rồi lại không; còn đây là chưa kết luận được gì. Ghi
    `flaky` ở trường hợp này làm báo cáo tự mâu thuẫn — vừa nói "chập chờn" vừa
    nói "bị chặn". Đã gặp thật trên portal (lượt chạy 2026-09-21 15:01).
    """
    from qctool.execute.browser import NeedsLogin

    class BlockedOnRerun(FakeBrowser):
        def start_case(self, case_id: str) -> None:
            super().start_case(case_id)

        def is_visible(self, args: dict) -> tuple[bool, str]:
            self.calls += 1
            if self.calls > 1:
                raise NeedsLogin("Bị chuyển về trang đăng nhập — chưa xác thực")
            return False, "«Xin chào» KHÔNG hiện trên màn hình"

    result = run_case(_case(), HttpSession("https://x.test"), BlockedOnRerun(), retry=1)
    assert result.status == STATUS_BLOCKED
    assert result.flaky is False
    assert any("chưa kết luận" in line for line in result.actual)
    assert len(result.attempts) == 2, "phải giữ vết của cả hai lần"


def test_api_case_after_failed_ui_case_is_not_contaminated():
    """Hồi quy: case API thuần không được thừa hưởng lỗi của case UI chạy trước.

    Đã gặp thật trên portal: 8 case API có **mọi bước `[OK]`** nhưng bị báo `Fail`
    kèm dòng "1 bước kiểm tra không đạt". Nguyên nhân: `soft_failures` của
    `BrowserSession` không được reset cho case không dùng trình duyệt, nên case API
    đọc phải giá trị còn sót của case UI trước đó.

    Đây là loại lỗi tệ nhất mà tool này có thể mắc: gán lỗi của case này cho case
    khác, rồi gửi dev đi tìm bug không tồn tại.
    """
    from qctool.execute.runner import run_cases

    ui_case = TestCase(id="TC_UI_900", module="UI", title="UI hỏng", objective="o",
                       source_quote="q", traces_to=["F-1"])
    ui_case.steps = [
        Step(1, StepKind.WHEN, "ui.goto", {"url": "/"}),
        Step(2, StepKind.THEN, "assert.visible", {"target": "khong-co"}),
    ]

    api_case = TestCase(id="TC_API_900", module="API", title="API đạt", objective="o",
                        source_quote="q", traces_to=["F-2"])
    api_case.steps = [
        Step(1, StepKind.WHEN, "http.request",
             {"method": "GET", "path": "/health", "auth": "none", "save_as": "res"}),
        Step(2, StepKind.THEN, "assert.http_status", {"expected": 200, "source": "res"}),
    ]

    class StubBrowser(FakeBrowser):
        def is_visible(self, args: dict) -> tuple[bool, str]:
            self.soft_failures.append("«khong-co» KHÔNG hiện trên màn hình")
            return False, "«khong-co» KHÔNG hiện trên màn hình"

    browser = StubBrowser()
    browser.soft_failures = []
    session = HttpSession("http://127.0.0.1:1", timeout=1)   # sẽ lỗi mạng, không sao

    # Case API dùng mock server thật ở nơi khác; ở đây chỉ cần chạy nó SAU case UI
    # hỏng và kiểm nó không bị dính `soft_failures`.
    import threading
    from tests.mock_server import create_server

    server = create_server(0, "/api/v1")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    real = HttpSession(f"http://{host}:{port}/api/v1", timeout=5)
    try:
        results = run_cases([ui_case, api_case], real, browser=browser, soft_assert=True)
    finally:
        server.shutdown()
        server.server_close()

    ui_result, api_result = results.cases
    assert ui_result.status == STATUS_FAIL, "case UI phải hỏng"
    assert api_result.status == STATUS_PASS, (
        f"case API bị lây lỗi của case UI: {api_result.actual}"
    )


# ── Báo cáo ─────────────────────────────────────────────────────────────────
def _result_with(*cases) -> RunResult:
    result = RunResult(started_at="2026-09-21 10:00:00", finished_at="2026-09-21 10:01:00",
                       base_url="https://x.test", environment="mock")
    result.cases = list(cases)
    return result


def test_report_has_flaky_section():
    browser = FakeBrowser(visible_after=1)
    flaky_case = run_case(_case(), HttpSession("https://x.test"), browser, retry=1)
    report = build_markdown(_result_with(flaky_case))

    assert "chập chờn" in report.lower()
    assert "## 6. Test chập chờn" in report


def test_report_has_evidence_section():
    browser = FakeBrowser(visible_after=99)
    failed = run_case(_case(), HttpSession("https://x.test"), browser)
    report = build_markdown(_result_with(failed))

    assert "## 7. Bằng chứng" in report
    assert "TC_X_001-fail.png" in report


def test_report_without_flaky_or_evidence_has_no_empty_sections():
    browser = FakeBrowser(visible_after=0)
    passed = run_case(_case(), HttpSession("https://x.test"), browser)
    report = build_markdown(_result_with(passed))

    assert "## 6. Test chập chờn" not in report, "không có chập chờn thì không mở mục"
    assert "## 7. Bằng chứng" not in report


def test_flaky_cases_property():
    browser = FakeBrowser(visible_after=1)
    flaky = run_case(_case(), HttpSession("https://x.test"), browser, retry=1)
    clean = run_case(_case(), HttpSession("https://x.test"), FakeBrowser())
    result = _result_with(flaky, clean)
    assert [c.case_id for c in result.flaky_cases] == ["TC_X_001"]


# ── CSV / JSON ──────────────────────────────────────────────────────────────
def test_flaky_and_evidence_exported(tmp_path):
    from qctool.report import write_csv, write_json

    browser = FakeBrowser(visible_after=1)
    flaky = run_case(_case(), HttpSession("https://x.test"), browser, retry=1)
    result = _result_with(flaky)

    write_json(result, tmp_path / "r.json")
    write_csv(result, tmp_path / "r.csv")

    assert '"flaky": true' in (tmp_path / "r.json").read_text(encoding="utf-8")
    csv_text = (tmp_path / "r.csv").read_text(encoding="utf-8-sig")
    assert "Chập chờn" in csv_text.splitlines()[0]

"""Browser session — chạy bước `ui.*` bằng trình duyệt thật (Playwright).

Cùng giao diện với `HttpSession` để runner xử lý cả hai giống nhau. Trình duyệt
chỉ mở khi thật sự có bước `ui.*` cần chạy — không tốn tài nguyên cho bộ test API.

Ba thứ tầng này thêm vào so với việc gọi Playwright thô, và lý do:

1. **Context riêng cho từng testcase.** Một context dùng chung nghĩa là case
   trước để lại dữ liệu phá case sau — đúng cái bẫy đã ghi ở brainstorm R4:
   "chạy riêng thì pass, chạy cả suite thì fail".
2. **Assert bằng `expect()` của Playwright**, tức là *tự chờ*. Đọc DOM một lần
   rồi kết luận là nguồn flake số một của UI test: SPA chưa render xong thì
   assertion sai một cách ngẫu nhiên, và cái sai ngẫu nhiên đó bị báo thành bug.
3. **Bằng chứng tự động**: ảnh chụp, trace, log console, request lỗi — gắn theo
   testcase ID. Không có nó thì người sửa bug chỉ nhận được chữ "Fail".
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from ..response_capture import origin_of, validate_capture, matches_request

DEFAULT_VIEWPORT = {"width": 1440, "height": 900}

# Request do chính trình duyệt phát ra để đo hiệu năng (GA, telemetry), không
# phải app gọi hỏng. Bỏ qua khi kiểm `assert.no_broken_requests`.
_IGNORED_REQUEST_HOSTS = ("google-analytics.com", "googletagmanager.com", "sentry.io")

# Lỗi ở tầng **mạng của máy test**, không phải câu trả lời của sản phẩm. Gặp mấy
# mã này thì chưa hề chạm được vào hệ thống cần test ⇒ `Blocked`, không `Fail`.
#
# Đã gặp thật trên portal: `goto` hết 30s rồi ném TimeoutError, trong log request
# có `net::ERR_NETWORK_CHANGED`, và trang dừng ở `chrome-error://chromewebdata/`.
# Báo cáo ghi case đó là `Lỗi` — tức là gửi dev đi tìm bug không tồn tại, trong khi
# nguyên nhân là mạng của máy chạy test đổi giữa lượt.
ENV_ERROR_MARKERS = (
    "ERR_NETWORK_CHANGED",
    "ERR_NAME_NOT_RESOLVED",
    "ERR_INTERNET_DISCONNECTED",
    "ERR_CONNECTION_REFUSED",
    "ERR_CONNECTION_TIMED_OUT",
    "ERR_ADDRESS_UNREACHABLE",
    "ERR_CONNECTION_RESET",
    "ERR_PROXY_CONNECTION_FAILED",
)

MAX_TEXT = 160


class BrowserError(Exception):
    """Không mở được trình duyệt, hoặc Playwright chưa cài."""


class NeedsEnvironment(Exception):
    """Bước này không chạy được vì **môi trường**, không phải vì sản phẩm.

    Ví dụ đã gặp thật: `assert.axe` cần tải axe-core từ CDN; mạng chập làm bước
    đó hỏng. Nếu để nó thành `Fail` thì báo cáo nói "sản phẩm sai" trong khi
    sản phẩm chưa hề được kiểm — đúng loại nói dối mà cả tool này sinh ra để tránh.
    """


class ResponseCaptureError(NeedsEnvironment):
    """Cannot identify one completed response; never echo transport/body secrets."""
    def __init__(self, code):
        self.code = code
        super().__init__(code + ": no unique safely captured UI response")


class NeedsLogin(NeedsEnvironment):
    """Case cần đăng nhập mà lượt chạy này không có thông tin đăng nhập.

    Phân biệt với `Fail`: sản phẩm chưa hề trả sai. Chuyển hướng về trang đăng
    nhập khi chưa đăng nhập là hành vi **đúng**. Báo `Fail` ở đây là gửi dev đi
    tìm bug không tồn tại.
    """


@dataclass
class Evidence:
    """Bằng chứng gắn theo testcase ID.

    Đây là thứ biến "Fail" từ một lời khẳng định thành một thứ kiểm chứng được.
    Ảnh + trace + log console + request lỗi nằm cùng một chỗ, cùng một ID.
    """

    case_id: str = ""
    screenshots: list[str] = field(default_factory=list)
    trace: str | None = None
    console: list[str] = field(default_factory=list)
    network: list[str] = field(default_factory=list)
    axe: list[str] = field(default_factory=list)
    note: str = ""

    def is_empty(self) -> bool:
        return not (self.screenshots or self.trace or self.console
                    or self.network or self.axe or self.note)

    def to_dict(self) -> dict:
        out: dict = {}
        if self.screenshots:
            out["screenshots"] = self.screenshots
        if self.trace:
            out["trace"] = self.trace
        if self.console:
            out["console"] = self.console[:20]
        if self.network:
            out["network"] = self.network[:20]
        if self.axe:
            out["axe"] = self.axe[:20]
        if self.note:
            out["note"] = self.note
        return out


def _short(text: str, limit: int = MAX_TEXT) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _looks_like_test_id(value: str) -> bool:
    """`target` là test id hay là nhãn hiển thị?

    `add-project` / `project_row_3` → test id. `Thêm dự án` → nhãn (có dấu cách
    hoặc ký tự ngoài ASCII không đáng tin để làm id).
    """
    return bool(re.fullmatch(r"[A-Za-z0-9_.:-]{2,60}", value or ""))


class BrowserSession:
    """Bọc Playwright lại, chỉ phơi ra những gì vocabulary cần."""

    def __init__(self, base_url: str, *, headless: bool = True,
                 timeout_ms: int = 30000, evidence_dir: Path | None = None,
                 authenticated: bool | None = None,
                 storage_state: Path | None = None,
                 viewport: dict | None = None,
                 trace: bool = False, axe: bool = False,
                 axe_severity: str = "serious",
                 inflight_ms: int = 1500) -> None:
        self.base_url = base_url.rstrip("/")
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.evidence_dir = Path(evidence_dir) if evidence_dir else None
        # `True` = có thông tin đăng nhập, `False` = chắc chắn chưa, `None` = không rõ
        self.authenticated = authenticated
        self.storage_state = storage_state
        self.viewport = dict(viewport or DEFAULT_VIEWPORT)
        self.trace_enabled = trace
        self.axe_enabled = axe
        self.axe_severity = axe_severity
        self.inflight_ms = inflight_ms

        self.case_id: str = ""
        self.soft: bool = False                    # chế độ assert mềm
        self.soft_failures: list[str] = []
        self.evidence = Evidence()

        self._captured_token: str | None = None
        self._pw = None
        self._browser = None
        self._page = None
        self._context = None
        self._expect = None
        self._console: list[str] = []
        self._network: list[str] = []
        self._capture_private = False
        self._inflight = 0
        self._last_activity = 0.0
        self._axe_source: str | None = None

    # ── Vòng đời ────────────────────────────────────────────────────────────
    def start(self) -> None:
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError as exc:
            raise BrowserError(
                "Chưa cài Playwright. Chạy:\n"
                "  uv add playwright\n"
                "  uv run playwright install chromium"
            ) from exc

        self._expect = expect
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)

    def close(self) -> None:
        with contextlib.suppress(Exception):
            if self._context is not None:
                self._context.close()
        for closer in (self._browser, self._pw):
            with contextlib.suppress(Exception):
                closer.close() if closer else None
            with contextlib.suppress(Exception):
                closer.stop() if closer and closer is self._pw else None

    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # ── Cô lập theo testcase ────────────────────────────────────────────────
    def start_case(self, case_id: str) -> None:
        """Mở context mới sạch cho một testcase.

        Mỗi case một context nghĩa là cookie/localStorage/session của case trước
        không rò sang case sau. Đây là điều kiện để "chạy riêng pass" và "chạy cả
        suite pass" là cùng một chuyện.
        """
        self.end_case()
        self._ensure_browser()
        options: dict = {
            "viewport": self.viewport,
            "ignore_https_errors": True,
        }
        if self.storage_state and Path(self.storage_state).is_file():
            options["storage_state"] = str(self.storage_state)

        self.case_id = case_id
        self.soft_failures = []
        self.evidence = Evidence(case_id=case_id)
        self._console = []
        self._network = []
        self._inflight = 0
        self._last_activity = time.monotonic()

        self._context = self._browser.new_context(**options)
        self._context.set_default_timeout(self.timeout_ms)
        if self.trace_enabled:
            with contextlib.suppress(Exception):
                self._context.tracing.start(screenshots=True, snapshots=True)

        self._page = self._context.new_page()
        self._page.on("console", self._on_console)
        self._page.on("pageerror", self._on_pageerror)
        self._page.on("request", self._on_request)
        self._page.on("response", self._on_response)
        self._page.on("requestfailed", self._on_requestfailed)

    def end_case(self, status: str = "") -> None:
        """Đóng context của case, lưu trace/console vào bằng chứng."""
        context = self._context
        if context is None:
            return

        self.evidence.console = list(self._console)
        self.evidence.network = list(self._network)

        if self.trace_enabled and self.evidence_dir and self.case_id:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            path = self.evidence_dir / f"{self.case_id}.trace.zip"
            with contextlib.suppress(Exception):
                context.tracing.stop(path=str(path))
                self.evidence.trace = path.name

        with contextlib.suppress(Exception):
            context.close()

        self._context = None
        self._page = None
        self._console = []
        self._network = []

    def _ensure_browser(self) -> None:
        if self._browser is None:
            raise BrowserError("Trình duyệt chưa được mở")

    def _implicit_context(self):
        """Context dùng cho việc *ngoài* testcase (đăng nhập, lấy token, crawl)."""
        if self._context is None:
            self.start_case("__session__")
        return self._context

    @property
    def page(self):
        self._ensure_browser()
        if self._page is None:
            self._implicit_context()
        return self._page

    @property
    def console_errors(self) -> list[str]:
        return list(self._console)

    @property
    def network_errors(self) -> list[str]:
        return list(self._network)

    # ── Thu thập trong lúc chạy ─────────────────────────────────────────────
    def _on_console(self, message) -> None:
        if message.type == "error":
            self._console.append("console.error during response capture (content omitted)" if self._capture_private
                                 else f"console.error: {_short(message.text)}")

    def _on_pageerror(self, error) -> None:
        self._console.append("pageerror during response capture (content omitted)" if self._capture_private
                             else f"pageerror: {_short(error)}")

    def _on_request(self, request) -> None:
        self._inflight += 1
        self._last_activity = time.monotonic()
        self._capture_auth_header(request)

    def _on_response(self, response) -> None:
        self._inflight = max(0, self._inflight - 1)
        self._last_activity = time.monotonic()
        with contextlib.suppress(Exception):
            if response.status >= 400:
                url = response.url
                if self._capture_private:
                    url = origin_of(url) + urlsplit(url).path
                if any(host in url for host in _IGNORED_REQUEST_HOSTS):
                    return
                self._network.append(
                    f"{response.request.method} {_short(url, 90)} → HTTP {response.status}"
                )

    def _on_requestfailed(self, request) -> None:
        self._inflight = max(0, self._inflight - 1)
        self._last_activity = time.monotonic()
        with contextlib.suppress(Exception):
            url = origin_of(request.url) + urlsplit(request.url).path if self._capture_private else request.url
            failure = "request failed; details omitted" if self._capture_private else request.failure or "lỗi mạng"
            self._network.append(f"{request.method} {_short(url, 90)} → không gửi được ({_short(failure, 60)})")

    def wait_network_quiet(self, quiet_ms: int | None = None,
                           max_wait_ms: int | None = None) -> bool:
        """Chờ mạng lắng xuống: không còn request đang bay trong `quiet_ms`.

        Vì sao không dùng `wait_for_load_state("networkidle")` một mình: SPA gọi
        API **sau** khi load xong, nên networkidle bắn trước lúc dữ liệu về. Và
        networkidle cũng không biết phân biệt "chưa gọi" với "gọi xong".
        """
        quiet = quiet_ms if quiet_ms is not None else self.inflight_ms
        deadline = time.monotonic() + (max_wait_ms or max(self.timeout_ms, 5000)) / 1000
        while time.monotonic() < deadline:
            if self._inflight <= 0 and (time.monotonic() - self._last_activity) * 1000 >= quiet:
                return True
            self.page.wait_for_timeout(100)
        return self._inflight <= 0

    # ── Lưu phiên đăng nhập ─────────────────────────────────────────────────
    def save_state(self, path: Path) -> None:
        """Lưu cookie + localStorage để lần sau không phải đăng nhập lại.

        Nhờ vậy crawl và chạy test dùng **cùng một phiên** — crawl được cả những
        trang chỉ hiện sau khi đăng nhập, thay vì chỉ thấy màn hình login.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        context = self._context
        if context is not None:
            context.storage_state(path=str(path))

    # ── Đăng nhập ───────────────────────────────────────────────────────────
    def session_alive(self) -> bool:
        """Phiên đã lưu (`storage_state`) còn dùng được không.

        Dùng trước khi crawl. `storage_state` lưu cookie + localStorage, nhưng
        **access token của SPA nằm trong bộ nhớ** (keycloak-js không persist — đúng
        chuẩn bảo mật), nên phiên hết hạn sau một lúc. Lúc đó app đẩy về `/login`
        và crawl chỉ thấy màn hình đăng nhập: 2 element thay vì 39.

        Đó là kiểu hỏng tệ nhất — không có lỗi nào được ném ra, chỉ có UI map rỗng,
        và hậu quả là gần như mọi case UI ở trạng thái *chưa map*. Nên phải **hỏi
        thẳng** app thay vì tin vào file phiên.
        """
        try:
            url = self.goto("/")
        except Exception:                               # noqa: BLE001
            return False
        if self._on_login_url(url):
            return False
        # Có element tương tác thật ⇒ đã vào được app, không phải màn hình login.
        return self._wait_for_render(max_wait_ms=6000)

    @staticmethod
    def _on_login_url(url: str) -> bool:
        path = url.split("?", 1)[0].rstrip("/").lower()
        return any(mark in path for mark in ("/login", "/signin", "/sign-in"))

    def login(self, username: str, password: str) -> str:
        """Đăng nhập qua form của IdP — giống người dùng thật làm.

        Vì sao không dùng password grant: client SPA công khai (Keycloak `vd-portal`)
        **không cho phép** direct access grants, và đó là cấu hình đúng về bảo mật.
        Cách duy nhất hoạt động được là mở form đăng nhập thật.

        Đăng nhập xong thì session trình duyệt đã có phiên, nên mọi case UI chạy
        sau đó đều ở trạng thái đã đăng nhập.
        """
        self.goto("/login")
        self.page.wait_for_timeout(1200)

        # Bấm nút đăng nhập của portal để chuyển sang IdP
        clicked = False
        for name in ("Sign in", "Sign In", "Log in", "Login", "Đăng nhập"):
            with contextlib.suppress(Exception):
                button = self.page.get_by_role("button", name=name, exact=False).first
                if button.count() > 0:
                    button.click(timeout=self.timeout_ms)
                    clicked = True
                    break
        if not clicked:
            raise BrowserError(
                f"Không tìm thấy nút đăng nhập trên trang (đang ở {self.page.url[:80]})"
            )

        # Chờ chuyển sang trang của IdP — đây là bước dễ hỏng nhất khi mạng chập
        for _ in range(12):
            self.page.wait_for_timeout(800)
            if "auth." in self.page.url or "openid-connect" in self.page.url:
                break
        else:
            raise BrowserError(
                f"Bấm đăng nhập nhưng không chuyển được sang trang IdP "
                f"(đang ở {self.page.url[:80]})"
            )

        # Điền form của IdP
        try:
            self.page.locator("input[name='username']").first.fill(username, timeout=15000)
            self.page.locator("input[name='password']").first.fill(password, timeout=15000)
        except Exception as exc:                        # noqa: BLE001
            raise BrowserError(
                f"Không thấy form đăng nhập của IdP (đang ở {self.page.url[:80]}). "
                f"Chi tiết: {type(exc).__name__}"
            ) from exc

        for selector in ("button[type='submit']", "input[type='submit']",
                         "#kc-login", "button:has-text('Sign In')"):
            with contextlib.suppress(Exception):
                button = self.page.locator(selector).first
                if button.count() > 0:
                    button.click(timeout=self.timeout_ms)
                    break
        else:
            self.page.keyboard.press("Enter")

        self.page.wait_for_timeout(4000)
        self._wait_for_render()

        url = self.page.url
        if "auth.datafactory" in url or "/protocol/openid-connect/auth" in url:
            raise BrowserError(
                "Đăng nhập không thành công — vẫn đang ở trang của IdP. "
                "Kiểm tra lại tài khoản/mật khẩu."
            )
        self.authenticated = True
        return f"Đã đăng nhập, hiện ở {url}"

    # ── Lấy token cho các test API ──────────────────────────────────────────
    def _capture_auth_header(self, request) -> None:
        """Bắt header Authorization từ request thật của app.

        SPA giữ token **trong bộ nhớ** (keycloak-js mặc định không persist — đúng
        chuẩn bảo mật), nên không đọc được từ localStorage. Nhưng mọi request API
        của app đều kèm `Authorization: Bearer …`, và ta nhìn thấy được.
        """
        if self._captured_token:
            return
        with contextlib.suppress(Exception):
            header = request.headers.get("authorization", "")
            if header.lower().startswith("bearer ") and len(header) > 20:
                self._captured_token = header[7:].strip()

    def extract_token(self, max_wait_ms: int = 12000) -> str | None:
        """Lấy access token để test API dùng chính phiên đăng nhập này.

        Vì sao cần: `--acc` mở trình duyệt và đăng nhập, nhưng test API chạy bằng
        HTTP client riêng — không có phiên. Thiếu bước này thì mọi case cần xác
        thực đều trả 401, và báo cáo đầy `Lỗi` trong khi sản phẩm bình thường.
        """
        if self._captured_token:
            return self._captured_token

        # Chưa thấy request nào mang token → điều hướng để app tự gọi API.
        with contextlib.suppress(Exception):
            self.page.reload(wait_until="load", timeout=self.timeout_ms)

        waited = 0
        while waited < max_wait_ms and not self._captured_token:
            self.page.wait_for_timeout(400)
            waited += 400
        return self._captured_token

    # ── Tìm element ─────────────────────────────────────────────────────────
    def _label_locator(self, label: str, *, allow_empty: bool = False):
        """Tìm element theo tên hiển thị, thử từ bền → kém bền.

        `get_by_text(label)` của Playwright là khớp **một phần** và có thể trả về
        locator rỗng thay vì ném lỗi — nên phải tự kiểm `count()`. Thiếu bước này
        thì element không tồn tại vẫn đi tiếp và đổ vỡ ở đâu đó xa hơn, với thông
        báo timeout khó hiểu.
        """
        page = self.page
        candidates = [
            page.get_by_role("button", name=label, exact=False),
            page.get_by_role("link", name=label, exact=False),
            page.get_by_role("textbox", name=label, exact=False),
            page.get_by_role("checkbox", name=label, exact=False),
            page.get_by_role("combobox", name=label, exact=False),
            page.get_by_label(label, exact=False),
            page.get_by_placeholder(label, exact=False),
            page.get_by_text(label, exact=False),
            page.locator(f'[data-testid="{label}"]'),
            page.locator(f'[name="{label}"]'),
        ]
        for locator in candidates:
            with contextlib.suppress(Exception):
                if locator.count() > 0:
                    return locator.first
        if allow_empty:
            return page.locator(f'[data-testid="{label}"]').first
        raise BrowserError(f"Không tìm thấy element «{label}» trên trang")

    def _test_id_locator(self, test_id: str):
        """Locator theo test id — ưu tiên `data-testid`, chấp nhận các biến thể."""
        page = self.page
        for selector in (f'[data-testid="{test_id}"]', f'[data-test-id="{test_id}"]',
                         f'[data-test="{test_id}"]', f'[data-cy="{test_id}"]',
                         f'[data-qa="{test_id}"]'):
            with contextlib.suppress(Exception):
                attr_locator = page.locator(selector)
                if attr_locator.count() > 0:
                    return attr_locator.first
        return page.get_by_test_id(test_id)

    def locate(self, args: dict, *, allow_empty: bool = False):
        """Tìm element theo `target` (test id) và/hoặc `by_name` (nhãn hiển thị).

        Thứ tự: test id trước (bền nhất — đổi giao diện không đổi id), rồi mới
        tới nhãn. Case cũ chỉ khai `target` mang nhãn vẫn chạy như trước.

        Không tìm thấy thì **ném lỗi ngay**, không trả về locator rỗng: locator
        rỗng chỉ đổ vỡ ở bước sau với thông báo timeout 30 giây, còn ở đây thông
        báo nói thẳng là không có element nào tên như vậy.
        """
        target = str(args.get("target") or "").strip()
        name = str(args.get("by_name") or "").strip()

        if target and _looks_like_test_id(target):
            locator = self._test_id_locator(target)
            with contextlib.suppress(Exception):
                if locator.count() > 0:
                    return locator

        return self._label_locator(name or target, allow_empty=allow_empty)

    def _label(self, args: dict) -> str:
        return str(args.get("by_name") or args.get("target") or "")

    # ── Assert ──────────────────────────────────────────────────────────────
    def set_assert_mode(self, soft: bool) -> None:
        """Assert mềm: bước sai không dừng case, để chạy hết các bước còn lại.

        Vì sao cần: khi kiểm UI/UX, người ta muốn biết **tất cả** chỗ sai của một
        màn hình trong một lượt, chứ không phải sửa một lỗi rồi chạy lại để thấy
        lỗi tiếp theo. Kết quả vẫn là `Fail` — chỉ khác là fail kèm danh sách.
        """
        self.soft = soft
        self.soft_failures = []

    def _record(self, ok: bool, detail: str) -> tuple[bool, str]:
        if not ok:
            self.soft_failures.append(detail)
            if self.soft:
                return True, f"{detail}  (đã ghi nhận, chạy tiếp)"
        return ok, detail

    def _check(self, locator, kind: str, describe: str, **kwargs) -> tuple[bool, str]:
        """Gọi `expect()` của Playwright — tự chờ tới khi điều kiện đúng."""
        timeout = kwargs.pop("timeout", self.timeout_ms)
        try:
            getattr(self._expect(locator), kind)(timeout=timeout, **kwargs)
            return self._record(True, describe)
        except Exception as exc:                        # noqa: BLE001
            reason = _short(str(exc).split("\n")[0], 200)
            return self._record(False, f"KHÔNG đúng: {describe}  [{reason}]")

    def _count(self, target: str, name: str) -> int:
        with contextlib.suppress(Exception):
            locator = self.locate({"target": target, "by_name": name}, allow_empty=True)
            return locator.count()
        return 0

    # ── Hành động ───────────────────────────────────────────────────────────
    def set_session(self, args: dict) -> str:
        """Chuyển phiên trình duyệt giữa `anonymous` và `authenticated`.

        Vì sao cần verb này: trình duyệt của lượt chạy mang sẵn phiên đăng nhập, mà
        feature login-sso lại có rất nhiều case chỉ có nghĩa khi **chưa** đăng nhập
        (`Router guard chạy`, `check-sso`, `Redirect /login`). Chạy chúng trong phiên
        đã đăng nhập thì kết quả vô nghĩa — hoặc tệ hơn: chúng `Pass` một cách giả tạo.

        `anonymous`: xoá cookie + localStorage + sessionStorage của mọi origin đang
        có, rồi mở lại trang để SPA khởi động từ trạng thái sạch.

        `authenticated`: nạp lại `storage_state` đã lưu từ lúc đăng nhập.
        """
        mode = args.get("mode")
        context = self._context
        if context is None:
            raise BrowserError("Trình duyệt chưa được mở")

        if mode == "anonymous":
            # Thứ tự và cách làm ở đây quan trọng — bản đầu tiên tôi viết sai và
            # test bắt được: xoá cookie rồi `goto(base_url)` thì chính trang đó
            # **đặt lại cookie** qua `Set-Cookie`, nên phiên sống lại ngay.
            #
            # Cách đúng: xoá storage trước (khi còn ở trong trang), rồi xoá cookie,
            # rồi mới điều hướng. Nhưng điều hướng nào cũng có thể nhận Set-Cookie
            # mới — nên xoá cookie LẦN NỮA sau khi điều hướng, và lần cuối cùng
            # không kèm `goto` nào cả.
            self._captured_token = None
            self.authenticated = False

            with contextlib.suppress(Exception):
                if self.page.url and not self.page.url.startswith("about:"):
                    self.page.evaluate(
                        "() => { try { localStorage.clear(); sessionStorage.clear(); }"
                        " catch (e) {} }"
                    )
            with contextlib.suppress(Exception):
                context.clear_cookies()
            with contextlib.suppress(Exception):
                self.page.goto("about:blank", timeout=self.timeout_ms)
            # Xoá lần cuối, sau mọi điều hướng — không còn gì đặt lại cookie nữa.
            with contextlib.suppress(Exception):
                context.clear_cookies()

            self._console.clear()
            return "Đã xoá phiên — trình duyệt giờ chạy như người dùng chưa đăng nhập"

        if mode == "authenticated":
            if not (self.storage_state and Path(self.storage_state).is_file()):
                raise NeedsLogin(
                    "Không có phiên đã lưu để nạp lại. Lượt chạy này chưa đăng "
                    "nhập lần nào — case cần xác thực chưa kết luận được gì."
                )
            state = json.loads(Path(self.storage_state).read_text(encoding="utf-8"))
            cookies = state.get("cookies") or []
            if cookies:
                with contextlib.suppress(Exception):
                    context.add_cookies(cookies)
            for origin in state.get("origins") or []:
                with contextlib.suppress(Exception):
                    self.page.goto(origin.get("origin", self.base_url),
                                   wait_until="domcontentloaded",
                                   timeout=self.timeout_ms)
                    for item in origin.get("localStorage") or []:
                        self.page.evaluate(
                            "([k, v]) => localStorage.setItem(k, v)",
                            [item.get("name"), item.get("value")],
                        )
            self.authenticated = True
            self._console.clear()
            return "Đã nạp lại phiên đăng nhập"

        raise BrowserError(
            f"`ui.session` chỉ nhận `anonymous` hoặc `authenticated`, gặp: {mode!r}"
        )

    def goto(self, url: str) -> str:
        target = url if url.startswith(("http://", "https://")) else self.base_url + url
        # `load` chứ không `domcontentloaded`: SPA chưa mount ở mốc domcontentloaded,
        # nên click/assert ngay sau đó sẽ chạy trên DOM rỗng và fail giả.
        last: Exception | None = None
        for attempt in range(3):
            try:
                self.page.goto(target, wait_until="load", timeout=self.timeout_ms)
                # Chromium hiện trang lỗi nội bộ khi không kết nối được; `goto` không
                # ném exception vì về mặt kỹ thuật nó đã "điều hướng xong".
                if self.page.url.startswith("chrome-error://"):
                    raise NeedsEnvironment(_env_reason(target, None, self._network))
                self._wait_for_render()
                self.wait_network_quiet(max_wait_ms=3000)
                return self.page.url
            except NeedsEnvironment:
                raise
            except Exception as exc:                    # noqa: BLE001
                last = exc
                if not _is_env_problem(exc, self._network):
                    raise
                # Lỗi mạng tạm thời (đổi wifi, DNS chập) — thử lại, đừng báo Fail
                self.page.wait_for_timeout(1500)
        raise NeedsEnvironment(_env_reason(target, last, self._network))

    def _wait_for_render(self, max_wait_ms: int = 12000) -> bool:
        """Chờ tới khi trang có element tương tác, hoặc hết thời gian.

        SPA phải chạy JS và gọi API lấy phiên rồi mới render menu. Chờ mạng lắng
        xuống trước, nếu không sẽ lúc được lúc không tuỳ tốc độ mạng.
        """
        from ..ui.crawl import INTERACTIVE

        with contextlib.suppress(Exception):
            self.page.wait_for_load_state("networkidle", timeout=min(max_wait_ms, 7000))

        waited = 0
        while waited < max_wait_ms:
            try:
                for tag in INTERACTIVE:
                    if self.page.locator(tag).count() > 0:
                        return True
            except Exception:                       # noqa: BLE001
                pass
            self.page.wait_for_timeout(400)
            waited += 400
        return False

    def click(self, args: dict) -> str:
        locator = self.locate(args)
        # networkidle can already be satisfied on an SPA's existing document.
        # It is not a barrier for a POST started by this click; navigating next
        # can cancel the request before the app stores its resulting session.
        # Track only writes started by the click, never old/background polling,
        # and retain no URL, headers, payload or response body.
        pending = set()
        collecting = True
        initial_url = self.page.url
        def started(request):
            if (collecting and request.resource_type in {'xhr', 'fetch'}
                    and request.method not in {'GET', 'HEAD', 'OPTIONS'}):
                pending.add(request)
        def finished(request):
            pending.discard(request)
        listeners = [('request', started), ('requestfinished', finished), ('requestfailed', finished)]
        deadline = time.monotonic() + self.timeout_ms / 1000
        for event, handler in listeners:
            self.page.on(event, handler)
        try:
            locator.click(timeout=self.timeout_ms)
            self.page.wait_for_timeout(50)  # Dispatch the click's immediate async work.
            collecting = False
            # A completed navigation is also a completion signal. Some apps
            # navigate after response headers and abandon an unread fetch body,
            # so the old document may never emit requestfinished for that body.
            while pending and self.page.url == initial_url and time.monotonic() < deadline:
                self.page.wait_for_timeout(50)
            if pending and self.page.url == initial_url:
                error = NeedsEnvironment('UI_ACTION_RESPONSE_TIMEOUT: click-triggered request did not complete within the browser timeout.')
                error.code = 'UI_ACTION_RESPONSE_TIMEOUT'
                raise error
            self.page.wait_for_timeout(50)  # Let the completed response update SPA state.
        finally:
            for event, handler in listeners:
                with contextlib.suppress(Exception):
                    self.page.remove_listener(event, handler)
        self._wait_for_render(max_wait_ms=4000)
        return f"Đã bấm «{self._label(args)}» → {self.page.url}"

    def click_and_capture(self, args: dict, step_seq: int) -> dict:
        """Inspect only requests started inside this click's bounded window.

        Listen before clicking; collect the entire window to reject duplicates.
        Download completion must occur within the window before reading JSON.
        Only public boolean success is retained; never headers/raw payloads.
        """
        spec = args["capture_response"]
        try:
            validate_capture(spec)
        except (ValueError, TypeError):
            raise ResponseCaptureError("INVALID_UI_RESPONSE_CAPTURE") from None
        page = self.page
        private_before = self._capture_private
        self._capture_private = True
        requests, responses, finished = [], [], set()
        deadline = time.monotonic() + spec.get("timeout_ms", 10000) / 1000
        def matches(req):
            return matches_request(req, spec)
        def on_request(req):
            if time.monotonic() <= deadline and matches(req):
                requests.append(req)
        def on_response(resp):
            if resp.request in requests and matches(resp.request):
                responses.append(resp)
        def on_finished(req):
            if req in requests:
                finished.add(req)
        listeners = [("request", on_request), ("response", on_response), ("requestfinished", on_finished)]
        for event, handler in listeners:
            page.on(event, handler)
        try:
            self.locate(args).click(timeout=max(1, int((deadline - time.monotonic()) * 1000)))
            while time.monotonic() < deadline:
                page.wait_for_timeout(min(50, max(1, int((deadline - time.monotonic()) * 1000))))
            if len(requests) > 1 or len(responses) > 1:
                raise ResponseCaptureError("AMBIGUOUS_UI_RESPONSE")
            if len(responses) != 1 or responses[0].request not in finished:
                raise ResponseCaptureError("UI_RESPONSE_TIMEOUT")
            response = responses[0]
            raw = response.body()
            if len(raw) > 1048576:
                raise ResponseCaptureError("UI_RESPONSE_BODY_LIMIT")
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError):
                data = None
            # Projection, not a redacted copy of an auth response: token/user/
            # password and all unknown payload fields never enter saved/results.
            body = {"success": data["success"]} if isinstance(data, dict) and type(data.get("success")) is bool else None
            return {"status": response.status, "body": body, "error": None,
                    "_ui_trigger": {"step_seq": step_seq, "method": spec["method"],
                                    "path": spec["path"], "origin": spec["origin"]}}
        except ResponseCaptureError:
            raise
        except Exception:
            raise ResponseCaptureError("UI_RESPONSE_CAPTURE_FAILED") from None
        finally:
            self._capture_private = private_before
            for event, handler in listeners:
                with contextlib.suppress(Exception):
                    page.remove_listener(event, handler)

    def click_and_observe_requests(self, args: dict, step_seq: int) -> dict:
        """Count exact requests during this submit window, including failed calls.

        Zero means absence only within the explicit bounded window. Every match
        counts; duplicates cannot be mistaken for absence. No response/body read.
        """
        spec = args["capture_requests"]
        try:
            validate_capture(spec)
        except (ValueError, TypeError):
            raise ResponseCaptureError("INVALID_UI_RESPONSE_CAPTURE") from None
        page = self.page
        private_before = self._capture_private
        self._capture_private = True
        count = 0
        deadline = None
        window_ms = spec.get("timeout_ms", 10000)
        def on_request(req):
            nonlocal count
            if (deadline is None or time.monotonic() <= deadline) and matches_request(req, spec):
                count += 1
        page.on("request", on_request)
        try:
            self.locate(args).click(timeout=window_ms)
            deadline = time.monotonic() + window_ms / 1000
            while time.monotonic() < deadline:
                page.wait_for_timeout(min(50, max(1, int((deadline-time.monotonic())*1000))))
            return {"body": {"request_count": count}, "_ui_trigger": {
                "step_seq": step_seq, "method": spec["method"], "path": spec["path"],
                "origin": spec["origin"], "window_ms": spec.get("timeout_ms", 10000)}}
        except Exception:
            raise ResponseCaptureError("UI_REQUEST_OBSERVATION_FAILED") from None
        finally:
            self._capture_private = private_before
            with contextlib.suppress(Exception):
                page.remove_listener("request", on_request)

    def fill(self, args: dict) -> str:
        locator = self.locate(args)
        locator.fill(str(args.get("value", "")), timeout=self.timeout_ms)
        return f"Đã điền «{args.get('_fixture_alias', args.get('value', ''))}» vào «{self._label(args)}»"

    def select(self, args: dict) -> str:
        locator = self.locate(args)
        locator.select_option(str(args.get("value", "")), timeout=self.timeout_ms)
        return f"Đã chọn {args.get('value')} ở «{self._label(args)}»"

    def hover(self, args: dict) -> str:
        locator = self.locate(args)
        locator.hover(timeout=self.timeout_ms)
        self._wait_for_render(max_wait_ms=2000)
        return f"Đã đưa chuột lên «{self._label(args)}»"

    def press(self, args: dict) -> str:
        key = str(args.get("key", ""))
        if args.get("target"):
            locator = self.locate(args)
            locator.press(key, timeout=self.timeout_ms)
            where = f"«{self._label(args)}»"
        else:
            self.page.keyboard.press(key)
            where = "trang"
        self._wait_for_render(max_wait_ms=3000)
        return f"Đã gõ {key} ở {where}"

    def check(self, args: dict) -> str:
        locator = self.locate(args)
        want = args.get("checked", True) is not False
        locator.set_checked(want, timeout=self.timeout_ms)
        return f"Đã {'tick' if want else 'bỏ tick'} «{self._label(args)}»"

    def scroll(self, args: dict) -> str:
        px = int(args.get("px") or 0)
        if args.get("target") or args.get("by_name"):
            locator = self.locate(args)
            locator.scroll_into_view_if_needed(timeout=self.timeout_ms)
            self.page.wait_for_timeout(300)
            return f"Đã cuộn tới «{self._label(args)}»"

        direction = str(args.get("direction") or "down")
        script = {
            "down": f"window.scrollBy(0, {px or 600})",
            "up": f"window.scrollBy(0, -{px or 600})",
            "top": "window.scrollTo(0, 0)",
            "bottom": "window.scrollTo(0, document.body.scrollHeight)",
        }.get(direction)
        if script is None:
            raise BrowserError(
                f"`ui.scroll` chỉ nhận up/down/top/bottom, gặp: {direction!r}"
            )
        self.page.evaluate(script)
        self.page.wait_for_timeout(400)
        return f"Đã cuộn {direction}"

    def wait_for(self, args: dict) -> str:
        """Chờ element đạt trạng thái — dùng `expect` để tự bỏ qua nhiễu thời điểm."""
        state = str(args.get("state") or "visible")
        timeout = int(args.get("timeout_ms") or self.timeout_ms)
        locator = self.locate(args, allow_empty=state == "hidden")
        kind = {"visible": "to_be_visible", "hidden": "to_be_hidden",
                "attached": "to_be_attached"}.get(state)
        if kind is None:
            raise BrowserError(
                f"`ui.wait_for` chỉ nhận visible/hidden/attached, gặp: {state!r}"
            )
        ok, detail = self._check(locator, kind, f"«{self._label(args)}» {state}",
                                 timeout=timeout)
        if not ok:
            raise BrowserError(detail)
        return f"«{self._label(args)}» đã {state}"

    # ── Kiểm tra ────────────────────────────────────────────────────────────
    def current_url(self) -> str:
        return self.page.url

    def url_matches(self, pattern: str) -> tuple[bool, str]:
        actual = self.current_url()
        if re.search(pattern, actual):
            return self._record(True, f"URL hiện tại khớp «{pattern}»: {actual}")

        # Bị đẩy về trang đăng nhập khi chưa đăng nhập KHÔNG phải lỗi sản phẩm.
        # Đó là precondition chưa thoả — phải báo Blocked, không phải Fail.
        if self.authenticated is False and self.on_login_page:
            raise NeedsLogin(
                "Bị chuyển về trang đăng nhập vì lượt chạy này chưa xác thực. "
                "Case cần đăng nhập trước — chưa kết luận được gì về sản phẩm."
            )
        return self._record(False, f"URL hiện tại là {actual} — KHÔNG khớp «{pattern}»")

    @property
    def on_login_page(self) -> bool:
        url = self.current_url().lower()
        return any(mark in url for mark in ("login", "signin", "sign-in", "auth/realms"))

    def is_visible(self, args: dict) -> tuple[bool, str]:
        name = self._label(args)
        try:
            locator = self.locate(args)
        except BrowserError as exc:
            return self._record(False, str(exc))
        return self._check(locator, "to_be_visible", f"«{name}» hiện trên màn hình")

    def not_visible(self, args: dict) -> tuple[bool, str]:
        name = self._label(args)
        try:
            locator = self.locate(args, allow_empty=True)
        except BrowserError as exc:
            return self._record(True, f"«{name}» không có trên trang — đúng như mong đợi")
        if locator.count() == 0:
            return self._record(True, f"«{name}» không có trên trang — đúng như mong đợi")
        return self._check(locator, "to_be_hidden",
                           f"«{name}» không hiện trên màn hình")

    def is_enabled(self, args: dict) -> tuple[bool, str]:
        name = self._label(args)
        try:
            locator = self.locate(args)
        except BrowserError as exc:
            return self._record(False, str(exc))
        return self._check(locator, "to_be_enabled", f"«{name}» bấm được")

    def is_disabled(self, args: dict) -> tuple[bool, str]:
        name = self._label(args)
        try:
            locator = self.locate(args)
        except BrowserError as exc:
            return self._record(False, str(exc))
        return self._check(locator, "to_be_disabled", f"«{name}» đang bị vô hiệu hoá")

    def text(self, args: dict) -> tuple[bool, str]:
        name = self._label(args)
        expected = str(args.get("expected", ""))
        operator = args.get("operator") or ("eq" if args.get("exact") else "contains")
        try:
            locator = self.locate(args)
        except BrowserError as exc:
            return self._record(False, str(exc))

        kind = {"contains": ("to_contain_text", {"expected": expected}),
                "eq": ("to_have_text", {"expected": expected}),
                "matches": ("to_have_text", {"expected": re.compile(expected)})}.get(operator)
        if kind is None:
            return self._record(False, f"operator `{operator}` không hợp lệ cho assert.text")
        describe = f"«{name}» hiển thị {'chứa ' if operator == 'contains' else ''}«{expected}»"
        return self._check(locator, kind[0], describe, **kind[1])

    def value(self, args: dict) -> tuple[bool, str]:
        name = self._label(args)
        expected = str(args.get("expected", ""))
        operator = args.get("operator") or "eq"
        try:
            locator = self.locate(args)
        except BrowserError as exc:
            return self._record(False, str(exc))

        kind = {"eq": ("to_have_value", {"value": expected}),
                "matches": ("to_have_value", {"value": re.compile(expected)}),
                "contains": ("to_have_value", {"value": re.compile(re.escape(expected))})}.get(operator)
        if kind is None:
            return self._record(False, f"operator `{operator}` không hợp lệ cho assert.value")
        return self._check(locator, kind[0], f"Ô «{name}» có giá trị «{expected}»", **kind[1])

    def attribute(self, args: dict) -> tuple[bool, str]:
        name = self._label(args)
        attr = str(args.get("name", ""))
        expected = args.get("expected")
        try:
            locator = self.locate(args)
        except BrowserError as exc:
            return self._record(False, str(exc))
        return self._check(locator, "to_have_attribute",
                           f"«{name}» có {attr}=«{expected}»",
                           name=attr, value=str(expected))

    def count(self, args: dict) -> tuple[bool, str]:
        name = self._label(args)
        expected = int(args.get("expected", 1))
        actual = self._count(str(args.get("target") or ""), str(args.get("by_name") or ""))
        ok = _compare_number(actual, expected, args.get("operator") or "eq")
        return self._record(ok, f"«{name}»: đếm được {actual} element"
                                + ("" if ok else f", mong đợi {expected}"))

    def focused(self, args: dict) -> tuple[bool, str]:
        name = self._label(args)
        try:
            locator = self.locate(args)
        except BrowserError as exc:
            return self._record(False, str(exc))
        return self._check(locator, "to_be_focused", f"«{name}» đang được focus")

    def checked(self, args: dict) -> tuple[bool, str]:
        name = self._label(args)
        want = args.get("expected", True) is not False
        try:
            locator = self.locate(args)
        except BrowserError as exc:
            return self._record(False, str(exc))
        return self._check(locator, "to_be_checked" if want else "not_to_be_checked",
                           f"«{name}» {'đã' if want else 'chưa'} được tick")

    def console_clean(self, args: dict) -> tuple[bool, str]:
        """Không có lỗi JS. `forbidden` lọc thêm lỗi không tính (nhiễu của bên thứ ba)."""
        errors = list(self._console)
        pattern = args.get("forbidden")
        if pattern:
            errors = [e for e in errors if not re.search(str(pattern), e)]
        limit = int(args.get("max_errors") or 0)
        if len(errors) <= limit:
            return self._record(True, "Không có lỗi JavaScript nào")
        return self._record(
            False,
            f"Có {len(errors)} lỗi JavaScript: " + "; ".join(errors[:3]),
        )

    def requests_clean(self, args: dict) -> tuple[bool, str]:
        """Không có request nào trả ≥400 (trừ `allow`)."""
        errors = list(self._network)
        allow = args.get("allow")
        if allow:
            pattern = allow if isinstance(allow, str) else "|".join(allow)
            errors = [e for e in errors if not re.search(pattern, e)]
        limit = int(args.get("max_errors") or 0)
        if len(errors) <= limit:
            return self._record(True, "Không có request nào trả lỗi")
        return self._record(
            False,
            f"Có {len(errors)} request lỗi: " + "; ".join(errors[:3]),
        )

    def axe_scan(self, args: dict) -> tuple[bool, str]:
        """Quét accessibility bằng axe-core (chèn từ CDN, chạy trong trang)."""
        severity = str(args.get("severity") or self.axe_severity)
        allowed = {"critical", "serious", "moderate", "minor", "all"}
        if severity not in allowed:
            return self._record(False, f"`severity` phải thuộc {sorted(allowed)}")

        try:
            self._ensure_axe(severity)
        except Exception as exc:                        # noqa: BLE001
            # Không nạp được axe-core (mạng chập) là thiếu môi trường, KHÔNG phải
            # sản phẩm sai. Ném `NeedsEnvironment` để case báo `Blocked` kèm lý do.
            raise NeedsEnvironment(
                f"Không nạp được axe-core để quét accessibility "
                f"({type(exc).__name__}: {_short(exc, 80)}). Cần mạng, hoặc chép "
                "sẵn axe.min.js cạnh qctool/execute/."
            ) from exc

        try:
            result = self.page.evaluate("() => window.__qctoolAxe()")
        except Exception as exc:                        # noqa: BLE001
            return self._record(False, f"Không quét được accessibility: "
                                       f"{type(exc).__name__}: {_short(exc, 120)}")

        violations = result.get("violations", [])
        if not violations:
            return self._record(True, "Không có vi phạm accessibility nào")

        found = [f"[{v['impact']}] {v['id']}: {_short(v['help'], 60)} "
                 f"({v['count']} chỗ)" for v in violations[:5]]
        self.evidence.axe.extend(found)
        return self._record(False, f"Có {len(violations)} vi phạm accessibility: "
                                   + "; ".join(found))

    def _ensure_axe(self, severity: str) -> None:
        """Nạp axe-core — ưu tiên file cục bộ (chạy offline), không thì lấy CDN."""
        if self._axe_source is None:
            self._axe_source = _axe_source()

        wanted = ["critical", "serious", "moderate", "minor"]
        if severity != "all":
            wanted = wanted[: wanted.index(severity) + 1] if severity in wanted else wanted

        self.page.evaluate(
            """([source, levels]) => {
                if (!window.axe) { (0, eval)(source); }
                window.__qctoolAxe = async () => {
                    const r = await window.axe.run(document, {
                        resultTypes: ['violations'],
                        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'] },
                    });
                    return {
                        violations: r.violations
                            .filter(v => levels.includes(v.impact))
                            .map(v => ({ id: v.id, impact: v.impact, help: v.help, count: v.nodes.length })),
                    };
                };
            }""",
            [self._axe_source, wanted],
        )

    # ── Bằng chứng ──────────────────────────────────────────────────────────
    def screenshot(self, name: str, full_page: bool = True) -> Path | None:
        """Lưu ảnh chụp — dùng khi case fail, để có bằng chứng."""
        if not self.evidence_dir:
            return None
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{self.case_id}-{name}")[:80]
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"{safe}.png"
        with contextlib.suppress(Exception):
            self.page.screenshot(path=str(path), full_page=full_page)
            self.evidence.screenshots.append(path.name)
            return path
        return None

    def capture_failure(self) -> None:
        """Ảnh + trạng thái trang lúc case vừa fail."""
        self.screenshot("fail")
        with contextlib.suppress(Exception):
            # Ghi vào `note` chứ KHÔNG vào `network`: đây là bối cảnh, không phải
            # một request lỗi. Trộn vào `network` làm báo cáo đếm sai số request lỗi.
            self.evidence.note = f"URL lúc fail: {self.page.url}"


def _is_env_problem(exc: Exception, network: list[str]) -> bool:
    """Lỗi này là của mạng máy test hay của sản phẩm?"""
    haystack = f"{exc} {' '.join(network[-3:])}"
    return any(marker in haystack for marker in ENV_ERROR_MARKERS)


def _env_reason(target: str, exc: Exception | None, network: list[str]) -> str:
    markers = [m for m in ENV_ERROR_MARKERS if m in f"{exc} {' '.join(network[-3:])}"]
    detail = f" ({', '.join(markers)})" if markers else ""
    return (f"Không mở được {target} sau 3 lần thử vì lỗi mạng của máy chạy test"
            f"{detail}. Chưa chạm được vào hệ thống cần test — chưa kết luận được gì "
            "về sản phẩm.")


def _compare_number(actual: int, expected: int, operator: str) -> bool:
    return {"eq": actual == expected, "ne": actual != expected,
            "gt": actual > expected, "gte": actual >= expected,
            "lt": actual < expected, "lte": actual <= expected}.get(
                operator, actual == expected)


def _axe_source() -> str:
    """Nội dung axe-core: file cạnh tool (chạy offline) trước, CDN sau.

    Thứ tự này quan trọng với máy CI không ra được Internet: chép sẵn
    `axe.min.js` vào `qctool/execute/` là quét được accessibility mà không cần mạng.
    """
    import os

    local = Path(__file__).with_name("axe.min.js")
    if local.is_file():
        return local.read_text(encoding="utf-8")

    if extra := os.environ.get("QCTOOL_AXE_PATH"):
        path = Path(extra).expanduser()
        if path.is_file():
            return path.read_text(encoding="utf-8")

    import urllib.request

    url = os.environ.get("QCTOOL_AXE_URL",
                         "https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js")
    with urllib.request.urlopen(url, timeout=20) as resp:   # noqa: S310 — URL cấu hình được
        return resp.read().decode("utf-8")

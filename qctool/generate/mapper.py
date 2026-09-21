"""Mapper: bước viết bằng văn xuôi → hành động cụ thể.

Đây là chỗ nối giữa tài liệu và trình duyệt. Nhận `perform.unmapped` /
`assert.unmapped` (văn xuôi từ acceptance criteria) và biến thành `ui.goto`,
`ui.click`, `assert.url_matches`…

**Nguyên tắc bất di bất dịch:** chỉ map khi CHẮC. Target phải có thật trong UI map,
hoặc URL phải trích được rõ ràng từ câu. Không chắc thì giữ nguyên `unmapped` —
case sẽ báo `Blocked` kèm lý do. Map bừa còn tệ hơn không map: một case chạy sai
mà báo `Pass` sẽ khiến người ta tin nhầm.

Mapper chạy **deterministic** — không LLM. Cùng input cho cùng output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from ..testcase import (
    PERF_DEFAULT_PERCENTILE,
    PERF_SAMPLES,
    Step,
    StepKind,
    TestCase,
    percentile_of,
)
from ..ui.crawl import UIMap, _norm, _only_filler_words

# ── Mẫu câu → ý định ────────────────────────────────────────────────────────
# `^(?:User|Người dùng|FE|Portal|Hệ thống)?` — tài liệu hay viết "User bấm …"
# chứ không chỉ "bấm …". Không cho phép tiền tố chủ ngữ thì những bước đó không
# map được, dù element có thật trong ui-map.
_SUBJECT = r"^(?:user|người\s+dùng|fe|portal|hệ\s+thống|spa|admin)\s+"
RE_CLICK = re.compile(
    r"^\s*(?:" + _SUBJECT + r")?(?:click|bấm|nhấn|chọn)\s+"
    r"(?:vào\s+|lên\s+|nút\s+|button\s+)?[\"'`]?(.+?)[\"'`]?\s*$",
    re.I)
RE_OPEN_PATH = re.compile(
    r"^\s*(?:" + _SUBJECT + r")?(?:mở|open|truy cập|navigate to|đi tới)\s+[`\"']?(/\S*)[`\"']?",
    re.I)
RE_REDIRECT = re.compile(r"(?:redirect|chuyển(?:\s+hướng)?|navigate)\s*(?:về|tới|to|đến)?\s*[`\"']?(/\S*?)[`\"']?\s*$", re.I)
RE_URL_IN_TEXT = re.compile(r"(?<![\w/])/([\w\-./{}$?=&]*[\w\-/])")
RE_VISIBLE = re.compile(r"(?:hiện|hiển thị|thấy|xuất hiện|visible|shown?)\s+(?:lên\s+)?[\"'`]?(.+?)[\"'`]?\s*$", re.I)
RE_NOT_VISIBLE = re.compile(r"(?:không|ẩn|hidden|not)\s+(?:hiện|hiển thị|thấy|visible|shown?)", re.I)
RE_FILL = re.compile(
    r"^\s*(?:" + _SUBJECT + r")?(?:nhập|điền|enter|fill|type)\s+"
    r"[\"'`]?(.+?)[\"'`]?\s+(?:vào|into)\s+[\"'`]?(.+?)[\"'`]?\s*$",
    re.I)
RE_HTTP = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/\S+)", re.I)

# `Response có đủ field: a, b, c` — hợp đồng dữ liệu khai trong SRS. Trước đây
# nhóm này luôn ở trạng thái chưa map, dù `assert.json_schema` kiểm được ngay.
RE_RESPONSE_FIELDS = re.compile(
    r"response\s+có\s+(?:đủ\s+)?(?:các\s+)?field[s]?\s*:\s*(.+?)\s*$", re.I)

# ── Trạng thái phiên (state machine của SPA) ─────────────────────────────────
# Tài liệu viết `Trạng thái hiện tại: Loading` / `Chuyển sang trạng thái «Authenticated»`.
# Đây là mô tả máy trạng thái phía FE, và mỗi trạng thái có **biểu hiện trên màn
# hình** (bảng Notes của `login-sso-states.md` nói rõ): Loading = spinner toàn
# trang, Unauthenticated = `/login`, Authenticated = AppShell, SoftExpired = banner.
# Nhờ vậy map được sang thứ kiểm được, thay vì để nguyên văn xuôi.
RE_STATE_CURRENT = re.compile(r"^\s*Trạng\s+thái\s+hiện\s+tại\s*:\s*(.+?)\s*$", re.I)
RE_STATE_TO = re.compile(
    r"(?:chuyển\s+sang|sang|→)\s*trạng\s+thái\s*[«\"'`]?(.+?)[»\"'`]?\s*$", re.I)

# Biểu hiện UI của từng trạng thái. Khoá là tên trạng thái (đã chuẩn hoá thường).
# `None` = chưa biết biểu hiện ⇒ không map, giữ nguyên văn xuôi (không đoán bừa).
STATE_SIGNS: dict[str, list[tuple[str, dict]]] = {
    "loading": [
        # Spinner toàn trang: không có element điều hướng nào hiện ra.
        ("assert.not_visible", {"target": "nav-projects", "by_name": "Dự án"}),
    ],
    "unauthenticated": [
        ("assert.url_matches", {"pattern": r"/login"}),
    ],
    "authenticated": [
        ("assert.not_visible", {"target": "sign_in", "by_name": "Sign in"}),
    ],
    "softexpired": [
        ("assert.visible", {"target": "upload-session-banner",
                            "by_name": "Upload session banner"}),
    ],
    "error": [
        ("assert.visible", {"target": "auth-error-banner",
                            "by_name": "Login error banner"}),
    ],
}

# Trạng thái nào cần phiên **ẩn danh** mới quan sát được. Mở `/` trong phiên đã
# đăng nhập thì app đưa thẳng vào dashboard, không bao giờ thấy `/login` — case
# `Loading → Unauthenticated` vì thế fail dù sản phẩm đúng (đã gặp thật).
STATE_NEEDS_ANONYMOUS = {"unauthenticated", "authenticating", "error"}
# Trạng thái nào cần phiên **đã đăng nhập** (AppShell, banner upload…).
STATE_NEEDS_AUTH = {"authenticated", "softexpired", "refreshing"}

# Đường dẫn để **gây ra** trạng thái, dùng cho bước `Trạng thái hiện tại: X`.
STATE_ENTRY_PATH = {
    "loading": "/",
    "unauthenticated": "/login",
    "authenticated": "/",
    "authenticating": "/login",
    "refreshing": "/",
    "softexpired": "/",
    "error": "/login",
}


def _state_session_steps(name: str) -> list[tuple[str, dict]]:
    """Bước đặt phiên trước khi quan sát một trạng thái."""
    if name in STATE_NEEDS_ANONYMOUS:
        return [("ui.session", {"mode": "anonymous"})]
    if name in STATE_NEEDS_AUTH:
        return [("ui.session", {"mode": "authenticated"})]
    return []

# Câu mô tả trạng thái nội bộ, không phải hành động trên màn hình
RE_STATE_ONLY = re.compile(
    r"^(?:portal\s+load\s+xong|load\s+xong|đã\s+đăng\s+nhập|app\s+mount|"
    r"init\s+completes?|check-?sso|keycloak\s+enabled|user\s+đã\s+login|"
    r"session\s+(?:active|hợp\s+lệ))",
    re.I)


@dataclass
class MapStats:
    total: int = 0
    mapped: int = 0
    still_unmapped: int = 0
    reasons: list[str] = None            # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.reasons is None:
            self.reasons = []


def map_testcases(cases: list[TestCase], ui_map: UIMap,
                  base_url: str | None = None,
                  api_paths: set[str] | None = None) -> MapStats:
    """Sửa tại chỗ: thay bước văn xuôi bằng hành động cụ thể khi map được.

    `api_paths` là tập đường dẫn API **có thật** (lấy từ OpenAPI spec). Chỉ những
    đường dẫn nằm trong đây mới được map thành `http.request`.

    Vì sao khắt khe: tài liệu viết `GET /auth/me`, nhưng API thật là
    `/api/v1/auth/me`. Nếu mapper tự ghép theo tài liệu, request sẽ bay vào SPA
    catch-all và nhận về HTML — rồi báo `Fail`. Đó là báo động giả, tệ hơn là
    để case ở trạng thái chưa map.
    """
    stats = MapStats(total=len(cases))
    root = (base_url or ui_map.base_url or "").rstrip("/")
    allowed = api_paths or set()

    for case in cases:
        before = case.needs_mapping
        case.steps = _map_steps(case.steps, ui_map, root, case.id, stats, allowed)

        # Chèn bước đặt phiên SAU khi map xong, vì lúc đó mới biết case có dùng
        # trình duyệt hay không. Gọi trước khi map thì mọi case đều còn là
        # `perform.unmapped` và không phân biệt được case UI với case API.
        if mode := _case_session(case):
            case.steps = [Step(1, StepKind.GIVEN, "ui.session", {"mode": mode}),
                          *[Step(s.seq + 1, s.kind, s.action, s.args, s.note)
                            for s in case.steps]]

        # Case đòi bị TỪ CHỐI truy cập, hoặc kiểm thứ PHẢI BỊ ẨN với người thiếu
        # quyền, thì cần tài khoản thiếu quyền — thứ tool không tự tạo được. Đánh
        # dấu để runner báo `Blocked`, không báo `Fail`: chạy bằng tài khoản đủ
        # quyền mà mong đợi 403 (hoặc mong đợi mục bị ẩn) là sai tiền đề.
        #
        # Xét cả **tiêu đề** và **mọi tham số** của bước: sau khi map, câu văn xuôi
        # không còn ở `expected` nữa mà nằm rải ở `target`/`by_name`/`pattern`.
        if not case.requires:
            blob = " ".join([
                case.title or "", case.objective or "",
                *[str(v) for step in case.steps for v in step.args.values()],
            ])
            case.requires = _setup_requirement(blob)

        # `execution` phải phản ánh trạng thái SAU khi map, không phải lúc sinh.
        #
        # Quy tắc: còn bước văn xuôi ⇒ người phải chạy; map hết được ⇒ máy chạy
        # được. Đây là tín hiệu tự nhiên, không cần thêm field đánh dấu "vì sao
        # thủ công": thao tác máy không làm nổi (nhập OTP, quét QR) thì mapper
        # cũng không map được, nên case tự ở lại `manual`.
        case.execution = "manual" if case.needs_mapping else "auto"

        if before and not case.needs_mapping:
            stats.mapped += 1
        elif case.needs_mapping:
            stats.still_unmapped += 1

    return stats


# Dấu hiệu case phải chạy trong phiên CHƯA đăng nhập.
#
# Đây là điều kiện tiên quyết của gần như toàn bộ feature login-sso: "Router guard
# chạy", "check-sso", "Redirect /login"… chỉ có nghĩa khi trình duyệt sạch phiên.
# Chạy chúng trong phiên đã đăng nhập thì kết quả vô nghĩa — hoặc tệ hơn, chúng
# `Pass` giả tạo vì trang không hề chuyển hướng.
RE_NEEDS_ANONYMOUS = re.compile(
    r"chưa\s+(?:authenticated|đăng\s+nhập|xác\s+thực)"
    r"|không\s+(?:có\s+)?(?:token|đăng\s+nhập)"
    r"|chưa\s+login|not\s+(?:signed|logged)\s*in"
    r"|anonymous|ẩn\s+danh"
    r"|login\s+(?:cancelled|failed)"
    r"|silent\s+iframe\s+fails|init\s+timeout",
    re.I)

# Dấu hiệu case cần phiên ĐÃ đăng nhập (mặc định, nhưng ghi rõ để đối xứng)
RE_NEEDS_AUTH = re.compile(
    r"đã\s+(?:authenticated|đăng\s+nhập)"
    r"|session\s+(?:active|hợp\s+lệ)|IdP\s+session"
    r"|topbar|sign\s*out|logout|đăng\s+xuất",
    re.I)


def _case_session(case: TestCase) -> str | None:
    """Case này cần phiên TRÌNH DUYỆT gì? `None` = không ràng buộc.

    **Chỉ áp dụng cho case có bước UI.** Case API tự quyết định xác thực bằng
    tham số `auth` của bước `http.request` (`none`/`bearer`) — chèn thêm bước
    `ui.session` vào chúng vừa vô nghĩa vừa làm hỏng: chạy trong CI không có
    trình duyệt thì case API lẽ ra `Pass` lại thành `Fail` vì thiếu browser.

    Tôi đã mắc đúng lỗi này: preconditions của case API viết "KHÔNG gửi token",
    khớp với mẫu "chưa xác thực", nên toàn bộ 8 case API bị chèn bước xoá phiên.
    """
    uses_ui = any(
        s.action.startswith("ui.") or s.action in
        ("assert.url_matches", "assert.visible", "assert.not_visible")
        for s in case.steps
    )
    if not uses_ui:
        return None

    blob = " ".join([
        case.title, case.objective,
        *case.preconditions,
        # Cả bước đã map (`ui.session`, `assert.url_matches`…) lẫn bước còn văn
        # xuôi: quyết định phiên phải dựa trên **nội dung case**, không phụ thuộc
        # việc mapper đã thay bước hay chưa.
        *(str(s.args.get("description") or s.args.get("expected")
              or s.args.get("pattern") or "") for s in case.steps),
    ])
    if RE_NEEDS_ANONYMOUS.search(blob):
        return "anonymous"
    # Trạng thái đích của case chuyển trạng thái quyết định phiên cần dùng:
    # `... → Unauthenticated` phải chạy ở phiên sạch, còn `... → Authenticated`
    # phải chạy ở phiên đã đăng nhập.
    target = _target_state_of(case)
    source = _source_state_of(case)
    if target in STATE_NEEDS_AUTH:
        # Nhưng nếu case đi TỪ một trạng thái chưa-đăng-nhập sang trạng thái đã
        # đăng nhập (`Unauthenticated → Authenticated`), hành vi cần kiểm chính là
        # việc **đăng nhập** — chạy sẵn trong phiên đăng nhập thì bước đó vô nghĩa.
        if source in STATE_NEEDS_ANONYMOUS:
            return "anonymous"
        return "authenticated"
    if target in STATE_NEEDS_ANONYMOUS:
        return "anonymous"
    if RE_NEEDS_AUTH.search(blob):
        return "authenticated"
    return None


def _source_state_of(case: TestCase) -> str | None:
    """Trạng thái NGUỒN của case chuyển trạng thái (`X → Y` thì đây là `X`)."""
    if m := re.match(r"\s*([A-Za-z]+)\s*→", case.title or ""):
        return _state_name(m.group(1))
    return None


def _target_state_of(case: TestCase) -> str | None:
    """Trạng thái ĐÍCH của case chuyển trạng thái, nếu là case loại đó.

    Đọc từ **tiêu đề** trước: tài liệu sinh tiêu đề dạng
    `Loading → Unauthenticated khi …`, và đó là nguồn ổn định nhất — sau khi map
    xong, bước THEN đã thành `assert.url_matches` và không còn chữ "Unauthenticated"
    để đọc. Đọc từ steps là phương án dự phòng cho case viết tay.
    """
    if m := re.search(r"→\s*([A-Za-z]+)", case.title or ""):
        return _state_name(m.group(1))
    for step in case.steps:
        text = str(step.args.get("expected") or step.args.get("description") or "")
        if m := RE_STATE_TO.search(text):
            return _state_name(m.group(1))
    return None


def _map_steps(steps: list[Step], ui_map: UIMap, root: str,
               case_id: str, stats: MapStats, api_paths: set[str]) -> list[Step]:
    out: list[Step] = []
    seq = 0

    for step in steps:
        if step.action not in ("perform.unmapped", "assert.unmapped"):
            seq += 1
            out.append(Step(seq, step.kind, step.action, step.args, step.note))
            continue

        text = (step.args.get("description") or step.args.get("expected") or "").strip()

        if step.action == "perform.unmapped":
            mapped = _map_action(text, ui_map, root, api_paths)
            mapped = _drop_unverified_http(mapped, api_paths, stats, case_id, text)
        else:
            mapped = _map_expectation(text, ui_map, root, api_paths)
            mapped = _drop_unverified_http(mapped, api_paths, stats, case_id, text)

        if mapped is None:
            seq += 1
            out.append(Step(seq, step.kind, step.action, step.args,
                            f"chưa map được: {text[:60]}"))
            stats.reasons.append(f"{case_id}: không map được «{text[:50]}»")
        else:
            for action, args in mapped:
                seq += 1
                out.append(Step(seq, step.kind, action, args))
    return out


def _drop_unverified_http(mapped, api_paths: set[str], stats: MapStats,
                          case_id: str, text: str):
    """Bỏ những `http.request` trỏ tới đường dẫn không có trong OpenAPI spec.

    Khi bỏ, phải bỏ **cả cụm** — trả `None` thay vì danh sách rỗng. Nếu chỉ bỏ
    riêng `http.request` mà giữ `assert.http_status` đi kèm, assert sẽ chạy mà
    không có response nào để kiểm, và case báo `Fail` vì lý do hoàn toàn do tool.
    """
    if not mapped:
        return mapped
    if any(action == "http.request" and args.get("path") not in api_paths
           for action, args in mapped):
        paths = [args.get("path") for action, args in mapped if action == "http.request"]
        stats.reasons.append(
            f"{case_id}: bỏ HTTP {'/'.join(str(p) for p in paths)} — không có trong "
            "OpenAPI spec, không dám chắc đường dẫn thật"
        )
        return None
    return mapped


# Dấu hiệu một `perform` đang nói về API chứ không phải trang web
RE_API_HINT = re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE)\s+/|p9\d|p95|p99|ms\b", re.I)


# Loại case cần điều kiện mà công cụ không tự tạo được, kèm lời giải thích
SETUP_HINTS = [
    (re.compile(r"(?:/forbidden|\b403\b|không\s+có\s+quyền|thiếu\s+quyền|forbidden|"
                r"not\s+allowed|access\s+denied)", re.I),
     "Cần một tài khoản KHÔNG có quyền thực hiện thao tác này "
     "(tài khoản đang dùng có thể đã đủ quyền)"),

    # Kiểm thứ **phải bị ẩn** với người thiếu quyền (sidebar lọc theo permission).
    # Tài khoản automation trong `.env` thường là admin — chạy case này bằng admin
    # thì mọi mục đều hiện, và case báo `Fail` trong khi sản phẩm đúng.
    # Đã gặp thật: `Nav Projects visible; Users hidden` báo `Fail` vì tài khoản
    # test là platform administrator (thấy Users là **đúng** với quyền đó).
    (re.compile(r"(?:nav\s+\w+\s+visible|sidebar|menu|nav)\b[^.]{0,80}?"
                r"(?:hidden|ẩn|không\s+hiện)", re.I),
     "Cần một tài khoản KHÔNG có quyền với mục bị kiểm ẩn — tài khoản đang dùng "
     "có thể là admin nên thấy đủ mọi mục, và như vậy là đúng"),
    (re.compile(r"(?:hidden|ẩn|không\s+hiện)\b[^.]{0,60}?"
                r"(?:permission|quyền|role|vai\s+trò)", re.I),
     "Cần tài khoản thiếu quyền để kiểm mục bị ẩn — tài khoản hiện tại có thể đủ quyền"),
]


def _setup_requirement(text: str) -> str | None:
    for pattern, reason in SETUP_HINTS:
        if pattern.search(text):
            return reason
    return None


# `Mở login` / `Mở portal URL mới` — tên trang, không phải đường dẫn
RE_OPEN_PAGE = re.compile(
    r"^\s*(?:" + _SUBJECT + r")?(?:mở|open|truy cập|đi tới|navigate to)\s+"
    r"[\"'`]?([^/`\"'].{0,40}?)[\"'`]?\s*$",
    re.I)

# Nhãn UI trần, không có động từ: `TopBar Sign Out`, `Settings`
RE_BARE_LABEL = re.compile(r"^\s*[\"'`]?([\w\s\-/&.]{2,48})[\"'`]?\s*$")

# Nhãn nói về route guard / trạng thái chưa đăng nhập → mở URL bị bảo vệ
RE_GUARD = re.compile(
    r"router\s+guard|route\s+guard|requireauth|requirepermission|"
    r"navigate\s+/|mở\s+portal\s+url\s+mới|app\s+mount|load\s+appshell",
    re.I)

# ── Nhãn nghiệp vụ UI/UX ────────────────────────────────────────────────────
# Tài liệu và NFR hay viết bằng văn xuôi: "không lộ stack trace ra UI", "nút bị
# vô hiệu hoá khi đang xử lý", "con trỏ nằm ở ô đầu tiên". Trước đây nhóm này
# luôn ở trạng thái chưa map, tức là NFR về UX không bao giờ được kiểm — dù
# công cụ có đủ khả năng kiểm. Đây là chỗ nối văn xuôi vào verb cụ thể.
RE_UI_UNAVAILABLE = re.compile(
    r"(?:vô\s+hiệu\s+hoá|disabled|không\s+bấm\s+được|khoá\s+lại|grey(?:ed)?\s*out|"
    r"không\s+cho\s+phép\s+bấm)", re.I)
RE_UI_AVAILABLE = re.compile(
    r"(?:bấm\s+được|kích\s+hoạt\s+được|enable[d]?|hoạt\s+động\s+được|"
    r"không\s+bị\s+khoá)", re.I)
RE_UI_JS_ERROR = re.compile(
    r"(?:stack\s*trace|lỗi\s+js|javascript\s+error|console\s*error|"
    r"không\s+lộ\s+lỗi|crash|white\s*screen|màn\s+hình\s+trắng)", re.I)
RE_UI_BROKEN_CALLS = re.compile(
    r"(?:gọi\s+api\s+thất\s+bại|request\s+lỗi|\b5\d\d\b\s*(?:error|lỗi)?|"
    r"không\s+gọi\s+được\s+api|broken\s+request)", re.I)
RE_UI_FOCUS = re.compile(
    r"(?:focus|con\s+trỏ|tiêu\s+điểm|tab\s+order|bàn\s+phím)", re.I)
RE_UI_A11Y = re.compile(
    r"(?:accessibilit|a11y|wcag|trình\s+đọc\s+màn\s+hình|screen\s*reader|"
    r"tương\s+phản|contrast)", re.I)


def _element_in_text(text: str, ui_map: UIMap):
    """Element nào của UI map được câu này nhắc tới.

    Ưu tiên nhãn dài (cụ thể hơn) để "Đăng nhập" không thắng "Đăng nhập bằng SSO".
    """
    lowered = text.lower()
    best = None
    for element in ui_map.elements:
        name = (element.name or "").lower()
        if not name or name not in lowered:
            continue
        if best is None or len(name) > len(best.name or ""):
            best = element
    return best


def _page_path(name: str, ui_map: UIMap) -> str | None:
    """Tên trang → đường dẫn thật, chỉ dựa vào element **có thật** trong ui-map.

    `Mở login` → `/login` vì ui-map có link hoặc đã crawl chính trang đó. Không
    đoán theo tên: nếu `/login` không nằm trong map thì trả `None` và case ở lại
    chưa map — đúng nguyên tắc không bịa đường dẫn.
    """
    needle = _norm(name)
    if not needle:
        return None
    for word in ("login", "signin", "sign-in", "đăng nhập"):
        if word in needle:
            for page in ui_map.pages:
                path = urlparse(page.url).path
                if path and any(w in path.lower() for w in ("login", "signin", "sign-in")):
                    return path
            return None

    # Khớp với link có thật trong map
    for element in ui_map.elements:
        if element.role == "link" and element.href:
            if needle and needle in _norm(element.name):
                return element.href
    return None


def _target_of(element) -> dict:
    """Tham số trỏ tới element: ưu tiên `test_id` (bền), rồi mới tới `id`+nhãn.

    Vì sao test_id quan trọng: nhãn hiển thị đổi khi dev sửa chữ, còn
    `data-testid` thì không. Dùng nhãn làm `target` nghĩa là mọi lần đổi chữ
    trong giao diện đều làm test đỏ — dù sản phẩm vẫn đúng.
    """
    if getattr(element, "test_id", None):
        return {"target": element.test_id, "by_name": element.name}
    return {"target": element.id, "by_name": element.name}


def _map_label(text: str, ui_map: UIMap, root: str) -> list[tuple[str, dict]] | None:
    """Nhãn mô tả ngắn → hành động UI cụ thể.

    Bốn nhóm, theo thứ tự tin cậy:

    1. **Route guard** (`Router guard chạy`, `Navigate /users manually`) — mở URL
       bị bảo vệ để xem hệ thống có chặn không.
    2. **`A → B`**: câu mô tả đường đi (`Settings → chọn ngôn ngữ`) — mở trang đầu.
    3. **Nhãn khớp element có thật** (`TopBar Sign Out`, `Logout`) — bấm.
    4. Không khớp gì → `None`, case ở lại chưa map.
    """
    if RE_GUARD.search(text):
        if m := RE_URL_IN_TEXT.search(text):
            return [("ui.goto", {"url": _join(root, m.group(1))})]
        return [("ui.goto", {"url": root})]

    # `Settings → chọn ngôn ngữ`: phần trước mũi tên là **nơi cần tới**.
    if "→" in text:
        head = text.split("→", 1)[0].strip()
        if path := _page_path(head, ui_map):
            return [("ui.goto", {"url": _join(root, path)})]
        if element := _element_for_bare_label(head, ui_map):
            if element.role == "link" and element.href:
                return [("ui.goto", {"url": _join(root, element.href)})]
            return [("ui.click", _target_of(element))]

    if m := RE_BARE_LABEL.match(text):
        label = m.group(1).strip()
        if element := _element_for_bare_label(label, ui_map):
            # Nhãn trỏ tới link có href → điều hướng; còn lại coi là bấm
            if element.role == "link" and element.href:
                return [("ui.goto", {"url": _join(root, element.href)})]
            return [("ui.click", _target_of(element))]
        # Nhãn có thể là tên trang (`Mở login` đã bắt ở trên; ở đây là `login`)
        if path := _page_path(label, ui_map):
            return [("ui.goto", {"url": _join(root, path)})]
    return None


def _element_for_bare_label(label: str, ui_map: UIMap):
    """Nhãn trần (`TopBar Sign Out`) có trỏ tới một element không.

    Chặt hơn `ui_map.find`: nhãn trần là **tên gọi**, không phải câu. Nếu chỉ khớp
    một phần thì `refresh fail no upload` (một điều kiện trong tài liệu) khớp với
    nút `Refresh` có thật trên trang, và mapper sinh ra bước `ui.click «Refresh»` —
    hành động không ai nói tới. Đã gặp thật: case `Refreshing → Unauthenticated khi
    refresh fail no upload` bấm nút Refresh rồi kiểm sai chỗ.

    Quy tắc: khớp trọn vẹn, hoặc phần thừa chỉ là từ đệm (`Nút Lưu`, `Save button`).
    """
    element = ui_map.find(label)
    if element is None:
        return None
    needle, found = _norm(label), _norm(element.name)
    if needle == found or found in needle and _only_filler_words(
            needle.replace(found, " ", 1)):
        return element
    # `ui_map.find` khớp được vì nhãn tài liệu **dài hơn** tên element
    # (`Click Sign in with Keycloak` → nút `Sign in`) — nhưng đó là nhánh câu lệnh
    # đã xử lý ở `_map_action`, không phải nhãn trần.
    return None


def _looks_like_api(text: str) -> bool:
    """Câu này đang nói về API, không phải về màn hình.

    `/auth/config p95 < 100ms` là yêu cầu hiệu năng API — map nó thành `ui.goto`
    sẽ mở trình duyệt tới một đường dẫn API và nhận về HTML, rồi báo Fail sai.

    Bao gồm cả trường hợp **có method + đường dẫn** (`GET /auth/me 200`): điều
    hướng tới endpoint API bằng trình duyệt là sai, kể cả khi đường dẫn không có
    trong spec. Đã gặp: không có spec thì câu này bị map thành `assert.url_matches`
    trên URL của endpoint.
    """
    if RE_HTTP.search(text):
        return True
    return bool(RE_API_HINT.search(text))


# Ngưỡng hiệu năng trên một endpoint: `/auth/config p95 < 100ms`.
# Nhóm này **phải** gọi API mới kiểm được — nhưng bằng `http.request`, không phải
# `ui.goto`. Trước đây chúng bị `_looks_like_api` chặn nên NFR hiệu năng không bao
# giờ được kiểm, dù đã có đủ verb (`http.request` + `assert.response_time`).
RE_PERF_ENDPOINT = re.compile(
    r"(?P<path>/[\w\-./{}$]+)\s*(?:p\d+\s*[<≤]\s*|dưới\s+|under\s+)?"
    r"(?P<ms>\d+(?:\.\d+)?)\s*ms", re.I)


def _anonymous_hint(text: str) -> bool:
    """Câu này nói rõ phải gọi **không** kèm token.

    Dùng chung cho `http.request`: `GET /auth/config không token` phải gửi ẩn danh
    — đó chính là thứ case định kiểm.
    """
    return bool(re.search(r"không\s+token|chưa\s+xác\s+thực|no\s+token|anonymous|"
                          r"unauth", text, re.I))


def _map_perf_endpoint(text: str, api_paths: set[str], root: str) -> list[tuple[str, dict]] | None:
    """`/auth/config p95 < 100ms` → GET + kiểm phân vị thời gian phản hồi.

    Chỉ map khi đường dẫn có trong spec (khớp theo hậu tố), đúng nguyên tắc không
    bịa endpoint.

    `p95` là **phân vị** thứ 95, không phải "mọi lần gọi đều dưới ngưỡng": yêu cầu
    cho phép 5% số lần gọi vượt ngưỡng. Vì vậy bước sinh ra lấy nhiều mẫu rồi so
    đúng phân vị tài liệu nói (`percentile_of` đọc `p95`/`p99` từ câu).
    """
    m = RE_PERF_ENDPOINT.search(text)
    if not m or not api_paths:
        return None
    real = _match_api_path(m.group("path"), api_paths)
    if not real:
        return None
    auth = "none" if _anonymous_hint(text) else "bearer"
    return [
        ("http.request", {"method": "GET", "path": real, "auth": auth, "save_as": "res"}),
        ("assert.response_time", {"max_ms": float(m.group("ms")), "source": "res",
                                  "percentile": percentile_of(text),
                                  "samples": PERF_SAMPLES}),
    ]


def _state_name(raw: str) -> str:
    """`«Unauthenticated»` → `unauthenticated`."""
    return _norm(re.sub(r"[«»\"'`]", "", raw or "")).replace(" ", "")


def _map_state_action(text: str, ui_map: UIMap, root: str) -> list[tuple[str, dict]] | None:
    """`Trạng thái hiện tại: Loading` → mở trang để rơi vào trạng thái đó.

    Việc **đặt phiên** (ẩn danh / đã đăng nhập) do `_case_session` lo, dựa trên
    trạng thái đích của cả case — không quyết ở đây, vì một case có thể có GIVEN ở
    trạng thái này và THEN ở trạng thái khác.

    Chỉ map khi biết đường dẫn vào trạng thái. Không biết thì trả `None` — case ở
    lại chưa map, đúng nguyên tắc không đoán.
    """
    m = RE_STATE_CURRENT.match(text) or re.match(
        r"^\s*(?:user\s+)?(?:ở|in)\s+trạng\s+thái\s*:?\s*(.+?)\s*$", text, re.I)
    if not m:
        return None
    name = _state_name(m.group(1))
    path = STATE_ENTRY_PATH.get(name)
    if not path:
        return None
    return [("ui.goto", {"url": _join(root, path)})]


def _map_state_expectation(text: str, ui_map: UIMap, root: str) -> list[tuple[str, dict]] | None:
    """`Chuyển sang trạng thái «Authenticated»` → kiểm biểu hiện UI của trạng thái đó."""
    m = RE_STATE_TO.search(text)
    if not m:
        return None
    name = _state_name(m.group(1))
    signs = STATE_SIGNS.get(name)
    if signs:
        return list(signs)
    # `Authenticating` / `Refreshing` là trạng thái **trung gian**, không có biểu
    # hiện ổn định để kiểm (thoáng qua trong lúc chờ mạng). Kiểm nó là tạo flake.
    if name in ("authenticating", "refreshing"):
        return []
    return None


def _map_http_endpoint(text: str, api_paths: set[str], root: str,
                       body: dict | None = None) -> list[tuple[str, dict]] | None:
    """Endpoint viết trong câu → `http.request` + assert trạng thái.

    Chỉ map khi đường dẫn **nằm trong spec** (sau khi chuẩn hoá tiền tố). Tài liệu
    hay viết `/auth/me` trong khi API thật ở `/api/v1/auth/me`; ghép bừa theo tài
    liệu là request bay vào SPA catch-all và nhận HTML.

    Chấp nhận khớp **theo hậu tố**: `/auth/me` ↔ `/api/v1/auth/me`.

    `body` lấy từ `test_data` của case (nếu tài liệu có khai). Thiếu body cho
    `PATCH`/`POST` thì request trả 422 — và đó là **lỗi của tool**, không phải của
    sản phẩm: đã gặp thật với `PATCH /auth/me {preferred_locale: "vi"}`.
    Vì vậy khi câu nói tới method cần body mà không có body, trả `None` để case ở
    lại chưa map thay vì chạy rồi báo `Fail` sai.
    """
    m = RE_HTTP.search(text)
    if not m or not api_paths:
        return None
    method, raw_path = m.group(1).upper(), m.group(2).rstrip(".,;`\"')")
    real = _match_api_path(raw_path, api_paths)
    if not real:
        return None

    needs_body = method in ("POST", "PUT", "PATCH")
    if needs_body and not body:
        # Có nhắc body trong câu (`PATCH body preferred_locale`) mà không trích
        # được giá trị → chưa đủ cơ sở để gọi.
        return None

    # `auth` theo ngữ cảnh câu: nếu câu nói rõ "không token"/"chưa xác thực" thì
    # gửi ẩn danh — đúng thứ case đó định kiểm.
    auth = "none" if _anonymous_hint(text) else "bearer"
    args: dict = {"method": method, "path": real, "auth": auth, "save_as": "res"}
    if body:
        args["body"] = body

    status = re.search(r"\b(200|201|204|400|401|403|404|409|422|500)\b", text)
    out: list[tuple[str, dict]] = [("http.request", args)]
    if status:
        out.append(("assert.http_status", {"expected": int(status.group(1)), "source": "res"}))
    return out


def _match_api_path(path: str, api_paths: set[str]) -> str | None:
    """Khớp đường dẫn trong tài liệu với đường dẫn thật trong spec."""
    clean = re.sub(r"[{][^}]*[}]", "", path.split("?")[0]).rstrip("/") or "/"
    for real in sorted(api_paths, key=len):
        if re.sub(r"[{][^}]*[}]", "", real).rstrip("/") == clean:
            return real
        if real.endswith(clean) or clean.endswith(real):
            return real
    return None


def _map_action(text: str, ui_map: UIMap, root: str,
                api_paths: set[str] | None = None) -> list[tuple[str, dict]] | None:
    """Vế WHEN — phải làm gì.

    Thứ tự ưu tiên, chắc chắn giảm dần:

    1. **Endpoint có trong spec** → `http.request`. Đây là thứ chắc chắn nhất: spec
       đã xác nhận đường dẫn tồn tại.
    2. **Trạng thái phiên** → mở trang để rơi vào trạng thái đó.
    3. Điều hướng theo đường dẫn/tên trang, bấm, điền.

    Lưu ý về `_looks_like_api`: nó chặn câu nói về API để không map thành `ui.goto`
    (mở trình duyệt tới một endpoint API rồi nhận HTML). Nhưng khi **đã có spec**,
    câu đó map được thành `http.request` thật — nên phải thử endpoint TRƯỚC khi
    loại câu ra.
    """
    if not text:
        return None

    # 1. Endpoint có thật trong spec.
    if api_paths and (mapped := _map_http_endpoint(text, api_paths, root)):
        return mapped

    # 1b. NFR hiệu năng trên một endpoint (`/auth/config p95 < 100ms`). Chạy
    # TRƯỚC `_looks_like_api`: nhóm câu này chứa `ms` nên bị nhánh đó chặn, mà
    # chặn thì NFR hiệu năng không bao giờ được kiểm dù đã có đủ verb.
    if api_paths and (perf := _map_perf_endpoint(text, api_paths, root)):
        return perf

    # 2. Trạng thái phiên → mở trang tương ứng.
    if mapped := _map_state_action(text, ui_map, root):
        return mapped

    # Câu nói về API mà spec không xác nhận đường dẫn → không map. Map thành
    # `ui.goto` sẽ mở trình duyệt tới endpoint và nhận HTML, rồi báo Fail sai.
    if _looks_like_api(text):
        return None

    # Mở một đường dẫn cụ thể. `Mở login` (không dấu `/`) cũng phải hiểu là điều
    # hướng tới `/login` — tài liệu hay viết tên trang thay vì đường dẫn.
    if m := RE_OPEN_PATH.match(text):
        path = m.group(1)
        return [("ui.goto", {"url": _join(root, path)})]
    if m := RE_OPEN_PAGE.match(text):
        if path := _page_path(m.group(1), ui_map):
            return [("ui.goto", {"url": _join(root, path)})]

    # Bấm một thứ có thật trên trang
    if m := RE_CLICK.match(text):
        target = m.group(1).strip()
        if element := ui_map.find(target):
            return [("ui.click", _target_of(element))]
        return None

    # Điền vào ô nhập
    if m := RE_FILL.match(text):
        value, target = m.group(1).strip(), m.group(2).strip()
        if element := ui_map.find(target):
            return [("ui.fill", {**_target_of(element), "value": value})]
        return None

    # Câu chỉ mô tả trạng thái nội bộ — không phải hành động, nhưng cũng không
    # phải lỗi. Không sinh bước nào; kỳ vọng ở vế THEN sẽ lo phần kiểm tra.
    if RE_STATE_ONLY.match(text):
        return []

    # ── Nhãn ngắn kiểu tài liệu: "Router guard chạy", "TopBar Sign Out" ──────
    # Đây là nhóm lớn nhất trong tài liệu thật (55/122 bước của login-sso). Chúng
    # là **nhãn mô tả**, không phải câu lệnh — nhưng vẫn trỏ tới hành động cụ thể:
    # "TopBar Sign Out" là nút đăng xuất, "Router guard chạy" là mở một URL bị bảo vệ.
    # Không xử lý nhóm này thì phần lớn case UI không bao giờ chạy được.
    if mapped := _map_label(text, ui_map, root):
        return mapped

    # Có nhắc tới một đường dẫn → coi như đi tới đó
    if m := RE_URL_IN_TEXT.search(text):
        return [("ui.goto", {"url": _join(root, m.group(1))})]

    return None


def _split_conditions(text: str) -> list[str]:
    """`Nav Projects visible; Users hidden` → hai điều kiện riêng.

    Tài liệu gộp nhiều kỳ vọng vào một câu. Chỉ map vế đầu là **bỏ sót** phần còn
    lại — thường đúng phần quan trọng (thứ phải bị ẩn đi).
    """
    parts = [p.strip(" .") for p in re.split(r"\s*;\s*", text) if p.strip(" .")]
    return parts if len(parts) > 1 else [text]


RE_NAMED_VISIBLE = re.compile(r"\bvisible\b|\bhiện\b|\bhiển\s+thị\b", re.I)
RE_NAMED_HIDDEN = re.compile(r"\bhidden\b|\bẩn\b|\bẩn\s+đi\b|\bkhông\s+hiện\b", re.I)


def _named_visibility(text: str, ui_map: UIMap) -> list[tuple[object, bool]]:
    """`Nav X visible; Y hidden` → [(element, True/False), …].

    Dạng câu này không có giới từ (`hiện lên «X»`) nên `RE_VISIBLE` không bắt được:
    nó đặt tên element **trước** từ khoá trạng thái. Tài liệu login-sso dùng dạng
    này để mô tả sidebar theo quyền — đúng thứ cần kiểm nhất.
    """
    out: list[tuple[object, bool]] = []
    for chunk in _split_conditions(text):
        positive = bool(RE_NAMED_VISIBLE.search(chunk))
        negative = bool(RE_NAMED_HIDDEN.search(chunk))
        if not (positive or negative):
            continue
        element = _element_in_text(chunk, ui_map)
        if element is not None:
            out.append((element, not negative))
    return out


def _ux_expectation(text: str, ui_map: UIMap) -> list[tuple[str, dict]] | None:
    """Kỳ vọng về hành vi/UX → verb cụ thể.

    Chỉ sinh khi câu nói tới một element **có thật** trong UI map (với nhóm cần
    element), hoặc khi câu nói về thứ kiểm được ở mức toàn trang (lỗi JS, request
    lỗi). Không có cơ sở thì trả `None` và case ở lại chưa map — không đoán.
    """
    if RE_UI_JS_ERROR.search(text):
        return [("assert.console_clean", {})]

    if RE_UI_BROKEN_CALLS.search(text):
        return [("assert.no_broken_requests", {})]

    if RE_UI_A11Y.search(text) and not RE_UI_FOCUS.search(text):
        return [("assert.axe", {})]

    element = _element_in_text(text, ui_map)
    if element is None:
        return None

    if RE_UI_UNAVAILABLE.search(text):
        return [("assert.disabled", _target_of(element))]
    if RE_UI_AVAILABLE.search(text):
        return [("assert.enabled", _target_of(element))]

    return None


def _map_expectation(text: str, ui_map: UIMap, root: str,
                     api_paths: set[str] | None = None) -> list[tuple[str, dict]] | None:
    """Vế THEN — phải kiểm cái gì."""
    if not text:
        return None

    actions: list[tuple[str, dict]] = []

    # Nhiều điều kiện trong một câu, ngăn bằng `;` hoặc `,`:
    # `Nav Projects visible; Users hidden` phải kiểm **cả hai** — chỉ kiểm vế đầu
    # là bỏ sót đúng nửa phần quan trọng (thứ bị ẩn).
    if len(parts := _split_conditions(text)) > 1:
        for part in parts:
            if sub := _map_expectation(part, ui_map, root, api_paths):
                actions.extend(sub)
        return actions or None

    # Kỳ vọng về hành vi/UX (vô hiệu hoá, lỗi JS, request lỗi, accessibility).
    # Kiểm nhóm này TRƯỚC nhóm "nhìn thấy": câu kiểu "nút bị vô hiệu hoá, không
    # bấm được" vừa khớp `visible` vừa khớp `disabled`, và map nhầm sang
    # `assert.visible` là bỏ mất đúng thứ cần kiểm.
    if ux := _ux_expectation(text, ui_map):
        return ux

    # Cặp "X visible / Y hidden" — dạng câu không có giới từ (`hiện lên «X»`).
    for element, positive in _named_visibility(text, ui_map):
        actions.append(("assert.visible" if positive else "assert.not_visible",
                        _target_of(element)))
    if actions:
        return actions

    # Trạng thái phiên (`Chuyển sang trạng thái «Authenticated»`).
    if state := _map_state_expectation(text, ui_map, root):
        return state

    # Đổi hướng tới một đường dẫn
    if m := RE_REDIRECT.search(text):
        path = m.group(1).rstrip(".,;")
        if path and path != "/":
            actions.append(("assert.url_matches", {"pattern": re.escape(path)}))

    # "Response có đủ field: a, b, c" → kiểm hợp đồng dữ liệu từ response đã lưu.
    if m := RE_RESPONSE_FIELDS.search(text):
        fields = [f.strip() for f in re.split(r"[,;]", m.group(1)) if f.strip()]
        if fields:
            actions.append(("assert.json_schema",
                            {"required": fields, "source": "res"}))
            return actions

    # Endpoint + mã trạng thái ở vế THEN (ví dụ "GET /auth/me 200").
    if api_paths and (endpoint := _map_http_endpoint(text, api_paths, root)):
        return endpoint

    # Không được nhìn thấy một thứ
    if RE_NOT_VISIBLE.search(text):
        for element in ui_map.elements:
            if element.name and element.name.lower() in text.lower():
                actions.append(("assert.not_visible", _target_of(element)))
                break
        return actions or None

    # Nhìn thấy một thứ
    if m := RE_VISIBLE.search(text):
        target = m.group(1).strip()
        if element := ui_map.find(target):
            actions.append(("assert.visible", _target_of(element)))

    # Câu nói về API mà spec KHÔNG xác nhận đường dẫn → không map nốt phần còn
    # lại. `RE_URL_IN_TEXT` bên dưới sẽ biến `/auth/me` thành `assert.url_matches`
    # trên URL của endpoint — sai hoàn toàn, vì đó không phải trang web.
    if _looks_like_api(text):
        return actions or None

    # Không trích được gì nhưng câu có nhắc đường dẫn → kiểm URL
    if not actions:
        if m := RE_URL_IN_TEXT.search(text):
            actions.append(("assert.url_matches", {"pattern": re.escape(m.group(1))}))

    return actions or None


def _join(root: str, path: str) -> str:
    """Ghép URL, LUÔN đảm bảo có dấu `/` giữa hai phần.

    Bug đã gặp: regex bắt nhóm không kèm dấu `/`, nên `root + "users"` ra
    `https://host.fitusers` — URL rác, và case fail vì lý do chẳng liên quan
    gì tới sản phẩm.
    """
    if path.startswith(("http://", "https://")):
        return path
    root = root.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return root + path

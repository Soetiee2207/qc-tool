"""Testcase IR — định dạng trung tâm của tool.

**File testcase theo template KHÔNG phải định dạng trung tâm.** IR này mới là.
Template chỉ là một renderer cắm vào sau. Lý do: template QC đổi theo dự án,
còn nếu engine sinh thẳng ra template thì mỗi lần đổi template là viết lại engine.

Điểm mấu chốt: **vocabulary đóng**. `Step.action` chỉ được là một trong ACTION_SPECS.
Verb lạ bị validator chặn. Đây là thứ biến output từ "đọc được" thành "chạy được" —
một bước viết bằng văn xuôi thì không ai thực thi được.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum


class StepKind(Enum):
    GIVEN = "given"
    WHEN = "when"
    THEN = "then"


class CaseType(Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    BOUNDARY = "boundary"
    SECURITY = "security"
    PERFORMANCE = "performance"
    STATE = "state"


class Priority(Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class Technique(Enum):
    """Vì sao testcase này tồn tại. Ghi lại để người review biết nó ở đâu ra."""

    EQUIVALENCE_PARTITIONING = "equivalence_partitioning"
    BOUNDARY_VALUE = "boundary_value"
    DECISION_TABLE = "decision_table"
    STATE_TRANSITION = "state_transition"
    ACCEPTANCE_CRITERION = "acceptance_criterion"
    ERROR_GUESSING = "error_guessing"
    SCHEMA_CONFORMANCE = "schema_conformance"
    AUTH_MATRIX = "auth_matrix"
    PERFORMANCE_THRESHOLD = "performance_threshold"


# ── Vocabulary đóng ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ActionSpec:
    """Một verb hợp lệ, kèm tham số bắt buộc và tham số tuỳ chọn."""

    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    doc: str = ""


ACTION_SPECS: dict[str, ActionSpec] = {
    # ── Thực hiện ───────────────────────────────────────────────────────────
    "http.request": ActionSpec(
        required=("method", "path"),
        optional=("body", "raw_body", "query", "headers", "auth", "save_as", "base"),
        doc="Gọi HTTP. `save_as` lưu response để bước sau dùng lại. "
            "`raw_body` gửi chuỗi thô — dùng để test body hỏng (JSON không hợp lệ). "
            "`base` ghi đè địa chỉ gốc, dùng khi operation thuộc service khác "
            "(spec khai `servers` ở cấp operation).",
    ),
    "ui.goto": ActionSpec(required=("url",), doc="Mở một URL."),
    "ui.session": ActionSpec(
        required=("mode",),
        optional=("as",),
        doc="Đặt phiên trình duyệt: `anonymous` xoá sạch cookie/storage để kiểm "
            "hành vi người dùng chưa đăng nhập; `authenticated` nạp lại phiên đã lưu. "
            "Đây là thứ cho phép test login/redirect/route guard — nếu trình duyệt "
            "vốn đã đăng nhập thì mọi case về màn hình login đều vô nghĩa.",
    ),
    # `by_name` là nhãn hiển thị mà mapper tra được từ UI map; `target` vẫn bắt
    # buộc để case cũ và case viết tay không đổi. Trước đây mapper sinh `by_name`
    # nhưng ACTION_SPECS không khai ⇒ `validate_batch` chạy sau mapper là chặn
    # sạch các bước vừa map (validator chỉ chạy trước mapper nên lỗi bị che).
    "ui.click": ActionSpec(
        required=("target",),
        optional=("by_name",),
        doc="Bấm element theo nhãn trong UI map.",
    ),
    "ui.fill": ActionSpec(
        required=("target", "value"),
        optional=("by_name",),
        doc="Điền giá trị vào ô nhập.",
    ),
    "ui.select": ActionSpec(
        required=("target", "value"),
        optional=("by_name",),
        doc="Chọn trong dropdown.",
    ),
    "ui.hover": ActionSpec(
        required=("target",),
        optional=("by_name",),
        doc="Đưa chuột lên element — kiểm menu/tooltip chỉ hiện khi hover.",
    ),
    "ui.press": ActionSpec(
        required=("key",),
        optional=("target",),
        doc="Gõ một phím (`Enter`, `Escape`, `Tab`…) — bàn phím là đường đi "
            "mà người dùng bàn phím thật sự dùng, và nhiều bug chỉ hiện ở đó.",
    ),
    "ui.check": ActionSpec(
        required=("target",),
        optional=("by_name", "checked"),
        doc="Tick/bỏ tick checkbox. `checked: false` để bỏ tick.",
    ),
    "ui.scroll": ActionSpec(
        required=(),
        optional=("target", "direction", "px"),
        doc="Cuộn trang (`direction: up|down|top|bottom`) hoặc cuộn tới element. "
            "Cần thiết để bắt lỗi sticky header che mất nội dung, hoặc nút chỉ "
            "hiện sau khi cuộn.",
    ),
    "ui.wait_for": ActionSpec(
        required=("target",),
        optional=("by_name", "state", "timeout_ms"),
        doc="Chờ element đạt trạng thái (`visible` mặc định, `hidden`, "
            "`attached`). Auto-wait của Playwright lo phần lớn trường hợp; "
            "verb này dành cho thứ hiện **sau** một sự kiện khác (upload xong, "
            "websocket đẩy về).",
    ),
    "db.query": ActionSpec(
        required=("sql",), optional=("save_as",), doc="Chạy truy vấn, lưu kết quả."
    ),
    "cli.run": ActionSpec(required=("command",), optional=("save_as",)),
    "wait": ActionSpec(
        required=("seconds",), optional=("reason",), doc="Chờ. Kèm lý do để không thành mánh vá flake."
    ),

    # ── Kiểm tra ────────────────────────────────────────────────────────────
    "assert.http_status": ActionSpec(required=("expected",), optional=("source",)),
    "assert.json_field": ActionSpec(
        required=("path", "expected"),
        optional=("operator", "source"),
        doc="So một field trong JSON. `path` dạng `$.a.b`.",
    ),
    "assert.json_schema": ActionSpec(
        required=("required",), optional=("types", "source"),
        doc="Kiểm tra có đủ field bắt buộc và đúng kiểu.",
    ),
    "assert.contains": ActionSpec(required=("actual", "expected")),
    "assert.not_contains": ActionSpec(required=("actual", "expected")),
    "assert.equals": ActionSpec(required=("actual", "expected")),
    "assert.visible": ActionSpec(
        required=("target",),
        optional=("by_name",),
        doc="Element có hiện trên UI không.",
    ),
    "assert.not_visible": ActionSpec(
        required=("target",), optional=("by_name",)
    ),
    # ── Kiểm tra UI/UX — auto-wait, chống flake ─────────────────────────────
    # Nhóm này dùng `expect()` của Playwright: tự chờ tới khi điều kiện đúng
    # hoặc hết timeout, thay vì đọc DOM một lần rồi kết luận. Đọc-một-lần là
    # nguồn flake số một của UI test: trang SPA chưa render xong thì mọi
    # assertion đều sai, nhưng sai một cách ngẫu nhiên.
    "assert.enabled": ActionSpec(
        required=("target",),
        optional=("by_name",),
        doc="Element không ở trạng thái disabled. Bắt lỗi nút bị khoá do "
            "thiếu quyền/dữ liệu — bug UX hay gặp và hay bị bỏ sót.",
    ),
    "assert.disabled": ActionSpec(
        required=("target",),
        optional=("by_name",),
        doc="Element đang bị vô hiệu hoá — ví dụ nút 'Đăng nhập' khi chưa "
            "nhập gì, hoặc khi `ssoBusy`.",
    ),
    "assert.text": ActionSpec(
        required=("target", "expected"),
        optional=("by_name", "exact", "operator"),
        doc="Chữ hiển thị của element. `operator`: `contains` (mặc định), "
            "`eq`, `matches` (regex).",
    ),
    "assert.value": ActionSpec(
        required=("target", "expected"),
        optional=("by_name", "operator"),
        doc="Giá trị trong ô nhập — kiểm form giữ/xoá giá trị đúng sau thao tác.",
    ),
    "assert.attr": ActionSpec(
        required=("target", "name", "expected"),
        optional=("by_name", "operator"),
        doc="Thuộc tính HTML (`href`, `aria-disabled`, `data-state`…). Nhiều "
            "hành vi chỉ nằm ở attribute chứ không ở chữ hiển thị.",
    ),
    "assert.count": ActionSpec(
        required=("target", "expected"),
        optional=("by_name", "operator"),
        doc="Số element khớp nhãn. Dùng cho danh sách: 0 kết quả, 5 dòng bảng, "
            "đúng 1 thông báo lỗi…",
    ),
    "assert.focused": ActionSpec(
        required=("target",),
        optional=("by_name",),
        doc="Element đang được focus — kiểm accessibility cơ bản: mở form thì "
            "con trỏ phải nằm ở ô đầu tiên.",
    ),
    "assert.checked": ActionSpec(
        required=("target",),
        optional=("by_name", "expected"),
        doc="Checkbox/radio đang tick (`expected: false` để kiểm chưa tick).",
    ),
    "assert.console_clean": ActionSpec(
        required=(),
        optional=("forbidden", "max_errors"),
        doc="Không có lỗi JS (`console.error` / `pageerror`) tích luỹ trong "
            "lượt chạy này. Đây là cách kiểm NFR «không lộ stack trace ra UI» "
            "và «không có lỗi JS khi thao tác».",
    ),
    "assert.no_broken_requests": ActionSpec(
        required=(),
        optional=("allow", "max_errors"),
        doc="Không có request nào trả ≥400 ngoài danh sách `allow` (regex). "
            "Bắt lỗi gọi API sai đường dẫn / 500 ẩn sau một màn hình trông "
            "vẫn bình thường.",
    ),
    "assert.screenshot": ActionSpec(
        required=("name",),
        optional=("full_page",),
        doc="Lưu ảnh làm bằng chứng cho case này (kể cả khi case đạt).",
    ),
    "assert.axe": ActionSpec(
        required=(),
        optional=("severity", "tags", "max_violations"),
        doc="Quét accessibility bằng axe-core. `severity`: `serious` (mặc "
            "định, bỏ qua lỗi nhẹ), `critical`, `all`.",
    ),
    "assert.url_matches": ActionSpec(
        required=("pattern",), doc="URL hiện tại khớp mẫu (regex)."
    ),
    "assert.db_row": ActionSpec(required=("table", "where", "expected")),
    "assert.response_time": ActionSpec(
        required=("max_ms",),
        optional=("source", "percentile", "samples"),
        doc="Thời gian phản hồi dưới ngưỡng. Dùng cho NFR hiệu năng. "
            "`percentile` (mặc định 95) và `samples`: ngưỡng p95 phải đo bằng "
            "p95 của nhiều lần gọi, không phải một lần gọi.",
    ),
    "assert.text_matches": ActionSpec(required=("actual", "pattern")),

    # ── Chờ map sang hành động cụ thể ───────────────────────────────────────
    # Acceptance criterion trong tài liệu thường viết bằng văn xuôi, không nêu
    # endpoint hay element. Hai verb dưới đây giữ nguyên văn xuôi đó thay vì
    # đoán bừa — và executor sẽ báo `Blocked: chưa map` thay vì chạy sai.
    #
    # Đặt tên trung tính (`perform.unmapped`) chứ không phải `ui.perform`:
    # "Router guard chạy" không phải hành động UI, và gọi nó là UI sẽ là nói dối.
    "perform.unmapped": ActionSpec(
        required=("description",),
        optional=("expectation",),
        doc="Hành động mô tả bằng văn xuôi, CHƯA map sang hành động cụ thể. Cần người map.",
    ),
    "assert.unmapped": ActionSpec(
        required=("expected",),
        doc="Kỳ vọng viết bằng văn xuôi. Chưa kiểm tra tự động được — cần map.",
    ),
}

ACTION_VERBS = frozenset(ACTION_SPECS)

# ── Ngưỡng hiệu năng ────────────────────────────────────────────────────────
# Tài liệu viết `p95 < 100ms` — đó là **phân vị**, không phải "mọi lần gọi đều
# dưới ngưỡng". Yêu cầu cho phép 5% số lần gọi vượt ngưỡng. Đo một lần gọi rồi
# so với ngưỡng p95 là kiểm chặt hơn yêu cầu, và đã báo `Fail` sai thật trên
# portal (`/auth/config`: một mẫu 162ms, nhưng p95 của 30 mẫu là 84ms).
#
# Vì vậy bước kiểm phải lấy nhiều mẫu. 20 mẫu: p95 rơi vào mẫu lớn nhất, đủ để
# một lần chậm bất thường không kéo cả kết luận, mà vẫn nhanh. Đây là kiểm tra
# hồi quy, không phải đo tải.
PERF_SAMPLES = 20
PERF_DEFAULT_PERCENTILE = 95.0


def percentile_of(text: str) -> float:
    """Phân vị tài liệu nói tới (`p95`, `p99`); không nêu thì mặc định p95."""
    m = re.search(r"\bp(\d{1,2})\b", text or "", re.I)
    if m:
        value = float(m.group(1))
        if 50 <= value <= 100:
            return value
    return PERF_DEFAULT_PERCENTILE

_OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "matches", "exists"}


class ValidationError(Exception):
    """Testcase không hợp lệ. Nêu rõ chỗ sai, đừng chỉ nói 'invalid'."""


@dataclass
class Step:
    seq: int
    kind: StepKind
    action: str
    args: dict = field(default_factory=dict)
    note: str = ""

    def validate(self) -> None:
        if self.action not in ACTION_SPECS:
            close = _closest(self.action, ACTION_VERBS)
            hint = f" Có phải anh muốn `{close}`?" if close else ""
            raise ValidationError(
                f"Bước {self.seq}: verb `{self.action}` không có trong vocabulary đóng.{hint} "
                f"Verb hợp lệ: {', '.join(sorted(ACTION_VERBS))}"
            )
        spec = ACTION_SPECS[self.action]
        missing = [a for a in spec.required if a not in self.args or self.args[a] in (None, "")]
        if missing:
            raise ValidationError(
                f"Bước {self.seq} (`{self.action}`): thiếu tham số bắt buộc {missing}. "
                f"Bắt buộc: {list(spec.required)}, tuỳ chọn: {list(spec.optional)}"
            )
        unknown = set(self.args) - set(spec.required) - set(spec.optional)
        if unknown:
            raise ValidationError(
                f"Bước {self.seq} (`{self.action}`): tham số lạ {sorted(unknown)}. "
                f"Cho phép: {sorted(set(spec.required) | set(spec.optional))}"
            )
        if "operator" in self.args and self.args["operator"] not in _OPERATORS:
            raise ValidationError(
                f"Bước {self.seq}: operator `{self.args['operator']}` không hợp lệ. "
                f"Cho phép: {sorted(_OPERATORS)}"
            )

    def to_dict(self) -> dict:
        out = {"seq": self.seq, "kind": self.kind.value, "action": self.action}
        if self.args:
            out["args"] = self.args
        if self.note:
            out["note"] = self.note
        return out

    def _label(self) -> str:
        """Nhãn người đọc cho element — ưu tiên nhãn trong UI map."""
        return self.args.get("by_name") or self.args.get("target", "")

    def describe(self) -> str:
        """Một dòng người đọc được — để render vào cột `Test Steps`.

        Cột này là chỗ **người QC đọc để làm theo**. Không được lộ cấu trúc nội
        bộ (`perform.unmapped:`, `description=`) ra đây: với case thủ công, đó là
        toàn bộ nội dung người đọc có.
        """
        spec = ACTION_SPECS.get(self.action)
        if self.action == "http.request":
            method = self.args.get("method", "GET")
            path = self.args.get("path", "")
            extra = ""
            if self.args.get("query"):
                extra = "?" + "&".join(f"{k}={v}" for k, v in self.args["query"].items())
            if self.args.get("raw_body") is not None:
                body = f" raw_body={self.args['raw_body']!r}"
            elif self.args.get("body"):
                body = f" body={json.dumps(self.args['body'], ensure_ascii=False)}"
            else:
                body = ""
            base = self.args.get("base")
            where = f"{base}{path}" if base else path
            return f"Gọi {method} {where}{extra}{body}"
        if self.action == "assert.url_matches":
            return f"URL hiện tại khớp «{self.args.get('pattern')}»"
        if self.action == "assert.visible":
            name = self.args.get("by_name") or self.args.get("target", "")
            return f"«{name}» hiện trên màn hình"
        if self.action == "assert.not_visible":
            name = self.args.get("by_name") or self.args.get("target", "")
            return f"«{name}» KHÔNG hiện trên màn hình"
        if self.action == "perform.unmapped":
            description = self.args.get("description", "")
            expectation = self.args.get("expectation", "")
            if expectation and expectation not in description:
                return f"{description} → {expectation}"
            return description
        if self.action == "assert.unmapped":
            return f"Kiểm tra: {self.args.get('expected', '')}"
        # Bước UI cũng phải đọc được như câu, không phải `ui.click: target=sign_in`.
        # Case luồng trộn cả bước map được lẫn bước văn xuôi; nếu chỉ sửa phần văn
        # xuôi thì người đọc vẫn gặp cú pháp máy ở giữa các bước.
        if self.action == "ui.goto":
            return f"Mở {self.args.get('url', '')}"
        if self.action == "ui.session":
            mode = self.args.get("mode")
            if mode == "anonymous":
                return "Xoá phiên đăng nhập (chạy như người dùng chưa đăng nhập)"
            return "Nạp lại phiên đã đăng nhập"
        if self.action == "ui.click":
            name = self.args.get("by_name") or self.args.get("target", "")
            return f"Bấm «{name}»"
        if self.action == "ui.fill":
            name = self.args.get("by_name") or self.args.get("target", "")
            return f"Nhập «{self.args.get('value', '')}» vào «{name}»"
        if self.action == "ui.select":
            name = self.args.get("by_name") or self.args.get("target", "")
            return f"Chọn «{self.args.get('value', '')}» trong «{name}»"
        if self.action == "ui.hover":
            name = self.args.get("by_name") or self.args.get("target", "")
            return f"Đưa chuột lên «{name}»"
        if self.action == "ui.press":
            target = self.args.get("target")
            where = f"«{self.args.get('by_name') or target}»" if target else "trang"
            return f"Gõ phím {self.args.get('key')} ở {where}"
        if self.action == "ui.check":
            name = self.args.get("by_name") or self.args.get("target", "")
            action = "Bỏ tick" if self.args.get("checked") is False else "Tick"
            return f"{action} «{name}»"
        if self.action == "ui.scroll":
            name = self.args.get("by_name") or self.args.get("target")
            if name:
                return f"Cuộn tới «{name}»"
            where = {"up": "lên trên", "down": "xuống dưới",
                     "top": "lên đầu trang", "bottom": "xuống cuối trang"}.get(
                         self.args.get("direction", "down"), "xuống dưới")
            px = self.args.get("px")
            return f"Cuộn {where}" + (f" {px}px" if px else "")
        if self.action == "ui.wait_for":
            name = self.args.get("by_name") or self.args.get("target", "")
            state = {"hidden": "biến mất", "attached": "có trong trang",
                     "visible": "hiện ra"}.get(self.args.get("state", "visible"), "hiện ra")
            return f"Chờ «{name}» {state}"
        # Nhóm kiểm tra UI/UX — đọc như câu, không phơi tên tham số.
        if self.action == "assert.enabled":
            return f"«{self._label()}» bấm được (không bị vô hiệu hoá)"
        if self.action == "assert.disabled":
            return f"«{self._label()}» đang bị vô hiệu hoá"
        if self.action == "assert.text":
            return f"«{self._label()}» hiển thị {_op_word(self.args)} «{self.args.get('expected')}»"
        if self.action == "assert.value":
            return (f"Ô «{self._label()}» có giá trị {_op_word(self.args)} "
                    f"«{self.args.get('expected')}»")
        if self.action == "assert.attr":
            return (f"«{self._label()}» có thuộc tính {self.args.get('name')} "
                    f"{_op_word(self.args)} «{self.args.get('expected')}»")
        if self.action == "assert.count":
            return (f"«{self._label()}»: có {self.args.get('expected')} element "
                    f"trên màn hình")
        if self.action == "assert.focused":
            return f"«{self._label()}» đang được focus"
        if self.action == "assert.checked":
            word = "đã được tick" if self.args.get("expected", True) else "chưa được tick"
            return f"«{self._label()}» {word}"
        if self.action == "assert.console_clean":
            return "Không có lỗi JavaScript nào trong lượt chạy này"
        if self.action == "assert.no_broken_requests":
            return "Không có request nào trả lỗi (≥400) khi thao tác"
        if self.action == "assert.screenshot":
            return f"Ảnh bằng chứng «{self.args.get('name')}» được lưu"
        if self.action == "assert.axe":
            return (f"Không có lỗi accessibility mức "
                    f"«{self.args.get('severity', 'serious')}» trở lên")
        if self.action.startswith("assert."):
            pretty = ", ".join(f"{k}={v}" for k, v in self.args.items() if k != "source")
            return f"Kiểm tra {self.action.removeprefix('assert.')}: {pretty}"
        if spec is None:
            return f"{self.action}({self.args})"
        pretty = ", ".join(f"{k}={v}" for k, v in self.args.items())
        return f"{self.action}: {pretty}"

    def expects(self) -> str:
        """Diễn giải kỳ vọng — để render vào cột `Expected Result`."""
        a = self.args
        match self.action:
            case "assert.http_status":
                return f"Hệ thống trả về HTTP {a.get('expected')}"
            case "assert.json_field":
                op = a.get("operator", "eq")
                word = {"eq": "bằng", "ne": "khác", "gt": "lớn hơn", "gte": "lớn hơn hoặc bằng",
                        "lt": "nhỏ hơn", "lte": "nhỏ hơn hoặc bằng", "in": "thuộc",
                        "not_in": "không thuộc", "matches": "khớp mẫu", "exists": "tồn tại"}.get(op, op)
                return f"Field `{a.get('path')}` {word} {a.get('expected')!r}"
            case "assert.json_schema":
                return f"Response có đủ field bắt buộc: {', '.join(a.get('required', []))}"
            case "assert.response_time":
                pct = a.get("percentile", 95)
                n = a.get("samples", 1)
                if n > 1:
                    return (f"Phân vị p{pct:g} thời gian phản hồi dưới "
                            f"{a.get('max_ms')}ms (qua {n} lần gọi)")
                return f"Thời gian phản hồi dưới {a.get('max_ms')}ms"
            case "assert.contains":
                return f"Nội dung có chứa {a.get('expected')!r}"
            case "assert.not_contains":
                return f"Nội dung KHÔNG chứa {a.get('expected')!r}"
            case "assert.equals":
                return f"Giá trị bằng {a.get('expected')!r}"
            case "assert.visible":
                return f"`{a.get('target')}` hiện trên màn hình"
            case "assert.not_visible":
                return f"`{a.get('target')}` KHÔNG hiện trên màn hình"
            case "assert.enabled":
                return f"`{a.get('target')}` bấm được, không bị vô hiệu hoá"
            case "assert.disabled":
                return f"`{a.get('target')}` đang bị vô hiệu hoá"
            case "assert.text":
                return (f"`{a.get('target')}` hiển thị {_op_word(a)} "
                        f"{a.get('expected')!r}")
            case "assert.value":
                return f"`{a.get('target')}` có giá trị {_op_word(a)} {a.get('expected')!r}"
            case "assert.attr":
                return (f"`{a.get('target')}` có `{a.get('name')}` {_op_word(a)} "
                        f"{a.get('expected')!r}")
            case "assert.count":
                return (f"Có {a.get('expected')} element khớp "
                        f"`{a.get('target')}` trên màn hình")
            case "assert.focused":
                return f"`{a.get('target')}` đang được focus"
            case "assert.checked":
                return ("`%s` đã được tick" % a.get("target") if a.get("expected", True)
                        else "`%s` chưa được tick" % a.get("target"))
            case "assert.console_clean":
                return "Không có lỗi JavaScript (console.error / pageerror)"
            case "assert.no_broken_requests":
                return "Không có request nào trả về mã lỗi ≥400"
            case "assert.screenshot":
                return f"Đã lưu ảnh bằng chứng `{a.get('name')}`"
            case "assert.axe":
                return (f"Không có vi phạm accessibility mức "
                        f"`{a.get('severity', 'serious')}` trở lên")
            case "assert.url_matches":
                return f"URL hiện tại khớp `{a.get('pattern')}`"
            case "assert.db_row":
                return f"Dòng trong `{a.get('table')}` khớp {a.get('where')} có {a.get('expected')}"
            case "assert.unmapped":
                return f"{a.get('expected')}"
            case "perform.unmapped":
                # Bước văn xuôi: in thẳng câu của tài liệu. Không thêm tiền tố máy
                # móc (`perform.unmapped:`, `(chưa map)`) — cột Test Steps là chỗ
                # người QC đọc để làm theo, không phải chỗ phơi cấu trúc nội bộ.
                description = a.get("description", "")
                expectation = a.get("expectation", "")
                if expectation and expectation not in description:
                    return f"{description} → {expectation}"
                return description
            case _:
                return self.describe()


def _op_word(args: dict) -> str:
    """Diễn giải `operator` thành chữ Việt — để cột Expected Result đọc được."""
    op = args.get("operator", "contains")
    if args.get("exact") and op == "contains":
        op = "eq"
    return {"contains": "có chứa", "eq": "bằng", "ne": "khác",
            "matches": "khớp mẫu", "gte": "≥", "lte": "≤",
            "has": "có", "not_has": "không có"}.get(op, op)


def _closest(word: str, candidates: frozenset[str]) -> str | None:
    """Gợi ý verb gần giống — giúp sửa lỗi chính tả nhanh."""
    def distance(a: str, b: str) -> int:
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
            prev = cur
        return prev[-1]

    best = min(candidates, key=lambda c: distance(word.lower(), c.lower()))
    return best if distance(word.lower(), best.lower()) <= 4 else None


@dataclass
class TestCase:
    """Một testcase. Tên class tránh bị pytest thu thập nhầm (xem `__test__`)."""

    __test__ = False

    id: str
    module: str
    title: str
    objective: str
    steps: list[Step] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    test_data: dict = field(default_factory=dict)
    priority: Priority = Priority.MEDIUM
    case_type: CaseType = CaseType.POSITIVE
    technique: Technique = Technique.SCHEMA_CONFORMANCE
    # traceability — bắt buộc, không có thì case là orphan
    traces_to: list[str] = field(default_factory=list)
    # điều kiện môi trường mà tool không tự tạo được (tài khoản thiếu quyền, dữ
    # liệu gây xung đột…). Có giá trị ⇒ runner báo `Blocked`, KHÔNG báo `Fail`,
    # vì thất bại là do thiếu môi trường test chứ không phải sản phẩm có bug.
    requires: str | None = None
    # nguồn gốc — trả lời được câu "sao lại có case này?"
    source_quote: str = ""
    source_ref: str = ""
    generated_by: str = "engine"        # engine | llm
    # `auto` — tool chạy được. `manual` — có bước mà máy không tự làm được (bấm
    # trên UI chưa map, nhập OTP, thao tác nhiều vai trò…), người phải làm theo
    # các bước ghi trong case.
    #
    # Phân biệt với `requires`: `requires` là thiếu ĐIỀU KIỆN môi trường (tài khoản
    # không quyền, dữ liệu chưa có) → `Blocked`. `manual` là case **vẫn hợp lệ và
    # vẫn chạy được**, chỉ là do người chạy → `Not Executed` trong lượt tự động.
    # Gộp hai thứ này làm một sẽ đẩy case thủ công vào `Blocked`, làm báo cáo mất
    # đúng nhóm việc mà QC cần làm tay.
    execution: str = "auto"
    # kết quả chạy — điền ở chặng execute, không phải lúc sinh
    status: str | None = None
    actual: list[str] = field(default_factory=list)
    environment: str | None = None
    executed_by: str | None = None
    executed_at: str | None = None
    created_by: str | None = None
    created_at: str | None = None

    def validate(self) -> None:
        if not self.id:
            raise ValidationError("Testcase thiếu `id`")
        # `[A-Z0-9_]+` chứ không phải `[A-Z0-9]+`: tên feature nhiều từ (`login-sso`
        # → `LOGIN_SSO`) sinh ra module có dấu gạch, và regex cũ chặn oan chúng.
        # Chặn ở đây không phải để bắt lỗi sản phẩm mà để bắt lỗi đặt tên — báo
        # động sai làm người dùng tưởng tool hỏng.
        if not re.match(r"^TC_[A-Z0-9_]+_\d{3}$", self.id):
            raise ValidationError(
                f"`{self.id}` sai quy ước. Phải là `TC_<MODULE>_<NNN>`, "
                "ví dụ `TC_AUTH_001` hoặc `TC_LOGIN_SSO_001`"
            )
        if not self.traces_to:
            raise ValidationError(
                f"`{self.id}` không trace về requirement nào — case orphan. "
                "Mọi testcase phải trả lời được 'sinh ra để kiểm cái gì?'"
            )
        if not self.steps:
            raise ValidationError(f"`{self.id}` không có bước nào")
        for step in self.steps:
            step.validate()
        if not any(s.action.startswith("assert.") for s in self.steps):
            raise ValidationError(
                f"`{self.id}` không có bước kiểm tra nào (`assert.*`). "
                "Một testcase không kiểm gì cả thì không phải testcase."
            )
        if not self.source_quote:
            raise ValidationError(
                f"`{self.id}` thiếu `source_quote` — không truy được về câu nào trong tài liệu"
            )
        if self.needs_mapping and self.status == "Pass":
            raise ValidationError(
                f"`{self.id}` còn bước chưa map (`{'`, `'.join(self.UNMAPPED_ACTIONS)}`) "
                "nhưng đang được đánh dấu Pass. Case chưa map chỉ được ở trạng thái "
                "`Not Executed` hoặc `Blocked`."
            )
        if self.execution == "manual" and self.status == "Pass":
            raise ValidationError(
                f"`{self.id}` là case THỦ CÔNG nhưng đang được đánh dấu Pass. "
                "Lượt chạy tự động không chạm vào case này, nên nó không thể tự "
                "nhiên đạt. Người chạy phải điền kết quả bằng tay."
            )

    @property
    def expected(self) -> list[str]:
        return [s.expects() for s in self.steps if s.action.startswith("assert.")]

    UNMAPPED_ACTIONS = frozenset({"perform.unmapped", "assert.unmapped"})

    @property
    def needs_mapping(self) -> bool:
        """Case này còn bước chưa map sang hành động cụ thể hay không.

        Case sinh từ acceptance criterion thường ở trạng thái này: tài liệu nói
        *"sidebar chỉ hiện module tôi được phép"* nhưng không nói element nào.
        Tool giữ nguyên văn xuôi và đánh dấu — trung thực hơn là đoán ra một
        selector rồi chạy sai mà không ai biết.
        """
        return any(s.action in self.UNMAPPED_ACTIONS for s in self.steps)

    def steps_text(self) -> str:
        actions = [s for s in self.steps if not s.action.startswith("assert.")]
        # Case thủ công: bước `assert.unmapped` chính là một bước người phải làm
        # ("Kiểm tra: màn hình hiện thông báo X"). Bỏ nó đi thì người đọc không
        # biết phải xác nhận cái gì.
        if self.execution == "manual":
            actions = [s for s in self.steps if s.action != "assert.unmapped"] + [
                s for s in self.steps if s.action == "assert.unmapped"
            ]
        return "\n".join(f"{i}. {s.describe()}" for i, s in enumerate(actions, 1))

    def expected_text(self) -> str:
        items = self.expected
        if self.execution == "manual":
            # Kỳ vọng đã nằm trong cột Test Steps dưới dạng bước kiểm tra, nên
            # không lặp lại ở đây. Cột Expected Result để trống cho người chạy
            # ghi kết quả — đúng như template quy định.
            items = [s.expects() for s in self.steps if s.action == "assert.unmapped"]
            return "\n".join(items)
        return "\n".join(f"{i}. {e}" for i, e in enumerate(items, 1))

    @property
    def content_hash(self) -> str:
        """Vân tay nội dung — KHÔNG gồm `id`.

        Cố ý bỏ `id` ra: hai testcase có cùng bước và cùng kỳ vọng nhưng khác ID
        **là trùng nhau**, và validator cần phát hiện được. Nếu tính cả `id` thì
        mọi cặp đều khác hash và việc kiểm trùng trở nên vô nghĩa.
        """
        payload = {
            "module": self.module,
            "title": self.title,
            "traces_to": self.traces_to,
            "steps": [s.to_dict() for s in self.steps],
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        out = {
            "id": self.id,
            "module": self.module,
            "title": self.title,
            "objective": self.objective,
            "priority": self.priority.value,
            "type": self.case_type.value,
            "technique": self.technique.value,
            "traces_to": self.traces_to,
            "generated_by": self.generated_by,
        }
        if self.execution != "auto":
            out["execution"] = self.execution
        if self.preconditions:
            out["preconditions"] = self.preconditions
        if self.requires:
            out["requires"] = self.requires
        if self.test_data:
            out["test_data"] = self.test_data
        out["steps"] = [s.to_dict() for s in self.steps]
        out["expected"] = self.expected
        out["content_hash"] = self.content_hash
        out["provenance"] = {"source_quote": self.source_quote, "source_ref": self.source_ref}
        for key in ("status", "actual", "environment", "executed_by", "executed_at",
                    "created_by", "created_at"):
            value = getattr(self, key)
            if value:
                out[key] = value
        return out

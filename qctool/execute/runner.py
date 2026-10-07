"""Chặng 3 — Execute: chạy testcase thật.

Đây là chặng biến tool từ "máy sinh testcase" thành "tool QC". Không có nó thì
output chỉ là tài liệu.

Runner chạy từng case theo đúng thứ tự bước, ghi lại kết quả thật, và **không
bao giờ nói dối**: case không chạy được thì ghi `Blocked` kèm lý do, không ghi
`Pass` cho xong.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import math
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime

from ..testcase import TestCase
from ..test_fixtures import FixtureStore, FixtureUnavailable, REGISTRY, is_alias
from .browser import NeedsEnvironment, NeedsLogin

# User-Agent tự khai tên tool. KHÔNG để mặc định của thư viện chuẩn.
#
# `urllib` mặc định gửi `Python-urllib/3.x`, và môi trường dev của portal chặn
# UA đó bằng 403. Hậu quả: **mọi** request đều 403, kể cả endpoint public —
# 17 testcase báo `Fail` trong khi sản phẩm hoàn toàn bình thường.
#
# Đây là loại báo động giả tệ nhất: nó trông y như bug thật.
USER_AGENT = "qc-tool/0.0.1 (automated QC; +https://github.com/vindynamics/qc-tool)"

STATUS_PASS = "Pass"
STATUS_FAIL = "Fail"
STATUS_BLOCKED = "Blocked"
STATUS_NOT_EXECUTED = "Not Executed"

# Verb chạy trên trình duyệt. Danh sách này phải khớp với `_run_ui_step` — thêm
# verb UI mà quên khai ở đây thì case chạy nhưng báo "chưa mở trình duyệt".
UI_VERBS = frozenset({
    "ui.goto", "ui.session", "ui.click", "ui.fill", "ui.select", "ui.hover",
    "ui.press", "ui.check", "ui.scroll", "ui.wait_for",
    "assert.url_matches", "assert.visible", "assert.not_visible",
    "assert.enabled", "assert.disabled", "assert.text", "assert.value",
    "assert.attr", "assert.count", "assert.focused", "assert.checked",
    "assert.console_clean", "assert.no_broken_requests", "assert.axe",
    "assert.screenshot",
})

# Bước UI không nằm trong danh sách này thì mặc định là bước kiểm tra (soft).
UI_ASSERT_VERBS = frozenset(v for v in UI_VERBS if v.startswith("assert."))


def needs_browser(cases: list[TestCase]) -> bool:
    """Lượt chạy này có bước nào cần trình duyệt không.

    Trước đây là hai danh sách cứng chép ở `runner` và `pipeline`, nên thêm verb
    UI là phải nhớ sửa cả hai chỗ. Giờ chỉ còn một chỗ.
    """
    return any(step.action in UI_VERBS for case in cases for step in case.steps)


@dataclass
class StepResult:
    seq: int
    action: str
    ok: bool
    detail: str
    duration_ms: float = 0.0
    issue_code: str | None = None

    def to_dict(self) -> dict:
        result = {"seq": self.seq, "action": self.action, "ok": self.ok,
                  "detail": self.detail, "duration_ms": round(self.duration_ms, 1)}
        if self.issue_code:
            result["issue_code"] = self.issue_code
        return result


@dataclass
class CaseResult:
    case_id: str
    title: str
    module: str
    status: str
    actual: list[str] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)
    blocked_reason: str | None = None
    duration_ms: float = 0.0
    # Số bước của testcase, lấy lúc sinh. `steps` ở trên rỗng với case thủ công
    # (chưa chạy bước nào), nên báo cáo cần con số này để nói người đọc phải làm
    # bao nhiêu việc — nếu không sẽ hiển thị "0 bước" và trông như case rỗng.
    step_count: int = 0
    manual: bool = False
    # Kết quả các lần chạy lại. Rỗng nghĩa là case ổn định ngay lần đầu.
    attempts: list[str] = field(default_factory=list)
    # `True` khi case chỉ đạt ở lần chạy lại — tức là **chập chờn**, không phải
    # đạt. Báo cáo phải nói riêng nhóm này: một case lúc được lúc không là bug
    # (của sản phẩm hoặc của test), không phải bằng chứng chất lượng.
    flaky: bool = False
    evidence: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_PASS

    def to_dict(self) -> dict:
        out = {
            "case_id": self.case_id,
            "module": self.module,
            "title": self.title,
            "status": self.status,
            "actual": self.actual,
            "duration_ms": round(self.duration_ms, 1),
            "steps": [s.to_dict() for s in self.steps],
        }
        if self.step_count:
            out["step_count"] = self.step_count
        if self.manual:
            out["manual"] = True
        if self.blocked_reason:
            out["blocked_reason"] = self.blocked_reason
        if self.attempts:
            out["attempts"] = self.attempts
        if self.flaky:
            out["flaky"] = True
        if self.evidence:
            out["evidence"] = self.evidence
        return out


@dataclass
class RunResult:
    started_at: str
    finished_at: str
    base_url: str
    cases: list[CaseResult] = field(default_factory=list)
    environment: str = ""

    @property
    def counts(self) -> dict[str, int]:
        out = {STATUS_PASS: 0, STATUS_FAIL: 0, STATUS_BLOCKED: 0, STATUS_NOT_EXECUTED: 0}
        for case in self.cases:
            out[case.status] = out.get(case.status, 0) + 1
        return out

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def flaky_cases(self) -> list[CaseResult]:
        return [c for c in self.cases if c.flaky]

    @property
    def pass_rate(self) -> float:
        executed = self.counts[STATUS_PASS] + self.counts[STATUS_FAIL]
        return (self.counts[STATUS_PASS] / executed * 100) if executed else 0.0

    def by_module(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for case in self.cases:
            bucket = out.setdefault(case.module, {
                STATUS_PASS: 0, STATUS_FAIL: 0, STATUS_BLOCKED: 0, STATUS_NOT_EXECUTED: 0,
            })
            bucket[case.status] = bucket.get(case.status, 0) + 1
        return out

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "base_url": self.base_url,
            "environment": self.environment,
            "summary": {"total": self.total, **self.counts,
                        "pass_rate": round(self.pass_rate, 1)},
            "results": [c.to_dict() for c in self.cases],
        }


class HttpSession:
    """Client HTTP tối giản. Dùng thư viện chuẩn để không thêm phụ thuộc."""

    def __init__(self, base_url: str, bearer_token: str | None = None,
                 timeout: int = 30, verify_ssl: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.bearer_token = bearer_token
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        # Kết nối giữ lại giữa các request (`Connection: keep-alive`). **Không
        # phải để chạy nhanh hơn** mà để số đo có nghĩa: mở kết nối mới cho mỗi
        # request tốn thêm một lần bắt tay TCP+TLS, đo được 109ms trên môi trường
        # dev — lớn hơn cả ngưỡng p95 của NFR hiệu năng. Đo gộp như vậy rồi đem so
        # với ngưỡng là báo lỗi giả: đã gặp thật với `/auth/config p95 < 100ms`.
        self._conn: http.client.HTTPConnection | None = None
        self._conn_key: tuple | None = None

    def _connection(self, scheme: str, host: str, port: int) -> http.client.HTTPConnection:
        """Lấy kết nối đang mở, hoặc mở kết nối mới nếu chưa có / đã hỏng.

        Đổi host giữa hai request (`base` ghi đè) thì phải đóng kết nối cũ —
        dùng lại kết nối của host khác là gửi request sai chỗ.
        """
        key = (scheme, host, port)
        if self._conn is not None and self._conn_key != key:
            self.close()
        if self._conn is None:
            if scheme == "https":
                ctx = ssl.create_default_context()
                if not self.verify_ssl:
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                self._conn = http.client.HTTPSConnection(
                    host, port, timeout=self.timeout, context=ctx)
            else:
                self._conn = http.client.HTTPConnection(host, port, timeout=self.timeout)
            self._conn_key = key
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.close()
            self._conn = None
            self._conn_key = None

    def request(self, method: str, path: str, *, body: dict | None = None,
                raw_body: str | None = None, query: dict | None = None,
                auth: str = "bearer", headers: dict | None = None,
                base: str | None = None) -> dict:
        full = (base.rstrip("/") if base else self.base_url) + path
        if query:
            clean = {k: v for k, v in query.items() if v is not None}
            full += "?" + urllib.parse.urlencode(clean, doseq=True)

        data = None
        head = dict(headers or {})
        # Luôn gửi UA tự khai. Xem chú thích `USER_AGENT` ở đầu file.
        head.setdefault("User-Agent", USER_AGENT)
        if raw_body is not None:
            data = raw_body.encode("utf-8")
            head.setdefault("Content-Type", "application/json")
        elif body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            head.setdefault("Content-Type", "application/json")
        if auth == "bearer" and self.bearer_token:
            head["Authorization"] = f"Bearer {self.bearer_token}"

        parts = urllib.parse.urlsplit(full)
        host = parts.hostname or ""
        port = parts.port or (443 if parts.scheme == "https" else 80)
        target = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))

        started = time.perf_counter()
        try:
            resp = self._send(method, target, data, head, parts.scheme, host, port)
        except Exception as exc:                       # mạng, DNS, timeout…
            elapsed = (time.perf_counter() - started) * 1000
            return {"status": None, "body": None, "raw": "",
                    "duration_ms": elapsed, "error": f"{type(exc).__name__}: {exc}"}

        elapsed = (time.perf_counter() - started) * 1000
        if isinstance(resp, dict):                     # lỗi giao thức đã xử lý
            resp["duration_ms"] = elapsed
            return resp
        status, raw, server_ms = resp
        return {"status": status, "body": _maybe_json(raw), "raw": raw,
                "duration_ms": elapsed, "server_ms": server_ms, "error": None}

    def _send(self, method: str, target: str, data, head: dict,
              scheme: str, host: str, port: int):
        """Gửi một request, tự mở lại kết nối **một lần** nếu kết nối cũ đã chết.

        Server đóng kết nối keep-alive sau một lúc; gặp lúc đó thì `urllib`-style
        là `RemoteDisconnected`. Thử lại trên kết nối mới — nếu không thử lại thì
        một kết nối hết hạn thành "không gọi được API", tức lỗi giả.
        """
        for attempt in (1, 2):
            conn = self._connection(scheme, host, port)
            try:
                conn.request(method.upper(), target, body=data, headers=head)
                resp = conn.getresponse()
                raw = resp.read().decode("utf-8", errors="replace")
                return resp.status, raw, _server_time_ms(resp)
            except (http.client.HTTPException, OSError):
                self.close()                           # kết nối hỏng → bỏ, thử lại
                if attempt == 2:
                    raise
        raise AssertionError("không tới được đây")


def _maybe_json(raw: str):
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _server_time_ms(resp) -> float | None:
    """Thời gian phía server, đọc từ `Server-Timing` nếu server có gửi.

    Tách được "chậm vì mạng/tới nơi" khỏi "chậm vì chính service" — hai loại này
    dẫn tới hai kết luận rất khác nhau về sản phẩm. Không có header thì trả `None`,
    và đó chỉ là mất thông tin thêm, không phải lỗi.

    Với Cloudflare, `cfOrigin;dur=` là thời gian **service gốc** trả lời — đúng
    thứ NFR hiệu năng nói tới. `cfEdge;dur=` là thời gian ở biên, không phải của
    sản phẩm, nên phải chọn đúng chứ không lấy `dur=` đầu tiên gặp được.
    """
    raw = resp.getheader("Server-Timing") or ""
    fields: dict[str, float] = {}
    for part in raw.split(","):
        name, dur = None, None
        for field in part.split(";"):
            field = field.strip()
            if "=" not in field:
                name = name or field
                continue
            key, _, value = field.partition("=")
            if key.strip() == "dur":
                with contextlib.suppress(ValueError):
                    dur = float(value.strip().strip('"'))
        if dur is not None:
            fields[(name or "").strip()] = dur
    for key in ("cfOrigin", "origin"):
        if key in fields:
            return fields[key]
    others = [v for k, v in fields.items() if k != "cfEdge"]
    return others[0] if others else None


def _sample_latency(session: HttpSession, saved: dict, path: str,
                    samples: int) -> tuple[list[float] | None, str]:
    """Gọi lại `path` thêm `samples - 1` lần để đo phân vị thời gian phản hồi.

    Dùng nguyên tham số của lần gọi đầu (method, query, auth, base) — đổi tham số
    là đo một thứ khác với thứ case đang kiểm. Trả `(None, lý do)` nếu bất kỳ lần
    gọi nào lỗi: thà nói "không đủ mẫu" còn hơn ghép một con số từ dữ liệu khuyết.
    """
    args = saved.get("_args") or {}
    durations = [saved["duration_ms"]]
    for _ in range(max(0, samples - 1)):
        resp = session.request(
            args.get("method", "GET"), path,
            body=args.get("body"), raw_body=args.get("raw_body"),
            query=args.get("query"),
            auth=args.get("auth", "bearer"), headers=args.get("headers"),
            base=args.get("base"),
        )
        if resp["error"]:
            return None, resp["error"]
        durations.append(resp["duration_ms"])
    return durations, ""


def _percentile(values: list[float], p: float) -> float:
    """Phân vị thứ `p` (0–100), nội suy tuyến tính giữa hai mẫu kề nhau."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * (p / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return ordered[int(k)]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


# ── Chạy một testcase ────────────────────────────────────────────────────────
def run_case(case: TestCase, session: HttpSession,
             browser: object | None = None, *, retry: int = 0,
             soft_assert: bool = False, fixture_store: FixtureStore | None = None) -> CaseResult:
    """Chạy một case, có thử lại để **tách flake khỏi fail thật**.

    Vì sao retry quan trọng ở đây chứ không phải ở tầng Playwright: một case đạt
    ở lần thử thứ hai **không phải là đạt** — nó là chập chờn, và cả hai khả năng
    (sản phẩm có race condition, hoặc test viết giòn) đều là bug cần người xem.
    Nên lần thử lại không được phép xoá dấu vết: kết quả vẫn `Pass` nhưng mang cờ
    `flaky` và giữ lại lý do của lần hỏng đầu tiên.
    """
    result = _run_once(case, session, browser, soft_assert=soft_assert, fixture_store=fixture_store)
    if retry <= 0 or result.status not in (STATUS_FAIL,):
        return result

    first_detail = "; ".join(result.actual[-2:])
    original_duration = result.duration_ms

    for attempt in range(1, retry + 1):
        again = _run_once(case, session, browser, soft_assert=soft_assert, fixture_store=fixture_store)
        if again.status == STATUS_PASS:
            # Lần đầu hỏng, lần này đạt → chập chờn. Giữ kết quả đạt nhưng ghi rõ.
            again.attempts = result.attempts + [
                f"lần {attempt}: {first_detail}"
            ]
            again.flaky = True
            again.duration_ms += original_duration
            again.actual.insert(
                0,
                f"⚠ CHẬP CHỜN: lần chạy đầu không đạt, lần {attempt} mới đạt. "
                f"Lý do lần đầu: {first_detail}",
            )
            return again

        if again.status == STATUS_BLOCKED:
            # Lần chạy lại KHÔNG chạy được (thiếu đăng nhập, thiếu dữ liệu). Đây
            # không phải "chập chờn" — chập chờn nghĩa là đạt rồi lại không, còn
            # đây là chưa kết luận được gì. Ghi `Blocked` kèm vết của lần hỏng đầu,
            # để người đọc thấy cả hai sự thật.
            again.attempts = result.attempts + [
                f"lần 0: {first_detail}",
                f"lần {attempt}: chưa chạy được — {again.blocked_reason or ''}",
            ]
            again.duration_ms += original_duration
            again.actual.insert(
                0,
                f"Chạy lại lần {attempt} thì không chạy được (thiếu điều kiện), nên "
                f"chưa kết luận được về sản phẩm. Lần đầu hỏng vì: {first_detail}",
            )
            return again

        result.attempts.append(f"lần {attempt}: {'; '.join(again.actual[-2:])}")
        result.duration_ms += again.duration_ms

    result.attempts.insert(0, f"lần 0: {first_detail}")
    result.actual.insert(
        0,
        f"Đã thử lại {retry} lần, lần nào cũng hỏng — đây là lỗi thật, "
        f"không phải chập chờn.",
    )
    return result


def _run_once(case: TestCase, session: HttpSession,
              browser: object | None = None, *,
              soft_assert: bool = False, fixture_store: FixtureStore | None = None) -> CaseResult:
    result = CaseResult(case_id=case.id, title=case.title, module=case.module,
                        status=STATUS_NOT_EXECUTED, step_count=len(case.steps),
                        manual=case.execution == "manual")

    # Case thủ công: các bước viết cho NGƯỜI làm, máy không chạy được.
    #
    # Trạng thái phải là `Not Executed`, không phải `Pass` (máy có làm gì đâu) và
    # cũng không phải `Blocked` (không thiếu gì cả — case hoàn toàn hợp lệ, chỉ là
    # việc của người). Gộp vào `Blocked` sẽ chôn nhóm việc QC cần làm tay vào cùng
    # chỗ với "thiếu môi trường", và báo cáo mất khả năng phân biệt hai thứ đó.
    if case.execution == "manual":
        result.status = STATUS_NOT_EXECUTED
        result.blocked_reason = ""
        result.actual = [
            f"Cần người chạy thủ công theo {len(case.steps)} bước ở cột «Test Steps»."
        ]
        return result

    # Case cần setup môi trường mà tool không tự tạo được → Blocked, KHÔNG Fail.
    # Ghi Fail ở đây là đổ lỗi cho sản phẩm trong khi thật ra thiếu môi trường test.
    if case.requires:
        result.status = STATUS_BLOCKED
        result.blocked_reason = case.requires
        result.actual = [f"Chưa chạy: {case.requires}"]
        return result

    # Case còn bước chưa map mà vẫn mang `execution=auto` là mâu thuẫn — chặn lại
    # thay vì chạy nửa vời rồi báo kết quả sai.
    if case.needs_mapping:
        result.status = STATUS_BLOCKED
        result.blocked_reason = (
            "Case còn bước viết bằng văn xuôi chưa map sang hành động cụ thể."
        )
        result.actual = ["Chưa chạy: case chưa được map sang hành động cụ thể."]
        return result

    fixture_steps = [step for step in case.steps if step.action == "ui.fill"
                     and is_alias(step.args.get("value")) and REGISTRY in case.test_data]
    if fixture_steps:
        try:
            if fixture_store is None:
                raise FixtureUnavailable()
            for step in fixture_steps:
                alias = step.args["value"]
                if not case.test_data[REGISTRY].get(alias, {}).get("available"):
                    raise FixtureUnavailable()
                fixture_store.resolve(alias)
        except FixtureUnavailable:
            result.status = STATUS_BLOCKED
            result.blocked_reason = "Trusted fixture data is unavailable"
            result.actual = [result.blocked_reason]
            return result
    capture_settings = {}
    if (fixture_steps or any(s.args.get("capture_response") or s.args.get("capture_requests") for s in case.steps)) and browser is not None:
        for name, replacement in (("trace_enabled", False), ("evidence_dir", None)):
            if hasattr(browser, name):
                capture_settings[name] = getattr(browser, name)
                setattr(browser, name, replacement)

    started = time.perf_counter()
    saved: dict[str, dict] = {}

    # Mỗi case một context trình duyệt sạch: case trước không để lại cookie/dữ
    # liệu phá case sau. Đây là điều kiện để "chạy riêng pass" và "chạy cả suite
    # pass" là cùng một chuyện.
    has_ui = any(s.action in UI_VERBS for s in case.steps)
    try:
        if browser is not None and has_ui:
            browser.start_case(case.id)
            if soft_assert:
                browser.set_assert_mode(True)
        for step in case.steps:
            step_started = time.perf_counter()
            try:
                if step.action in UI_VERBS:
                    if step.action == "ui.click" and "capture_response" in step.args:
                        from .browser import ResponseCaptureError
                        if browser is None:
                            raise ResponseCaptureError("UI_RESPONSE_CAPTURE_FAILED")
                        capture = step.args["capture_response"]
                        saved.pop(capture.get("save_as", "res"), None)
                        response = browser.click_and_capture(step.args, step.seq)
                        saved[capture.get("save_as", "res")] = response
                        ok, detail = True, f"Captured {capture['method']} {capture['path']} → HTTP {response['status']} (trigger step {step.seq})"
                    elif step.action == "ui.click" and "capture_requests" in step.args:
                        if browser is None:
                            from .browser import ResponseCaptureError
                            raise ResponseCaptureError("UI_REQUEST_OBSERVATION_FAILED")
                        capture = step.args["capture_requests"]
                        key = capture.get("save_as", "res")
                        saved.pop(key, None)
                        observation = browser.click_and_observe_requests(step.args, step.seq)
                        saved[key] = observation
                        ok, detail = observation["body"]["request_count"] == 0, (f"Observed {capture['method']} {capture['path']}: "
                            f"{observation['body']['request_count']} requests in {capture.get('timeout_ms',10000)}ms "
                            f"(trigger step {step.seq})")
                    elif step in fixture_steps:
                        from dataclasses import replace
                        runtime_step = replace(step, args={**step.args,
                            "value": fixture_store.resolve(step.args["value"]),
                            "_fixture_alias": step.args["value"]})
                        ok, detail = _run_ui_step(runtime_step, browser)
                    else:
                        ok, detail = _run_ui_step(step, browser)
                else:
                    ok, detail = _run_step(step, session, saved)
            except NeedsEnvironment as exc:
                # Không đủ điều kiện chạy — KHÔNG phải sản phẩm có lỗi.
                if getattr(exc, "code", None):
                    result.steps.append(StepResult(step.seq, step.action, False, str(exc),
                        (time.perf_counter() - step_started) * 1000, exc.code))
                result.status = STATUS_BLOCKED
                message = fixture_store.redact(str(exc)) if fixture_store else str(exc)
                result.blocked_reason = message
                result.actual.append(f"Chưa chạy: {message}")
                result.duration_ms = (time.perf_counter() - started) * 1000
                return result
            except Exception as exc:                   # lỗi bất ngờ → Fail, không sập runner
                ok, detail = False, f"Lỗi khi chạy bước: {type(exc).__name__}: {exc}"
            if fixture_store:
                detail = fixture_store.redact(detail)
            elapsed = (time.perf_counter() - step_started) * 1000
            result.steps.append(StepResult(step.seq, step.action, ok, detail, elapsed))
            result.actual.append(("[OK] " if ok else "[X] ") + detail)

            if not ok and step.action.startswith("assert."):
                result.status = STATUS_FAIL
                result.duration_ms = (time.perf_counter() - started) * 1000
                return result
            if not ok and (step.action == "http.request" or
                           step.action == "ui.click" and "capture_requests" in step.args):
                result.status = STATUS_FAIL
                result.blocked_reason = detail
                result.duration_ms = (time.perf_counter() - started) * 1000
                return result

        # Assert mềm: bước sai không dừng case, nên sau khi hết bước mới biết case
        # này có đạt hay không. Vẫn là `Fail` nếu có bất kỳ bước nào sai.
        #
        # CHỈ đọc khi case này thật sự có bước UI. Case API thuần không gọi
        # `start_case` nên `soft_failures` còn nguyên giá trị của case UI chạy
        # trước đó — đọc nó là gán lỗi của case khác cho case này. Đã gặp thật:
        # 8 case API có mọi bước `[OK]` nhưng bị báo `Fail` kèm dòng "1 bước kiểm
        # tra không đạt".
        if has_ui and (soft_failures := list(getattr(browser, "soft_failures", []) or [])):
            result.status = STATUS_FAIL
            result.actual.insert(
                0, f"{len(soft_failures)} bước kiểm tra không đạt (chạy hết case rồi mới kết luận)."
            )
            result.duration_ms = (time.perf_counter() - started) * 1000
            return result

        result.status = STATUS_PASS
        result.duration_ms = (time.perf_counter() - started) * 1000
        return result
    finally:
        # Bằng chứng được chụp trước khi đóng context — đóng rồi thì trang không
        # còn để chụp. Còn trace thì chỉ **ghi xong** khi `end_case` chạy, nên phải
        # đọc evidence SAU đó; đọc trước là mất luôn đường dẫn trace.
        try:
            if browser is not None and has_ui:
                if result.status == STATUS_FAIL:
                    with contextlib.suppress(Exception):
                        browser.capture_failure()
                browser.end_case(result.status)
                result.evidence = browser.evidence.to_dict()
        finally:
            if browser is not None:
                for name, value in capture_settings.items():
                    setattr(browser, name, value)
            if fixture_store:
                result.actual = fixture_store.redact(result.actual)
                result.evidence = fixture_store.redact(result.evidence)


def _run_step(step, session: HttpSession, saved: dict) -> tuple[bool, str]:
    args = step.args

    match step.action:
        case "http.request":
            resp = session.request(
                args["method"], args["path"],
                body=args.get("body"), raw_body=args.get("raw_body"),
                query=args.get("query"),
                auth=args.get("auth", "bearer"), headers=args.get("headers"),
                base=args.get("base"),
            )
            if resp["error"]:
                return False, f"Không gọi được {args['method']} {args['path']}: {resp['error']}"
            key = args.get("save_as", "res")
            # Ghi lại cách gọi để bước sau **gọi lại được** khi cần lấy mẫu
            # (`assert.response_time` cần nhiều mẫu mới đo được phân vị).
            resp["_path"] = args["path"]
            resp["_args"] = args
            saved[key] = resp
            server = f", server {resp['server_ms']:.0f}ms" if resp.get("server_ms") is not None else ""
            return True, (f"{args['method']} {args['path']} → HTTP {resp['status']} "
                          f"({resp['duration_ms']:.0f}ms{server})")

        case "assert.http_status":
            resp = saved.get(args.get("source", "res"))
            if resp is None:
                return False, "Không tìm thấy response để kiểm tra"
            expected, actual = int(args["expected"]), resp["status"]
            if actual == expected:
                return True, f"HTTP {actual} — đúng như mong đợi"
            return False, f"Mong đợi HTTP {expected}, thực tế HTTP {actual}"

        case "assert.json_schema":
            resp = saved.get(args.get("source", "res"))
            if resp is None:
                return False, "Không tìm thấy response để kiểm tra"
            body = resp["body"]
            required = args["required"]
            if not isinstance(body, dict):
                return False, f"Response không phải object JSON (nhận {type(body).__name__})"
            missing = [f for f in required if f not in body]
            if missing:
                return False, f"Thiếu field bắt buộc: {missing}"
            return True, f"Có đủ {len(required)} field bắt buộc: {', '.join(required)}"

        case "assert.json_field":
            resp = saved.get(args.get("source", "res"))
            if resp is None:
                return False, "Không tìm thấy response để kiểm tra"
            path = args["path"].lstrip("$").lstrip(".").split(".")
            node = resp["body"]
            for part in path:
                if not isinstance(node, dict) or part not in node:
                    return False, f"Không có field `{args['path']}` trong response"
                node = node[part]
            expected = args["expected"]
            operator = args.get("operator", "eq")
            ok = _compare(node, expected, operator)
            return ok, (f"`{args['path']}` = {node!r}" +
                        ("" if ok else f", mong đợi {operator} {expected!r}"))

        case "assert.response_time":
            if saved.get(args.get("source", "res"), {}).get("_ui_trigger"):
                return False, "Latency resampling is not supported for UI-captured responses"
            # Ngưỡng tài liệu ghi là **phân vị** (`p95 < 100ms`), không phải "mọi
            # lần gọi đều dưới 100ms". Một lần gọi không đo được phân vị — lấy mẫu
            # ngẫu nhiên một request rồi so với ngưỡng p95 là *kiểm chặt hơn yêu
            # cầu*, và vì thế báo `Fail` sai (đã gặp thật: `/auth/config` một mẫu
            # 162ms, nhưng p95 thật của 30 mẫu là 84ms).
            #
            # Ở đây lấy `samples` lần gọi rồi so **đúng phân vị** tài liệu nói.
            # `percentile` cho phép tài liệu ghi rõ p90/p99; mặc định 95.
            limit = float(args["max_ms"])
            pct = float(args.get("percentile", 95))
            source = args.get("source", "res")
            path = (saved.get(source) or {}).get("_path") or ""
            samples = int(args.get("samples", 1))
            if path and samples > 1:
                durations, failure = _sample_latency(session, saved[source], path, samples)
                if durations is None:
                    # Không lấy đủ mẫu vì mạng — đó là thiếu điều kiện đo, không
                    # phải sản phẩm chậm. Ném `NeedsEnvironment` để case thành
                    # `Blocked` kèm lý do, thay vì `Fail` oan.
                    raise NeedsEnvironment(
                        f"Không lấy đủ mẫu để đo phân vị p{pct:g}: {failure}"
                    )
                actual = _percentile(durations, pct)
                detail = (f"p{pct:g} = {actual:.0f}ms qua {len(durations)} lần gọi "
                          f"(nhỏ nhất {min(durations):.0f}ms, lớn nhất {max(durations):.0f}ms)")
            else:
                resp = saved.get(source)
                if resp is None:
                    return False, "Không tìm thấy response để kiểm tra"
                actual = resp["duration_ms"]
                detail = f"{actual:.0f}ms (một lần gọi)"
            if actual <= limit:
                return True, f"{detail} — trong ngưỡng {limit:.0f}ms"
            server = (saved.get(source) or {}).get("server_ms")
            extra = f"; phía server {server:.0f}ms" if server is not None else ""
            return False, f"{detail} — VƯỢT ngưỡng {limit:.0f}ms{extra}"

        case "wait":
            seconds = float(args["seconds"])
            time.sleep(min(seconds, 30))
            return True, f"Đã chờ {seconds}s"

        case verb if verb.startswith("assert.") or verb.startswith("perform."):
            return False, (f"Verb `{verb}` chưa có adapter — cần người map "
                           "sang hành động cụ thể")

        case verb if verb.startswith(("ui.", "db.", "cli.")):
            return False, f"Verb `{verb}` chưa có adapter (sẽ làm ở M06/M04)"

        case _:
            return False, f"Verb `{step.action}` chưa có adapter"


def _run_ui_step(step, browser) -> tuple[bool, str]:
    """Chạy một bước trên trình duyệt. Không có browser ⇒ Blocked, không phải Fail."""
    if browser is None:
        raise NeedsEnvironment("Chưa mở trình duyệt — cần URL web để chạy bước UI")

    args = step.args
    match step.action:
        case "ui.goto":
            return True, f"Mở {args.get('url')} → {browser.goto(args['url'])}"
        case "ui.session":
            return True, browser.set_session(args)
        case "ui.click":
            return True, browser.click(args)
        case "ui.fill":
            return True, browser.fill(args)
        case "ui.select":
            return True, browser.select(args)
        case "ui.hover":
            return True, browser.hover(args)
        case "ui.press":
            return True, browser.press(args)
        case "ui.check":
            return True, browser.check(args)
        case "ui.scroll":
            return True, browser.scroll(args)
        case "ui.wait_for":
            return True, browser.wait_for(args)
        case "assert.url_matches":
            return browser.url_matches(args["pattern"])
        case "assert.visible":
            return browser.is_visible(args)
        case "assert.not_visible":
            return browser.not_visible(args)
        case "assert.enabled":
            return browser.is_enabled(args)
        case "assert.disabled":
            return browser.is_disabled(args)
        case "assert.text":
            return browser.text(args)
        case "assert.value":
            return browser.value(args)
        case "assert.attr":
            return browser.attribute(args)
        case "assert.count":
            return browser.count(args)
        case "assert.focused":
            return browser.focused(args)
        case "assert.checked":
            return browser.checked(args)
        case "assert.console_clean":
            return browser.console_clean(args)
        case "assert.no_broken_requests":
            return browser.requests_clean(args)
        case "assert.axe":
            return browser.axe_scan(args)
        case "assert.screenshot":
            path = browser.screenshot(str(args["name"]),
                                      bool(args.get("full_page", True)))
            if path is None:
                return False, ("Không lưu được ảnh — lượt chạy này không có "
                               "thư mục bằng chứng")
            return True, f"Đã lưu ảnh bằng chứng: {path.name}"
        case _:
            return False, f"Verb `{step.action}` chưa có adapter trình duyệt"


def _compare(actual, expected, operator: str) -> bool:
    match operator:
        case "eq":
            return actual == expected
        case "ne":
            return actual != expected
        case "gt":
            return actual > expected
        case "gte":
            return actual >= expected
        case "lt":
            return actual < expected
        case "lte":
            return actual <= expected
        case "in":
            return actual in expected
        case "not_in":
            return actual not in expected
        case "exists":
            return actual is not None
        case _:
            return actual == expected


def run_cases(cases: list[TestCase], session: HttpSession,
              environment: str = "", browser: object | None = None, *,
              retry: int = 0, soft_assert: bool = False,
              fixture_store: FixtureStore | None = None) -> RunResult:
    started = datetime.now()
    results = RunResult(
        started_at=started.strftime("%Y-%m-%d %H:%M:%S"),
        finished_at="",
        base_url=session.base_url,
        environment=environment or session.base_url,
    )
    for case in cases:
        results.cases.append(
            run_case(case, session, browser, retry=retry, soft_assert=soft_assert, fixture_store=fixture_store)
        )
    results.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return results

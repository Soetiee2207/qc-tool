"""Sinh testcase từ đặc tả OpenAPI.

Đây là track **deterministic** — không dùng LLM. Sinh theo kỹ thuật đã đặt tên:
phân lớp tương đương (EP), phân tích giá trị biên (BVA), ma trận xác thực,
và kiểm tra lỗi.

Vì sao deterministic làm phần lớn công việc: nó đảm bảo **độ phủ** thay vì trông
chờ may mắn. LLM giỏi nghĩ ra tình huống bất ngờ, nhưng không đảm bảo đã thử
`minLength-1`. Hai thứ bù nhau.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..testcase import (
    PERF_DEFAULT_PERCENTILE,
    PERF_SAMPLES,
    CaseType,
    Priority,
    Step,
    StepKind,
    Technique,
    TestCase,
)

# Mã HTTP → ý nghĩa, để đặt tiêu đề case đọc được
HTTP_MEANING = {
    "200": "thành công",
    "201": "tạo thành công",
    "204": "thành công, không có nội dung trả về",
    "400": "yêu cầu không hợp lệ",
    "401": "chưa xác thực",
    "403": "không có quyền",
    "404": "không tìm thấy",
    "409": "xung đột dữ liệu",
    "422": "dữ liệu không hợp lệ",
    "500": "lỗi hệ thống",
}

ERROR_TYPES = {
    "400": CaseType.NEGATIVE,
    "401": CaseType.SECURITY,
    "403": CaseType.SECURITY,
    "404": CaseType.NEGATIVE,
    "409": CaseType.NEGATIVE,
    "422": CaseType.NEGATIVE,
    "500": CaseType.NEGATIVE,
}

SAFE_INT_MAX = 2147483647


@dataclass
class Endpoint:
    """Một operation đã rút gọn thành thứ generator dùng được."""

    method: str
    path: str
    summary: str
    operation_id: str
    tags: list[str]
    requires_auth: bool
    qc_id: str | None
    priority: Priority
    latency_p95_ms: int | None
    test_data: dict
    parameters: list[dict]        # tham số path + query
    request_body: dict | None     # schema
    request_required: list[str]
    responses: dict[str, dict]    # mã → {schema}
    # `servers` khai ở cấp operation (hoặc cấp path) trong spec. Rỗng nghĩa là
    # dùng `servers` gốc của cả file. Đây là cơ chế chuẩn của OpenAPI để một
    # spec mô tả nhiều service — không tôn trọng nó thì mọi request của service
    # phụ đều đi sai host và nhận 404.
    servers: list[str] = field(default_factory=list)
    # Effective declared servers for evidence; does not change http.request base overrides.
    contract_servers: list[str] = field(default_factory=list)

    @property
    def module(self) -> str:
        if self.qc_id:
            return self.qc_id
        return self.tags[0] if self.tags else self.path.strip("/").split("/")[0]

    @property
    def success_code(self) -> str | None:
        for code in ("200", "201", "204"):
            if code in self.responses:
                return code
        return None

    @property
    def error_codes(self) -> list[str]:
        return sorted(c for c in self.responses if c.startswith(("4", "5")))


class IdAllocator:
    """Cấp `TC_<MODULE>_<NNN>` tuần tự, không trùng."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._used: set[str] = set()

    def next(self, module: str) -> str:
        slug = _slug(module)
        n = self._counters.get(slug, 0) + 1
        while f"TC_{slug}_{n:03d}" in self._used:
            n += 1
        self._counters[slug] = n
        tc_id = f"TC_{slug}_{n:03d}"
        self._used.add(tc_id)
        return tc_id


def _slug(module: str) -> str:
    """Tên module → phần ID testcase. `login-sso` → `LOGIN_SSO`.

    Giữ dấu `_` giữa các từ để ID còn đọc được (`TC_LOGIN_SSO_008` thay vì
    `TC_LOGINSSO_008`). Validator yêu cầu `TC_<MODULE>_<NNN>` với MODULE chỉ gồm
    chữ in hoa/số/`_`, nên mọi ký tự khác đều quy về `_`.
    """
    text = re.sub(r"[^A-Za-z0-9]+", "_", (module or "").upper()).strip("_")
    # Mã tài liệu kiểu `F-HEALTH-01`, `F_01`, `F-PROJ-01`: chữ `F` + số/mã không
    # mang thông tin gì cho ID testcase — bỏ phần `F[_<mã>]` ở đầu, còn lại
    # `HEALTH_01`, `PROJ_01`.
    if re.match(r"^F(_[A-Z0-9]+)*_\d+$", text) or text == "F_01":
        text = re.sub(r"^F_", "", text)
    return text[:24].strip("_") or "GEN"


# ── Sinh case cho một endpoint ───────────────────────────────────────────────
def _resolve_path(path: str, data: dict) -> str:
    """Thay `{param}` trong đường dẫn bằng giá trị thật.

    Không có bước này thì request đi tới `/projects/{project_id}` nguyên văn và
    luôn nhận 404 — biến mọi case có path param thành fail giả.
    """
    out = path
    for key, value in data.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def _path_params_to_data(parameters: list[dict]) -> dict:
    """Điền giá trị mẫu cho tham số đường dẫn, để URL dựng được."""
    out: dict = {}
    for p in parameters:
        if p["in"] != "path":
            continue
        out[p["name"]] = _sample_value(p.get("schema", {}))
    return out


def _sample_value(schema: dict) -> object:
    """Sinh một giá trị hợp lệ đại diện cho schema — dùng cho phân lớp tương đương."""
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    match schema.get("type"):
        case "string":
            if schema.get("format") == "uuid":
                return "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
            if schema.get("format") == "email":
                return "user@example.com"
            if schema.get("format") == "date-time":
                return "2026-01-01T00:00:00Z"
            length = schema.get("minLength", 1)
            return "a" * max(length, 3)
        case "integer":
            return schema.get("minimum", 1)
        case "number":
            return schema.get("minimum", 1)
        case "boolean":
            return True
        case "array":
            return [ _sample_value(schema.get("items", {})) ]
        case _:
            return "sample"


def _boundary_values(schema: dict) -> list[tuple[str, object, str]]:
    """Giá trị biên: (nhãn, giá trị, giá trị này vi phạm hay hợp lệ).

    BVA kinh điển: với mỗi biên thử `min-1, min, max, max+1`.
    Đây là thứ LLM hay quên nhưng bug hay nằm đúng ở đây (lệch một đơn vị).
    """
    out: list[tuple[str, object, str]] = []
    t = schema.get("type")

    if t == "string":
        mn, mx = schema.get("minLength"), schema.get("maxLength")
        if mn:
            out.append((f"dài {mn - 1} ký tự (dưới tối thiểu {mn})", "a" * (mn - 1), "invalid"))
            out.append((f"dài đúng {mn} ký tự (bằng tối thiểu)", "a" * mn, "valid"))
            if mn > 1:
                out.append((f"chuỗi rỗng (dưới tối thiểu {mn})", "", "invalid"))
        if mx:
            if mx > 1:
                out.append((f"dài đúng {mx} ký tự (bằng tối đa)", "a" * mx, "valid"))
            out.append((f"dài {mx + 1} ký tự (vượt tối đa {mx})", "a" * (mx + 1), "invalid"))

    elif t in ("integer", "number"):
        mn, mx = schema.get("minimum"), schema.get("maximum")
        if mn is not None:
            out.append((f"bằng {mn - 1} (dưới tối thiểu {mn})", mn - 1, "invalid"))
            out.append((f"bằng {mn} (bằng tối thiểu)", mn, "valid"))
        if mx is not None:
            out.append((f"bằng {mx} (bằng tối đa)", mx, "valid"))
            out.append((f"bằng {mx + 1} (vượt tối đa {mx})", mx + 1, "invalid"))

    elif t == "array":
        mx = schema.get("maxItems")
        if mx:
            item = _sample_value(schema.get("items", {"type": "string"}))
            if mx > 1:
                out.append((f"đúng {mx} phần tử (bằng tối đa)", [item] * mx, "valid"))
            out.append((f"{mx + 1} phần tử (vượt tối đa)", [item] * (mx + 1), "invalid"))

    elif "enum" in schema and schema["enum"]:
        values = schema["enum"]
        for v in values:
            out.append((f"giá trị hợp lệ `{v}`", v, "valid"))
        out.append(("giá trị không nằm trong danh sách", "__not_in_enum__", "invalid"))

    return out


def _where(schema: dict, prop: str) -> str:
    if "properties" in schema:
        return f"body `{prop}`"
    return f"`{prop}`"


def _base_arg(ep: Endpoint) -> dict:
    """`base` cho bước `http.request` khi operation khai `servers` riêng.

    Spec khai `servers` ở cấp operation nghĩa là operation đó thuộc **service
    khác** với `servers` gốc. Nếu bỏ qua, mọi request của service phụ đều gửi
    tới host của service chính và nhận 404 — sai host thì kết quả vô nghĩa.

    Lấy server đầu tiên; pipeline sẽ thay bằng server khớp môi trường khi có
    đủ thông tin (xem `_apply_servers`).
    """
    return {"base": ep.servers[0]} if ep.servers else {}


def generate_for_endpoint(ep: Endpoint, alloc: IdAllocator,
                          skipped: list[str] | None = None) -> list[TestCase]:
    cases: list[TestCase] = []
    skipped = skipped if skipped is not None else []
    path_data = _path_params_to_data(ep.parameters)
    quote = f"{ep.method} {ep.path} — {ep.summary}"
    ref = f"openapi:{ep.operation_id}"
    trace = [ep.qc_id] if ep.qc_id else []

    def make(**kw) -> TestCase:
        base = dict(
            id=alloc.next(ep.module),
            module=ep.module,
            traces_to=list(trace),
            source_quote=quote,
            source_ref=ref,
            generated_by="engine",
        )
        base.update(kw)
        return TestCase(**base)

    extra_args = _base_arg(ep)

    # ── 1. Happy path ───────────────────────────────────────────────────────
    if code := ep.success_code:
        body = _build_valid_body(ep) if ep.request_body else None
        steps = [
            Step(1, StepKind.WHEN, "http.request", {
                "method": ep.method,
                "path": _resolve_path(ep.path, path_data),
                "auth": "bearer" if ep.requires_auth else "none",
                **({"body": body} if body else {}),
                **extra_args,
                "save_as": "res",
            }),
            Step(2, StepKind.THEN, "assert.http_status",
                 {"expected": int(code), "source": "res"}),
        ]
        if code != "204" and (schema := _success_schema(ep)):
            if required := schema.get("required"):
                steps.append(Step(len(steps) + 1, StepKind.THEN, "assert.json_schema", {
                    "required": list(required), "source": "res",
                }))
        if ep.latency_p95_ms:
            # `x-qc-latency-p95-ms` là **phân vị** thứ 95 → phải lấy nhiều mẫu mới
            # đo được. Đo một lần rồi so với ngưỡng p95 là kiểm chặt hơn yêu cầu
            # và báo lỗi giả.
            steps.append(Step(len(steps) + 1, StepKind.THEN, "assert.response_time",
                              {"max_ms": ep.latency_p95_ms, "source": "res",
                               "percentile": PERF_DEFAULT_PERCENTILE,
                               "samples": PERF_SAMPLES}))

        cases.append(make(
            title=_title(ep, f"trả {code} khi dữ liệu hợp lệ"),
            objective=f"Xác nhận «{_human(ep)}» hoạt động đúng ở luồng chính",
            steps=steps,
            priority=ep.priority,
            case_type=CaseType.POSITIVE,
            technique=Technique.EQUIVALENCE_PARTITIONING,
            preconditions=_preconditions(ep),
            test_data=body or path_data or {},
        ))

    # ── 2. Mã lỗi đã khai báo ───────────────────────────────────────────────
    for err_code in ep.error_codes:
        if not _can_trigger(ep, err_code):
            # Không dựng được input để chạm lỗi này → không sinh case rỗng nghĩa.
            # Case dạng "gọi bình thường, mong đợi 422" luôn fail giả và làm
            # báo cáo mất giá trị.
            skipped.append(
                f"{ep.method} {ep.path}: bỏ case {err_code} — "
                f"{HTTP_MEANING.get(err_code, 'lỗi')} nhưng không có cách dựng input để chạm"
            )
            continue

        meaning = HTTP_MEANING.get(err_code, "lỗi")
        needs = _setup_needed(ep, err_code)
        steps = [Step(1, StepKind.WHEN, "http.request", {
            "method": ep.method, "path": _resolve_path(ep.path, path_data),
            "auth": _auth_for_error(ep, err_code),
            **_body_args_for_error(ep, err_code),
            **extra_args,
            "save_as": "res",
        })]
        steps.append(Step(2, StepKind.THEN, "assert.http_status",
                          {"expected": int(err_code), "source": "res"}))
        # Chỉ kiểm cấu trúc body khi SPEC nói rõ schema. Trước đây chỗ này hardcode
        # `["code"]` — tên field do tôi tự nghĩ ra, không có trong tài liệu. Response
        # thật của portal là `detail.error.code` lồng ba tầng, nên assert đó luôn sai
        # và đổ lỗi oan cho sản phẩm.
        if err_code in ("401", "403"):
            error_schema = (ep.responses.get(err_code) or {}).get("schema") or {}
            if required_fields := error_schema.get("required"):
                steps.append(Step(3, StepKind.THEN, "assert.json_schema",
                                  {"required": list(required_fields), "source": "res"}))

        cases.append(make(
            title=_title(ep, f"trả {err_code} khi {meaning}")
                  + (" [cần setup]" if needs else ""),
            objective=f"Xác nhận «{_human(ep)}» xử đúng trường hợp {meaning}",
            steps=steps,
            priority=Priority.HIGH if err_code in ("401", "403") else ep.priority,
            case_type=ERROR_TYPES.get(err_code, CaseType.NEGATIVE),
            technique=Technique.ERROR_GUESSING if err_code == "500" else Technique.SCHEMA_CONFORMANCE,
            preconditions=_preconditions(ep, error_code=err_code),
            test_data=path_data or {},
            requires=needs,
        ))

    # ── 3. Giá trị biên trên tham số ────────────────────────────────────────
    for param in ep.parameters:
        schema = param.get("schema", {})
        for label, value, validity in _boundary_values(schema):
            if validity == "valid":
                continue        # case hợp lệ đã nằm trong happy path
            cases.append(_boundary_case(ep, param, label, value, path_data, alloc))

    # ── 4. Giá trị biên + field thiếu trong body ────────────────────────────
    if ep.request_body:
        schema = ep.request_body
        props = schema.get("properties", {})
        required = schema.get("required", [])

        for name, prop_schema in props.items():
            if name in required:
                cases.append(_missing_field_case(ep, name, path_data, alloc))
            for label, value, validity in _boundary_values(prop_schema):
                if validity == "valid":
                    continue
                cases.append(_body_boundary_case(ep, name, prop_schema, label, value, path_data, alloc))

    # ── 5. Ma trận xác thực ─────────────────────────────────────────────────
    if ep.requires_auth:
        cases.append(make(
            title=_title(ep, "từ chối khi không có token"),
            objective=f"Xác nhận «{_human(ep)}» không cho truy cập ẩn danh",
            steps=[
                Step(1, StepKind.WHEN, "http.request",
                     {"method": ep.method, "path": _resolve_path(ep.path, path_data),
                      "auth": "none", **extra_args, "save_as": "res"}),
                Step(2, StepKind.THEN, "assert.http_status", {"expected": 401, "source": "res"}),
            ],
            priority=Priority.HIGH,
            case_type=CaseType.SECURITY,
            technique=Technique.AUTH_MATRIX,
            preconditions=["Không gửi header Authorization"],
            test_data=path_data or {},
        ))

    return cases


def _human(ep: Endpoint) -> str:
    """Mô tả endpoint bằng ngôn ngữ người đọc, để đặt title và objective.

    Ưu tiên `summary` của spec — đó là câu người viết spec đã chọn, thường đã là
    tiếng Việt nghiệp vụ. Không có thì dựng câu ngắn từ method + path, chứ không
    nhét nguyên đường dẫn dài vào title: tiêu đề dài 70 ký tự toàn dấu `/` và
    `{realm}` thì người đọc lướt qua không hiểu case này kiểm cái gì.
    """
    summary = " ".join((ep.summary or "").split()).strip()
    if summary and summary.upper() != f"{ep.method} {ep.path}".upper():
        return summary
    return f"{ep.method} {ep.path}"


def _title(ep: Endpoint, suffix: str) -> str:
    """Tiêu đề case: câu nghiệp vụ + điều kiện, KHÔNG phải `METHOD /path`.

    Method và path không mất — chúng nằm ở bước 1 của Test Steps và trong
    `provenance.source_quote`, là chỗ người chạy cần chúng.
    """
    base = _human(ep)
    return f"{base} — {suffix}"


def _preconditions(ep: Endpoint, error_code: str | None = None) -> list[str]:
    out = []
    if ep.requires_auth:
        out.append("Đã đăng nhập, có Bearer token hợp lệ")
    if error_code == "401":
        out = ["KHÔNG gửi token, hoặc token đã hết hạn"]
    elif error_code == "403":
        out.append("Token hợp lệ nhưng tài khoản thiếu quyền cần thiết")
    elif error_code == "404":
        out.append("Tài nguyên được tham chiếu không tồn tại")
    return out or ["Hệ thống đang chạy, dữ liệu nền đã sẵn sàng"]


# Mã lỗi mà tool KHÔNG tự tạo được điều kiện gây ra, nếu chỉ có một tài khoản.
# Sinh case vẫn đúng, nhưng phải đánh dấu để runner báo `Blocked` thay vì `Fail` —
# nếu không, báo cáo sẽ đổ lỗi cho sản phẩm trong khi thật ra thiếu môi trường test.
_NEEDS_SETUP = {
    "403": "Cần một tài khoản KHÔNG có quyền thực hiện thao tác này",
    "404": "Cần một ID chắc chắn không tồn tại trong hệ thống",
    "409": "Cần dữ liệu sẵn có để gây xung đột (bản ghi trùng, ràng buộc còn vướng)",
    "500": "Cần cách ép hệ thống lỗi (không thể tạo từ bên ngoài)",
}


def _setup_needed(ep: Endpoint, err_code: str) -> str | None:
    return _NEEDS_SETUP.get(err_code)


def _sends_body(ep: Endpoint, err_code: str) -> bool:
    """Case lỗi này có gửi body không.

    401 là lỗi xác thực — body không liên quan, và gửi body vào endpoint cần
    token chỉ làm case rối thêm. 403/409/500 cần body hợp lệ (token đúng, dữ
    liệu đúng) để chạm đúng nhánh lỗi cần kiểm.
    """
    return bool(ep.request_body) and err_code not in ("401",)


def _can_trigger(ep: Endpoint, err_code: str) -> bool:
    """Tool có dựng được input để CHẠM vào lỗi này không?

    Trả `False` chỉ khi case sẽ **hoàn toàn rỗng nghĩa** — ví dụ `GET /projects`
    không body, không tham số ràng buộc, mà lại sinh case "mong đợi 422". Case đó
    không gửi gì sai cả nên luôn fail giả.

    Với lỗi cần môi trường (403/404/409/500) thì **vẫn sinh**, nhưng đánh dấu
    `requires` để runner báo `Blocked`. Bỏ hẳn đi là giấu mất một khoảng trống
    thật của bộ test — báo cáo sẽ không còn thấy là mình thiếu gì.
    """
    if err_code == "400":
        return ep.request_body is not None

    if err_code == "422":
        return ep.request_body is not None or any(
            p.get("schema", {}).get("enum")
            or p.get("schema", {}).get("minimum") is not None
            or p.get("schema", {}).get("minLength") is not None
            for p in ep.parameters
            if p.get("in") == "query"
        )

    # 401/403/404/409/500: dựng được, chỉ là cần môi trường → `requires` lo.
    return True


# Body JSON hỏng thật — dùng cho case 400 (không parse được).
MALFORMED_JSON = '{"name": "abc", '


def _violating_query(ep: Endpoint) -> dict:
    """Tham số query vi phạm ràng buộc của spec — để chạm lỗi validate thật.

    Cần riêng cho trường hợp endpoint **không có body** nhưng vẫn có tham số
    query ràng buộc (`GET /projects?page=0` trong khi `minimum: 1`). Không có
    bước này thì case "mong đợi 422" gửi request hoàn toàn hợp lệ và luôn fail
    giả — đúng loại báo động sai mà `_can_trigger` sinh ra để chặn.
    """
    for param in ep.parameters:
        if param.get("in") != "query":
            continue
        schema = param.get("schema", {})
        if schema.get("enum"):
            return {param["name"]: "__not_in_enum__"}
        if schema.get("minimum") is not None:
            return {param["name"]: schema["minimum"] - 1}
        if schema.get("minLength") is not None:
            return {param["name"]: "a" * (schema["minLength"] - 1)}
    return {}


def _body_args_for_error(ep: Endpoint, err_code: str) -> dict:
    """Tham số body cho case lỗi — `body` hoặc `raw_body` tuỳ mã lỗi."""
    if err_code == "422" and not ep.request_body:
        # Không có body để làm sai → phải làm sai tham số query, nếu không case
        # này không chạm được vào lỗi nào cả.
        return {"query": _violating_query(ep)} if _violating_query(ep) else {}
    if not _sends_body(ep, err_code):
        return {}
    if err_code == "400":
        return {"raw_body": MALFORMED_JSON}
    body = _body_for_error(ep, err_code)
    return {"body": body} if body is not None else {}


def _auth_for_error(ep: Endpoint, code: str) -> str:
    if code == "401":
        return "none"
    if ep.requires_auth:
        return "bearer"
    return "none"


def _body_for_error(ep: Endpoint, code: str) -> dict | None:
    """Body cho case lỗi.

    400 nghĩa là **body không đọc được** — phải gửi chuỗi hỏng thật, không phải
    JSON hợp lệ chứa field lạ. Gửi JSON hợp lệ thì server trả 422 (dữ liệu sai),
    không phải 400 (không parse được) — case sẽ fail giả.
    """
    match code:
        case "400":
            return None                     # dùng `raw_body` thay thế
        case "422":
            return _invalid_body(ep)
        case _:
            return _build_valid_body(ep)


def _wrong_type_value(schema: dict) -> object:
    """Một giá trị **sai kiểu** so với schema — để chạm lỗi validate thật.

    `type` có thể là danh sách (`["string", "null"]`) theo JSON Schema. Khi đó
    chọn kiểu đầu tiên rồi trả về giá trị sai kiểu của chính kiểu ấy: với
    `["string","null"]` thì `null` là hợp lệ, nên phải trả số mới vi phạm.
    """
    declared = schema.get("type")
    if isinstance(declared, list):
        declared = next((t for t in declared if t != "null"), None)
    match declared:
        case "string":
            return 123
        case "integer" | "number":
            return "không-phải-số"
        case "boolean":
            return "không-phải-boolean"
        case "array":
            return {"không": "phải mảng"}
        case "object":
            return ["không", "phải", "object"]
        case _:
            return 123


def _invalid_body(ep: Endpoint) -> dict:
    """Body vi phạm schema, để server thực sự trả 422.

    Trước đây chỗ này trả `{"__invalid__": True}` — một object JSON hoàn toàn
    hợp lệ, chỉ chứa field lạ. Server bỏ qua field lạ (đúng như thiết kế) và trả
    **200**, nên case "mong đợi 422" luôn `Fail` dù sản phẩm không có lỗi.

    Cách đúng: lấy một field có thật trong schema rồi gửi sai kiểu. Đó mới là
    thứ mà tầng validate của server phải từ chối.
    """
    schema = ep.request_body or {}
    props = schema.get("properties", {})
    if not props:
        return {"__invalid__": True}        # không có schema để vi phạm, đành vậy

    # Ưu tiên field bắt buộc: field tuỳ chọn gửi sai kiểu vẫn nên bị chặn, nhưng
    # field bắt buộc là chắc chắn nhất.
    name = next((n for n in schema.get("required", []) if n in props), next(iter(props)))
    return {name: _wrong_type_value(props[name])}


def _build_valid_body(ep: Endpoint) -> dict:
    schema = ep.request_body or {}
    data = dict(ep.test_data)
    for name, prop in schema.get("properties", {}).items():
        if name not in data:
            data[name] = _sample_value(prop)
    for name in schema.get("required", []):
        if name not in data:
            data[name] = _sample_value(schema.get("properties", {}).get(name, {}))
    return data


def _success_schema(ep: Endpoint) -> dict:
    for code in ("200", "201"):
        if code in ep.responses:
            return ep.responses[code].get("schema") or {}
    return {}


def _boundary_case(ep: Endpoint, param: dict, label: str, value: object,
                   path_data: dict, alloc: IdAllocator) -> TestCase:
    name = param["name"]
    location = param["in"]
    args: dict = {
        "method": ep.method,
        "path": _resolve_path(ep.path, path_data),
        "auth": "bearer" if ep.requires_auth else "none",
        **_base_arg(ep),
        "save_as": "res",
    }
    if location == "query":
        args["query"] = {name: value}
    else:
        # tham số đường dẫn sai → URL trỏ tới tài nguyên không hợp lệ
        args["path"] = ep.path.replace("{" + name + "}", str(value))

    return TestCase(
        id=alloc.next(ep.module),
        module=ep.module,
        title=_title(ep, f"tham số `{name}` {label}"),
        objective=f"Kiểm tra «{_human(ep)}» từ chối `{name}` nằm ngoài miền hợp lệ",
        steps=[
            Step(1, StepKind.WHEN, "http.request", args),
            Step(2, StepKind.THEN, "assert.http_status",
                 {"expected": _expected_for_bad_param(ep), "source": "res"}),
        ],
        priority=Priority.MEDIUM,
        case_type=CaseType.BOUNDARY,
        technique=Technique.BOUNDARY_VALUE,
        traces_to=[ep.qc_id] if ep.qc_id else [],
        source_quote=f"{ep.method} {ep.path} — tham số `{name}` {label}",
        source_ref=f"openapi:{ep.operation_id}#parameters.{name}",
        preconditions=_preconditions(ep),
        test_data={name: value},
    )


def _expected_for_bad_param(ep: Endpoint) -> int:
    for code in ("422", "400"):
        if code in ep.responses:
            return int(code)
    return 400


def _missing_field_case(ep: Endpoint, field: str, path_data: dict,
                        alloc: IdAllocator) -> TestCase:
    body = _build_valid_body(ep)
    body.pop(field, None)
    return TestCase(
        id=alloc.next(ep.module),
        module=ep.module,
        title=_title(ep, f"trả 422 khi thiếu `{field}` bắt buộc"),
        objective=f"Xác nhận «{_human(ep)}» coi `{field}` là bắt buộc, "
                  f"không có giá trị mặc định ngầm",
        steps=[
            Step(1, StepKind.WHEN, "http.request", {
                "method": ep.method, "path": _resolve_path(ep.path, path_data), "body": body,
                "auth": "bearer" if ep.requires_auth else "none", **_base_arg(ep),
                "save_as": "res",
            }),
            Step(2, StepKind.THEN, "assert.http_status",
                 {"expected": _expected_for_bad_param(ep), "source": "res"}),
        ],
        priority=Priority.HIGH,
        case_type=CaseType.NEGATIVE,
        technique=Technique.BOUNDARY_VALUE,
        traces_to=[ep.qc_id] if ep.qc_id else [],
        source_quote=f"{ep.method} {ep.path} — `{field}` là field bắt buộc",
        source_ref=f"openapi:{ep.operation_id}#requestBody.required",
        preconditions=_preconditions(ep),
        test_data={"body_không_có": field},
    )


def _body_boundary_case(ep: Endpoint, field: str, schema: dict, label: str,
                        value: object, path_data: dict, alloc: IdAllocator) -> TestCase:
    body = _build_valid_body(ep)
    body[field] = value
    return TestCase(
        id=alloc.next(ep.module),
        module=ep.module,
        title=_title(ep, f"body `{field}` {label}"),
        objective=f"Kiểm tra «{_human(ep)}» thực thi ràng buộc biên của `{field}`",
        steps=[
            Step(1, StepKind.WHEN, "http.request", {
                "method": ep.method, "path": _resolve_path(ep.path, path_data), "body": body,
                "auth": "bearer" if ep.requires_auth else "none", **_base_arg(ep),
                "save_as": "res",
            }),
            Step(2, StepKind.THEN, "assert.http_status",
                 {"expected": _expected_for_bad_param(ep), "source": "res"}),
        ],
        priority=Priority.MEDIUM,
        case_type=CaseType.BOUNDARY,
        technique=Technique.BOUNDARY_VALUE,
        traces_to=[ep.qc_id] if ep.qc_id else [],
        source_quote=f"{ep.method} {ep.path} — `{field}` {label}",
        source_ref=f"openapi:{ep.operation_id}#requestBody.properties.{field}",
        preconditions=_preconditions(ep),
        test_data={field: _preview(value)},
    )


def _preview(value: object) -> object:
    """Rút gọn giá trị dài để không làm ngập cột Test Data."""
    if isinstance(value, str) and len(value) > 40:
        return f"{value[:20]}…({len(value)} ký tự)"
    if isinstance(value, list) and len(value) > 5:
        return f"[{len(value)} phần tử]"
    return value

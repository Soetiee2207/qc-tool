"""Test cho chặng generate + validate.

Mỗi test ứng với một tính chất phải giữ, hoặc một bug đã gặp thật.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qctool.generate import IdAllocator, generate_all  # noqa: E402
from qctool.generate.loader import SpecError, load_endpoints, resolve_ref  # noqa: E402
from qctool.generate.from_openapi import generate_for_endpoint  # noqa: E402
from qctool.testcase import (  # noqa: E402
    ACTION_VERBS,
    CaseType,
    Priority,
    Step,
    StepKind,
    TestCase,
    ValidationError,
)
from qctool.validate import validate_batch  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_SPEC = Path(__file__).resolve().parent.parent / "samples" / "openapi" / "task-manager-sample.yaml"


# ── Vocabulary đóng ──────────────────────────────────────────────────────────
def test_unknown_verb_rejected():
    """Verb lạ phải bị chặn — đây là thứ khiến output chạy được thay vì chỉ đọc được."""
    step = Step(1, StepKind.WHEN, "click_the_button",
                {"target": "Login"})
    with pytest.raises(ValidationError, match="vocabulary đóng"):
        step.validate()


def test_unknown_verb_suggests_close_match():
    """Gợi ý verb gần giống giúp sửa nhanh."""
    step = Step(1, StepKind.WHEN, "http.requestt", {"method": "GET", "path": "/x"})
    with pytest.raises(ValidationError, match="http.request"):
        step.validate()


def test_missing_required_arg_rejected():
    step = Step(1, StepKind.WHEN, "http.request", {"method": "GET"})  # thiếu path
    with pytest.raises(ValidationError, match="thiếu tham số bắt buộc"):
        step.validate()


def test_unknown_arg_rejected():
    step = Step(1, StepKind.WHEN, "http.request",
                {"method": "GET", "path": "/x", "wrong_arg": 1})
    with pytest.raises(ValidationError, match="tham số lạ"):
        step.validate()


# ── Tính chất của TestCase ───────────────────────────────────────────────────
def _case(**kw) -> TestCase:
    base = dict(
        id="TC_AUTH_001", module="AUTH", title="t", objective="o",
        steps=[Step(1, StepKind.THEN, "assert.http_status", {"expected": 200})],
        traces_to=["AC-1"], source_quote="q",
    )
    return TestCase(**{**base, **kw})


def test_case_without_trace_rejected():
    """Case orphan phải bị chặn — không trả lời được 'sinh ra để kiểm cái gì?'"""
    with pytest.raises(ValidationError, match="orphan"):
        _case(traces_to=[]).validate()


def test_case_without_assert_rejected():
    """Một testcase không kiểm gì cả thì không phải testcase."""
    with pytest.raises(ValidationError, match="không có bước kiểm tra"):
        _case(steps=[Step(1, StepKind.WHEN, "http.request",
                          {"method": "GET", "path": "/x"})]).validate()


def test_case_without_source_quote_rejected():
    with pytest.raises(ValidationError, match="source_quote"):
        _case(source_quote="").validate()


def test_bad_id_format_rejected():
    with pytest.raises(ValidationError, match="sai quy ước"):
        _case(id="AUTH-1").validate()


def test_unmapped_case_cannot_be_marked_pass():
    """Case còn bước văn xuôi không được đánh dấu Pass — nếu không, báo cáo sẽ nói dối."""
    case = _case(
        steps=[
            Step(1, StepKind.WHEN, "perform.unmapped", {"description": "bấm nút"}),
            Step(2, StepKind.THEN, "assert.unmapped", {"expected": "thấy trang chủ"}),
        ],
        status="Pass",
    )
    with pytest.raises(ValidationError, match="chưa map"):
        case.validate()


def test_unmapped_case_allowed_when_not_executed():
    case = _case(steps=[
        Step(1, StepKind.WHEN, "perform.unmapped", {"description": "bấm nút"}),
        Step(2, StepKind.THEN, "assert.unmapped", {"expected": "thấy trang chủ"}),
    ])
    assert case.needs_mapping
    case.validate()          # không được ném lỗi


# ── Loader OpenAPI ───────────────────────────────────────────────────────────
def test_load_sample_spec():
    endpoints, warnings, info = load_endpoints(SAMPLE_SPEC)
    assert len(endpoints) == 7
    assert not warnings
    assert "SAMPLE" in info["title"]


def test_ref_resolver_handles_nested_without_false_cycle():
    """Bug: resolver cũ đếm độ sâu cây nên báo vòng tròn sai ở spec lồng sâu.

    Chỉ `$ref` trỏ vòng tròn thật mới là lỗi; cây lồng 20 tầng thì hợp lệ.
    """
    spec = {
        "components": {"schemas": {
            "A": {"type": "object", "properties": {
                "b": {"$ref": "#/components/schemas/B"},
            }},
            "B": {"type": "object", "properties": {
                "c": {"$ref": "#/components/schemas/C"},
            }},
            "C": {"type": "object", "properties": {"x": {"type": "string"}}},
        }},
    }
    node = {"$ref": "#/components/schemas/A"}
    resolved = resolve_ref(spec, node)
    assert resolved["properties"]["b"]["properties"]["c"]["properties"]["x"]["type"] == "string"


def test_ref_resolver_detects_real_cycle():
    spec = {"components": {"schemas": {
        "A": {"properties": {"self": {"$ref": "#/components/schemas/A"}}},
    }}}
    with pytest.raises(SpecError, match="vòng tròn"):
        resolve_ref(spec, {"$ref": "#/components/schemas/A"})


def test_ref_to_missing_target_reports_clearly():
    spec = {"components": {"schemas": {}}}
    with pytest.raises(SpecError, match="không tồn tại"):
        resolve_ref(spec, {"$ref": "#/components/schemas/Nope"})


# ── Generator ────────────────────────────────────────────────────────────────
def test_generated_cases_all_validate():
    endpoints, _, _ = load_endpoints(SAMPLE_SPEC)
    alloc = IdAllocator()
    cases = [c for ep in endpoints for c in generate_for_endpoint(ep, alloc)]
    assert len(cases) > 40
    for case in cases:
        case.validate()          # ném lỗi nếu case nào hỏng


def test_generated_ids_unique():
    endpoints, _, _ = load_endpoints(SAMPLE_SPEC)
    alloc = IdAllocator()
    cases = [c for ep in endpoints for c in generate_for_endpoint(ep, alloc)]
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids))


def test_generated_cases_all_traced():
    endpoints, _, _ = load_endpoints(SAMPLE_SPEC)
    alloc = IdAllocator()
    cases = [c for ep in endpoints for c in generate_for_endpoint(ep, alloc)]
    assert all(c.traces_to for c in cases)


def test_auth_matrix_generates_401_case():
    """Endpoint cần token phải sinh case kiểm tra truy cập ẩn danh bị chặn."""
    endpoints, _, _ = load_endpoints(SAMPLE_SPEC)
    alloc = IdAllocator()
    health = next(e for e in endpoints if e.path == "/health")
    projects = next(e for e in endpoints if e.path == "/projects" and e.method == "GET")

    health_cases = generate_for_endpoint(health, alloc)
    assert not any(c.case_type == CaseType.SECURITY for c in health_cases), \
        "/health là public, không nên có case kiểm tra token"

    proj_cases = generate_for_endpoint(projects, alloc)
    auth_cases = [c for c in proj_cases if c.case_type == CaseType.SECURITY]
    assert auth_cases, "endpoint cần token phải có case kiểm tra xác thực"


def test_boundary_values_generated_from_constraints():
    """minLength/maxLength/minimum/maximum phải sinh ra case biên."""
    endpoints, _, _ = load_endpoints(SAMPLE_SPEC)
    alloc = IdAllocator()
    create = next(e for e in endpoints if e.path == "/projects" and e.method == "POST")
    cases = generate_for_endpoint(create, alloc)
    boundary = [c for c in cases if c.technique.value == "boundary_value"]
    assert len(boundary) >= 6
    titles = " ".join(c.title for c in boundary)
    assert "vượt tối đa" in titles, "phải có case vượt biên trên"


# ── Generator từ requirement ─────────────────────────────────────────────────


# ── Validator lô ─────────────────────────────────────────────────────────────
def test_validator_finds_gap():
    reqs = [
        {"id": "AC-1", "kind": "acceptance_criterion"},
        {"id": "AC-2", "kind": "acceptance_criterion"},
    ]
    cases = [_case(traces_to=["AC-1"])]
    report = validate_batch(cases, reqs)
    assert report.gaps == {"acceptance_criterion": ["AC-2"]}
    assert report.coverage["acceptance_criterion"] == (1, 2)


def test_validator_finds_orphan_and_duplicate():
    a = _case(id="TC_AUTH_001")
    b = _case(id="TC_AUTH_002")            # y hệt a → trùng nội dung
    report = validate_batch([a, b])
    assert len(report.duplicates) == 1


def test_validator_flags_duplicate_ids():
    a = _case(id="TC_AUTH_001")
    b = _case(id="TC_AUTH_001", title="khác")
    report = validate_batch([a, b])
    assert any("xuất hiện 2 lần" in e for e in report.errors)


def test_full_pipeline_runs():
    """Chạy cả pipeline trên dữ liệu mẫu — không ném lỗi, có case."""
    cases, report, meta = generate_all(
        requirements_path=None, openapi_path=SAMPLE_SPEC, module_override="SAMPLE",
    )
    assert len(cases) > 40
    assert report.total == len(cases)
    assert not report.errors


# ── Hồi quy: spec thật nhiều service, và body "không hợp lệ" ─────────────────
def _write_spec(tmp_path, body: str):
    import yaml

    path = tmp_path / "spec.yaml"
    path.write_text(body, encoding="utf-8")
    return path


MULTI_SERVICE_SPEC = """
openapi: 3.0.0
info: {title: t, version: "1"}
servers:
  - url: https://portal.test/api/v1
paths:
  /thing:
    get:
      operationId: getThing
      responses:
        "200": {description: ok}
  /realms/{realm}/token:
    post:
      operationId: idpToken
      x-external: true
      responses:
        "200": {description: ok}
  /other:
    get:
      operationId: getOther
      servers:
        - url: https://other.test
      responses:
        "200": {description: ok}
"""


def test_external_operation_is_skipped():
    """`x-external: true` là service khác — sinh case cho nó là sinh case luôn sai.

    Spec thật của portal trộn endpoint Keycloak vào cùng file. Tool từng sinh
    8 case rồi chạy trên host portal và nhận 404, báo `Fail` trong khi sản phẩm
    không có lỗi nào.
    """
    import tempfile
    from pathlib import Path as _P

    with tempfile.TemporaryDirectory() as td:
        spec = _write_spec(_P(td), MULTI_SERVICE_SPEC)
        endpoints, warnings, _info = load_endpoints(spec)

    ops = {e.operation_id for e in endpoints}
    assert "idpToken" not in ops
    assert ops == {"getThing", "getOther"}
    assert any("x-external" in w for w in warnings)


def test_operation_level_servers_are_kept():
    """`servers` cấp operation phải được giữ để request đi đúng host."""
    import tempfile
    from pathlib import Path as _P

    with tempfile.TemporaryDirectory() as td:
        spec = _write_spec(_P(td), MULTI_SERVICE_SPEC)
        endpoints, _w, _info = load_endpoints(spec)

    by_op = {e.operation_id: e for e in endpoints}
    assert by_op["getOther"].servers == ["https://other.test"]
    assert by_op["getThing"].servers == []      # dùng servers gốc
    # và bước sinh ra phải mang theo `base`
    cases = generate_for_endpoint(by_op["getOther"], IdAllocator(), [])
    assert cases[0].steps[0].args["base"] == "https://other.test"


INVALID_BODY_SPEC = """
openapi: 3.0.0
info: {title: t, version: "1"}
servers: [{url: https://portal.test}]
paths:
  /me:
    patch:
      operationId: patchMe
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                preferred_locale: {type: [string, "null"]}
      responses:
        "200": {description: ok}
        "422": {description: invalid}
"""


def test_invalid_body_actually_violates_schema():
    """Body cho case 422 phải SAI KIỂU, không phải JSON hợp lệ chứa field lạ.

    `{"__invalid__": true}` là object hợp lệ; server bỏ qua field lạ và trả 200.
    Case "mong đợi 422" vì thế luôn `Fail` dù sản phẩm không có lỗi.
    """
    import tempfile
    from pathlib import Path as _P

    with tempfile.TemporaryDirectory() as td:
        spec = _write_spec(_P(td), INVALID_BODY_SPEC)
        endpoints, _w, _info = load_endpoints(spec)

    cases = generate_for_endpoint(endpoints[0], IdAllocator(), [])
    bad = [c for c in cases if "422" in c.title]
    assert bad, "phải sinh được case 422"

    sent = bad[0].steps[0].args["body"]
    assert sent != {"__invalid__": True}, "body cũ từng lách qua validate của server"
    assert "preferred_locale" in sent, "phải dùng field có thật trong schema"
    assert not isinstance(sent["preferred_locale"], (str, type(None))), \
        "giá trị phải sai kiểu so với schema (string|null)"


def test_wrong_type_value_matches_schema_type():
    from qctool.generate.from_openapi import _wrong_type_value

    assert isinstance(_wrong_type_value({"type": "string"}), int)
    assert isinstance(_wrong_type_value({"type": ["string", "null"]}), int)
    assert isinstance(_wrong_type_value({"type": "integer"}), str)
    assert isinstance(_wrong_type_value({"type": "boolean"}), str)


def test_422_case_without_body_sends_violating_query():
    """Case 422 trên endpoint không có body phải gửi query VI PHẠM.

    `GET /projects` với `page: minimum 1` mà không gửi gì sai thì case "mong đợi
    422" gửi một request hoàn toàn hợp lệ — luôn fail giả, đổ lỗi oan cho sản phẩm.
    """
    from qctool.generate.from_openapi import Endpoint as _Ep, _body_args_for_error

    ep = _Ep(
        method="GET", path="/projects", summary="s", operation_id="listProjects",
        tags=["projects"], requires_auth=True, qc_id=None, priority=Priority.MEDIUM,
        latency_p95_ms=None, test_data={},
        parameters=[{"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1}}],
        request_body=None, request_required=[], responses={"200": {}, "422": {}},
    )
    args = _body_args_for_error(ep, "422")
    assert args.get("query") == {"page": 0}, "phải gửi giá trị dưới minimum"


def test_422_case_with_body_still_sends_bad_body():
    """Có body thì vẫn ưu tiên làm sai body, không đụng tới query."""
    from qctool.generate.from_openapi import Endpoint as _Ep, _body_args_for_error

    ep = _Ep(
        method="POST", path="/projects", summary="s", operation_id="createProject",
        tags=["projects"], requires_auth=True, qc_id=None, priority=Priority.MEDIUM,
        latency_p95_ms=None, test_data={},
        parameters=[{"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1}}],
        request_body={"type": "object", "properties": {"name": {"type": "string"}}},
        request_required=["name"], responses={"201": {}, "422": {}},
    )
    args = _body_args_for_error(ep, "422")
    assert "body" in args and "query" not in args
    assert not isinstance(args["body"]["name"], str)


def test_describe_has_no_internal_vocabulary():
    """Cột Test Steps không được lộ `perform.unmapped:` — người QC đọc cột đó."""
    from qctool.testcase import Step, StepKind

    step = Step(1, StepKind.WHEN, "perform.unmapped",
                {"description": "Bấm Sign in", "expectation": "Redirect IdP"})
    text = step.describe()
    assert "perform.unmapped" not in text
    assert "description=" not in text
    assert text == "Bấm Sign in → Redirect IdP"


def test_slug_keeps_words_separated():
    """`login-sso` → `LOGIN_SSO`, không dồn thành `LOGINSSO`."""
    from qctool.generate.from_openapi import _slug

    assert _slug("login-sso") == "LOGIN_SSO"
    assert _slug("F-PROJ-01") == "PROJ_01"
    assert _slug("auth") == "AUTH"


# ── Hồi quy: phiên ẩn danh — điều kiện để test login/redirect/guard ─────────


def test_unmapped_text_gets_no_internal_vocabulary():
    """Cột Test Steps không lộ `perform.unmapped:` — người QC đọc cột đó."""
    from qctool.testcase import Step

    for action, args, expect in (
        ("perform.unmapped", {"description": "Bấm Sign in", "expectation": "Redirect"},
         "Bấm Sign in → Redirect"),
        ("assert.unmapped", {"expected": "Hiện banner"}, "Kiểm tra: Hiện banner"),
        ("ui.session", {"mode": "anonymous"},
         "Xoá phiên đăng nhập (chạy như người dùng chưa đăng nhập)"),
        ("ui.click", {"target": "sign_in", "by_name": "Sign in"}, "Bấm «Sign in»"),
        ("ui.goto", {"url": "https://x.test/login"}, "Mở https://x.test/login"),
    ):
        text = Step(1, StepKind.WHEN, action, args).describe()
        assert text == expect, f"{action}: {text!r} != {expect!r}"
        assert "unmapped" not in text and "target=" not in text

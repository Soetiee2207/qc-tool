"""Đọc file OpenAPI thành danh sách `Endpoint` mà generator dùng được.

Cố ý hỗ trợ **tối thiểu** những gì generator cần, không giải mã toàn bộ OpenAPI:
`$ref`, `allOf` đơn giản, tham số, body, responses. Spec thật thường có nhiều thứ
kỳ lạ hơn — gặp thì báo rõ chứ không đoán bừa.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from qctool.core.testcase import Priority
from qctool.generate.from_openapi import Endpoint

METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
_SKIP_KEYS = {"parameters", "summary", "description", "$ref"}


class SpecError(Exception):
    """Spec không đọc được. Nói rõ chỗ nào, đừng chỉ báo 'invalid'."""


def load_spec(path: Path) -> dict:
    if not path.is_file():
        raise SpecError(f"Không tìm thấy file spec: {path}")
    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpecError(f"YAML không hợp lệ trong {path}:\n{exc}") from exc
    if not isinstance(spec, dict):
        raise SpecError(f"{path}: nội dung không phải một mapping YAML")
    if "paths" not in spec:
        raise SpecError(f"{path}: thiếu khoá `paths` — không phải file OpenAPI")
    return spec


def resolve_ref(spec: dict, node: dict, _seen: frozenset[str] = frozenset()) -> dict:
    """Thay `$ref` bằng nội dung thật.

    Chống đệ quy bằng cách theo dõi **chuỗi $ref đang đi**, không đếm độ sâu cây.
    Đếm độ sâu cây là sai: một spec bình thường lồng 15 tầng vẫn hợp lệ, trong khi
    `$ref` tự trỏ vào chính nó thì hỏng ngay ở tầng thứ hai. Chỉ vòng lặp $ref thật
    mới là lỗi.
    """
    if not isinstance(node, dict):
        return node

    if "$ref" in node:
        pointer = node["$ref"]
        if not pointer.startswith("#/"):
            raise SpecError(f"Chỉ hỗ trợ `$ref` nội bộ (`#/...`), gặp: {pointer}")
        if pointer in _seen:
            chain = " → ".join([*_seen, pointer])
            raise SpecError(f"`$ref` tự trỏ vòng tròn: {chain}")
        target = spec
        for part in pointer[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                raise SpecError(f"`$ref` trỏ tới chỗ không tồn tại: {pointer}")
            target = target[part]
        merged = dict(resolve_ref(spec, target, _seen | {pointer}))
        merged.update({k: v for k, v in node.items() if k != "$ref"})
        return merged

    out: dict = {}
    for key, value in node.items():
        if key == "allOf":
            combined: dict = {}
            for part in value:
                resolved = resolve_ref(spec, part, _seen)
                combined.update(resolved)
                if "required" in resolved:
                    combined.setdefault("required", [])
                    combined["required"] = list(
                        dict.fromkeys(combined["required"] + resolved["required"])
                    )
            out.update(combined)
        elif isinstance(value, dict):
            out[key] = resolve_ref(spec, value, _seen)
        elif isinstance(value, list):
            out[key] = [resolve_ref(spec, v, _seen) if isinstance(v, dict) else v for v in value]
        else:
            out[key] = value
    return out


def _priority(raw: str | None) -> Priority:
    match (raw or "").lower():
        case "high":
            return Priority.HIGH
        case "low":
            return Priority.LOW
        case _:
            return Priority.MEDIUM


def _build_endpoint(spec: dict, path: str, method: str, op: dict,
                    path_level_params: list[dict], path_level_servers: list[str],
                    warnings: list[str]) -> Endpoint:
    params = list(path_level_params) + list(op.get("parameters", []))
    params = [resolve_ref(spec, p) for p in params]

    body_schema = None
    if rb := op.get("requestBody"):
        rb = resolve_ref(spec, rb)
        content = rb.get("content", {})
        for mime in ("application/json", *content.keys()):
            if mime in content:
                body_schema = resolve_ref(spec, content[mime].get("schema", {}))
                break
        if body_schema is None:
            warnings.append(f"{method.upper()} {path}: có requestBody nhưng không tìm thấy schema JSON")

    responses: dict[str, dict] = {}
    for code, resp in (op.get("responses") or {}).items():
        resp = resolve_ref(spec, resp)
        schema = None
        content = resp.get("content", {})
        for mime in ("application/json", *content.keys()):
            if mime in content:
                schema = resolve_ref(spec, content[mime].get("schema", {}))
                break
        responses[str(code)] = {"schema": schema}

    op_id = op.get("operationId") or f"{method}_{path.strip('/').replace('/', '_')}"
    security = op.get("security")
    requires_auth = security != [] if security is not None else bool(spec.get("security"))

    # `servers` cấp operation thắng cấp path, cấp path thắng cấp file — đúng
    # thứ tự ưu tiên OpenAPI quy định. Endpoint khai server riêng là endpoint
    # thuộc service khác, phải gọi đúng host của nó.
    servers: list[str] = []
    for source in (op.get("servers"), path_level_servers):
        if source:
            servers = [s.get("url", "") for s in source if isinstance(s, dict)]
            servers = [s for s in servers if s]
            break

    return Endpoint(
        method=method.upper(),
        path=path,
        summary=op.get("summary") or f"{method.upper()} {path}",
        operation_id=op_id,
        tags=list(op.get("tags", [])),
        requires_auth=requires_auth,
        qc_id=op.get("x-qc-id"),
        priority=_priority(op.get("x-qc-priority")),
        latency_p95_ms=op.get("x-qc-latency-p95-ms"),
        test_data=dict(op.get("x-qc-test-data", {})),
        parameters=params,
        request_body=body_schema,
        request_required=list((body_schema or {}).get("required", [])),
        responses=responses,
        servers=servers,
        contract_servers=servers or [s["url"] for s in spec.get("servers", [])
                                    if isinstance(s, dict) and isinstance(s.get("url"), str)],
        observe_only=op.get("x-qc-observe-only") is True,
    )


def load_endpoints(path: Path) -> tuple[list[Endpoint], list[str], dict]:
    """Trả (danh sách endpoint, cảnh báo, thông tin spec)."""
    spec = load_spec(path)
    warnings: list[str] = []
    endpoints: list[Endpoint] = []

    for route, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            warnings.append(f"`paths.{route}` không phải mapping — bỏ qua")
            continue
        path_params = [p for p in item.get("parameters", []) if isinstance(p, dict)]
        path_servers = [s for s in item.get("servers", []) if isinstance(s, dict)]
        for method, op in item.items():
            if method.lower() not in METHODS or not isinstance(op, dict):
                continue
            if not op.get("responses"):
                warnings.append(f"{method.upper()} {route}: không có `responses` — bỏ qua")
                continue
            if op.get("x-external") is True:
                # `x-external: true` là quy ước của dự án, không thuộc chuẩn
                # OpenAPI: operation này KHÔNG do service đang test cung cấp.
                #
                # Sinh case cho nó là sinh case luôn sai. Trước đây tool vẫn
                # sinh, rồi chạy trên môi trường thật và nhận 404 — 8 testcase
                # `Fail` trong khi sản phẩm không có lỗi nào. Báo động giả kiểu
                # này nguy hiểm hơn bỏ sót: nó dạy người đọc bỏ qua màu đỏ.
                warnings.append(
                    f"{method.upper()} {route}: `x-external: true` — không phải endpoint "
                    f"của service đang test, bỏ qua (không sinh case)"
                )
                continue
            endpoints.append(_build_endpoint(spec, route, method, op, path_params,
                                             path_servers, warnings))

    if not endpoints:
        raise SpecError(f"{path}: không tìm thấy operation nào")

    info = {
        "title": spec.get("info", {}).get("title", ""),
        "version": spec.get("info", {}).get("version", ""),
        "servers": [s.get("url", "") for s in spec.get("servers", [])],
    }
    return endpoints, warnings, info

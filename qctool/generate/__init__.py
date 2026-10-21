"""Deterministic OpenAPI generation and manual source-preserving standalone output.

Prose with a configured URL/model is authored by qctool.generation, not a mapper.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import yaml

from qctool.core.testcase import TestCase
from qctool.core.validate import Report, validate_batch
from qctool.generate.from_openapi import IdAllocator, generate_for_endpoint
from qctool.generate.loader import load_endpoints


def _module_for(feature: str) -> str:
    """Tên module hiển thị trong cột `Module / Feature Name`.

    Giữ tên feature gốc, chỉ chuẩn hoá dấu phân cách. Tên feature vốn đã dễ đọc
    (`login-sso`, `login-sso`), việc ghép chữ hoa (`LoginSso`) làm nó khó nhận ra
    hơn — mà đây là cột người đọc dùng để lọc và nhóm.
    """
    return (feature or "GEN").replace("/", "-").replace("_", "-").strip() or "GEN"


def generate_all(
    requirements_path: Path | None = None,
    openapi_path: Path | None = None,
    module_override: str | None = None,
) -> tuple[list[TestCase], Report, dict]:
    """Sinh testcase từ mọi nguồn có sẵn. Trả (cases, report, metadata)."""
    cases: list[TestCase] = []
    alloc = IdAllocator()
    meta: dict = {"sources": {}, "unverifiable": [], "warnings": [], "coverage_sources": {}}
    requirements: list[dict] = []
    flow_sources: dict = {}
    endpoint_index: dict = {}

    data: dict = {}
    if requirements_path and requirements_path.is_file():
        data = yaml.safe_load(requirements_path.read_text(encoding="utf-8")) or {}
        requirements = data.get("requirements", [])
        default_module = module_override or data.get("feature", "GEN")
        meta["sources"]["requirements"] = {
            "path": str(requirements_path), "total": len(requirements),
            "features": data.get("features", []),
        }

        endpoint_index = _endpoint_index(requirements)
        meta["linked_endpoints"] = len(endpoint_index)

        flow_sources = data.get("flows") or {}
        if flow_sources:
            meta["sources"]["flows"] = _flow_source_summary(flow_sources)

    if openapi_path and openapi_path.is_file():
        endpoints, warnings, info = load_endpoints(openapi_path)
        endpoint_list = [{"path": ep.path, "method": ep.method,
                          "operation_id": ep.operation_id} for ep in endpoints]
        # Danh sách endpoint phải nằm trong `sources.openapi` chứ không chỉ ở
        # `meta["endpoints"]` — `write_cases` chỉ ghi `sources`, nên để ở ngoài là
        # mất khi đọc lại file, và lượt chạy sau không biết đường dẫn nào có thật.
        meta["sources"]["openapi"] = {"path": str(openapi_path), **info,
                                      "endpoints": endpoint_list}
        meta["warnings"].extend(warnings)
        skipped: list[str] = []
        for ep in endpoints:
            if ep.observe_only:
                # Ví dụ POST /api/orders trên production: sinh case "trả 201 khi hợp lệ"
                # là tạo đơn thật. Chỉ agent (mode write, đã xác nhận) mới được gọi.
                skipped.append(f"{ep.method} {ep.path}: x-qc-observe-only — không sinh case API tự động")
                continue
            emitted = generate_for_endpoint(ep, alloc, skipped)
            # A declared contract operation is an explicit source even without
            # x-qc-id. This is not coverage of an unrelated business requirement.
            for case in emitted:
                if not case.traces_to:
                    case.traces_to = ['openapi:' + ep.operation_id]
            cases.extend(emitted)
        meta["skipped"] = skipped
        meta["endpoints"] = endpoint_list

    # Case API trace về functional requirement tương ứng nếu khớp đường dẫn.
    # Không nối được thì để nguyên — case vẫn hợp lệ, chỉ là chưa gắn được vào
    # requirement nào trong SRS, và validator sẽ nhắc.
    meta["linked_cases"] = _link_api_cases(cases, endpoint_index)

    if requirements or flow_sources:
        # Standalone generate without a URL/model cannot dry-run. Preserve source
        # as manual intents; the normal pipeline supplies agent/runtime inputs.
        from qctool.generation import run_generation
        outcome = run_generation(requirements, existing_cases=cases, flows=flow_sources,
                                 module=module_override or data.get('feature', 'GEN'))
        cases = list(outcome.cases)
    meta["coverage_sources"] = _coverage_universe(requirements, flow_sources)
    report = validate_batch(cases, requirements or None,
                            sources=meta["coverage_sources"] or None)
    return cases, report, meta


def _feature_of(req: dict) -> str:
    """Feature mà một requirement thuộc về.

    ID canonical đã mang tiền tố feature (`AC-login-sso-001-2`), nhưng tên feature
    có thể chứa dấu `-` nên không tách được bằng `split("-")`. Dùng khoá tường
    minh từ lúc ingest, fallback về nhóm theo tiền tố ID.
    """
    if feature := req.get("feature"):
        return feature
    rid = req.get("id", "")
    source = (req.get("source") or {}).get("file", "")
    # `source.file` là đường dẫn tương đối trong feature; khi gộp nhiều feature
    # ingest_tree đã ghi kèm feature vào `source.file` nếu cần.
    return req.get("_feature") or (source.split("/")[0] if "/" in source else "") or rid.split("-")[0]


def _flow_source_summary(flows: dict) -> dict:
    from qctool.ingest.flows import counts

    return {"counts": counts(flows), "features": len(flows)}


def _endpoint_index(requirements: list[dict]) -> dict[tuple[str, str], str]:
    """`(METHOD, đường-dẫn-chuẩn-hoá)` → ID functional requirement.

    SRS viết `GET /api/v1/auth/me`, OAS khai `/auth/me`. Bỏ tiền tố `/api/v1` (và
    các biến thể có version) thì hai bên khớp nhau, và case API trace được về FR —
    thay vì đứng một mình như case mồ côi.
    """
    index: dict[tuple[str, str], str] = {}
    for req in requirements:
        if req.get("kind") != "functional":
            continue
        api = req.get("api") or {}
        endpoint = api.get("endpoint") or ""
        if not endpoint:
            continue
        parts = endpoint.split()
        if len(parts) != 2:
            continue
        method, path = parts[0].upper(), parts[1]
        index[(method, _normalise_path(path))] = req["id"]
    return index


def _normalise_path(path: str) -> str:
    """Bỏ tiền tố version để so khớp giữa tài liệu và spec."""
    import re as _re

    path = path.strip()
    path = _re.sub(r"^/api/v\d+(\.\d+)?", "", path, flags=_re.I)
    return path if path.startswith("/") else "/" + path


def _link_api_cases(cases: list[TestCase], index: dict[tuple[str, str], str]) -> int:
    """Gắn case API về functional requirement tương ứng. Trả số case đã nối."""
    linked = 0
    for case in cases:
        if case.traces_to:
            continue
        for step in case.steps:
            if step.action != "http.request":
                continue
            method = str(step.args.get("method", "")).upper()
            path = _normalise_path(str(step.args.get("path", "")))
            if req_id := index.get((method, path)):
                case.traces_to = [req_id]
                linked += 1
            break
    return linked


def _coverage_universe(requirements: list[dict], flows: dict) -> dict:
    """Mọi thứ lẽ ra phải có testcase — để đo độ phủ ở chặng report.

    Trả `{loại: {id: mô tả ngắn}}`. Report đối chiếu tập này với `traces_to` của
    testcase sinh ra để biết còn sót gì.
    """
    universe: dict[str, dict[str, str]] = {}

    for req in requirements:
        kind = req.get("kind", "unknown")
        universe.setdefault(kind, {})[req["id"]] = (req.get("title") or "")[:70]

    per_feature = ({"": flows} if "counts" in (flows or {}) else (flows or {}))
    for payload in per_feature.values():
        if not isinstance(payload, dict):
            continue
        for kind in ("flow", "decision", "transition", "error_surface", "scenario"):
            for item in payload.get(kind, []):
                label = (item.get("title") or item.get("flow")
                         or item.get("condition") or item.get("trigger")
                         or item.get("surface") or "")
                if kind == "transition":
                    label = f'{item.get("from_state")} → {item.get("to_state")}'
                universe.setdefault(kind, {})[item["id"]] = _clean_label(label)

    return universe


def _clean_label(text: str) -> str:
    return " ".join((text or "").split())[:70]


def write_cases(cases: list[TestCase], out_path: Path, meta: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_by": "qc-tool generate",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "summary": {
            "total": len(cases),
            "by_type": _count(c.case_type.value for c in cases),
            "by_technique": _count(c.technique.value for c in cases),
            "by_priority": _count(c.priority.value for c in cases),
            "needs_mapping": sum(1 for c in cases if c.needs_mapping),
        },
        "sources": meta["sources"],
        "unverifiable": meta["unverifiable"],
        "skipped": meta.get("skipped", []),
        "warnings": meta["warnings"],
        "testcases": [c.to_dict() for c in cases],
    }

    header = (
        "# Sinh tự động bởi qc-tool — KHÔNG sửa tay.\n"
        "# Sửa nguồn (tài liệu / OpenAPI) rồi chạy lại: qctool step generate ...\n"
        "#\n"
        "# Case có `needs_mapping: true` là case sinh từ acceptance criterion bằng văn xuôi —\n"
        "# phải map sang hành động cụ thể trước khi chạy tự động được.\n"
    )
    body = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=100)
    out_path.write_text(header + body, encoding="utf-8")


def _count(values) -> dict:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return out

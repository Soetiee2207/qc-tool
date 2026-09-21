"""Kiểm tra file OpenAPI trước khi đưa cho tool.

Chạy:   uv run scripts/validate_openapi.py templates/api/openapi-template.yaml

Kiểm tra:
  - YAML hợp lệ
  - có 3 khoá bắt buộc: openapi, info, paths
  - mỗi operation có ít nhất 1 response
  - cảnh báo field còn để trống / TODO chưa điền
  - điểm lại số endpoint, số response, các field x-qc-* tìm được
"""

import sys
from pathlib import Path

import yaml

METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
REQUIRED_TOP = ["openapi", "info", "paths"]


def check(path: Path) -> int:
    """Trả về số lỗi (0 = đạt)."""
    errors: list[str] = []
    warnings: list[str] = []

    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"LỖI  YAML không hợp lệ:\n{exc}")
        return 1

    if not isinstance(spec, dict):
        print("LỖI  File không phải một mapping YAML ở cấp cao nhất.")
        return 1

    for key in REQUIRED_TOP:
        if key not in spec:
            errors.append(f"Thiếu khoá bắt buộc ở cấp cao nhất: `{key}`")

    if "paths" not in spec:
        report(path, spec, errors, warnings)
        return 1

    endpoints: list[tuple[str, str, dict]] = []
    for route, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            errors.append(f"`paths.{route}` không phải một mapping.")
            continue
        for method, op in item.items():
            if method.lower() not in METHODS:
                continue
            if not isinstance(op, dict):
                errors.append(f"`{method.upper()} {route}` không phải một mapping.")
                continue
            endpoints.append((method.upper(), route, op))

            if not op.get("responses"):
                errors.append(f"`{method.upper()} {route}` không khai báo `responses`.")
            if not op.get("summary"):
                warnings.append(f"`{method.upper()} {route}` thiếu `summary` — tool sẽ đặt tên testcase kém hơn.")

    if not endpoints:
        errors.append("Không tìm thấy operation nào trong `paths`.")

    raw = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(raw.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#") and "TODO" in stripped.upper():
            warnings.append(f"dòng {lineno}: còn TODO chưa điền — {stripped.lstrip('# ')[:70]}")

    return report(path, spec, errors, warnings, endpoints)


def report(path, spec, errors, warnings, endpoints=None) -> int:
    endpoints = endpoints or []
    print(f"File: {path}")
    print(f"  title  : {spec.get('info', {}).get('title', '(chưa có)')}")
    print(f"  version: {spec.get('info', {}).get('version', '(chưa có)')}")
    servers = spec.get("servers") or []
    print(f"  servers: {', '.join(s.get('url', '?') for s in servers) or '(chưa khai báo)'}")
    print(f"  endpoints: {len(endpoints)}")
    for method, route, op in endpoints:
        flag = op.get("x-qc-id", "—")
        auth = op.get("x-qc-requires-auth")
        auth_s = {True: "cần token", False: "public", None: "?"}[auth]
        nresp = len(op.get("responses") or {})
        print(f"    {method:<6} {route:<34} x-qc-id={flag:<8} {auth_s:<10} {nresp} response")
    n_xqc = sum(1 for _m, _r, op in endpoints for k in op if k.startswith("x-qc-"))
    print(f"  field x-qc-*: {n_xqc}")
    print()

    for w in warnings:
        print(f"CẢNH BÁO  {w}")
    for e in errors:
        print(f"LỖI      {e}")

    if errors:
        print(f"\n→ {len(errors)} lỗi, {len(warnings)} cảnh báo.")
        return len(errors)
    print(f"→ Đạt. {len(warnings)} cảnh báo.")
    return 0


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"LỖI  Không tìm thấy file: {path}")
        raise SystemExit(2)
    raise SystemExit(1 if check(path) else 0)


if __name__ == "__main__":
    main()

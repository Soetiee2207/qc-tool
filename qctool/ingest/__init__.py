"""Chặng 1 — Ingest: tài liệu → requirements.yaml.

Gom tài liệu yêu cầu về một manifest có ID ổn định + content hash + trích dẫn nguồn.

Đây là **nền móng**. Không có hash thì mỗi lần tài liệu đổi phải sinh lại toàn bộ
và mất hết công review — xem brainstorm §3.1.

Nhận **một feature** (thư mục có `urd.md`/`srs.md`) hoặc **cả cây tài liệu**
(thư mục cha chứa nhiều feature con). Trường hợp thứ hai là cách dùng thật: người
dùng trỏ vào `docs/` của repo, không phải từng feature một.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import yaml

from ..model import Attachment, Requirement, file_sha256
from . import flows as flows_mod
from . import markdown

# Tài liệu chính: parse sâu để lấy requirement
PRIMARY_DOCS = {
    "urd.md": "urd",
    "srs.md": "srs",
}

# Tài liệu phụ: glob tương đối trong từng thư mục feature.
#
# Trước đây là path cứng (`srs/login-sso-flows.md`) — chỉ đúng cho một feature duy
# nhất. Đổi sang glob để feature nào có file cùng vai trò cũng được nhận.
ATTACHMENT_GLOBS = [
    ("srs/*flow*.md", "flows"),
    ("srs/*state*.md", "states"),
    ("ascii-screen/*.md", "wireframe"),
    ("brainstorms/*.md", "brainstorm"),
]

# Thư mục không bao giờ chứa tài liệu yêu cầu — bỏ qua khi quét cây.
SKIP_DIRS = {"OAS", ".git", "node_modules", "__pycache__", ".venv", "venv",
             "reports", "artifacts", ".pytest_cache", "dist", "build"}

KIND_ORDER = {
    "user_story": 0,
    "acceptance_criterion": 1,
    "functional": 2,
    "non_functional": 3,
}

MAX_DEPTH = 6


class NoDocuments(Exception):
    """Không tìm thấy tài liệu nào — kèm gợi ý đường dẫn đúng."""


def discover_features(root: Path, max_depth: int = MAX_DEPTH) -> list[Path]:
    """Tìm mọi thư mục con có tài liệu yêu cầu, quét theo chiều sâu.

    Trả về danh sách **đã sắp xếp** để thứ tự chạy ổn định giữa các lần (quan
    trọng: ID testcase sinh theo thứ tự, không sắp xếp thì mỗi lần chạy ra một
    bộ ID khác nhau và diff vô nghĩa).
    """
    found: list[Path] = []
    root = root.resolve()

    def walk(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(directory.iterdir())
        except (PermissionError, OSError):
            return
        if any((directory / name).is_file() for name in PRIMARY_DOCS):
            found.append(directory)
            return                      # feature đã tìm thấy thì không đệ quy tiếp
        for entry in entries:
            if entry.is_dir() and entry.name not in SKIP_DIRS and not entry.name.startswith("."):
                walk(entry, depth + 1)

    walk(root, 0)
    return found


def _attachments(feature_dir: Path) -> list[Attachment]:
    out: list[Attachment] = []
    for pattern, doc_type in ATTACHMENT_GLOBS:
        for path in sorted(feature_dir.glob(pattern)):
            if path.is_file():
                out.append(Attachment(
                    path=str(path.relative_to(feature_dir)),
                    doc_type=doc_type,
                    sha256=file_sha256(path),
                ))
    return out


def ingest_one(feature_dir: Path, feature: str) -> dict:
    """Đọc một thư mục tài liệu feature → dict sẵn sàng ghi YAML."""
    requirements: list[Requirement] = []
    warnings: list[str] = []
    sources: list[dict] = []

    for filename, doc_type in PRIMARY_DOCS.items():
        path = feature_dir / filename
        if not path.is_file():
            warnings.append(f"Thiếu tài liệu chính: {filename}")
            continue
        sources.append({
            "path": filename, "type": doc_type, "sha256": file_sha256(path),
        })
        found, warns = markdown.parse_markdown(path, feature, doc_type)
        requirements.extend(found)
        warnings.extend(warns)

    attachments = _attachments(feature_dir)

    # Luồng nghiệp vụ: sequence diagram, state machine, bảng quyết định…
    # Đây là nguồn case UI tốt nhất — xem `flows.py`.
    flow_data = flows_mod.extract(feature_dir, feature, warnings)

    requirements = _dedupe(requirements, warnings)
    requirements.sort(key=lambda r: (KIND_ORDER.get(r.kind, 9), r.id))
    return {
        "feature": feature,
        "feature_dir": str(feature_dir),
        "generated_by": "qc-tool ingest",
        "counts": _counts(requirements),
        "sources": sources,
        "attachments": [a.to_dict() for a in attachments],
        "flows": flow_data,
        "warnings": warnings,
        "requirements": [r.to_dict() for r in requirements],
    }


def ingest_feature(feature_dir: Path, feature: str | None = None) -> dict:
    """Đọc tài liệu từ một thư mục — hoặc cả cây nếu đó là thư mục cha.

    Thư mục có `urd.md`/`srs.md` → đọc như một feature.
    Thư mục cha (không có file nào ở cấp gốc) → quét tìm mọi feature con.

    Vì sao cần nhánh thứ hai: người dùng trỏ vào `docs/` của repo, nơi mỗi feature
    nằm trong thư mục riêng. Trước đây tool tìm `urd.md` ngay cấp gốc, không thấy,
    rồi báo "0 requirement" — trong khi tài liệu nằm ngay đó, chỉ sâu hơn một cấp.
    """
    feature_dir = feature_dir.resolve()
    if not feature_dir.is_dir():
        raise NoDocuments(f"Không thấy thư mục tài liệu: {feature_dir}")

    has_docs = any((feature_dir / name).is_file() for name in PRIMARY_DOCS)
    if has_docs:
        data = ingest_one(feature_dir, feature or feature_dir.name)
        data["features"] = [data["feature"]]
        return data

    found = discover_features(feature_dir)
    if not found:
        raise NoDocuments(
            f"Không tìm thấy tài liệu yêu cầu nào trong {feature_dir}.\n"
            f"  Đã quét tối đa {MAX_DEPTH} cấp, tìm file: "
            f"{', '.join(PRIMARY_DOCS)}\n"
            f"  Nếu tài liệu nằm ở thư mục khác, trỏ thẳng vào thư mục chứa "
            f"`urd.md` / `srs.md`."
        )

    if len(found) == 1:
        data = ingest_one(found[0], feature or found[0].name)
        data["features"] = [data["feature"]]
        data["root"] = str(feature_dir)
        return data

    return ingest_tree(found, root=feature_dir)


def ingest_tree(dirs: list[Path], root: Path) -> dict:
    """Gộp nhiều feature thành một manifest.

    Mỗi feature giữ requirement riêng; ID đã được scope theo feature ở `ids.canonical`
    nên không đè lên nhau dù tài liệu đánh số trùng (`US-001` xuất hiện ở 15 feature
    khác nhau trong repo portal — xem `ids.canonical`).
    """
    requirements: list[Requirement] = []
    warnings: list[str] = []
    per_feature: list[dict] = []
    attachments: list[Attachment] = []
    flows: dict = {}

    for directory in dirs:
        name = directory.name
        try:
            rel = str(directory.relative_to(root))
        except ValueError:
            rel = name
        try:
            data = ingest_one(directory, name)
        except Exception as exc:                        # noqa: BLE001
            warnings.append(f"{rel}: đọc lỗi — {type(exc).__name__}: {exc}")
            continue

        per_feature.append({
            "feature": name,
            "path": rel,
            "counts": data["counts"],
            "warnings": len(data["warnings"]),
        })
        warnings.extend(f"{rel}: {w}" for w in data["warnings"])
        requirements.extend(_as_requirement(r) for r in data["requirements"])
        attachments.extend(Attachment(**a) for a in data["attachments"])
        if data["flows"]:
            flows[name] = data["flows"]

    requirements = _dedupe(requirements, warnings)
    requirements.sort(key=lambda r: (r.id.split("-")[0], r.id))

    return {
        "feature": root.name,
        "root": str(root),
        "generated_by": "qc-tool ingest",
        "counts": _counts(requirements),
        "features": [f["feature"] for f in per_feature],
        "per_feature": per_feature,
        "sources": [],
        "attachments": [a.to_dict() for a in attachments],
        "flows": flows,
        "warnings": warnings,
        "requirements": [r.to_dict() for r in requirements],
    }


def _as_requirement(raw: dict) -> Requirement:
    """Dựng lại `Requirement` từ dict đã `to_dict()`.

    Cần vì `ingest_one` trả dict (để ghi YAML), còn bước gộp nhiều feature phải
    thao tác trên object. Đi qua lại chỉ ở đây, không rải khắp code.
    """
    from ..model import ApiSpec, SourceRef

    known = {f for f in Requirement.__dataclass_fields__}
    data = {k: v for k, v in raw.items() if k in known}
    if api := data.get("api"):
        data["api"] = ApiSpec(**{k: v for k, v in api.items()
                                 if k in ApiSpec.__dataclass_fields__})
    if src := data.get("source"):
        data["source"] = SourceRef(**{k: v for k, v in src.items()
                                      if k in SourceRef.__dataclass_fields__})
    return Requirement(**data)


def _dedupe(requirements: list[Requirement], warnings: list[str]) -> list[Requirement]:
    """Bỏ requirement trùng ID — giữ bản đầu, báo cảnh báo."""
    seen: dict[str, Requirement] = {}
    for req in requirements:
        if req.id in seen:
            warnings.append(
                f"Trùng ID `{req.id}` (nguồn {req.source_ids}) — giữ bản ở "
                f"{seen[req.id].source.file if seen[req.id].source else '?'}, bỏ bản sau"
            )
            continue
        seen[req.id] = req
    return list(seen.values())


def _counts(requirements: list[Requirement]) -> dict:
    counts: dict[str, int] = {}
    for req in requirements:
        counts[req.kind] = counts.get(req.kind, 0) + 1
    for group in ("SEC", "PERF", "AVAIL", "I18N", "OBS"):
        n = sum(1 for r in requirements if r.category == group)
        if n:
            counts[f"non_functional:{group}"] = n
    counts["total"] = len(requirements)
    return counts


def write_yaml(data: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(
        data, allow_unicode=True, sort_keys=False, width=100, default_flow_style=False,
    )
    header = (
        "# Sinh tự động bởi qc-tool — KHÔNG sửa tay.\n"
        "# Sửa tài liệu nguồn rồi chạy lại: uv run qctool ingest <feature-dir>\n"
        f"# generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} (GMT+7)\n"
        "#\n"
        "# `content_hash` chỉ tính trên nội dung ngữ nghĩa của requirement — sửa chỗ khác\n"
        "# trong file không làm nó đổi. Đây là cơ sở để sinh lại tăng dần thay vì làm lại từ đầu.\n"
    )
    out_path.write_text(header + body, encoding="utf-8")


def summary(data: dict) -> str:
    c = data["counts"]
    features = data.get("features") or [data["feature"]]
    lines = [
        f"Feature: {data['feature']}",
    ]
    if len(features) > 1:
        lines.append(f"  số feature            : {len(features)}")
    lines += [
        f"  user story            : {c.get('user_story', 0)}",
        f"  acceptance criterion  : {c.get('acceptance_criterion', 0)}",
        f"  functional (FR)       : {c.get('functional', 0)}",
        f"  non-functional (NFR)  : {c.get('non_functional', 0)}",
    ]
    nfr_breakdown = [
        f"{g} {c[f'non_functional:{g}']}"
        for g in ("SEC", "PERF", "AVAIL", "I18N", "OBS")
        if f"non_functional:{g}" in c
    ]
    if nfr_breakdown:
        lines.append(f"    theo nhóm           : {', '.join(nfr_breakdown)}")
    lines.append(f"  TỔNG                  : {c.get('total', 0)}")
    lines.append(f"  tài liệu phụ          : {len(data['attachments'])}")

    flow_counts = flows_mod.counts(data.get("flows"))
    if flow_counts:
        lines.append("  luồng nghiệp vụ       : " + " · ".join(
            f"{k} {v}" for k, v in flow_counts.items()))

    if data["warnings"]:
        lines.append("")
        lines.append(f"  ⚠ {len(data['warnings'])} cảnh báo:")
        for w in data["warnings"][:15]:
            lines.append(f"    - {w}")
        if len(data["warnings"]) > 15:
            lines.append(f"    … và {len(data['warnings']) - 15} cảnh báo nữa")
    return "\n".join(lines)

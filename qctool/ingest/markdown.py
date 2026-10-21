"""Parser tài liệu markdown → danh sách Requirement.

Chỉ hỗ trợ `.md` ở M01 (quyết định D5). `.docx`/`.pdf` làm sau — parser dễ vỡ hơn
và 2 tài liệu pilot đều là markdown.

Nguyên tắc: **không đoán**. Thấy gì ghi nấy. Chỗ nào tài liệu không nói rõ thì
để trống và ghi vào danh sách cảnh báo, không tự suy diễn.
"""

from __future__ import annotations

import re
from pathlib import Path

from qctool.core.model import ApiSpec, Requirement, SourceRef
from qctool.ingest import ids

# ── Nhận dạng cấu trúc ───────────────────────────────────────────────────────
H_US = re.compile(r"^###\s+(US-\d{3})\s+—\s+(.+?)\s*$")
H_AC_TABLE = re.compile(r"^\*\*Acceptance Criteria\*\*\s*$")
H_NFR_GROUP = re.compile(r"^###\s+\d+\.\d+\.?\s+(.+?)\s*\(NFR-([A-Z0-9]+)\)\s*$")
H_FUNC_DETAIL = re.compile(r"^####\s+\d+\.\d+\.\d+\.\s+(F-\d{2})\s+(.+?)\s*$")
H_SECTION = re.compile(r"^#{1,5}\s")
H_SUBSECTION = re.compile(r"^#####\s+(.+?)\s*$")
H_TABLE_ROW = re.compile(r"^\|(.+)\|\s*$")
TABLE_SEP = re.compile(r"^\|[\s:\-|]+\|\s*$")
BOLD = re.compile(r"\*\*(.+?)\*\*")
CODE = re.compile(r"`([^`]+)`")

NFR_GROUP_LABEL = {
    "SEC": "Security",
    "PERF": "Performance",
    "AVAIL": "Availability",
    "I18N": "i18n",
    "OBS": "Observability",
}


def _strip_md(text: str) -> str:
    """Bỏ định dạng markdown, giữ nội dung chữ."""
    text = BOLD.sub(r"\1", text)
    text = CODE.sub(r"\1", text)
    text = text.replace("\\|", "|")
    return text.strip()


def _cells(line: str) -> list[str]:
    """Tách một hàng bảng markdown thành các ô.

    Phải tôn trọng dấu `\\|` — tài liệu dùng nó để viết kiểu union như
    `string\\|null` bên trong một ô. Nếu cắt thẳng theo `|`, ô đó bị vỡ thành
    hai và mọi cột phía sau lệch đi một ô.
    """
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]

    cells: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == "\\" and i + 1 < len(inner) and inner[i + 1] == "|":
            buf.append("|")          # trả về ký tự thật, bỏ dấu thoát
            i += 2
            continue
        if ch == "|":
            cells.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    cells.append("".join(buf).strip())
    return cells


def _tables(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    """Đọc bảng markdown liền mạch bắt đầu từ `start`. Trả (hàng, dòng kế tiếp).

    Bỏ qua dòng trống trước bảng — tài liệu thật hay có dòng trống giữa tiêu đề
    và bảng, và nếu không nhảy qua thì mọi bảng đều đọc ra rỗng.

    Bỏ luôn **hàng tiêu đề**: trong markdown, hàng tiêu đề là hàng ngay trước
    dòng phân cách `| --- | --- |`. Nhận diện bằng vị trí như vậy chắc hơn là
    đoán theo tên cột — tài liệu mỗi nơi đặt tiêu đề một kiểu.
    """
    rows: list[list[str]] = []
    i = start
    while i < len(lines) and not lines[i].strip():
        i += 1
    while i < len(lines):
        line = lines[i]
        if not H_TABLE_ROW.match(line):
            break
        if TABLE_SEP.match(line):
            # Hàng ngay trước dòng phân cách chính là hàng tiêu đề → bỏ
            if rows:
                rows.pop()
            i += 1
            continue
        rows.append(_cells(line))
        i += 1
    return rows, i


# ── URD: user story + acceptance criteria ────────────────────────────────────
US_FIELD = {
    "**As a**": "as_a",
    "**I want**": "i_want",
    "**So that**": "so_that",
}


def parse_urd(path: Path, feature: str) -> tuple[list[Requirement], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    rel = path.name
    out: list[Requirement] = []
    warnings: list[str] = []

    i = 0
    while i < len(lines):
        if m := H_US.match(lines[i]):
            us_raw, title = m.group(1), m.group(2).strip()
            us_id = ids.canonical(us_raw, feature)
            start_line = i + 1
            us = Requirement(
                id=us_id,
                kind="user_story",
                title=_strip_md(title),
                source_ids=[us_raw],
                source=SourceRef(file=rel, line=start_line, quote=lines[i].strip()),
            )
            i += 1

            # thân user story: As a / I want / So that
            while i < len(lines) and not H_AC_TABLE.match(lines[i]):
                if H_SECTION.match(lines[i]) and not lines[i].startswith("**"):
                    break
                raw = lines[i].strip()
                for prefix, attr in US_FIELD.items():
                    if raw.startswith(prefix):
                        setattr(us, attr, _strip_md(raw[len(prefix):]))
                i += 1

            # bảng acceptance criteria
            if i < len(lines) and H_AC_TABLE.match(lines[i]):
                i += 1
                rows, i = _tables(lines, i)
                for row in rows:
                    if len(row) < 4:
                        continue
                    ac_raw = _strip_md(row[0])
                    if not ids.AC_RE.match(ac_raw):
                        continue
                    out.append(Requirement(
                        id=ids.canonical(ac_raw, feature),
                        kind="acceptance_criterion",
                        title=f"{_strip_md(row[3])[:80]}",
                        source_ids=[ac_raw],
                        belongs_to=us_id,
                        traces_to=[us_id],
                        given=_strip_md(row[1]),
                        when=_strip_md(row[2]),
                        then=_strip_md(row[3]),
                        source=SourceRef(file=rel, line=start_line, quote=row[3].strip()),
                    ))
            out.append(us)
            continue
        i += 1

    if not out:
        warnings.append(f"{rel}: không tìm thấy user story nào (mẫu `### US-001 — …`)")
    return out, warnings


# ── SRS: functional requirements ─────────────────────────────────────────────
def parse_srs_functions(path: Path, feature: str) -> tuple[list[Requirement], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    rel = path.name
    out: list[Requirement] = []
    warnings: list[str] = []

    # Bảng "Function List" §3.1 cho tên + US trace
    index: dict[str, dict] = {}
    for i, line in enumerate(lines):
        if line.strip().startswith("| F-") and "|" in line:
            row = _cells(line)
            if len(row) >= 4 and ids.FR_RE.match(_strip_md(row[0])):
                index[_strip_md(row[0])] = {
                    "title": _strip_md(row[1]),
                    "impl": _strip_md(row[2]),
                    "us": _strip_md(row[3]),
                }

    # Thân chi tiết §3.2.x
    i = 0
    while i < len(lines):
        if m := H_FUNC_DETAIL.match(lines[i]):
            fid, title = m.group(1), m.group(2).strip()
            start = i + 1
            block_end = len(lines)
            j = i + 1
            while j < len(lines):
                if H_FUNC_DETAIL.match(lines[j]) or re.match(r"^##\s+4\.", lines[j]):
                    block_end = j
                    break
                j += 1

            req = Requirement(
                id=ids.canonical(fid, feature),
                kind="functional",
                title=_strip_md(title),
                source_ids=[fid],
                source=SourceRef(file=rel, line=start, quote=title),
                api=ApiSpec(),
            )
            meta = index.get(fid, {})
            if meta.get("us"):
                req.traces_to = [ids.canonical(meta["us"], feature)]
            if meta.get("impl") and meta["impl"] != "—":
                req.api.implementation = meta["impl"]

            _parse_function_block(lines, start, block_end, req, warnings)
            out.append(req)
            i = block_end
            continue
        i += 1

    if not out:
        warnings.append(f"{rel}: không tìm thấy functional requirement nào (mẫu `#### 3.2.1. F-01 …`)")
    return out, warnings


def _parse_function_block(
    lines: list[str], start: int, end: int, req: Requirement, warnings: list[str]
) -> None:
    """Đọc các mục A/B bên trong một function detail.

    Theo dõi "mục đang đọc" **tiến về phía trước** thay vì dò ngược lại khi gặp
    bảng. Dò ngược rất dễ bắt nhầm nhãn của mục khác khi một mục có nhiều bảng
    liên tiếp (Request / Response / Error responses nằm chung mục B).
    """
    i = start
    api = req.api
    assert api is not None
    target = "unknown"          # mục đang đọc: flow | api | impl | ...

    while i < end:
        raw = lines[i].strip()

        # ── Nhãn mục: đổi target ────────────────────────────────────────────
        if H_SUBSECTION.match(lines[i]):
            head = raw.lower()
            if "flow" in head:
                target = "flow"
            elif "api specification" in head:
                target = "api"
            elif "implementation" in head:
                target = "impl"
            else:
                target = "unknown"
            i += 1
            continue

        if raw.startswith("**Request**"):
            target = "request"
            i += 1
            continue
        if raw.startswith("**Response 200**") or raw.startswith("**Response**"):
            target = "response"
            i += 1
            continue
        if raw.startswith("**Error responses**"):
            target = "errors"
            i += 1
            continue
        if raw.startswith("**Error handling**"):
            target = "error_handling"
            i += 1
            continue

        if raw.startswith("**Traceability:**"):
            value = _strip_md(raw.replace("**Traceability:**", ""))
            if value and value not in req.traces_to:
                req.traces_to.append(value)
            i += 1
            continue

        if raw.startswith("**Location:**"):
            api.implementation = _strip_md(raw.replace("**Location:**", ""))
            i += 1
            continue

        if raw.startswith("**Endpoint:**"):
            api.endpoint = _strip_md(raw.replace("**Endpoint:**", ""))
            i += 1
            continue

        if raw.startswith("**Method:**"):
            api.method = _strip_md(raw.replace("**Method:**", ""))
            i += 1
            continue

        if raw.startswith("**Auth:**"):
            api.auth = _strip_md(raw.replace("**Auth:**", ""))
            target = "unknown"
            i += 1
            continue

        # ── Bảng: phân loại theo target đang mở ─────────────────────────────
        if H_TABLE_ROW.match(lines[i]):
            rows, i = _tables(lines, i)
            _store_table(rows, target, api)
            continue

        i += 1


def _store_table(rows: list[list[str]], target: str, api: ApiSpec) -> None:
    for row in rows:
        if target == "flow" and len(row) >= 3:
            api.flow.append(_strip_md(row[2]))
        elif target == "request" and len(row) >= 5:
            api.request.append({
                "no": _strip_md(row[0]), "field": _strip_md(row[1]),
                "type": _strip_md(row[2]), "default": _strip_md(row[3]),
                "required": _strip_md(row[4]),
                "description": _strip_md(row[5]) if len(row) > 5 else "",
            })
        elif target == "response" and len(row) >= 3:
            api.response.append({
                "no": _strip_md(row[0]),
                "field": _strip_md(row[1]),
                "type": _strip_md(row[2]),
                "description": _strip_md(row[3]) if len(row) > 3 else "",
            })
        elif target == "errors" and len(row) >= 3:
            api.errors.append({
                "http": _strip_md(row[0]), "condition": _strip_md(row[1]),
                "detail": _strip_md(row[2]),
            })
        elif target == "error_handling" and len(row) >= 2:
            api.error_handling.append({
                "condition": _strip_md(row[0]), "behavior": _strip_md(row[1]),
            })


def parse_srs_responses(path: Path, feature: str) -> tuple[dict[str, list[dict]], list[str]]:
    """Bảng "Response 200" nằm ở mục B của từng function."""
    lines = path.read_text(encoding="utf-8").splitlines()
    out: dict[str, list[dict]] = {}
    current: str | None = None

    i = 0
    while i < len(lines):
        if m := H_FUNC_DETAIL.match(lines[i]):
            current = ids.canonical(m.group(1), feature)
            i += 1
            continue
        if lines[i].strip().startswith("**Response 200**") and current:
            rows, i = _tables(lines, i + 1)
            fields = []
            for row in rows:
                if len(row) < 3 or not row[0].isdigit() and not row[0].startswith("H"):
                    continue
                fields.append({
                    "field": _strip_md(row[1]),
                    "type": _strip_md(row[2]),
                    "description": _strip_md(row[3]) if len(row) > 3 else "",
                })
            out[current] = fields
            continue
        i += 1
    return out, []


# ── SRS: non-functional requirements ─────────────────────────────────────────
def parse_srs_nfr(path: Path, feature: str) -> tuple[list[Requirement], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    rel = path.name
    out: list[Requirement] = []
    warnings: list[str] = []

    # Thu thập theo thứ tự xuất hiện, rồi mới cấp số canonical
    collected: list[tuple[str, str, str, int]] = []   # (source_id, group, text, line)
    i = 0
    current_group: str | None = None
    while i < len(lines):
        if m := H_NFR_GROUP.match(lines[i]):
            current_group = m.group(2)
            i += 1
            continue
        if current_group and lines[i].strip().startswith("| NFR-"):
            row = _cells(lines[i])
            if len(row) >= 2:
                source_id = _strip_md(row[0])
                if ids.NFR_RE.match(source_id):
                    collected.append((source_id, current_group, _strip_md(row[1]), i + 1))
            i += 1
            continue
        if re.match(r"^##\s+5\.", lines[i]):
            break
        i += 1

    mapping = ids.allocate_nfr_numbers([c[0] for c in collected], feature)
    for source_id, group, text, line in collected:
        out.append(Requirement(
            id=mapping[source_id],
            kind="non_functional",
            category=group,
            title=text[:100],
            source_ids=[source_id],
            statement=text,
            source=SourceRef(file=rel, line=line, quote=text),
        ))

    if not out:
        warnings.append(f"{rel}: không tìm thấy NFR nào (mẫu `| NFR-XXX-01 | … |`)")
    return out, warnings


# ── Điểm vào ─────────────────────────────────────────────────────────────────
def parse_markdown(path: Path, feature: str, doc_type: str) -> tuple[list[Requirement], list[str]]:
    if doc_type == "urd":
        reqs, warnings = parse_urd(path, feature)
    elif doc_type == "srs":
        funcs, w1 = parse_srs_functions(path, feature)
        responses, _ = parse_srs_responses(path, feature)
        for req in funcs:
            if req.api is not None and req.id in responses:
                req.api.response = responses[req.id]
        nfrs, w2 = parse_srs_nfr(path, feature)
        reqs, warnings = funcs + nfrs, w1 + w2
    else:
        raise ValueError(f"doc_type không hỗ trợ: {doc_type}")

    # Gắn feature ở một chỗ duy nhất, thay vì sửa từng hàm parse.
    for req in reqs:
        if not req.feature:
            req.feature = feature
    return reqs, warnings

"""Đọc **luồng nghiệp vụ** từ tài liệu phụ: sequence diagram, state machine, bảng quyết định.

Vì sao cần module này: tài liệu của dự án viết luồng nghiệp vụ rất kỹ, nhưng ở dạng
sơ đồ và bảng chứ không phải văn xuôi. Ví dụ thật trong `brainstorms/baseline-from-code.md`:

    ### 5.1 First visit protected route
    1. User mở URL bất kỳ (vd. `/projects`).
    2. `RequireAuth` thấy chưa authenticated → redirect `/login?callback=<encoded path>`.
    3. User bấm **Sign in with Keycloak** → redirect IdP.
    4. IdP trả về portal với tokens → `GET /auth/me` → navigate `callback`.

Đó **đã gần như là một testcase hoàn chỉnh** — đúng thứ người QC cần: click vào đâu,
ra cái gì, bước này sang bước kia thế nào. Trước đây tool chỉ hash file này để biết
nó đổi, không đọc nội dung, nên toàn bộ nguồn case UI tốt nhất bị bỏ phí.

Nguyên tắc giữ nguyên như phần còn lại của tool: **không đoán**. Cấu trúc không khớp
mẫu đã biết thì ghi cảnh báo và bỏ qua, không suy diễn ra một luồng không có trong
tài liệu. Người review phải đối chiếu được từng bước về đúng dòng đã sinh ra nó.
"""

from __future__ import annotations

import re
from pathlib import Path

from qctool.ingest.markdown import _cells, _strip_md

# ── Mẫu nhận dạng ────────────────────────────────────────────────────────────
RE_MERMAID_OPEN = re.compile(r"^\s*```\s*mermaid\s*$")
RE_FENCE = re.compile(r"^\s*```\s*$")
RE_SEQ_DIAGRAM = re.compile(r"^\s*sequenceDiagram\b")
RE_STATE_DIAGRAM = re.compile(r"^\s*stateDiagram(?:-v2)?\b")
RE_FLOWCHART = re.compile(r"^\s*(?:flow)?chart\s+(?:TD|LR|TB|RL)\b")

# `A->>B: thông điệp` và biến thể `A->B:`, `A-->B:`
RE_SEQ_MSG = re.compile(r"^\s*(\w+)\s*-{1,2}>{1,2}\s*(\w+)\s*:\s*(.+?)\s*$")
RE_SEQ_BRANCH = re.compile(r"^\s*(alt|else|opt|loop|par)\b\s*(.*)$")

# `draft --> active: PATCH status=active`
RE_STATE_TRANS = re.compile(r"^\s*(\[\*\]|[\w\s]+?)\s*-->\s*(\[\*\]|[\w\s]+?)\s*(?::\s*(.+?))?\s*$")

# `[SSO Keycloak] → [/projects] → [GET /projects] → [Card grid + filters]`
RE_ARROW_CHAIN = re.compile(r"^\s*\[[^\]]+\]\s*(?:→|->)\s*\[[^\]]+\]")

# Tiêu đề mục luồng: `### 5.1 Tiêu đề` (brainstorm §5)
RE_FLOW_HEADING = re.compile(r"^#{3,4}\s+(\d+\.\d+)\s+(.+?)\s*$")
RE_CORE_FLOWS = re.compile(r"^#{2,3}\s+5\.?\s+Core Flows", re.I)
RE_ANY_H2 = re.compile(r"^##\s")

# Bước đánh số: `1. nội dung`
RE_NUMBERED = re.compile(r"^\s*(\d{1,2})[.)]\s+(.+?)\s*$")

# Dấu mũi tên ngăn hành động và kết quả mong đợi trong một bước
ARROW = "→"

# ── Bảng ─────────────────────────────────────────────────────────────────────
# Nhận dạng bảng theo TÊN CỘT, không theo số thứ tự mục — tiêu đề mục đổi giữa
# các tài liệu (`6.1 Decision Points`, `6.1 Decision Points` khác số…), còn tên
# cột thì ổn định. Đoán theo vị trí mục sẽ vỡ ngay khi ai đó chèn một mục.
TABLE_KINDS = {
    "decision": [
        {"id", "flow"},
        {"condition", "khi nào"},
    ],
    "scenario": [
        {"from state"},
        {"user action", "action"},
    ],
    "transition": [
        {"from", "from state"},
        {"to"},
        {"trigger"},
    ],
    "error_surface": [
        {"surface"},
        {"trigger"},
        {"ux", "ux mong đợi", "result"},
    ],
    "interaction": [
        {"element"},
        {"action"},
    ],
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", _strip_md(text or "")).strip().lower()


def _classify_table(headers: list[str]) -> str | None:
    """Bảng này thuộc loại nào, dựa trên tên cột."""
    cells = {_norm(h) for h in headers}
    for kind, required in TABLE_KINDS.items():
        if all(any(cell in cells for cell in group) for group in required):
            return kind
    return None


def _split_step(text: str) -> tuple[str, str]:
    """Tách một bước luồng thành (hành động, kết quả mong đợi).

    Tài liệu viết `User bấm Sign in with Keycloak → redirect IdP`. Vế phải dấu
    mũi tên chính là kỳ vọng. Không có mũi tên thì cả câu là hành động — thà để
    người đọc tự quyết còn hơn tự chế ra một kỳ vọng không có trong tài liệu.
    """
    text = _strip_md(text).strip().rstrip(".")
    if ARROW not in text:
        return text, ""
    action, _, expected = text.partition(ARROW)
    action = action.strip().rstrip(".,")
    expected = expected.strip().rstrip(".")
    if not action:
        return expected, ""
    return action, expected


class _Collector:
    """Gom mục theo loại + cấp ID tuần tự, ổn định giữa các lần chạy."""

    PREFIX = {
        "flow": "FLOW",
        "transition": "STATE",
        "decision": "DEC",
        "scenario": "SCEN",
        "error_surface": "ERR",
    }

    def __init__(self, feature: str) -> None:
        self.feature = feature
        self.items: dict[str, list[dict]] = {k: [] for k in self.PREFIX}
        self._counters: dict[str, int] = {}

    def add(self, kind: str, **payload) -> None:
        n = self._counters.get(kind, 0) + 1
        self._counters[kind] = n
        self.items[kind].append({
            "id": f"{self.PREFIX[kind]}-{self.feature}-{n:03d}",
            **payload,
        })

    def to_dict(self) -> dict:
        out = {kind: items for kind, items in self.items.items() if items}
        return out


# ── Bóc từng dạng nguồn ──────────────────────────────────────────────────────
def _parse_numbered_flows(lines: list[str], rel: str, col: _Collector) -> list[str]:
    """Luồng viết bằng list đánh số trong mục `Core Flows` của brainstorm."""
    warnings: list[str] = []
    i = 0
    in_core = False

    while i < len(lines):
        line = lines[i]

        if RE_CORE_FLOWS.match(line):
            in_core = True
            i += 1
            continue
        if in_core and RE_ANY_H2.match(line) and not RE_CORE_FLOWS.match(line):
            in_core = False

        if not in_core:
            i += 1
            continue

        if m := RE_FLOW_HEADING.match(line):
            title = _strip_md(m.group(2))
            start = i + 1
            steps: list[dict] = []
            i += 1
            while i < len(lines):
                if RE_FLOW_HEADING.match(lines[i]) or RE_ANY_H2.match(lines[i]):
                    break
                if m2 := RE_NUMBERED.match(lines[i]):
                    action, expected = _split_step(m2.group(2))
                    steps.append({
                        "seq": len(steps) + 1,
                        "action": action,
                        "expected": expected,
                        "quote": _strip_md(m2.group(2)),
                    })
                i += 1
            if len(steps) >= 2:
                col.add(
                    "flow", title=title, source_kind="numbered", steps=steps,
                    source_file=rel, source_line=start,
                    source_quote=f"{title} — {len(steps)} bước",
                )
            elif steps:
                warnings.append(
                    f"{rel}:{start}: luồng «{title[:40]}» chỉ có 1 bước — "
                    "không đủ để thành một testcase, bỏ qua"
                )
            continue
        i += 1

    return warnings


def _parse_mermaid_sequence(lines: list[str], rel: str, col: _Collector) -> list[str]:
    """Sequence diagram — mỗi mục là một luồng tương tác giữa các thành phần."""
    warnings: list[str] = []
    i = 0

    while i < len(lines):
        if not (m := RE_MERMAID_OPEN.match(lines[i])):
            i += 1
            continue

        block_start = i + 1
        # Tìm tiêu đề gần nhất phía trên để đặt tên luồng
        title = ""
        for back in range(i - 1, max(-1, i - 12), -1):
            if h := re.match(r"^#{2,4}\s+(.+?)\s*$", lines[back]):
                title = _strip_md(h.group(1))
                break

        j = block_start
        while j < len(lines) and not RE_FENCE.match(lines[j]):
            j += 1
        block = lines[block_start:j]
        i = j + 1

        if not block or not RE_SEQ_DIAGRAM.match(block[0]):
            continue

        # Gom bước theo NHÁNH. `alt`/`else` trong sequence diagram là hai kịch bản
        # khác nhau, không phải hai bước liên tiếp. Trộn chúng thành một luồng
        # tuyến tính sẽ tạo ra case mô tả một đường đi không tồn tại: "nếu session
        # hợp lệ → fetch /auth/me" rồi ngay sau đó "nếu không → hiện LoginScreen".
        segments: list[tuple[str, list[dict]]] = []
        current_label = ""
        current: list[dict] = []
        branch = ""

        for offset, raw in enumerate(block[1:], start=block_start + 1):
            stripped = raw.strip()
            if bm := RE_SEQ_BRANCH.match(raw):
                word, label = bm.group(1), _strip_md(bm.group(2))
                if word in ("alt", "opt", "par"):
                    if current:
                        segments.append((current_label, current))
                    current, current_label = [], label or f"{word} (1)"
                elif word == "else":
                    if current:
                        segments.append((current_label, current))
                    current, current_label = [], label or "else"
                continue
            if stripped in ("end", "") or stripped.startswith("participant"):
                continue
            if mm := RE_SEQ_MSG.match(raw):
                actor_from, actor_to, message = mm.group(1), mm.group(2), _strip_md(mm.group(3))
                action, expected = _split_step(message)
                current.append({
                    "actor_from": actor_from,
                    "actor_to": actor_to,
                    "action": action,
                    "expected": expected,
                    "quote": message,
                    "line": offset,
                })

        if current:
            segments.append((current_label, current))

        # Bỏ nhánh rỗng, đánh số lại từng nhánh
        segments = [(label, steps) for label, steps in segments if steps]
        for label, steps in segments:
            for n, step in enumerate(steps, start=1):
                step["seq"] = n
                if label:
                    step["branch"] = label

        multi = len(segments) > 1
        for label, steps in segments:
            if len(steps) < 2:
                warnings.append(
                    f"{rel}:{block_start}: nhánh «{label or 'chính'}» của sequence "
                    f"diagram chỉ có {len(steps)} bước — bỏ qua"
                )
                continue
            first = next((s.get("line") for s in steps if s.get("line")), block_start)
            for step in steps:
                step.pop("line", None)
            full_title = title or "Luồng tương tác"
            if multi and label:
                full_title = f"{full_title} — {label}"
            col.add(
                "flow", title=full_title, source_kind="sequence", steps=steps,
                source_file=rel, source_line=first,
                source_quote=f"sequenceDiagram — {len(steps)} bước"
                             + (f" (nhánh {label})" if multi and label else ""),
            )

    return warnings


def _parse_mermaid_state(lines: list[str], rel: str, col: _Collector) -> list[str]:
    """State machine — mỗi chuyển trạng thái là một testcase riêng.

    Chuyển trạng thái là đơn vị test tự nhiên: từ trạng thái A, khi X xảy ra,
    hệ thống phải sang trạng thái B. Không cần gộp thành luồng dài.
    """
    warnings: list[str] = []
    i = 0

    while i < len(lines):
        if not RE_MERMAID_OPEN.match(lines[i]):
            i += 1
            continue

        block_start = i + 1
        j = block_start
        while j < len(lines) and not RE_FENCE.match(lines[j]):
            j += 1
        block = lines[block_start:j]
        i = j + 1

        if not block or not RE_STATE_DIAGRAM.match(block[0]):
            continue

        for offset, raw in enumerate(block[1:], start=block_start + 1):
            if not (m := RE_STATE_TRANS.match(raw)):
                continue
            src, dst, trigger = m.group(1).strip(), m.group(2).strip(), m.group(3)
            if src == dst:
                continue                    # tự chuyển → không phải chuyển trạng thái
            trigger = _strip_md(trigger or "").replace("\\n", " · ").strip()
            col.add(
                "transition",
                from_state=src,
                to_state=dst,
                trigger=trigger,
                source_file=rel,
                source_line=offset,
                source_quote=_strip_md(raw),
            )

    return warnings


def _parse_tables(lines: list[str], rel: str, col: _Collector) -> list[str]:
    """Bảng quyết định / kịch bản / chuyển trạng thái / bề mặt lỗi."""
    warnings: list[str] = []

    for kind, headers, rows, line_no in _iter_tables(lines):
        if kind == "decision":
            for row in rows:
                if len(row) < 5:
                    continue
                col.add(
                    "decision", flow=row[1], condition=row[2],
                    yes=row[3], no=row[4],
                    source_file=rel, source_line=line_no,
                    source_quote=" | ".join(row[:5]),
                )
        elif kind == "scenario":
            for row in rows:
                if len(row) < 5:
                    continue
                col.add(
                    "scenario", from_state=row[0], action=row[1], rule=row[2],
                    then_action=row[3], result=row[4],
                    source_file=rel, source_line=line_no,
                    source_quote=" | ".join(row[:5]),
                )
        elif kind == "transition":
            for row in rows:
                if len(row) < 3:
                    continue
                col.add(
                    "transition", from_state=row[0], to_state=row[1], trigger=row[2],
                    actor=row[3] if len(row) > 3 else "",
                    permission=row[4] if len(row) > 4 else "",
                    side_effects=row[5] if len(row) > 5 else "",
                    source_file=rel, source_line=line_no,
                    source_quote=" | ".join(row[:6]),
                )
        elif kind == "error_surface":
            for row in rows:
                if len(row) < 3:
                    continue
                col.add(
                    "error_surface", surface=row[0], trigger=row[1], ux=row[2],
                    source_file=rel, source_line=line_no,
                    source_quote=" | ".join(row[:3]),
                )

    return warnings


def _iter_tables(lines: list[str]):
    """Duyệt mọi bảng markdown, trả (loại, tiêu đề cột, hàng, số dòng)."""
    i = 0
    while i < len(lines):
        if not lines[i].strip().startswith("|"):
            i += 1
            continue
        start = i
        block: list[list[str]] = []
        while i < len(lines) and lines[i].strip().startswith("|"):
            block.append(_cells(lines[i]))
            i += 1
        if len(block) < 3:
            continue
        header, sep, *rows = block
        if not re.match(r"^[\s:\-|]+$", lines[start + 1].strip().strip("|")):
            continue
        kind = _classify_table(header)
        if kind is None:
            continue
        yield kind, header, rows, start + 1


# ── Điểm vào ─────────────────────────────────────────────────────────────────
ATTACHMENT_PATTERNS = [
    "srs/*flow*.md",
    "srs/*state*.md",
    "srs/*diagram*.md",
    "brainstorms/*.md",
    "ascii-screen/*.md",
]


def extract(feature_dir: Path, feature: str, warnings: list[str]) -> dict:
    """Đọc mọi tài liệu phụ của một feature → luồng nghiệp vụ có cấu trúc.

    Trả dict rỗng nếu feature không có tài liệu phụ nào — không phải lỗi, chỉ là
    feature đó chưa viết luồng.
    """
    col = _Collector(feature)
    seen: set[Path] = set()

    for pattern in ATTACHMENT_PATTERNS:
        for path in sorted(feature_dir.glob(pattern)):
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            rel = str(path.relative_to(feature_dir))
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError) as exc:
                warnings.append(f"{rel}: không đọc được — {type(exc).__name__}: {exc}")
                continue

            warnings.extend(_parse_numbered_flows(lines, rel, col))
            warnings.extend(_parse_mermaid_sequence(lines, rel, col))
            warnings.extend(_parse_mermaid_state(lines, rel, col))
            warnings.extend(_parse_tables(lines, rel, col))

    data = col.to_dict()
    if not data:
        return {}
    data["counts"] = {
        "flow": len(data.get("flow", [])),
        "transition": len(data.get("transition", [])),
        "decision": len(data.get("decision", [])),
        "scenario": len(data.get("scenario", [])),
        "error_surface": len(data.get("error_surface", [])),
    }
    return data


LABELS = {
    "flow": "luồng",
    "transition": "chuyển trạng thái",
    "decision": "điểm quyết định",
    "scenario": "kịch bản",
    "error_surface": "bề mặt lỗi",
}


def counts(flows: dict | None) -> dict[str, int]:
    """Đếm số mục, gộp qua nhiều feature nếu `flows` là dict theo feature."""
    if not flows:
        return {}
    totals: dict[str, int] = {}
    # `flows` có thể là dữ liệu một feature (có khoá "counts") hoặc dict theo feature
    sources = [flows] if "counts" in flows else list(flows.values())
    for data in sources:
        if not isinstance(data, dict):
            continue
        for kind, n in (data.get("counts") or {}).items():
            totals[kind] = totals.get(kind, 0) + n
    return {LABELS.get(k, k): v for k, v in totals.items() if v}

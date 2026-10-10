"""Kiểm tra testcase trước khi ghi ra file.

Đây là cửa chặn cuối trước khi output rời khỏi tool. Ba nhóm kiểm tra:

1. **Từng case** — `TestCase.validate()` (vocabulary, traceability, có assert, có nguồn).
2. **Toàn bộ lô** — ID trùng, case trùng nhau, requirement không có case nào (gap),
   case không trace về đâu (orphan).
3. **Chất lượng** — case chưa map, tỉ lệ case âm, độ phủ theo loại requirement.

Nhóm 2 và 3 mới là thứ khiến bộ testcase dùng được: một lô 500 case mà 400 case là
orphan thì tệ hơn 50 case trace đầy đủ.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from qctool.core.testcase import TestCase, ValidationError


@dataclass
class Report:
    total: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    gaps: dict[str, list[str]] = field(default_factory=dict)   # kind → requirement id chưa có case
    orphans: list[str] = field(default_factory=list)
    duplicates: list[tuple[str, str]] = field(default_factory=list)
    needs_mapping: list[str] = field(default_factory=list)
    by_technique: Counter = field(default_factory=Counter)
    by_type: Counter = field(default_factory=Counter)
    by_priority: Counter = field(default_factory=Counter)
    coverage: dict[str, tuple[int, int]] = field(default_factory=dict)  # kind → (có case, tổng)
    # Độ phủ theo mọi nguồn (requirement + luồng nghiệp vụ). Xem `coverage_detail`.
    coverage_detail: dict[str, dict] = field(default_factory=dict)
    manual_cases: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def text(self) -> str:
        lines: list[str] = []

        if self.errors:
            lines.append(f"LỖI ({len(self.errors)}) — phải sửa trước khi dùng:")
            lines += [f"  - {e}" for e in self.errors]

        if self.duplicates:
            lines.append("")
            lines.append(f"CASE TRÙNG NHAU ({len(self.duplicates)}) — cùng bước, khác ID:")
            for a, b in self.duplicates:
                lines.append(f"  - {a} ≡ {b}")

        if self.gaps:
            lines.append("")
            total_gap = sum(len(v) for v in self.gaps.values())
            lines.append(f"REQUIREMENT CHƯA CÓ TEST ({total_gap}):")
            for kind, ids in sorted(self.gaps.items()):
                shown = ", ".join(ids[:6]) + (f" … +{len(ids) - 6}" if len(ids) > 6 else "")
                lines.append(f"  {kind:<22} {len(ids):>3}  {shown}")

        if self.orphans:
            lines.append("")
            lines.append(f"CASE KHÔNG GẮN REQUIREMENT NÀO ({len(self.orphans)}):")
            shown = ", ".join(self.orphans[:8]) + (
                f" … +{len(self.orphans) - 8}" if len(self.orphans) > 8 else ""
            )
            lines.append(f"  {shown}")

        if self.needs_mapping:
            lines.append("")
            lines.append(
                f"CASE CHƯA MAP ({len(self.needs_mapping)}) — sinh từ acceptance criterion, "
                "còn bước viết bằng văn xuôi:"
            )
            shown = ", ".join(self.needs_mapping[:8]) + (
                f" … +{len(self.needs_mapping) - 8}" if len(self.needs_mapping) > 8 else ""
            )
            lines.append(f"  {shown}")
            lines.append("  → Cần map sang hành động cụ thể trước khi chạy tự động được.")

        if self.warnings:
            lines.append("")
            lines.append(f"CẢNH BÁO ({len(self.warnings)}):")
            lines += [f"  - {w}" for w in self.warnings]

        lines.append("")
        lines.append(f"TỔNG: {self.total} testcase")
        if self.coverage:
            lines.append("Độ phủ requirement:")
            for kind, (covered, total) in sorted(self.coverage.items()):
                pct = (covered / total * 100) if total else 0
                lines.append(f"  {kind:<22} {covered:>3}/{total:<3} ({pct:.0f}%)")
        if self.by_technique:
            lines.append("Kỹ thuật sinh: " + ", ".join(
                f"{k}={v}" for k, v in self.by_technique.most_common()))
        if self.by_type:
            lines.append("Loại case: " + ", ".join(
                f"{k}={v}" for k, v in self.by_type.most_common()))
        return "\n".join(lines)


def validate_batch(cases: list[TestCase], requirements: list[dict] | None = None,
                   sources: dict | None = None) -> Report:
    report = Report(total=len(cases))

    # ── 1. Từng case ────────────────────────────────────────────────────────
    for case in cases:
        try:
            case.validate()
        except ValidationError as exc:
            report.errors.append(str(exc))

    # ── 2. ID trùng ─────────────────────────────────────────────────────────
    seen: dict[str, int] = {}
    for case in cases:
        seen[case.id] = seen.get(case.id, 0) + 1
    for tc_id, count in seen.items():
        if count > 1:
            report.errors.append(f"ID `{tc_id}` xuất hiện {count} lần — mỗi testcase phải có ID riêng")

    # ── 3. Case trùng nội dung ──────────────────────────────────────────────
    by_hash: defaultdict[str, list[str]] = defaultdict(list)
    for case in cases:
        by_hash[case.content_hash].append(case.id)
    for ids in by_hash.values():
        if len(ids) > 1:
            report.duplicates.append((ids[0], ids[1]))

    # ── 4. Orphan ───────────────────────────────────────────────────────────
    report.orphans = [c.id for c in cases if not c.traces_to]

    # ── 5. Chưa map ─────────────────────────────────────────────────────────
    report.needs_mapping = [c.id for c in cases if c.needs_mapping]
    report.manual_cases = [c.id for c in cases if c.execution == "manual"]

    # ── 6. Thống kê ─────────────────────────────────────────────────────────
    report.by_technique = Counter(c.technique.value for c in cases)
    report.by_type = Counter(c.case_type.value for c in cases)
    report.by_priority = Counter(c.priority.value for c in cases)

    # ── 7. Gap — requirement không có case nào ──────────────────────────────
    if requirements:
        covered = {rid for c in cases for rid in c.traces_to}
        gaps: defaultdict[str, list[str]] = defaultdict(list)
        totals: defaultdict[str, int] = defaultdict(int)
        for req in requirements:
            kind = req.get("kind", "unknown")
            totals[kind] += 1
            if req["id"] not in covered:
                gaps[kind].append(req["id"])
        report.gaps = dict(gaps)
        report.coverage = {
            kind: (totals[kind] - len(gaps.get(kind, [])), totals[kind])
            for kind in totals
        }

    # ── 8. Độ phủ theo MỌI nguồn, kể cả luồng nghiệp vụ ─────────────────────
    # `coverage` ở trên chỉ đếm requirement. Nhưng case sinh từ luồng (sequence
    # diagram, decision point, state machine) trace về `FLOW-*`/`DEC-*`/… chứ
    # không về requirement nào — nếu chỉ nhìn `coverage`, 33 case UI vừa sinh sẽ
    # vô hình, và người dùng lại có cảm giác "sao ít case thế".
    if sources is None:
        sources = {}
        if requirements:
            universe: defaultdict[str, dict[str, str]] = defaultdict(dict)
            for req in requirements:
                universe[req.get("kind", "unknown")][req["id"]] = (
                    req.get("title") or "")[:70]
            sources = dict(universe)

    if sources:
        covered = {rid for c in cases for rid in c.traces_to}
        detail: dict[str, dict] = {}
        for kind, items in sources.items():
            if not items:
                continue
            have = {rid: label for rid, label in items.items() if rid in covered}
            missing = {rid: label for rid, label in items.items() if rid not in covered}
            detail[kind] = {
                "total": len(items),
                "covered": len(have),
                "missing": missing,
            }
        report.coverage_detail = detail

    if report.orphans:
        report.warnings.append(
            f"{len(report.orphans)} case không trace về requirement nào — "
            "sinh ra để kiểm cái gì?"
        )
    if report.duplicates:
        report.warnings.append(
            f"{len(report.duplicates)} cặp case trùng nội dung — "
            "giữ một cái, hoặc sửa cho khác nhau"
        )
    return report


SOURCE_LABELS = {
    "user_story": "User story",
    "acceptance_criterion": "Acceptance criteria",
    "functional": "Functional (FR)",
    "non_functional": "Non-functional (NFR)",
    "flow": "Luồng nghiệp vụ",
    "decision": "Điểm quyết định",
    "transition": "Chuyển trạng thái",
    "error_surface": "Bề mặt lỗi",
    "scenario": "Kịch bản theo vai trò",
}


def coverage_line(report: Report) -> str:
    """Một dòng gọn để in ra console: `AC 15/15 · FR 10/10 · Luồng 5/5 …`."""
    if not report.coverage_detail:
        return ""
    parts = []
    for kind, stats in report.coverage_detail.items():
        label = SOURCE_LABELS.get(kind, kind)
        parts.append(f"{label} {stats['covered']}/{stats['total']}")
    return " · ".join(parts)

"""Chặng 4 — Report: kết quả chạy → báo cáo người đọc được.

Ngôn ngữ đơn giản, số liệu lên đầu. "54 test, 48 đạt, 4 lỗi" — không phải
"Test execution summary: 92.31% pass rate".
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from qctool.execute.runner import (
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_NOT_EXECUTED,
    STATUS_PASS,
    RunResult,
)


def write_json(result: RunResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_csv(result: RunResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Mã test", "Module", "Tên test", "Kết quả", "Thời gian (ms)",
                         "Thực tế", "Ghi chú", "Bằng chứng", "Chập chờn"])
        for case in result.cases:
            writer.writerow([
                case.case_id, case.module, case.title, case.status,
                f"{case.duration_ms:.0f}",
                " | ".join(case.actual),
                case.blocked_reason or "",
                " ".join(_evidence_paths(case.evidence)),
                "có" if case.flaky else "",
            ])


def _evidence_paths(evidence: dict) -> list[str]:
    """Đường dẫn tương đối của bằng chứng — để người đọc mở được ngay."""
    out: list[str] = []
    for shot in evidence.get("screenshots", []) or []:
        out.append(f"evidence/{shot}")
    if evidence.get("trace"):
        out.append(f"evidence/{evidence['trace']}")
    return out


def write_junit(result: RunResult, path: Path) -> None:
    """JUnit XML để CI nuốt được."""
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = result.counts
    suite = ET.Element("testsuite", {
        "name": "qc-tool",
        "tests": str(result.total),
        "failures": str(counts[STATUS_FAIL]),
        "errors": str(counts[STATUS_BLOCKED]),
        "skipped": str(counts[STATUS_NOT_EXECUTED]),
        "time": f"{sum(c.duration_ms for c in result.cases) / 1000:.3f}",
        "timestamp": result.started_at,
    })
    for case in result.cases:
        tc = ET.SubElement(suite, "testcase", {
            "classname": case.module, "name": case.case_id, "time": f"{case.duration_ms / 1000:.3f}",
        })
        detail = "\n".join(case.actual) or case.status
        if case.evidence:
            paths = _evidence_paths(case.evidence)
            if paths:
                detail += "\n\nBằng chứng: " + ", ".join(paths)
        if case.flaky:
            detail += "\n\n⚠ Test chập chờn: lần chạy đầu không đạt, chạy lại mới đạt."
        if case.status == STATUS_FAIL:
            failure = ET.SubElement(tc, "failure", {"message": (case.actual or ["Fail"])[-1]})
            failure.text = detail
        elif case.status == STATUS_BLOCKED:
            error = ET.SubElement(tc, "error", {"message": case.blocked_reason or "Blocked"})
            error.text = detail
        elif case.status == STATUS_NOT_EXECUTED:
            ET.SubElement(tc, "skipped")
    ET.indent(suite, space="  ")
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' +
                    ET.tostring(suite, encoding="unicode"), encoding="utf-8")


def render_markdown(result: RunResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_markdown(result), encoding="utf-8")


def build_markdown(result: RunResult) -> str:
    review = [c for c in result.cases if c.generation_status == 'needs_review']
    counts = result.counts
    executed = counts[STATUS_PASS] + counts[STATUS_FAIL]
    failures = [c for c in result.cases if c.status == STATUS_FAIL]
    blocked = [c for c in result.cases if c.status == STATUS_BLOCKED]
    not_run = [c for c in result.cases if c.status == STATUS_NOT_EXECUTED]
    flaky = result.flaky_cases

    lines = [
        f"# Báo cáo kiểm thử — {result.environment or result.base_url}",
        "",
        f"**Môi trường:** {result.base_url} · "
        f"**Bắt đầu:** {result.started_at} · **Kết thúc:** {result.finished_at}",
        "",
        "---",
        "",
        "## 1. Tóm tắt",
        "",
        f"> {_headline(result, counts, executed)}",
        "",
        "| | Số lượng |",
        "|---|---|",
        f"| Tổng số test | {result.total} |",
        f"| Đạt | {counts[STATUS_PASS]} |",
        f"| **Lỗi** | **{counts[STATUS_FAIL]}** |",
        f"| Bị chặn | {counts[STATUS_BLOCKED]} |",
        f"| Chưa chạy | {counts[STATUS_NOT_EXECUTED]} |",
        "",
    ]
    if review:
        lines.extend(['', '### Testcase cần review oracle', '',
            'Kết quả runtime không thay thế việc review ý nghĩa assertion.', '',
            *[f"- {c.case_id}: {'; '.join(c.review_reasons)}" for c in review], ''])

    if flaky:
        # Nói riêng, và nói ngay dưới bảng số: một test lúc đạt lúc không KHÔNG
        # phải bằng chứng chất lượng, mà là vấn đề cần người xem (race condition
        # của sản phẩm, hoặc test viết giòn).
        lines += [
            f"⚠ **{len(flaky)} test chập chờn** — lần chạy đầu không đạt, phải chạy "
            "lại mới đạt: "
            + ", ".join(f"`{c.case_id}`" for c in flaky[:10])
            + ("…" if len(flaky) > 10 else ""),
            "",
        ]
    if executed:
        lines.append(f"**Tỉ lệ đạt:** {result.pass_rate:.0f}% "
                     f"({counts[STATUS_PASS]}/{executed} test đã chạy)")
        lines.append("")

    # ── 2. Theo module ──────────────────────────────────────────────────────
    lines += ["## 2. Chi tiết theo module", "",
              "| Module | Tổng | Đạt | Lỗi | Bị chặn | Chưa chạy |",
              "|---|---|---|---|---|---|"]
    for module, bucket in sorted(result.by_module().items()):
        total = sum(bucket.values())
        lines.append(f"| {module} | {total} | {bucket[STATUS_PASS]} | "
                     f"{bucket[STATUS_FAIL]} | {bucket[STATUS_BLOCKED]} | "
                     f"{bucket[STATUS_NOT_EXECUTED]} |")
    lines.append(f"| **Tổng** | **{result.total}** | **{counts[STATUS_PASS]}** | "
                 f"**{counts[STATUS_FAIL]}** | **{counts[STATUS_BLOCKED]}** | "
                 f"**{counts[STATUS_NOT_EXECUTED]}** |")
    lines.append("")

    # ── 3. Lỗi ──────────────────────────────────────────────────────────────
    lines += ["## 3. Danh sách lỗi", ""]
    if not failures:
        lines += ["Không có lỗi nào.", ""]
    else:
        for i, case in enumerate(failures, 1):
            lines += [
                f"### Lỗi {i} — {case.title}",
                "",
                "| | |",
                "|---|---|",
                f"| Mã test | {case.case_id} |",
                f"| Module | {case.module} |",
                f"| Thời gian | {case.duration_ms:.0f}ms |",
                "",
            ]
            if case.flaky:
                lines += ["**Test này chập chờn** — lần chạy lại cho kết quả khác.", ""]
            if paths := _evidence_paths(case.evidence):
                lines += ["**Bằng chứng:** " + " · ".join(f"`{p}`" for p in paths), ""]
            if case.evidence.get("note"):
                lines += [f"**Bối cảnh lúc hỏng:** {case.evidence['note']}", ""]
            if case.evidence.get("network"):
                lines += ["**Request lỗi khi thao tác:**", ""]
                lines += [f"- `{item}`" for item in case.evidence["network"][:6]]
                lines.append("")
            if case.evidence.get("console"):
                lines += ["**Lỗi JavaScript:**", ""]
                lines += [f"- `{item}`" for item in case.evidence["console"][:6]]
                lines.append("")
            lines += [
                "**Diễn biến:**",
                "",
            ]
            lines += [f"```\n{d}\n```" for d in case.actual]
            lines.append("")

    # ── 4. Chưa chạy được — tách thủ công khỏi bị chặn ──────────────────────
    # Hai nhóm này khác nhau về bản chất và khác nhau về việc phải làm:
    #   · Thủ công  → VIỆC CỦA NGƯỜI. Case hợp lệ, đọc bước là làm được ngay.
    #   · Bị chặn   → THIẾU ĐIỀU KIỆN. Cần bổ sung tài khoản/dữ liệu rồi mới chạy.
    # Trộn vào một bảng thì người đọc không biết bắt đầu từ đâu.
    if not_run:
        lines += ["## 4. Cần người chạy thủ công", "",
                  f"{len(not_run)} test dưới đây không chạy tự động được. "
                  "Máy không làm nổi các bước này (thao tác trên màn hình chưa map "
                  "được sang element cụ thể, nhập liệu từ thiết bị ngoài, nhiều vai "
                  "trò…), nhưng bước đã ghi đủ để người làm theo.", "",
                  "| Mã test | Tên | Số bước |", "|---|---|---|"]
        for case in not_run:
            steps = case.step_count or len(case.steps)
            lines.append(f"| {case.case_id} | {case.title[:70]} | {steps} |")
        lines.append("")

    if blocked:
        lines += ["## 5. Bị chặn — thiếu điều kiện môi trường", "",
                  "| Mã test | Tên | Lý do |", "|---|---|---|"]
        for case in blocked:
            reason = (case.blocked_reason or "—").replace("\n", " ")
            lines.append(f"| {case.case_id} | {case.title[:60]} | {reason[:120]} |")
        lines.append("")

    # ── 6. Chập chờn ────────────────────────────────────────────────────────
    # Tách riêng khỏi mục Lỗi vì cách xử lý khác hẳn: lỗi thì sửa sản phẩm, còn
    # chập chờn thì phải tìm nguyên nhân (race condition, timeout, thiếu chờ).
    if flaky:
        lines += ["## 6. Test chập chờn — cần xem lại", "",
                  "Những test dưới đây **lần đầu không đạt**, chỉ đạt sau khi chạy lại. "
                  "Không tính là đạt: một test lúc được lúc không là vấn đề của sản "
                  "phẩm (race condition) hoặc của test (chờ chưa đúng chỗ).", "",
                  "| Mã test | Tên | Lần chạy | Lý do lần đầu |", "|---|---|---|---|"]
        for case in flaky:
            reason = (case.attempts[0] if case.attempts else "—")[:110].replace("\n", " ")
            lines.append(f"| {case.case_id} | {case.title[:50]} | "
                         f"{len(case.attempts) + 1} | {reason} |")
        lines.append("")

    # ── 7. Bằng chứng ───────────────────────────────────────────────────────
    with_evidence = [c for c in result.cases if c.evidence]
    if with_evidence:
        lines += ["## 7. Bằng chứng", "",
                  "Ảnh chụp và trace nằm trong thư mục `evidence/`, "
                  "đặt tên theo mã test. Mở trace bằng "
                  "`uv run playwright show-trace <file>`.", "",
                  "| Mã test | Ảnh | Trace | Lỗi JS | Request lỗi |", "|---|---|---|---|---|"]
        for case in with_evidence:
            shots = ", ".join(case.evidence.get("screenshots", [])) or "—"
            trace = case.evidence.get("trace") or "—"
            console = len(case.evidence.get("console", []))
            network = len(case.evidence.get("network", []))
            lines.append(f"| {case.case_id} | {shots} | {trace} | "
                         f"{console or '—'} | {network or '—'} |")
        lines.append("")

    lines += [
        "---",
        "",
        f"*Nguồn số liệu: `results.json` · `results.csv` · `junit.xml` — "
        f"sinh lúc {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
    ]
    return "\n".join(lines)


def _headline(result: RunResult, counts: dict, executed: int) -> str:
    if result.total == 0:
        return "Không có testcase nào để chạy."

    manual = counts[STATUS_NOT_EXECUTED]
    blocked = counts[STATUS_BLOCKED]
    leftovers = []
    if manual:
        leftovers.append(f"{manual} cần người chạy thủ công")
    if blocked:
        leftovers.append(f"{blocked} bị chặn vì thiếu điều kiện")
    if result.flaky_cases:
        leftovers.append(f"{len(result.flaky_cases)} chập chờn")
    tail = (" " + ", ".join(leftovers) + ".") if leftovers else ""

    if counts[STATUS_FAIL] == 0 and executed:
        return f"Tất cả {executed} test đã chạy đều đạt.{tail}"
    if counts[STATUS_FAIL] == 0:
        return f"Chưa chạy được test nào tự động.{tail}"
    return (f"Có {counts[STATUS_FAIL]} lỗi trên {executed} test đã chạy. "
            f"Xem Mục 3 để biết chi tiết.{tail}")

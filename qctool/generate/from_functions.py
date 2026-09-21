"""Sinh testcase từ **functional requirement** trong SRS.

Vì sao cần track riêng: SRS mô tả mỗi chức năng bằng bốn thứ —

    #### 3.2.6. F-06  Logout
    **Flow:** clearSession + logout redirectUri origin/login
    **Error handling:**
      | Init timeout | Show login, optional authError |
      | Refresh fail | clearSession → /login |
      | Unsafe callback | defaultHomePath(permissions) |

Trước đây chỉ có 3/10 FR có `endpoint` nên sinh được case API; **7 FR còn lại sinh
ra 0 case** dù tài liệu mô tả đủ để kiểm. Bảng `error_handling` thì bị bỏ hoàn toàn
— trong khi đó chính là danh sách **hành vi khi lỗi**, thứ dễ sai nhất trong sản phẩm.

Ba nguồn trong mỗi FR:

| Nguồn | Sinh ra |
|---|---|
| `flow` | Case luồng chính: mỗi bước tài liệu → một bước testcase |
| `error_handling` | Mỗi dòng → một case: khi <điều kiện> thì phải <hành vi> |
| `errors` (bảng HTTP) | Mỗi mã lỗi → một case (chỉ khi có endpoint) |
"""

from __future__ import annotations

import re

from ..testcase import (
    CaseType,
    Priority,
    Step,
    StepKind,
    Technique,
    TestCase,
)
from .from_openapi import IdAllocator

# Câu mô tả hành vi lỗi → thường là case âm
NEGATIVE_MARKERS = (
    "không", "chặn", "từ chối", "lỗi", "fail", "reject", "deny", "forbidden",
    "ẩn", "hidden", "no ", "not ", "timeout", "clear", "unsafe",
)


def _clean(text: str) -> str:
    return " ".join(str(text or "").split()).strip().rstrip(".")


def _negative(text: str) -> bool:
    lowered = text.lower()
    return any(m in lowered for m in NEGATIVE_MARKERS)


def _split_flow(text: str) -> str:
    """Dòng `Flow` đôi khi gộp nhiều bước bằng `+` hoặc `;` — tách cho dễ đọc."""
    text = _clean(text)
    for sep in (";", " → "):
        if sep in text:
            return text
    return text


# Đích đến cụ thể ghi ngay trong dòng `Flow`: `Unauthenticated → /login?callback=`.
# Đây là **kết quả quan sát được**, khác hẳn phần mô tả cơ chế bên trong
# (`persistReturnPath`, `uses can(permission) from context`) — nhóm sau không kiểm
# được từ ngoài và không được đoán thành assertion.
RE_FLOW_DESTINATION = re.compile(r"→\s*(/[\w\-./?=&{}]*)")


def generate_from_functions(requirements: list[dict], alloc: IdAllocator,
                            module: str) -> list[TestCase]:
    """Sinh case từ mọi functional requirement có mô tả flow hoặc error handling."""
    out: list[TestCase] = []

    # Bảng `Error handling` trong SRS là bảng **dùng chung** cho cả nhóm chức năng:
    # cùng ba dòng "Init timeout / Refresh fail / Unsafe callback" bị chép nguyên
    # vào 7 mục FR. Sinh case cho từng bản sao tạo ra 21 case trùng nội dung —
    # người đọc báo cáo thấy 3 hành vi lỗi được "kiểm" 7 lần mà không hiểu vì sao.
    #
    # Giữ lại ở chức năng ĐẦU TIÊN gặp bảng đó, và ghi rõ trong trace rằng nó là
    # hành vi dùng chung. Trung thực hơn là nhân bản: số testcase phải phản ánh số
    # thứ cần kiểm, không phải số lần tài liệu chép lại.
    seen_error_tables: set[frozenset] = set()

    for req in requirements:
        if req.get("kind") != "functional":
            continue
        api = req.get("api") or {}
        if not api:
            continue

        title = _clean(req.get("title"))
        req_id = req["id"]
        source_ref = (f"{req.get('source', {}).get('file', '')}:"
                      f"{req.get('source', {}).get('line', '')}")

        # ── 1. Luồng chính ─────────────────────────────────────────────────
        flow_steps = [_clean(s) for s in api.get("flow", []) if _clean(s)]
        if flow_steps:
            steps: list[Step] = []
            for raw in flow_steps:
                steps.append(Step(len(steps) + 1, StepKind.WHEN, "perform.unmapped",
                                  {"description": _split_flow(raw)}))
            # Kỳ vọng phải là thứ **kiểm được**. Trước đây câu này luôn là
            # «Chức năng X hoàn tất đúng như tài liệu mô tả» — một câu không nói
            # gì cả: nó không sai, nhưng cũng không kiểm điều gì, nên case mãi ở
            # trạng thái "chưa map" dù tài liệu có nêu đích đến rõ ràng.
            #
            # Dòng `Flow` của portal thật viết `Unauthenticated → /login?callback=`
            # — đích đến đó là kết quả quan sát được, dùng luôn. Không có đích đến
            # thì giữ câu mô tả cũ và case ở lại `manual`, đúng nguyên tắc không đoán.
            expected = f"Chức năng «{title}» hoàn tất đúng như tài liệu mô tả"
            for raw in flow_steps:
                if m := RE_FLOW_DESTINATION.search(raw):
                    expected = f"Chuyển tới {m.group(1)}"
                    break
            steps.append(Step(len(steps) + 1, StepKind.THEN, "assert.unmapped", {
                "expected": expected,
            }))
            out.append(TestCase(
                id=alloc.next(module),
                module=module,
                title=f"{title} — luồng chính",
                objective=f"Kiểm chứng chức năng «{title}» ({req_id}) chạy đúng luồng chính",
                steps=steps,
                priority=Priority.HIGH,
                case_type=CaseType.POSITIVE,
                technique=Technique.ACCEPTANCE_CRITERION,
                traces_to=[req_id],
                source_quote=f"{title}: " + " / ".join(flow_steps),
                source_ref=source_ref,
                test_data={"số bước": len(flow_steps)},
                execution="manual",
            ))

        # ── 2. Xử lý lỗi ───────────────────────────────────────────────────
        pairs = [
            (_clean(e.get("condition")), _clean(e.get("behavior")))
            for e in api.get("error_handling", [])
        ]
        pairs = [(c, b) for c, b in pairs if c and b]
        if pairs:
            fingerprint = frozenset(pairs)
            if fingerprint in seen_error_tables:
                continue
            seen_error_tables.add(fingerprint)

        for condition, behavior in pairs:
            out.append(TestCase(
                id=alloc.next(module),
                module=module,
                title=f"Xử lý lỗi khi {condition} → {behavior[:58]}",
                objective=(f"Kiểm chứng hành vi khi {condition}: {behavior}. "
                           f"(Hành vi dùng chung, khai trong SRS ở {req_id})"),
                steps=[
                    Step(1, StepKind.GIVEN, "perform.unmapped",
                         {"description": condition}),
                    Step(2, StepKind.WHEN, "perform.unmapped",
                         {"description": f"Gây ra tình huống: {condition}"}),
                    Step(3, StepKind.THEN, "assert.unmapped", {"expected": behavior}),
                ],
                priority=Priority.HIGH if _negative(behavior) else Priority.MEDIUM,
                case_type=CaseType.NEGATIVE if _negative(behavior) else CaseType.STATE,
                technique=Technique.ERROR_GUESSING,
                traces_to=[req_id],
                source_quote=f"{req_id} | {condition} | {behavior}",
                source_ref=source_ref,
                test_data={"tình huống": condition},
                execution="manual",
            ))

        # ── 3. Trường bắt buộc trong response ──────────────────────────────
        fields = [_clean(f.get("field")) for f in api.get("response", [])
                  if _clean(f.get("field")) not in ("", "—")]
        if fields and api.get("endpoint"):
            out.append(TestCase(
                id=alloc.next(module),
                module=module,
                title=f"{title} — response có đủ {len(fields)} field tài liệu khai",
                objective=f"Kiểm chứng hợp đồng dữ liệu của «{title}» ({req_id})",
                steps=[
                    Step(1, StepKind.WHEN, "perform.unmapped",
                         {"description": f"Gọi {api['endpoint']}"}),
                    Step(2, StepKind.THEN, "assert.unmapped", {
                        "expected": "Response có đủ field: " + ", ".join(fields),
                    }),
                ],
                priority=Priority.MEDIUM,
                case_type=CaseType.POSITIVE,
                technique=Technique.SCHEMA_CONFORMANCE,
                traces_to=[req_id],
                source_quote=f"{title} — response fields: {', '.join(fields)}",
                source_ref=source_ref,
                test_data={"endpoint": api["endpoint"]},
                execution="manual",
            ))

    return out

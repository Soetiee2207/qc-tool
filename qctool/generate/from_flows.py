"""Sinh testcase từ **luồng nghiệp vụ** (output của `ingest/flows.py`).

Đây là track sinh case UI nghiệp vụ — phần mà trước đây tool làm kém nhất. OpenAPI
cho biết API đúng hay sai; luồng nghiệp vụ mới cho biết *người dùng bấm vào đâu,
màn hình ra cái gì, bước này sang bước kia có đúng không*.

Bốn loại nguồn, bốn cách sinh case khác nhau về bản chất:

| Nguồn | Cách sinh |
|---|---|
| `flow` | Một case cho cả luồng. **Mỗi bước tài liệu → một bước testcase.** |
| `decision` | **Hai** case: nhánh YES và nhánh NO. Bản chất decision table là vậy. |
| `transition` | Một case cho mỗi chuyển trạng thái: sự kiện X → phải sang trạng thái Y. |
| `error_surface` | Một case: khi trigger xảy ra, người dùng phải thấy đúng thông báo đó. |

**Vì sao case từ luồng là `execution="manual"`:** tài liệu viết *"User bấm Sign in
with Keycloak"* — tool không tự biết nút đó nằm ở element nào cho tới khi crawl
được trang. Case vẫn hoàn toàn hợp lệ và có giá trị: người QC đọc là làm theo được
ngay. Đánh dấu `manual` để runner **không** chạy nó và **không** báo `Pass`/`Blocked`
sai — nó vào nhóm "cần người chạy" trong báo cáo.

Sau khi crawl xong, mapper có thể nâng một số case `manual` lên `auto` nếu map được
hết các bước sang element có thật.
"""

from __future__ import annotations

from ..testcase import (
    CaseType,
    Priority,
    Step,
    StepKind,
    Technique,
    TestCase,
)
from .from_openapi import IdAllocator

# Từ khoá nhận diện case âm trong luồng/quyết định
NEGATIVE_MARKERS = (
    "không", "chặn", "từ chối", "cấm", "lỗi", "thất bại", "fail", "reject", "deny",
    "forbidden", "hidden", "ẩn", "không hiện", "không crash", "no ", "not ", "popup",
)


def _looks_negative(text: str) -> bool:
    lowered = (text or "").lower()
    return any(m in lowered for m in NEGATIVE_MARKERS)


def _clean(text: str) -> str:
    return " ".join((text or "").split()).strip()


def generate_from_flows(flows: dict, alloc: IdAllocator, module: str) -> list[TestCase]:
    """Sinh toàn bộ case từ dữ liệu `flows.yaml` của MỘT feature."""
    if not flows:
        return []

    cases: list[TestCase] = []
    cases.extend(_flows_cases(flows.get("flow", []), alloc, module))
    cases.extend(_decision_cases(flows.get("decision", []), alloc, module))
    cases.extend(_transition_cases(flows.get("transition", []), alloc, module))
    cases.extend(_error_surface_cases(flows.get("error_surface", []), alloc, module))
    cases.extend(_scenario_cases(flows.get("scenario", []), alloc, module))
    return cases


# ── Luồng ────────────────────────────────────────────────────────────────────
def _flows_cases(items: list[dict], alloc: IdAllocator, module: str) -> list[TestCase]:
    out: list[TestCase] = []
    for flow in items:
        steps_raw = flow.get("steps", [])
        if len(steps_raw) < 2:
            continue

        steps: list[Step] = []
        expected: list[str] = []

        for raw in steps_raw:
            action = _clean(raw.get("action"))
            want = _clean(raw.get("expected"))
            if not action:
                continue
            args: dict = {"description": action}
            if want:
                args["expectation"] = want
            steps.append(Step(len(steps) + 1, StepKind.WHEN, "perform.unmapped", args))
            if want:
                expected.append(want)

        if not steps:
            continue

        # Kỳ vọng cuối cùng của luồng là điều quan trọng nhất — luồng đúng nghĩa
        # là kết thúc ở đúng chỗ. Nếu tài liệu không viết kỳ vọng nào (ví dụ
        # sequence diagram chỉ có thông điệp), thì lấy bước cuối làm kỳ vọng.
        final = _clean(flow.get("final") or (expected[-1] if expected else ""))
        if not final:
            final = _clean(steps_raw[-1].get("action"))

        steps.append(Step(len(steps) + 1, StepKind.THEN, "assert.unmapped",
                          {"expected": final}))

        title = _clean(flow.get("title")) or "Luồng nghiệp vụ"
        out.append(TestCase(
            id=alloc.next(module),
            module=module,
            title=f"{title} — {len(steps_raw)} bước",
            objective=f"Kiểm chứng luồng «{title}» đi đúng từng bước như tài liệu mô tả",
            steps=steps,
            priority=Priority.HIGH,
            case_type=CaseType.STATE if _looks_negative(final) else CaseType.POSITIVE,
            technique=Technique.STATE_TRANSITION,
            traces_to=[flow["id"]],
            source_quote=_clean(flow.get("source_quote") or title),
            source_ref=f"{flow.get('source_file', '')}:{flow.get('source_line', '')}",
            test_data={"luồng": title, "số bước": len(steps_raw)},
            execution="manual",
        ))
    return out


# ── Điểm quyết định ──────────────────────────────────────────────────────────
def _decision_cases(items: list[dict], alloc: IdAllocator, module: str) -> list[TestCase]:
    """Decision table: mỗi điểm quyết định sinh HAI case, một cho mỗi nhánh.

    Sinh một case cho cả hai nhánh là sai bản chất: chỉ cần một nhánh chạy đúng
    thì case vẫn "đạt", trong khi nhánh còn lại có thể hỏng hoàn toàn.

    Bước WHEN dùng **nguyên văn** `flow` của tài liệu (`Duyệt danh sách project`),
    không bọc thêm câu đệm kiểu «Thực hiện «…»». Câu đệm không mang thêm thông tin
    nào để người chạy làm theo — nó chỉ làm cột Test Steps dài ra.
    """
    out: list[TestCase] = []
    for dec in items:
        flow = _clean(dec.get("flow"))
        condition = _clean(dec.get("condition"))
        branches = [("đúng", dec.get("yes"), CaseType.POSITIVE),
                    ("sai", dec.get("no"), CaseType.NEGATIVE)]

        for label, expectation, case_type in branches:
            expectation = _clean(expectation)
            if not expectation:
                continue
            out.append(TestCase(
                id=alloc.next(module),
                module=module,
                title=f"{flow} — khi {condition}: {expectation[:66]}",
                objective=(
                    f"Kiểm chứng nhánh «{label}» của quyết định «{flow}»: "
                    f"khi {condition}, hệ thống phải {expectation}"
                ),
                steps=[
                    Step(1, StepKind.GIVEN, "perform.unmapped",
                         {"description": condition}),
                    Step(2, StepKind.WHEN, "perform.unmapped",
                         {"description": flow}),
                    Step(3, StepKind.THEN, "assert.unmapped", {"expected": expectation}),
                ],
                priority=Priority.HIGH,
                case_type=case_type,
                technique=Technique.DECISION_TABLE,
                traces_to=[dec["id"]],
                source_quote=_clean(dec.get("source_quote") or condition),
                source_ref=f"{dec.get('source_file', '')}:{dec.get('source_line', '')}",
                test_data={"điều kiện": condition, "nhánh": label},
                execution="manual",
            ))
    return out


# ── Chuyển trạng thái ────────────────────────────────────────────────────────
def _transition_cases(items: list[dict], alloc: IdAllocator, module: str) -> list[TestCase]:
    """Mỗi chuyển trạng thái là một case: ở trạng thái A, khi X, phải sang B.

    Bỏ qua `[*]` — đó là ký hiệu mermaid cho "bắt đầu/kết thúc", không phải trạng
    thái có thật. Sinh case «từ trạng thái [*]» là sinh case không ai thực hiện được.
    """
    out: list[TestCase] = []
    seen: set[tuple[str, str, str]] = set()

    for trans in items:
        src = _clean(trans.get("from_state"))
        dst = _clean(trans.get("to_state"))
        trigger = _clean(trans.get("trigger"))
        if not src or not dst or src == "[*]" or dst == "[*]" or src == dst:
            continue
        key = (src, dst, trigger)
        if key in seen:              # mermaid + bảng thường mô tả cùng chuyển
            continue
        seen.add(key)

        action = trigger or f"tác động đưa hệ thống từ {src} sang {dst}"
        steps = []
        if src:
            steps.append(Step(1, StepKind.GIVEN, "perform.unmapped",
                              {"description": f"Trạng thái hiện tại: {src}"}))
        steps.append(Step(len(steps) + 1, StepKind.WHEN, "perform.unmapped",
                          {"description": action}))
        steps.append(Step(len(steps) + 1, StepKind.THEN, "assert.unmapped",
                          {"expected": f"Chuyển sang trạng thái «{dst}»"}))

        out.append(TestCase(
            id=alloc.next(module),
            module=module,
            title=f"{src} → {dst}" + (f" khi {action[:48]}" if trigger else ""),
            objective=f"Kiểm chứng trạng thái chuyển từ «{src}» sang «{dst}»",
            steps=steps,
            priority=Priority.MEDIUM,
            case_type=CaseType.STATE,
            technique=Technique.STATE_TRANSITION,
            traces_to=[trans["id"]],
            source_quote=_clean(trans.get("source_quote") or f"{src} → {dst}: {trigger}"),
            source_ref=f"{trans.get('source_file', '')}:{trans.get('source_line', '')}",
            test_data={"từ": src, "sang": dst, "kích hoạt": trigger or "—"},
            execution="manual",
        ))
    return out


# ── Bề mặt lỗi ───────────────────────────────────────────────────────────────
def _error_surface_cases(items: list[dict], alloc: IdAllocator, module: str) -> list[TestCase]:
    out: list[TestCase] = []
    for err in items:
        surface = _clean(err.get("surface"))
        trigger = _clean(err.get("trigger"))
        ux = _clean(err.get("ux"))
        if not (surface or ux):
            continue
        out.append(TestCase(
            id=alloc.next(module),
            module=module,
            title=f"Lỗi «{surface}»: {trigger[:50]} → {ux[:50]}",
            objective=f"Kiểm chứng khi {trigger}, người dùng thấy đúng «{ux}»",
            steps=[
                Step(1, StepKind.GIVEN, "perform.unmapped", {"description": trigger}),
                Step(2, StepKind.WHEN, "perform.unmapped",
                     {"description": f"Thao tác gây ra «{surface}»"}),
                Step(3, StepKind.THEN, "assert.unmapped", {"expected": ux}),
            ],
            priority=Priority.MEDIUM,
            case_type=CaseType.NEGATIVE,
            technique=Technique.ERROR_GUESSING,
            traces_to=[err["id"]],
            source_quote=_clean(err.get("source_quote") or f"{surface} | {trigger} | {ux}"),
            source_ref=f"{err.get('source_file', '')}:{err.get('source_line', '')}",
            test_data={"bề mặt": surface, "kích hoạt": trigger},
            execution="manual",
        ))
    return out


# ── Kịch bản theo vai trò ────────────────────────────────────────────────────
def _scenario_cases(items: list[dict], alloc: IdAllocator, module: str) -> list[TestCase]:
    """Scenario matrix: mỗi dòng là một tổ hợp vai trò × thao tác × kết quả."""
    out: list[TestCase] = []
    for sc in items:
        role = _clean(sc.get("from_state"))
        action = _clean(sc.get("action"))
        rule = _clean(sc.get("rule"))
        result = _clean(sc.get("result")) or _clean(sc.get("then_action"))
        if not (action and result):
            continue
        out.append(TestCase(
            id=alloc.next(module),
            module=module,
            title=f"[{role}] {action[:45]} → {result[:45]}",
            objective=f"Kiểm chứng kịch bản cho vai trò «{role}»" + (f" — luật: {rule}" if rule else ""),
            steps=[
                Step(1, StepKind.GIVEN, "perform.unmapped",
                     {"description": f"Vai trò: {role}"}),
                Step(2, StepKind.WHEN, "perform.unmapped", {"description": action}),
                Step(3, StepKind.THEN, "assert.unmapped", {"expected": result}),
            ],
            priority=Priority.MEDIUM,
            case_type=CaseType.SECURITY if _looks_negative(result) else CaseType.POSITIVE,
            technique=Technique.DECISION_TABLE,
            traces_to=[sc["id"]],
            source_quote=_clean(sc.get("source_quote") or f"{role} | {action} | {result}"),
            source_ref=f"{sc.get('source_file', '')}:{sc.get('source_line', '')}",
            test_data={"vai trò": role, "thao tác": action},
            execution="manual",
        ))
    return out

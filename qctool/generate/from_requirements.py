"""Sinh testcase từ requirement phi-API: acceptance criteria và NFR.

Đầu vào là `requirements.yaml` (output của chặng ingest), không phải OpenAPI.

- **Acceptance criterion** dạng Given/When/Then map rất thẳng sang testcase:
  Given → precondition, When → bước, Then → kỳ vọng. Đây là nguồn case
  chất lượng cao nhất vì tài liệu đã nói rõ cả ba vế.

- **NFR** chỉ sinh được case khi **có ngưỡng định lượng**. `p95 < 100ms` thì test được;
  "shall be user-friendly" thì không. Trường hợp không kiểm chứng được thì **không sinh**,
  mà ghi vào danh sách `unverifiable` để báo cáo biết đó là lỗ hổng của tài liệu —
  không phải lỗi của tool, và cũng không được giấu đi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..testcase import (
    PERF_SAMPLES,
    CaseType,
    Priority,
    Step,
    StepKind,
    Technique,
    TestCase,
    percentile_of,
)
from .from_openapi import IdAllocator

# NFR đo được: tìm ngưỡng số trong câu
RE_MS = re.compile(r"(?:p\d+\s*[<≤]\s*|dưới\s+|under\s+|<\s*)(\d+(?:\.\d+)?)\s*ms", re.I)
RE_SECONDS = re.compile(r"(?:dưới|trong|under|within)\s+(\d+(?:\.\d+)?)\s*(?:giây|s\b|seconds?)", re.I)


@dataclass
class Unverifiable:
    """Requirement không sinh được testcase — và vì sao."""

    requirement_id: str
    title: str
    reason: str


@dataclass
class GenerateResult:
    cases: list[TestCase] = field(default_factory=list)
    unverifiable: list[Unverifiable] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def generate_from_acceptance(requirements: list[dict], alloc: IdAllocator,
                             module: str) -> GenerateResult:
    """Sinh từ acceptance criterion Given/When/Then."""
    result = GenerateResult()
    us_titles = {r["id"]: r.get("title", "") for r in requirements if r["kind"] == "user_story"}

    for req in requirements:
        if req["kind"] != "acceptance_criterion":
            continue
        given, when, then = req.get("given"), req.get("when"), req.get("then")
        if not all((given, when, then)):
            result.warnings.append(
                f"{req['id']}: thiếu vế Given/When/Then — bỏ qua, không đoán"
            )
            continue

        us = req.get("belongs_to")
        us_title = us_titles.get(us, "")
        semantic = f"{when} {then}".lower()
        case_type = CaseType.NEGATIVE if _looks_negative(semantic) else CaseType.POSITIVE
        priority = Priority.HIGH if case_type == CaseType.NEGATIVE else Priority.MEDIUM

        result.cases.append(TestCase(
            id=alloc.next(module),
            module=module,
            title=_title_from(when, then),
            objective=f"Kiểm chứng {req['id']}" + (f" của {us}" if us else ""),
            steps=[
                Step(1, StepKind.WHEN, "perform.unmapped",
                     {"description": when.strip(), "expectation": then.strip()}),
                Step(2, StepKind.THEN, "assert.unmapped", {"expected": then.strip()}),
            ],
            priority=priority,
            case_type=case_type,
            technique=Technique.ACCEPTANCE_CRITERION,
            traces_to=[req["id"]] + ([us] if us else []),
            source_quote=f"Given {given} / When {when} / Then {then}",
            source_ref=f"{req.get('source', {}).get('file', '')}:"
                       f"{req.get('source', {}).get('line', '')}",
            preconditions=[given],
            test_data={},
            generated_by="engine",
            # Acceptance criterion viết bằng văn xuôi: `When`/`Then` chưa map sang
            # element UI hay endpoint cụ thể. Case vẫn dùng được ngay cho người
            # chạy tay, nhưng runner không được tự nhận là chạy được. Mapper sẽ
            # nâng lên `auto` nếu map hết được các bước.
            execution="manual",
        ))

    return result


def _clean(text: str) -> str:
    return " ".join((text or "").split()).strip().rstrip(".")


def _looks_negative(text: str) -> bool:
    """Dấu hiệu case âm: hệ thống phải TỪ CHỐI hoặc KHÔNG làm gì."""
    markers = ("không", "chặn", "từ chối", "cấm", "lỗi", "fail", "reject", "deny",
               "forbidden", "hidden", "không hiện", "không crash", "no ", "not ")
    return any(m in text for m in markers)


def _title_from(when: str, then: str) -> str:
    w = when.strip().rstrip(".")
    t = then.strip().rstrip(".")
    return f"{w} → {t}"[:180]


def generate_from_nfr(requirements: list[dict], alloc: IdAllocator,
                      module: str) -> GenerateResult:
    """Sinh từ NFR — chỉ khi có ngưỡng đo được."""
    result = GenerateResult()

    for req in requirements:
        if req["kind"] != "non_functional":
            continue
        text = req.get("statement") or req.get("title") or ""
        threshold = _extract_threshold(text)

        if threshold is None:
            result.unverifiable.append(Unverifiable(
                requirement_id=req["id"],
                title=req.get("title", ""),
                reason="Không có ngưỡng định lượng trong câu — không kiểm chứng được tự động",
            ))
            continue

        kind, value, unit = threshold
        limit = f"{int(value)}{unit}" if unit == "ms" else f"{value:g} giây"
        statement = _clean(text)
        result.cases.append(TestCase(
            id=alloc.next(module),
            module=module,
            title=f"{statement[:90]} — phải dưới {limit}",
            objective=f"Kiểm chứng ngưỡng hiệu năng của {req['id']}: dưới {limit}",
            steps=[
                Step(1, StepKind.WHEN, "perform.unmapped", {"description": text.strip()}),
                Step(2, StepKind.THEN, "assert.response_time", {
                    "max_ms": value if unit == "ms" else int(value * 1000),
                    # Ngưỡng trong tài liệu là **phân vị** (`p95 < 100ms`), nên
                    # phải đo bằng p95 của nhiều lần gọi. So một lần gọi với ngưỡng
                    # p95 là kiểm chặt hơn yêu cầu, và đã báo `Fail` sai thật.
                    "percentile": percentile_of(text),
                    "samples": PERF_SAMPLES,
                }),
            ],
            priority=Priority.MEDIUM,
            case_type=CaseType.PERFORMANCE,
            technique=Technique.PERFORMANCE_THRESHOLD,
            traces_to=[req["id"]],
            source_quote=text,
            source_ref=f"{req.get('source', {}).get('file', '')}:"
                       f"{req.get('source', {}).get('line', '')}",
            generated_by="engine",
        ))

    return result


def _extract_threshold(text: str) -> tuple[str, float, str] | None:
    """Tìm ngưỡng thời gian trong câu NFR. Không có thì trả None — không đoán."""
    if m := RE_MS.search(text):
        return ("ms", float(m.group(1)), "ms")
    if m := RE_SECONDS.search(text):
        return ("s", float(m.group(1)), "s")
    return None

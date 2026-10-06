"""Lập testcase logic chỉ từ nghĩa vụ coverage tường minh, không dùng LLM."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Iterable

from .coverage import CoverageObligation, CoverageReport, CoverageStatus, _matches, _text
from .generate.from_openapi import IdAllocator
from .testcase import CaseType, Step, StepKind, Technique, TestCase


@dataclass(frozen=True)
class CoveragePlanLink:
    obligation: CoverageObligation
    testcase_id: str
    generated: bool


@dataclass(frozen=True)
class SkippedCoverageObligation:
    obligation: CoverageObligation
    code: str
    reason: str


@dataclass(frozen=True)
class CoveragePlan:
    cases: tuple[TestCase, ...]
    links: tuple[CoveragePlanLink, ...]
    skipped: tuple[SkippedCoverageObligation, ...]

    @property
    def obligation_to_testcase(self) -> dict[str, str]:
        return {link.obligation.id: link.testcase_id for link in self.links}

    def to_dict(self) -> dict:
        return {"cases": [case.to_dict() for case in self.cases],
                "links": [asdict(link) for link in self.links],
                "skipped": [asdict(item) for item in self.skipped]}


def _intent(obligation: CoverageObligation) -> tuple:
    return (_text(obligation.condition), _text(obligation.action),
            _text(obligation.expected), tuple(sorted(obligation.test_data)))


def _unsupported(obligation: CoverageObligation) -> str | None:
    if not obligation.expected.strip():
        return "No explicit expected outcome"
    if not obligation.source.source_id or not obligation.source.field:
        return "No exact source ID/field provenance"
    if obligation.testcase_ids:
        return "Missing status conflicts with existing covering testcase IDs"
    if obligation.kind in {"decision_branch", "permission_role", "state_outcome"}:
        if not obligation.condition.strip() or not obligation.action.strip():
            return "Required explicit condition/action metadata is absent"
    if obligation.kind == "happy_path" and not obligation.action.strip():
        return "Happy-path action metadata is absent"
    if obligation.kind == "negative_error" and not obligation.condition.strip():
        return "Error condition metadata is absent"
    if obligation.kind == "decision_branch":
        label = {"yes": "đúng", "no": "sai"}.get(obligation.source.field)
        if not label or dict(obligation.test_data).get("nhánh") != label:
            return "Decision branch metadata is absent or inconsistent"
    elif obligation.kind == "permission_role":
        role = dict(obligation.test_data).get("vai trò")
        if not role or obligation.condition != f"Vai trò: {role}":
            return "Explicit role metadata is absent or inconsistent"
    elif obligation.kind not in {"business_outcome", "negative_error", "happy_path", "state_outcome"}:
        return "Unsupported obligation structure"
    return None


def _candidate(obligation: CoverageObligation, testcase_id: str, module: str) -> TestCase:
    steps = []
    for kind, text in ((StepKind.GIVEN, obligation.condition),
                       (StepKind.WHEN, obligation.action)):
        if text:
            steps.append(Step(len(steps) + 1, kind, "perform.unmapped", {"description": text}))
    steps.append(Step(len(steps) + 1, StepKind.THEN, "assert.unmapped",
                      {"expected": obligation.expected}))
    for step in steps:
        step.note = "[source-clause] " + json.dumps({
            "obligation_id": obligation.id, "source": asdict(obligation.source),
            "field": step.kind.value,
            "text": step.args.get("description", step.args.get("expected")),
        }, ensure_ascii=False, sort_keys=True)
    case_type, technique = CaseType.STATE, Technique.ACCEPTANCE_CRITERION
    if obligation.kind == "happy_path":
        case_type = CaseType.POSITIVE
    elif obligation.kind == "negative_error":
        case_type, technique = CaseType.NEGATIVE, Technique.ERROR_GUESSING
    elif obligation.kind == "permission_role":
        case_type, technique = CaseType.SECURITY, Technique.DECISION_TABLE
    elif obligation.kind == "decision_branch":
        case_type = CaseType.POSITIVE if obligation.source.field == "yes" else CaseType.NEGATIVE
        technique = Technique.DECISION_TABLE
    elif obligation.kind == "state_outcome":
        technique = Technique.STATE_TRANSITION
    source = obligation.source
    # If no quote was supplied, use only the explicit obligation text, not a
    # synthesized business expectation. The link retains the original source.
    quote = source.quote or " / ".join(t for t in (
        obligation.condition, obligation.action, obligation.expected) if t)
    case = TestCase(
        id=testcase_id, module=module,
        title=f"{obligation.action or obligation.condition or source.source_id} → {obligation.expected}",
        objective=f"Kiểm chứng nghĩa vụ {obligation.id}", steps=steps,
        preconditions=[obligation.condition] if obligation.condition else [],
        test_data=dict(obligation.test_data), case_type=case_type, technique=technique,
        traces_to=[source.source_id], source_quote=quote,
        source_ref=f"{source.file}:{source.line}" if source.file and source.line is not None else source.file,
        generated_by="engine", execution="manual",
    )
    case.validate()
    return case


def plan_coverage(report: CoverageReport, *, existing_cases: Iterable[TestCase] = (),
                  module: str = "COV", reserved_case_ids: Iterable[str] = ()) -> CoveragePlan:
    """Generate detached logical candidates only for report.missing_obligations.

    Exact duplicate missing intents share one candidate with all source traces
    and audit links. Covered intents are not cloned across source IDs: they are
    skipped for explicit traceability review, without editing existing cases.
    Existing cases may be supplied to catch stale reports and reserve IDs.
    No interpretation of prose, additional setup steps, or LLM calls occurs.
    """
    existing = tuple(existing_cases)
    used_ids = {c.id for c in existing} | set(reserved_case_ids)
    covered = {}
    for requirement in report.requirements:
        used_ids.update(requirement.traced_testcase_ids)
        for obligation in requirement.obligations:
            used_ids.update(obligation.testcase_ids)
            if obligation.status == CoverageStatus.COVERED:
                covered[_intent(obligation)] = obligation
    allocator = IdAllocator()
    cases, links, skipped = [], [], []
    generated = {}
    for obligation in report.unassessable_obligations:
        skipped.append(SkippedCoverageObligation(
            obligation, "UNASSESSABLE", obligation.reason or "Coverage cannot be assessed deterministically"))
    for obligation in report.missing_obligations:
        reason = _unsupported(obligation)
        if reason:
            skipped.append(SkippedCoverageObligation(obligation, "UNSUPPORTED_OBLIGATION", reason))
            continue
        matches = [c for c in existing if obligation.source.source_id in c.traces_to
                   and _matches(c, obligation.condition, obligation.action,
                                obligation.expected, dict(obligation.test_data))]
        if matches:
            chosen = min(matches, key=lambda c: c.id)
            links.append(CoveragePlanLink(obligation, chosen.id, False))
            skipped.append(SkippedCoverageObligation(
                obligation, "EXISTING_INTENT", "An explicitly traced existing testcase already covers this intent"))
            continue
        intent = _intent(obligation)
        if intent in covered:
            skipped.append(SkippedCoverageObligation(
                obligation, "COVERED_INTENT", "Identical intent is already covered; source traceability needs review"))
            continue
        if intent in generated:
            candidate = generated[intent]
            if obligation.source.source_id not in candidate.traces_to:
                candidate.traces_to.append(obligation.source.source_id)
        else:
            testcase_id = allocator.next(module)
            while testcase_id in used_ids:
                testcase_id = allocator.next(module)
            used_ids.add(testcase_id)
            candidate = _candidate(obligation, testcase_id, module)
            generated[intent] = candidate
            cases.append(candidate)
        links.append(CoveragePlanLink(obligation, candidate.id, True))
    return CoveragePlan(tuple(cases), tuple(links), tuple(skipped))

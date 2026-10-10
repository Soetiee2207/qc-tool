"""Độ phủ ý định test từ metadata tường minh; không suy diễn hoặc sinh case.

Không phải độ phủ thực thi/Pass. Case manual có thể phủ một nghĩa vụ nguồn.
Không chứng minh tương đương ngữ nghĩa giữa prose và assertion đã được map.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable

from qctool.core.model import Requirement
from qctool.core.testcase import StepKind, TestCase


class CoverageStatus(str, Enum):
    COVERED = "covered"
    PARTIALLY_COVERED = "partially_covered"
    UNCOVERED = "uncovered"
    UNASSESSABLE = "not_deterministically_assessable"


@dataclass(frozen=True)
class CoverageSource:
    source_id: str
    source_ids: tuple[str, ...]
    field: str
    file: str = ""
    line: int | None = None
    quote: str = ""


@dataclass(frozen=True)
class CoverageObligation:
    id: str
    kind: str
    condition: str
    action: str
    expected: str
    source: CoverageSource
    status: CoverageStatus
    testcase_ids: tuple[str, ...]
    reason: str = ""
    # Explicit generator branch/role metadata, immutable and retained for planning.
    test_data: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RequirementCoverage:
    requirement_id: str
    kind: str
    status: CoverageStatus
    source: CoverageSource
    traced_testcase_ids: tuple[str, ...]
    obligations: tuple[CoverageObligation, ...]
    reason: str = ""


@dataclass(frozen=True)
class CoverageReport:
    requirements: tuple[RequirementCoverage, ...]

    @property
    def missing_obligations(self) -> tuple[CoverageObligation, ...]:
        """Nghĩa vụ chắc chắn chưa phủ; unknown nằm riêng để tránh kết luận sai."""
        return self._obligations_with(CoverageStatus.UNCOVERED)

    @property
    def unassessable_obligations(self) -> tuple[CoverageObligation, ...]:
        return self._obligations_with(CoverageStatus.UNASSESSABLE)

    def _obligations_with(self, status: CoverageStatus) -> tuple[CoverageObligation, ...]:
        # Parent summaries repeat child obligations; report-level lists must not.
        return tuple({o.id: o for r in self.requirements for o in r.obligations
                      if o.status == status}.values())

    def to_dict(self) -> dict:
        return asdict(self)


def _text(value: str | None) -> str:
    # Whitespace only: no case folding, keyword classification or fuzzy matching.
    return " ".join((value or "").split())


def _source(row: dict, field: str) -> CoverageSource:
    source = row.get("source") or {}
    return CoverageSource(row["id"], tuple(row.get("source_ids", [])), field,
                          source.get("file", row.get("source_file", "")),
                          source.get("line", row.get("source_line")),
                          source.get("quote", row.get("source_quote", "")))


def _matches(case: TestCase, condition: str, action: str, expected: str,
             data: dict) -> bool:
    # Validated agent metadata preserves the exact original obligation; no
    # prose grammar is used to equate DOM labels with requirement phrases.
    intent = case.source_intent
    if intent and case.generation_status in {'ready', 'needs_review'}:
        return (intent.get('given', '') == condition and intent.get('when', '') == action
                and intent.get('expected', '') == expected
                and all(case.test_data.get(k) == v for k, v in data.items()))
    def descriptions(kind):
        return {_text(s.args.get("description")) for s in case.steps
                if s.kind == kind and s.action == "perform.unmapped"}
    given = descriptions(StepKind.GIVEN) | {_text(p) for p in case.preconditions}
    when = descriptions(StepKind.WHEN)
    # Only explicit expected prose; an arbitrary assert.text is not proof that
    # the complete original business outcome is covered.
    outcomes = {_text(s.args.get("expected")) for s in case.steps
                if s.action == "assert.unmapped" and s.kind == StepKind.THEN}
    outcomes.update(_text(s.args.get("expectation")) for s in case.steps
                    if s.action == "perform.unmapped" and s.kind == StepKind.WHEN
                    and _text(s.args.get("description")) == action)
    # A small explicit metadata convention also survives mapping. Do not infer
    # routes from arbitrary prose or broad regex patterns: exact "Open <url>"
    # and "URL <url>" source clauses must match concrete runtime arguments.
    for step in case.steps:
        if step.kind == StepKind.WHEN and step.action == "ui.goto":
            url = step.args.get("url")
            if isinstance(url, str) and url:
                when.add(f"Open {url}")
        if step.kind == StepKind.THEN and step.action == "assert.url_matches":
            pattern = step.args.get("pattern")
            if isinstance(pattern, str) and pattern.startswith("/"):
                route = pattern.removesuffix("$")
                if not any(char in route for char in ".*+?[](){}^$|\\"):
                    outcomes.add(f"URL {route}")
    return (expected in outcomes and (not condition or condition in given)
            and (not action or action in when)
            and all(case.test_data.get(k) == v for k, v in data.items()))


def _definitions(row: dict):
    """Yield (source field, obligation kind, given, when, then, branch metadata)."""
    kind = row.get("kind")
    if kind == "acceptance_criterion":
        if all(_text(row.get(k)) for k in ("given", "when", "then")):
            yield "then", "business_outcome", row["given"], row["when"], row["then"], {}
    for i, expected in enumerate(row.get("acceptance", [])):
        if _text(expected):
            yield f"acceptance[{i}]", "business_outcome", "", "", expected, {}
    api = row.get("api") or {}
    for i, entry in enumerate(api.get("error_handling", [])):
        if entry.get("condition") and entry.get("behavior"):
            yield (f"api.error_handling[{i}]", "negative_error", entry["condition"],
                   "", entry["behavior"], {})
    if kind == "decision" and row.get("condition") and row.get("flow"):
        for branch, label in (("yes", "đúng"), ("no", "sai")):
            if row.get(branch):
                yield branch, "decision_branch", row["condition"], row["flow"], row[branch], {"nhánh": label}
    if kind == "scenario" and row.get("action") and (row.get("result") or row.get("then_action")):
        yield ("result", "permission_role", f"Vai trò: {row.get('from_state', '')}",
               row["action"], row.get("result") or row["then_action"],
               {"vai trò": _text(row.get("from_state"))})
    if kind == "transition" and all(row.get(k) for k in ("from_state", "to_state", "trigger")):
        yield ("to_state", "state_outcome", f"Trạng thái hiện tại: {row['from_state']}",
               row["trigger"], f"Chuyển sang trạng thái «{row['to_state']}»", {})
    if kind == "flow":
        for i, step in enumerate(row.get("steps", [])):
            if step.get("action") and step.get("expected"):
                yield f"steps[{i}].expected", "happy_path", "", step["action"], step["expected"], {}
    if kind == "error_surface" and row.get("trigger") and row.get("ux"):
        yield "ux", "negative_error", row["trigger"], "", row["ux"], {}


def _aggregate(statuses: list[CoverageStatus]) -> CoverageStatus:
    if not statuses:
        return CoverageStatus.UNASSESSABLE
    if all(s == CoverageStatus.COVERED for s in statuses):
        return CoverageStatus.COVERED
    if CoverageStatus.COVERED in statuses:
        return CoverageStatus.PARTIALLY_COVERED
    if CoverageStatus.UNASSESSABLE in statuses:
        return CoverageStatus.UNASSESSABLE
    return CoverageStatus.UNCOVERED


def analyze_coverage(requirements: Iterable[Requirement | dict], cases: Iterable[TestCase],
                     *, flows: dict | None = None) -> CoverageReport:
    """Analyse native requirements and optional ingest flow sources, read-only.

    ID trace is necessary but not sufficient for outcome coverage. A traced
    case without exact condition/action/expected metadata is unknown, not proof
    of absence. Parent user stories aggregate only explicit belongs_to children.
    Unsupported prose, including boundary descriptions, remains unassessable.
    Status describes the enumerated obligations, not every meaning in prose.
    """
    rows = [r.to_dict() if isinstance(r, Requirement) else r for r in requirements]
    if flows:
        groups = [flows] if any(k in flows for k in ("flow", "decision", "scenario", "transition", "error_surface")) else flows.values()
        for group in groups:
            for kind in ("flow", "decision", "scenario", "transition", "error_surface"):
                rows.extend({**r, "kind": kind} for r in group.get(kind, []))
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("Coverage source IDs must be unique")
    cases = tuple(cases)
    results = []
    for row in rows:
        linked = tuple(c for c in cases if row["id"] in c.traces_to)
        obligations = []
        for field, kind, given, when, expected, data in _definitions(row):
            given, when, expected = map(_text, (given, when, expected))
            have = tuple(sorted({c.id for c in linked if _matches(c, given, when, expected, data)}))
            opaque = any(not any(s.action == "assert.unmapped" for s in c.steps)
                         or any(s.action.startswith("assert.") and s.action != "assert.unmapped"
                                for s in c.steps) for c in linked)
            status = (CoverageStatus.COVERED if have else
                      CoverageStatus.UNASSESSABLE if opaque else CoverageStatus.UNCOVERED)
            obligations.append(CoverageObligation(
                f"{row['id']}:{field}", kind, given, when, expected, _source(row, field),
                status, have, "Traced cases lack exact outcome/branch metadata" if status == CoverageStatus.UNASSESSABLE else "",
                tuple(sorted(data.items()))))
        results.append(RequirementCoverage(
            row["id"], row.get("kind", "unknown"), _aggregate([o.status for o in obligations]),
            _source(row, ""), tuple(sorted({c.id for c in linked})), tuple(obligations),
            "No supported explicit outcome metadata (prose/limits are not interpreted)" if not obligations else ""))
    # Explicit parent relationship is the only relation used for aggregation.
    by_id = {r.requirement_id: r for r in results}
    for i, row in enumerate(rows):
        children = [by_id[r["id"]] for r in rows if r.get("belongs_to") == row["id"]]
        if row.get("kind") == "user_story" and children:
            own = results[i]
            obligations = own.obligations + tuple(o for child in children for o in child.obligations)
            results[i] = RequirementCoverage(
                own.requirement_id, own.kind, _aggregate(
                    ([own.status] if own.obligations else []) + [c.status for c in children]),
                own.source, own.traced_testcase_ids, obligations,
                "Aggregated explicit belongs_to acceptance criteria")
    return CoverageReport(tuple(results))

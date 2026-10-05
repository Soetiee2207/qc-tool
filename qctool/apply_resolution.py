"""Apply already validated step repairs to a detached testcase copy.

This boundary accepts a ProposalValidationResult, never a raw LLM proposal.
It performs no evidence lookup or interpretation.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from .executability import ExecutabilityReport, analyze_executability
from .llm_resolution import ProposedChange
from .proposal_validation import (
    ProposalValidationResult, _case_fingerprint, _changes_fingerprint,
)
from .step_expansion import candidate_with_changes
from .testcase import TestCase, ValidationError


@dataclass(frozen=True)
class ApplicationIssue:
    code: str
    message: str
    step_seq: int | None = None


@dataclass(frozen=True)
class AppliedChange:
    change: ProposedChange
    before_args: dict
    validated_by: str = "deterministic-proposal-validator"

    def to_dict(self) -> dict:
        return {
            "step_seq": self.change.step_seq,
            "before": {"action": self.change.from_action, "args": deepcopy(self.before_args)},
            "after": ({"steps": [atom.to_dict() for atom in self.change.expansion]}
                      if self.change.expansion else
                      {"action": self.change.action, "args": deepcopy(self.change.args)}),
            "reason": self.change.reason,
            "evidence": [evidence.to_dict() for evidence in self.change.evidence],
            "validated_by": self.validated_by,
        }


@dataclass(frozen=True)
class ApplyResult:
    case: TestCase
    applied_changes: tuple[AppliedChange, ...]
    issues: tuple[ApplicationIssue, ...]
    before: ExecutabilityReport
    after: ExecutabilityReport
    promoted_to_auto: bool = False


def apply_validated_resolution(
    case: TestCase, validation_result: ProposalValidationResult,
) -> ApplyResult:
    """Apply exact validated changes; stale or altered validation is atomic no-op.

    A manual case is promoted only when it originally needed mapping, all mapped
    steps now have runtime support, and an auto-mode probe has no execution gaps.
    """
    if not isinstance(validation_result, ProposalValidationResult):
        raise TypeError("apply_validated_resolution requires ProposalValidationResult")

    before = analyze_executability(case)
    detached = deepcopy(case)
    issues: list[ApplicationIssue] = []
    if case.id != validation_result.testcase_id:
        issues.append(ApplicationIssue("TESTCASE_MISMATCH", "Validation belongs to another testcase."))
    if (_case_fingerprint(case) != validation_result.case_fingerprint
            or before != validation_result.before):
        issues.append(ApplicationIssue("STALE_TESTCASE", "Testcase changed after validation."))
    if _changes_fingerprint(validation_result.valid_changes) != validation_result.valid_changes_fingerprint:
        issues.append(ApplicationIssue("VALIDATION_RESULT_CHANGED", "Validated changes were altered."))

    # Identify a changed or missing step precisely, even when the whole-case
    # fingerprint already shows that validation is stale.
    for change in validation_result.valid_changes:
        matches = [step for step in detached.steps if step.seq == change.step_seq]
        if len(matches) != 1:
            issues.append(ApplicationIssue("STEP_NOT_FOUND", "Validated step is missing or duplicated.",
                                           change.step_seq))
        elif matches[0].action != change.from_action:
            issues.append(ApplicationIssue("ACTION_CHANGED", "Validated step action has changed.",
                                           change.step_seq))
    if issues:
        return ApplyResult(detached, (), tuple(issues), before, before)

    applied: list[AppliedChange] = []
    for change in validation_result.valid_changes:
        step = next(step for step in detached.steps if step.seq == change.step_seq)
        applied.append(AppliedChange(deepcopy(change), deepcopy(step.args)))
    detached, _ = candidate_with_changes(case, validation_result.valid_changes)

    try:
        detached.validate()
        structural_error = None
    except ValidationError as exc:
        structural_error = str(exc)
    after_changes = analyze_executability(detached)
    if (structural_error != after_changes.validation_error
            or structural_error is not None and before.validation_error is None):
        issues.append(ApplicationIssue("APPLY_VALIDATION_ERROR", "Applied copy failed structural validation."))
    if after_changes != validation_result.after:
        issues.append(ApplicationIssue("VALIDATION_RESULT_MISMATCH", "Applied copy differs from validated candidate."))
    if issues:
        return ApplyResult(deepcopy(case), (), tuple(issues), before, before)

    promoted = False
    if (applied and case.execution == "manual" and case.needs_mapping
            and not detached.needs_mapping and before.validation_error is None):
        auto_candidate = deepcopy(detached)
        auto_candidate.execution = "auto"
        if analyze_executability(auto_candidate).executable:
            auto_candidate.validate()
            detached = auto_candidate
            promoted = True

    return ApplyResult(detached, tuple(applied), (), before,
                       analyze_executability(detached), promoted)

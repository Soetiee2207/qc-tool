"""One standalone resolution attempt, optionally followed by evidence collection.

There is no retry with the enriched context, no provider implementation, and no
pipeline integration. Stage failures preserve earlier committed results.
"""

from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path

from .apply_resolution import ApplyResult, apply_validated_resolution
from .executability import ExecutabilityReport, analyze_executability
from .exploration_execution import ExplorationExecutionResult, execute_validated_exploration
from .exploration_plan import ExplorationPlan, ExplorationPlanValidationResult, validate_exploration_plan
from .generate.from_openapi import Endpoint
from .llm_exploration import ExplorationLLM, propose_exploration
from .llm_resolution import LLMResponseError, ResolutionLLM, ResolutionProposal, propose_resolution
from .llm_provider import LLMProviderError
from .proposal_validation import ProposalValidationResult, validate_resolution_proposal
from .resolution_context import ResolutionContext, build_resolution_context
from .resolve import ResolutionResult, resolve_deterministically
from .testcase import TestCase
from .ui.crawl import UIMap


@dataclass(frozen=True)
class ResolutionCycleIssue:
    stage: str
    code: str
    message: str


@dataclass(frozen=True)
class ResolutionCycleStage:
    stage: str
    status: str


@dataclass(frozen=True)
class ResolutionCycleResult:
    case: TestCase
    context: ResolutionContext
    before: ExecutabilityReport
    after: ExecutabilityReport
    deterministic: ResolutionResult | None
    proposal: ResolutionProposal | None
    validation: ProposalValidationResult | None
    application: ApplyResult | None
    exploration_plan: ExplorationPlan | None
    exploration_validation: ExplorationPlanValidationResult | None
    exploration_execution: ExplorationExecutionResult | None
    issues: tuple[ResolutionCycleIssue, ...]
    audit: tuple[ResolutionCycleStage, ...]

    @property
    def needs_another_cycle(self) -> bool:
        """Unresolved work remains; this does not promise another attempt succeeds."""
        return not self.after.executable and bool(self.after.gaps)


def _refresh_context(
    case: TestCase, context: ResolutionContext, report: ExecutabilityReport, *,
    ui_map: UIMap | None, endpoints: list[Endpoint] | None,
) -> ResolutionContext:
    fresh = build_resolution_context(case, report.gaps, ui_map=ui_map, endpoints=endpoints)
    detached = deepcopy(context)
    # Retain all selected and explored evidence. Add newly supplied trusted records
    # without replacing previous states or changing specification expectations.
    for field, key in (("observations", "ui_pages"), ("interface_contract", "api_operations")):
        records = getattr(detached, field).setdefault(key, [])
        unique = []
        for record in records:
            if record not in unique:
                unique.append(record)
        records[:] = unique
        for record in getattr(fresh, field)[key]:
            if record not in records:
                records.append(record)
    return replace(detached, testcase=fresh.testcase, gaps=tuple(report.gaps),
                   allowed_actions=fresh.allowed_actions)


def run_resolution_cycle(
    case: TestCase, context: ResolutionContext, *,
    resolution_llm: ResolutionLLM | None = None,
    exploration_llm: ExplorationLLM | None = None,
    base_url: str | None = None, storage_state: Path | None = None,
    ui_map: UIMap | None = None, endpoints: list[Endpoint] | None = None,
) -> ResolutionCycleResult:
    """Run resolution once, then collect evidence once if gaps remain.

    Optional ui_map/endpoints are passed to the existing deterministic resolver;
    selected ResolutionContext evidence is retained for LLM validation. Missing
    adapters are recorded as skipped stages. Failures are isolated and may still
    be followed by exploration, but never by a second resolution LLM request.
    Manual/auto decisions belong solely to the resolver/applier and analyzer.
    """
    working, packet = deepcopy(case), deepcopy(context)
    trusted_ui, trusted_endpoints = deepcopy(ui_map), deepcopy(endpoints)
    before = analyze_executability(working)
    after = before
    issues = []
    audit = [ResolutionCycleStage("analysis", "COMPLETED")]
    deterministic = proposal = validation = application = None
    plan = plan_validation = execution = None

    def finish():
        return deepcopy(ResolutionCycleResult(
            working, packet, before, after, deterministic, proposal, validation,
            application, plan, plan_validation, execution, tuple(issues), tuple(audit)))

    def attempt(stage, operation):
        try:
            value = deepcopy(operation())
        except Exception as exc:
            code = "LLM_RESPONSE_ERROR" if isinstance(exc, LLMResponseError) else "STAGE_FAILED"
            message = f"{stage} failed; earlier progress retained."
            if isinstance(exc, LLMProviderError):
                # Never serialize str(exc), transport URLs, headers or response body.
                # Whitelist codes too: an arbitrary adapter may construct this error.
                code = exc.code if exc.code in {
                    "INVALID_PROMPT", "HTTP_ERROR", "TIMEOUT", "NETWORK_ERROR",
                    "INVALID_RESPONSE", "EMPTY_RESPONSE", "INVALID_COMPLETION",
                } else "LLM_PROVIDER_ERROR"
                message = f"{stage}: {exc.safe_message} Earlier progress retained."
            issues.append(ResolutionCycleIssue(stage, code, message))
            audit.append(ResolutionCycleStage(stage, "FAILED"))
            return False, None
        audit.append(ResolutionCycleStage(stage, getattr(value, "status", "COMPLETED")))
        for issue in getattr(value, "issues", ()):
            issues.append(ResolutionCycleIssue(stage, issue.code, issue.message))
        return True, value

    def refresh():
        nonlocal packet
        ok, candidate = attempt("context", lambda: _refresh_context(
            deepcopy(working), deepcopy(packet), after,
            ui_map=deepcopy(trusted_ui), endpoints=deepcopy(trusted_endpoints)))
        if ok:
            packet = candidate
        return ok

    if packet.testcase.get("id") != working.id:
        issues.append(ResolutionCycleIssue("context", "TESTCASE_MISMATCH",
                                          "Context belongs to another testcase."))
        audit.append(ResolutionCycleStage("context", "REJECTED"))
        return finish()

    ok, deterministic = attempt("deterministic", lambda: resolve_deterministically(
        deepcopy(working), ui_map=deepcopy(trusted_ui), endpoints=deepcopy(trusted_endpoints)))
    if ok:
        working = deepcopy(deterministic.case)
        after = analyze_executability(working)
    if not refresh() or after.executable:
        return finish()

    if resolution_llm is None:
        issues.append(ResolutionCycleIssue("resolution_llm", "ADAPTER_REQUIRED",
                                          "No resolution LLM adapter supplied."))
        audit.append(ResolutionCycleStage("resolution_llm", "SKIPPED"))
    else:
        ok, proposal = attempt("resolution_llm", lambda: propose_resolution(
            deepcopy(packet), resolution_llm))
        if ok:
            ok, validation = attempt("proposal_validation", lambda: validate_resolution_proposal(
                deepcopy(proposal), deepcopy(packet), deepcopy(working)))
            if ok:
                ok, application = attempt("application", lambda: apply_validated_resolution(
                    deepcopy(working), deepcopy(validation)))
                if ok:
                    working = deepcopy(application.case)

    after = analyze_executability(working)
    audit.append(ResolutionCycleStage("reanalysis", "COMPLETED"))
    if not refresh() or after.executable or not after.gaps:
        return finish()

    if exploration_llm is None or base_url is None:
        code = "ADAPTER_REQUIRED" if exploration_llm is None else "BASE_URL_REQUIRED"
        issues.append(ResolutionCycleIssue("exploration_llm", code,
                                          "Exploration needs an adapter and application base URL."))
        audit.append(ResolutionCycleStage("exploration_llm", "SKIPPED"))
        return finish()

    ok, plan = attempt("exploration_llm", lambda: propose_exploration(
        deepcopy(packet), exploration_llm, gaps=after.gaps))
    if not ok:
        return finish()
    ok, plan_validation = attempt("exploration_validation", lambda: validate_exploration_plan(
        deepcopy(plan), deepcopy(packet), deepcopy(working), base_url))
    if not ok or not plan_validation.valid_requests:
        return finish()
    ok, execution = attempt("exploration_execution", lambda: execute_validated_exploration(
        deepcopy(plan_validation), deepcopy(packet), base_url=base_url, storage_state=storage_state))
    if ok:
        packet = deepcopy(execution.context)
    # Observation does not modify the testcase or its executability. Stop here.
    return finish()

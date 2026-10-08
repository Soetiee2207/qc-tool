"""One standalone resolution attempt, optionally followed by evidence collection.

There is no retry with the enriched context, no provider implementation, and no
pipeline integration. Stage failures preserve earlier committed results.
"""

from copy import deepcopy
from collections import Counter
import json
from dataclasses import dataclass, replace
from pathlib import Path

from .apply_resolution import ApplyResult, apply_validated_resolution
from .executability import ExecutabilityReport, analyze_executability
from .exploration_execution import ExplorationExecutionResult, execute_validated_exploration
from .exploration_plan import ExplorationPlan, ExplorationPlanValidationResult, validate_exploration_plan
from .gap_routing import GapRoutingDecision, route_gaps
from .generate.from_openapi import Endpoint
from .llm_exploration import ExplorationLLM, propose_exploration
from .llm_resolution import LLMResponseError, ResolutionLLM, ResolutionProposal, propose_resolution
from .llm_provider import LLMProviderError, capture_provider_attempts
from .llm_prompt import PromptBudgetError
from .proposal_validation import ProposalValidationResult, validate_resolution_proposal
from .resolution_context import ResolutionContext, build_resolution_context
from .resolve import ResolutionResult, resolve_deterministically
from .test_fixtures import FixtureStore
from .test_data_preparation import TestDataPreparationResult, prepare_test_data
from .testcase import TestCase
from .ui.crawl import UIMap


@dataclass(frozen=True)
class ResolutionCycleIssue:
    stage: str
    code: str
    message: str
    diagnostics: dict | None = None


@dataclass(frozen=True)
class ResolutionCycleStage:
    stage: str
    status: str
    provider_attempts: tuple[dict, ...] = ()


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
    test_data_preparation: TestDataPreparationResult | None = None
    decisions: tuple[GapRoutingDecision, ...] = ()
    semantic_validation: ProposalValidationResult | None = None
    semantic_application: ApplyResult | None = None

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
            # A retained post-action snapshot already supplies this route.
            # Re-adding the pre-action map would duplicate stable locators.
            explored = field == "observations" and any(
                old.get("url") == record.get("url") and any(
                    source.get("action_observations") or source.get('state_id') for source in old.get("explorations", []))
                for old in records)
            same_content = field == "observations" and any(
                {k: v for k, v in old.items() if k != "elements"} ==
                {k: v for k, v in record.items() if k != "elements"} and
                Counter(json.dumps(e, sort_keys=True) for e in old.get("elements", [])) ==
                Counter(json.dumps(e, sort_keys=True) for e in record.get("elements", []))
                for old in records)
            if record not in records and not explored and not same_content:
                records.append(record)
    detached = replace(detached, testcase=fresh.testcase, allowed_actions=fresh.allowed_actions)
    return replace(detached, gaps=analyze_executability(case, context=detached).gaps)


def run_resolution_cycle(
    case: TestCase, context: ResolutionContext, *,
    resolution_llm: ResolutionLLM | None = None,
    exploration_llm: ExplorationLLM | None = None,
    base_url: str | None = None, storage_state: Path | None = None,
    fixture_store: FixtureStore | None = None,
    ui_map: UIMap | None = None, endpoints: list[Endpoint] | None = None,
    data_verification=None,
) -> ResolutionCycleResult:
    """Run resolution once, then collect evidence once if gaps remain.

    Optional ui_map/endpoints are passed to the existing deterministic resolver;
    selected ResolutionContext evidence is retained for LLM validation. Missing
    adapters are recorded as skipped stages. Failures are isolated and may still
    be followed by exploration only when new gaps actually require evidence.
    Existing evidence never triggers exploration merely because a proposal failed.
    Manual/auto decisions belong solely to the resolver/applier and analyzer.
    """
    packet = deepcopy(context)
    preparation = None
    working = deepcopy(case)
    if packet.testcase.get('id') == case.id:
        preparation = prepare_test_data(case, fixture_store=fixture_store,
                                        endpoints=endpoints or (), base_url=base_url,
                                        verification=data_verification)
        working = preparation.case
        if preparation.initial is not None:
            packet = replace(packet, data_acquisition=preparation.context_data(),
                             testcase=build_resolution_context(working, packet.gaps).testcase)
    if fixture_store:
        resolution_llm = fixture_store.guard_adapter(resolution_llm)
        exploration_llm = fixture_store.guard_adapter(exploration_llm)
    trusted_ui, trusted_endpoints = deepcopy(ui_map), deepcopy(endpoints)
    before = analyze_executability(working, context=packet)
    if preparation and preparation.initial is not None:
        packet = replace(packet, gaps=before.gaps)
    after = before
    issues = []
    decisions = []
    audit = [ResolutionCycleStage("analysis", "COMPLETED")]
    if preparation and preparation.initial is not None:
        audit.insert(0, ResolutionCycleStage('test_data_preparation', preparation.status.value))
        issues.extend(ResolutionCycleIssue('test_data_preparation', i['code'], i['message'])
                      for i in preparation.blockers)
    deterministic = proposal = validation = application = None
    plan = plan_validation = execution = None
    normalized_validation = normalized_application = None

    def finish():
        return deepcopy(ResolutionCycleResult(
            working, packet, before, after, deterministic, proposal, validation,
            application, plan, plan_validation, execution, tuple(issues), tuple(audit), preparation, tuple(decisions), normalized_validation, normalized_application))

    def attempt(stage, operation):
        try:
            with capture_provider_attempts() as provider_attempts:
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
            if isinstance(exc, PromptBudgetError):
                code, message = exc.code, str(exc)
            diagnostics = exc.diagnostics if isinstance(exc, (LLMResponseError, PromptBudgetError)) else None
            if diagnostics is not None and provider_attempts:
                provider_attempts[-1]["parser_failure"] = diagnostics
            issues.append(ResolutionCycleIssue(stage, code, message, diagnostics))
            audit.append(ResolutionCycleStage(stage, "FAILED", tuple(provider_attempts)))
            return False, None
        audit.append(ResolutionCycleStage(stage, getattr(value, "status", "COMPLETED"), tuple(provider_attempts)))
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

    def capability_attempt(capability):
        nonlocal packet
        import hashlib
        from .resolution_loop import _evidence_facts
        state = [working.to_dict(), sorted(_evidence_facts(packet)), packet.allowed_actions]
        fingerprint = hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        record = {'capability': capability, 'fingerprint': fingerprint}
        if record in packet.capability_attempts:
            audit.append(ResolutionCycleStage(capability + '_llm', 'SKIPPED_UNCHANGED_STATE'))
            issues.append(ResolutionCycleIssue(capability + '_llm', 'NO_NEW_EVIDENCE',
                                               'Equivalent source/evidence state already attempted; no repeated model call.'))
            return False
        packet = replace(packet, capability_attempts=packet.capability_attempts + (record,))
        return True

    def ground_semantics():
        nonlocal working, packet, after, normalized_validation, normalized_application
        from .semantic_ir import grounded_proposal
        canonical = grounded_proposal(working, packet, fixture_store)
        if not canonical.changes:
            return
        ok, normalized_validation = attempt("semantic_grounding", lambda: validate_resolution_proposal(
            canonical, packet, working, fixture_store=fixture_store))
        if ok:
            from .evidence_needs import rejection_needs
            packet = replace(packet, evidence_needs=rejection_needs(normalized_validation.issues, packet))
            ok, normalized_application = attempt("semantic_application", lambda: apply_validated_resolution(working, normalized_validation))
            if ok:
                working = deepcopy(normalized_application.case)
                after = analyze_executability(working, context=packet)

    if packet.testcase.get("id") != working.id:
        issues.append(ResolutionCycleIssue("context", "TESTCASE_MISMATCH",
                                          "Context belongs to another testcase."))
        audit.append(ResolutionCycleStage("context", "REJECTED"))
        return finish()

    if preparation and not preparation.available:
        decisions.append(route_gaps(working, packet, fixture_store=fixture_store, base_url=base_url, blocked=True))
        return finish()  # Neither model nor browser can invent missing/invalid data.

    ok, deterministic = attempt("deterministic", lambda: resolve_deterministically(
        deepcopy(working), ui_map=deepcopy(trusted_ui), endpoints=deepcopy(trusted_endpoints),
        fixture_store=fixture_store, context=deepcopy(packet)))
    if ok:
        working = deepcopy(deterministic.case)
        after = analyze_executability(working, context=packet)
    if not refresh():
        return finish()
    from .semantic_ir import normalize_explicit_identifiers, merge_semantics
    explicit = normalize_explicit_identifiers(packet)
    if explicit.clauses:
        packet = replace(packet, semantics=merge_semantics(packet.semantics, explicit.to_dict()))
    if packet.semantics:
        ground_semantics()
        if not refresh():
            return finish()
    from .workflow_evidence import outcome_needs
    packet = replace(packet, evidence_needs=outcome_needs(working, packet, fixture_store))
    decision = route_gaps(working, packet, fixture_store=fixture_store, base_url=base_url,
                          resolved_gaps=deterministic.resolved_gaps if deterministic else ())
    decisions.append(decision)
    if after.executable:
        return finish()
    if decision.selected_capability == 'none':
        issues.append(ResolutionCycleIssue('gap_routing', 'NO_SAFE_CAPABILITY', decision.reason))
        return finish()

    if decision.selected_capability == 'resolution' and resolution_llm is None:
        issues.append(ResolutionCycleIssue("resolution_llm", "ADAPTER_REQUIRED",
                                          "No resolution LLM adapter supplied."))
        audit.append(ResolutionCycleStage("resolution_llm", "SKIPPED"))
    elif decision.selected_capability == "resolution" and capability_attempt("resolution"):
        ok, proposal = attempt("resolution_llm", lambda: propose_resolution(
            deepcopy(packet), resolution_llm))
        if ok:
            ok, validation = attempt("proposal_validation", lambda: validate_resolution_proposal(
                deepcopy(proposal), deepcopy(packet), deepcopy(working), fixture_store=fixture_store))
            if ok:
                from .evidence_needs import rejection_needs
                packet = replace(deepcopy(validation.analysis_context), evidence_needs=rejection_needs(validation.issues, packet))
                ok, application = attempt("application", lambda: apply_validated_resolution(
                    deepcopy(working), deepcopy(validation)))
                if ok:
                    working = deepcopy(application.case)

    if packet.semantics and working.to_dict() != packet.testcase and not refresh():
        return finish()
    ground_semantics()
    after = analyze_executability(working, context=packet)
    audit.append(ResolutionCycleStage("reanalysis", "COMPLETED"))
    if not refresh() or after.executable or not after.gaps:
        return finish()

    if decision.selected_capability == 'resolution':
        packet = replace(packet, evidence_needs=outcome_needs(working, packet, fixture_store))
        decision = route_gaps(working, packet, fixture_store=fixture_store, base_url=base_url)
        decisions.append(decision)
    if decision.selected_capability != 'exploration':
        return finish()

    if exploration_llm is None or base_url is None:
        code = "ADAPTER_REQUIRED" if exploration_llm is None else "BASE_URL_REQUIRED"
        issues.append(ResolutionCycleIssue("exploration_llm", code,
                                          "Exploration needs an adapter and application base URL."))
        audit.append(ResolutionCycleStage("exploration_llm", "SKIPPED"))
        return finish()

    if not capability_attempt("exploration"):
        return finish()
    ok, plan = attempt("exploration_llm", lambda: propose_exploration(
        deepcopy(packet), exploration_llm, gaps=after.gaps, fixture_store=fixture_store))
    if not ok:
        return finish()
    ok, plan_validation = attempt("exploration_validation", lambda: validate_exploration_plan(
        deepcopy(plan), deepcopy(packet), deepcopy(working), base_url, fixture_store=fixture_store))
    if not ok or not plan_validation.valid_requests:
        return finish()
    ok, execution = attempt("exploration_execution", lambda: execute_validated_exploration(
        deepcopy(plan_validation), deepcopy(packet), base_url=base_url, storage_state=storage_state, fixture_store=fixture_store))
    if ok:
        packet = deepcopy(execution.context)
    # Observation does not modify the testcase or its executability. Stop here.
    return finish()

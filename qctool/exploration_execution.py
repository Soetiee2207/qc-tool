"""Execute approved page inspections and add observations, never expectations."""

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .exploration_plan import ExplorationPlanValidationResult, ValidatedExplorationRequest
from .resolution_context import ResolutionContext
from .ui.explore import ExplorationResult, _redact, _safe_url, explore_page


def _approved_record(item: ValidatedExplorationRequest) -> dict:
    record = item.to_dict()
    for purpose in record["purposes"]:
        purpose["reason"] = _redact(purpose["reason"])
    for grounding in record["grounding"]:
        for key in ("value", "page"):
            if isinstance(grounding.get(key), str):
                grounding[key] = _safe_url(grounding[key])
    return record


@dataclass(frozen=True)
class ExplorationExecutionIssue:
    code: str
    message: str
    request_index: int


@dataclass(frozen=True)
class ExplorationExecutionResult:
    context: ResolutionContext
    exploration_results: tuple[ExplorationResult, ...]
    successful_requests: tuple[ValidatedExplorationRequest, ...]
    failed_requests: tuple[ValidatedExplorationRequest, ...]
    issues: tuple[ExplorationExecutionIssue, ...]

    def to_dict(self) -> dict:
        return {
            "context": self.context.to_dict(),
            "exploration_results": [result.to_dict() for result in self.exploration_results],
            "successful_requests": [_approved_record(item) for item in self.successful_requests],
            "failed_requests": [_approved_record(item) for item in self.failed_requests],
            "issues": [asdict(issue) for issue in self.issues],
        }


def _element_identity(element: dict) -> dict:
    # The UI-map serializer omits tags and false optional flags; the explorer
    # includes them. Ignore only those representational differences for matching.
    return {key: value for key, value in element.items()
            if key != "tag" and not (key in {"disabled", "checked"} and value is False)}


def _enrich(observations: dict, result: ExplorationResult,
            approved: ValidatedExplorationRequest) -> None:
    payload = result.to_dict()  # Preserve the explorer's already redacted output.
    page = payload["page"]
    if not page or not (page["title"] or page["elements"] or page["text"]
                        or payload["forms"] or payload["network"]):
        return
    provenance = {
        "source": payload["source"], "request": payload["request"],
        "testcase_id": approved.testcase_id,
        "purposes": [{**asdict(purpose), "reason": _redact(purpose.reason)}
                     for purpose in approved.purposes],
        "final_url": payload["final_url"], "redirect_url": payload["redirect_url"],
        "forms": payload["forms"], "network": payload["network"],
        "issues": payload["issues"], "truncated": payload["truncated"],
    }
    pages = observations.setdefault("ui_pages", [])
    # Deduplicate matching page snapshots, not merely URLs. Session-specific or
    # changed states remain separate; old observations are never contradicted away.
    for existing in pages:
        if (existing.get("url") == page["url"]
                and existing.get("title") == page["title"]
                and existing.get("session") in (None, approved.request.session)
                and existing.get("text", page["text"]) == page["text"]
                and [_element_identity(e) for e in existing.get("elements", [])]
                    == [_element_identity(e) for e in page["elements"]]):
            existing.setdefault("text", page["text"])
            existing["elements"] = page["elements"]
            existing.setdefault("session", approved.request.session)
            sources = existing.setdefault("explorations", [])
            if provenance not in sources:
                sources.append(provenance)
            return
    pages.append({**page, "session": approved.request.session,
                  "evidence": payload["source"], "explorations": [provenance]})


def execute_validated_exploration(
    validation_result: ExplorationPlanValidationResult, context: ResolutionContext, *,
    base_url: str, storage_state: Path | None = None,
    timeout_ms: int = 10000, render_wait_ms: int = 2000,
) -> ExplorationExecutionResult:
    """Execute only approved requests, independently, in validation order.

    Raw plans/requests are programming errors (TypeError) before any browser use.
    Testcase/gap bindings are checked again against the supplied context. Browser
    target/session checks remain in explore_page. No LLM, repair, or retry occurs.
    Failed inspections add issues but no evidence. Every returned artifact is
    detached; specification, interface_contract, testcase and gaps stay unchanged.
    """
    if not isinstance(validation_result, ExplorationPlanValidationResult) or any(
        not isinstance(item, ValidatedExplorationRequest)
        for item in validation_result.valid_requests
    ):
        raise TypeError("Expected an ExplorationPlanValidationResult containing validated requests")
    enriched = deepcopy(context)
    results, successful, failed, issues = [], [], [], []
    gaps = {(gap.code, gap.step_seq) for gap in context.gaps}
    for index, approved in enumerate(deepcopy(validation_result.valid_requests)):
        if approved.testcase_id != context.testcase.get("id"):
            failed.append(approved)
            issues.append(ExplorationExecutionIssue(
                "TESTCASE_MISMATCH", "Approved request belongs to another testcase.", index))
            continue
        if not approved.purposes or any(
            (purpose.gap_code, purpose.step_seq) not in gaps for purpose in approved.purposes
        ):
            failed.append(approved)
            issues.append(ExplorationExecutionIssue(
                "GAP_NOT_FOUND", "Approved request no longer refers to supplied unresolved gaps.", index))
            continue
        try:
            result = deepcopy(explore_page(
                deepcopy(approved.request), base_url=base_url,
                storage_state=storage_state if approved.requires_auth_state else None,
                timeout_ms=timeout_ms, render_wait_ms=render_wait_ms,
            ))
            # Stage enrichment independently so malformed results cannot leave
            # half-written observations or discard prior successful evidence.
            observations = deepcopy(enriched.observations)
            if result.explored:
                _enrich(observations, result, approved)
            results.append(result)
            issues.extend(ExplorationExecutionIssue(issue.code, issue.message, index)
                          for issue in result.issues)
            if result.explored:
                enriched = replace(enriched, observations=observations)
                successful.append(approved)
            else:
                failed.append(approved)
                if not result.issues:
                    issues.append(ExplorationExecutionIssue(
                        "NO_PAGE_OBSERVED", "Exploration returned no inspected page.", index))
        except Exception:
            # Exceptions may contain secrets. Retain a fixed diagnostic only.
            failed.append(approved)
            issues.append(ExplorationExecutionIssue(
                "EXPLORATION_FAILED", "Exploration or observation conversion failed.", index))
    return ExplorationExecutionResult(
        enriched, tuple(results), tuple(successful), tuple(failed), tuple(issues))

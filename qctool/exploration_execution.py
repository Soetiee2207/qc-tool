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
    if payload.get('states'):
        history = observations.setdefault('page_states', [])
        for state in payload['states']:
            state_flags = list(state.get('truncated', payload['truncated']))
            entry = {**deepcopy(state), 'truncated': state_flags, 'session': approved.request.session,
                     'testcase_id': approved.testcase_id,
                     'purposes': [asdict(p) for p in approved.purposes],
                     'validated_actions': deepcopy([g for g in approved.grounding
                                                   if g.get('source') == 'validated_action']),
                     'request': payload['request']}
            if not any(s['state_id'] == entry['state_id'] for s in history):
                history.append(entry)
            if not state['valid']:
                continue
            snapshot = state['page']
            pages = observations.setdefault('ui_pages', [])
            matching = [p for p in pages if p.get('url') == snapshot['url']
                        and p.get('session') in (None, approved.request.session)]
            if len(matching) > 1:
                continue  # Preserve ambiguous old evidence; never arbitrarily promote.
            page = matching[0] if matching else {}
            if not matching:
                pages.append(page)
            old = deepcopy({k: v for k, v in page.items() if k != 'explorations'})
            audit = page.setdefault('explorations', [])
            audit.append({'source': state['source'], 'state_id': state['state_id'],
                          'previous_snapshot': old, 'request': payload['request'],
                          'action_observations': [a for a in payload.get('action_observations', [])
                                                  if a.get('state_id') == state['state_id']],
                          'network': state['network'], 'truncated': state_flags})
            page.update(deepcopy(snapshot))
            page.update(session=approved.request.session, state_id=state['state_id'], evidence=state['source'])
            observations['current_state_id'] = state['state_id']
        return
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
    if payload.get("action_observations"):
        provenance["action_observations"] = payload["action_observations"]
    pages = observations.setdefault("ui_pages", [])
    legacy_state = None
    if approved.request.actions and payload.get("action_observations") and result.explored:
        # V1 click observations predate workflow states. Preserve the completed
        # action snapshot in the SAME state vocabulary so later fresh-context
        # inspection cannot erase its grounded controls or fabricate ambiguity.
        action = payload["action_observations"][-1]
        binding = next((g for g in approved.grounding if g.get("source") == "validated_click"
                        and g.get("action_index") == action.get("action_index")), None)
        if binding is not None:
            state_id = payload["source"]["observed_at"] + ":click:" + str(action.get("action_index", 0))
            legacy_state = {"state_id": state_id, "valid": True, "page": deepcopy(page),
                            "triggering_action": action.get("action_index", 0),
                            "source_clause": binding["source_clause"], "source": payload["source"],
                            "network": payload["network"], "session": approved.request.session,
                            "testcase_id": approved.testcase_id, "request": payload["request"],
                            "purposes": [asdict(p) for p in approved.purposes]}
            history = observations.setdefault("page_states", [])
            if not any(state.get("state_id") == state_id for state in history):
                history.append(legacy_state)
            provenance["state_id"] = state_id
            observations["current_state_id"] = state_id
    if approved.request.actions and payload.get("action_observations"):
        matching = [p for p in pages if p.get("url") == page["url"]
                    and p.get("session") in (None, approved.request.session)]
        if len(matching) == 1:
            existing = matching[0]
            # The current snapshot is the inspected post-action state. Keep the
            # prior snapshot in the audit, not as duplicate locator candidates.
            sources = existing.setdefault("explorations", [])
            snapshot = {k: deepcopy(existing[k]) for k in ("url", "title", "text", "elements") if k in existing}
            if snapshot != {k: page[k] for k in snapshot}:
                provenance["previous_snapshot"] = {**snapshot, "evidence": deepcopy(existing.get("evidence"))}
            if provenance not in sources:
                sources.append(provenance)
            existing.update(deepcopy(page))
            existing["session"] = approved.request.session
            existing["evidence"] = payload["source"]
            if legacy_state:
                existing["state_id"] = legacy_state["state_id"]
            return
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
                  "evidence": payload["source"], "explorations": [provenance],
                  **({"state_id": legacy_state["state_id"]} if legacy_state else {})})


def execute_validated_exploration(
    validation_result: ExplorationPlanValidationResult, context: ResolutionContext, *,
    base_url: str, storage_state: Path | None = None,
    timeout_ms: int = 10000, render_wait_ms: int = 2000, fixture_store=None,
    mutation_policy=None, mutation_budget=None,
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
    from .exploration_actions import mutation_policy as load_mutation_policy, MutationBudget
    mutation_policy = load_mutation_policy(mutation_policy, fixture_store=fixture_store)
    if mutation_policy and mutation_budget is None:
        mutation_budget = MutationBudget()
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
            extra = {"fixture_store": fixture_store} if fixture_store is not None else {}
            if mutation_policy:
                extra.update(mutation_policy=mutation_policy, mutation_budget=mutation_budget)
            result = deepcopy(explore_page(
                deepcopy(approved if approved.request.actions else approved.request), base_url=base_url,
                storage_state=storage_state if approved.requires_auth_state else None,
                timeout_ms=timeout_ms, render_wait_ms=render_wait_ms, **extra,
            ))
            # Stage enrichment independently so malformed results cannot leave
            # half-written observations or discard prior successful evidence.
            observations = deepcopy(enriched.observations)
            if result.explored or result.states:
                _enrich(observations, result, approved)
                enriched = replace(enriched, observations=observations)
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

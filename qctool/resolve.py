"""Evidence-backed, deterministic repairs for a few execution gaps.

The input case is never changed. This module does not run a browser, read a live
product, interpret business expectations, or participate in the pipeline.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, replace
import re
import json
from urllib.parse import urlsplit

from .executability import ExecutionGap, ExecutabilityReport, analyze_executability
from .generate.from_openapi import Endpoint
from .generate.mapper import RE_OPEN_PATH, _target_of
from .testcase import Step, StepKind, TestCase, ValidationError
from .test_fixtures import FixtureStore, FACT_REGISTRY
from .ui.crawl import UIMap, _norm
from .ui.explore import ExplorationRequest, validate_exploration_request


@dataclass(frozen=True)
class ResolutionChange:
    step_seq: int
    action: str
    before: dict
    after: dict
    evidence: dict
    from_action: str | None = None


@dataclass(frozen=True)
class ResolutionResult:
    case: TestCase
    before: ExecutabilityReport
    after: ExecutabilityReport
    resolved_gaps: tuple[ExecutionGap, ...]
    unresolved_gaps: tuple[ExecutionGap, ...]
    changes: tuple[ResolutionChange, ...]


def resolve_deterministically(
    case: TestCase, *, ui_map: UIMap | None = None,
    endpoints: list[Endpoint] | None = None,
    fixture_store: FixtureStore | None = None,
) -> ResolutionResult:
    """Repair only gaps tied to one exact, unique UI or OpenAPI record.

    ``endpoints`` is the output of ``load_endpoints()``. The returned case is a
    deep copy, including when no repair is possible. ``after`` is always obtained
    from ``analyze_executability``; the resolver never declares success itself.
    Exact supported Given clauses may expand only when the supplied fixture
    store proves every account fact and the route is a trusted same-origin page.
    Complete literal Open/URL clauses may replace unmapped verbs, retaining
    their source in the change audit. Manual promotion uses the applier's gate.
    """
    before = analyze_executability(case)
    repaired = deepcopy(case)
    changes: list[ResolutionChange] = []
    by_seq = Counter(step.seq for step in repaired.steps)
    attempted_http: set[int] = set()

    for gap in before.gaps:
        if gap.step_seq is None or by_seq[gap.step_seq] != 1:
            continue
        step = next(step for step in repaired.steps if step.seq == gap.step_seq)
        if gap.code == "UNMAPPED_ACTION" and ui_map is not None:
            mapped = _explicit_route(step, ui_map)
            if mapped is not None:
                action, args, evidence = mapped
                changes.append(ResolutionChange(
                    step.seq, action, deepcopy(step.args), deepcopy(args), evidence,
                    from_action=step.action,
                ))
                step.action, step.args = action, args
            continue
        repair: tuple[dict, dict] | None = None
        if gap.code == "MISSING_LOCATOR" and ui_map is not None:
            repair = _ui_locator(step, ui_map)
        elif gap.code == "MISSING_URL" and ui_map is not None:
            repair = _ui_url(step, ui_map)
        elif gap.code in {"MISSING_HTTP_METHOD", "MISSING_HTTP_PATH"} and endpoints is not None:
            if step.seq in attempted_http:
                continue
            attempted_http.add(step.seq)
            repair = _http_operation(step, repaired, endpoints)

        if repair is None:
            continue
        fields, evidence = repair
        before_args = deepcopy(step.args)
        step.args = {**step.args, **fields}
        changes.append(ResolutionChange(
            step.seq, step.action, before_args, deepcopy(step.args), evidence
        ))

    origins = {step.seq: step.seq for step in repaired.steps}
    if ui_map is not None and fixture_store is not None:
        repaired, setup_changes, origins = _trusted_given(repaired, ui_map, fixture_store)
        changes.extend(setup_changes)

    # Match the applier's promotion boundary: manual because of unmapped steps,
    # with every blocker now gone. Never promote setup/manual-only cases blindly.
    if (changes and case.execution == "manual" and case.needs_mapping
            and not repaired.needs_mapping and before.validation_error is None):
        auto_candidate = deepcopy(repaired)
        auto_candidate.execution = "auto"
        if analyze_executability(auto_candidate).executable:
            repaired = auto_candidate
    after = analyze_executability(repaired)
    remaining = Counter(replace(gap, step_seq=origins.get(gap.step_seq, gap.step_seq))
                        for gap in after.gaps)
    resolved: list[ExecutionGap] = []
    for gap in before.gaps:
        if remaining[gap]:
            remaining[gap] -= 1
        else:
            resolved.append(gap)
    return ResolutionResult(repaired, before, after, tuple(resolved), after.gaps, tuple(changes))


def _trusted_given(case: TestCase, ui_map: UIMap, store: FixtureStore):
    """Reuse the existing full-clause proof, proposal validator and safe applier.

    Generated proposals here are deterministic, not model output. No account
    fact is inferred from credentials; unknown clauses and ambiguous pages stop.
    """
    from .apply_resolution import apply_validated_resolution
    from .llm_resolution import AtomicProposal, EvidenceReference, ProposedChange, ResolutionProposal
    from .proposal_validation import validate_resolution_proposal
    from .resolution_context import build_resolution_context
    from .step_expansion import expected_expansion, candidate_with_changes

    context = build_resolution_context(case, analyze_executability(case).gaps, ui_map=ui_map)
    proposals = []
    for step in case.steps:
        if step.kind != StepKind.GIVEN or step.action != "perform.unmapped":
            continue
        meanings = expected_expansion(step, case.test_data, fixture_store=store)
        if (not meanings or [m["action"] for m in meanings] != ["ui.session", "ui.goto"]
                or "precondition_route" not in meanings[1]):
            continue
        route = meanings[1]["precondition_route"]
        target, issues = validate_exploration_request(ExplorationRequest(route), base_url=ui_map.base_url)
        if issues:
            continue
        pages = []
        for page in context.observations["ui_pages"]:
            url, errors = validate_exploration_request(ExplorationRequest(page["url"]), base_url=ui_map.base_url)
            if not errors and url == target:
                pages.append(page)
        if len(pages) != 1:
            continue
        source = EvidenceReference("testcase-step", {"step_seq": step.seq, "action": step.action})
        page_ref = EvidenceReference("ui-map", {"page": pages[0]["url"]})
        proposals.append(ProposedChange(
            step.seq, step.action, ("UNMAPPED_ACTION",), "", {},
            "Exact Given clause: trusted fixture facts and provisioned aliases prove the account; "
            "anonymous session and route are preserved as explicit actions.",
            (source, page_ref), (
                AtomicProposal("ui.session", deepcopy(meanings[0]["args"]), (source,)),
                AtomicProposal("ui.goto", {"url": pages[0]["url"]}, (source, page_ref)),
            )))
    validation = validate_resolution_proposal(ResolutionProposal(case.id, tuple(proposals), ()),
                                              context, case, fixture_store=store)
    applied = apply_validated_resolution(case, validation)
    if not applied.applied_changes or applied.issues:
        return case, [], {step.seq: step.seq for step in case.steps}
    _, origins = candidate_with_changes(case, validation.valid_changes)
    repaired = applied.case
    changes = []
    for record in applied.applied_changes:
        change = record.change
        changes.append(ResolutionChange(
            change.step_seq, "ui.session", deepcopy(record.before_args),
            {"steps": [atom.to_dict() for atom in change.expansion]},
            {"source": "trusted-fixture-and-ui-map", "facts": deepcopy(case.test_data.get(FACT_REGISTRY, {})),
             "references": [ref.to_dict() for ref in change.evidence],
             "validated_by": "deterministic-proposal-validator"}, from_action=change.from_action))
    # The shared applier preserves source clauses on each atom. Mark their actual
    # origin accurately: this proposal was constructed without an LLM call.
    changed_sequences = {c.step_seq for c in validation.valid_changes}
    for step in repaired.steps:
        if origins[step.seq] in changed_sequences:
            prefix, _, payload = step.note.rpartition("\n[resolution-expansion] ")
            audit = json.loads(payload)
            audit["type"] = "validated-deterministic-expansion"
            step.note = prefix + "\n[resolution-expansion] " + json.dumps(audit, ensure_ascii=False, sort_keys=True)
    return repaired, changes, origins


# Whole source clauses only; exclude regex/query/template syntax and prose.
# This deliberately supports fewer forms than the normal mapper's prose rules.
_LITERAL_ROUTE = r"/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*/?"
_OPEN_ROUTE = re.compile(r"Open\s+(" + _LITERAL_ROUTE + r")", re.I)
_URL_ROUTE = re.compile(r"URL\s+(" + _LITERAL_ROUTE + r")", re.I)


def _explicit_route(step: Step, ui_map: UIMap) -> tuple[str, dict, dict] | None:
    try:
        step.validate()
    except ValidationError:
        return None
    if step.action == "perform.unmapped":
        # An attached expectation cannot be silently discarded by a step repair.
        if set(step.args) != {"description"}:
            return None
        text = step.args["description"]
        grammar, action, argument = _OPEN_ROUTE, "ui.goto", "url"
    elif step.action == "assert.unmapped":
        text = step.args["expected"]
        grammar, action, argument = _URL_ROUTE, "assert.url_matches", "pattern"
    else:
        return None
    if not isinstance(text, str) or not (match := grammar.fullmatch(text.strip())):
        return None
    route = match.group(1)
    if action == "ui.goto":
        # Reuse the mapper's explicit navigation extraction after the strict gate.
        route = RE_OPEN_PATH.fullmatch(text.strip()).group(1)
    target, issues = validate_exploration_request(
        ExplorationRequest(route), base_url=ui_map.base_url)
    if issues:
        return None
    pages = []
    for page in ui_map.pages:
        resolved, page_issues = validate_exploration_request(
            ExplorationRequest(page.url), base_url=ui_map.base_url)
        if not page_issues and resolved == target:
            pages.append(page)
    if len(pages) != 1:
        return None
    args = {argument: route}
    Step(step.seq, step.kind, action, args, step.note).validate()
    return action, args, {
        "source": "ui-map", "page": pages[0].url,
        "source_text": text, "from_action": step.action,
        "match": "complete literal route clause and unique same-origin page",
    }


def _ui_locator(step: Step, ui_map: UIMap) -> tuple[dict, dict] | None:
    # A label is a locator hint, not evidence that the first fuzzy match is right.
    hint = step.args.get("by_name")
    if not isinstance(hint, str) or not _norm(hint):
        return None
    found = ui_map.find(hint)
    matches = [
        (page, element) for page in ui_map.pages for element in page.elements
        if _norm(element.name) == _norm(hint)
    ]
    if len(matches) != 1 or found is not matches[0][1]:
        return None
    page, element = matches[0]
    target = _target_of(element)["target"]
    if not target:
        return None
    return {"target": target}, {
        "source": "ui-map", "page": page.url, "element": element.to_dict(),
        "match": "unique exact normalized name",
    }


def _ui_url(step: Step, ui_map: UIMap) -> tuple[dict, dict] | None:
    # Only an explicit route in the step note can identify a crawled page.
    route = step.note.strip()
    if not route.startswith("/") or any(char.isspace() for char in route):
        return None
    pages = [page for page in ui_map.pages
             if urlsplit(page.url).path == urlsplit(route).path
             and urlsplit(page.url).query == urlsplit(route).query]
    if len(pages) != 1:
        return None
    return {"url": pages[0].url}, {
        "source": "ui-map", "page": pages[0].url, "route_hint": route,
    }


def _http_operation(
    step: Step, case: TestCase, endpoints: list[Endpoint],
) -> tuple[dict, dict] | None:
    method = step.args.get("method")
    path = step.args.get("path")
    note_path = step.note.strip() if step.note.strip().startswith("/") else ""
    if note_path and any(char.isspace() for char in note_path):
        note_path = ""
    if path and note_path and path != note_path:
        return None

    # source_ref is already an existing OpenAPI identity on generated cases.
    # It names the whole case, so use it only for a single HTTP request.
    op_id = None
    if case.source_ref.startswith("openapi:"):
        if sum(s.action == "http.request" for s in case.steps) != 1:
            return None
        op_id = case.source_ref.removeprefix("openapi:")
    route = path or note_path
    if not route and not op_id:
        return None
    candidates = [ep for ep in endpoints
                  if (not route or ep.path == route)
                  and (not method or ep.method == str(method).upper())
                  and (not op_id or ep.operation_id == op_id)]
    if len(candidates) != 1:
        return None
    ep = candidates[0]
    fields: dict = {}
    if not method:
        fields["method"] = ep.method
    if not path:
        # A path template is not a runnable URL without concrete parameter data.
        if "{" in ep.path or "}" in ep.path:
            return None
        fields["path"] = ep.path
    if ep.servers and not step.args.get("base"):
        if len(ep.servers) != 1 or urlsplit(ep.servers[0]).scheme not in {"http", "https"}:
            return None
        fields["base"] = ep.servers[0]
    if not fields:
        return None
    return fields, {
        "source": "openapi", "operation_id": ep.operation_id,
        "method": ep.method, "path": ep.path, "servers": tuple(ep.servers),
    }

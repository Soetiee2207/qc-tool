"""Deterministic validation of an untrusted resolution proposal.

This module never applies a proposal to a caller's testcase. An internal copy is
used only to measure whether each grounded change removes an execution gap.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

from .executability import ExecutabilityReport, analyze_executability
from .generate.mapper import RE_CLICK, RE_HTTP, RE_OPEN_PATH
from .llm_resolution import AtomicProposal, EvidenceReference, ProposedChange, ResolutionProposal, UnresolvedGap
from .resolution_context import ResolutionContext
from .step_expansion import candidate_with_changes, expected_expansion
from .test_fixtures import FixtureStore, REGISTRY, is_alias
from .testcase import ACTION_SPECS, Step, TestCase, ValidationError
from .ui.crawl import _norm


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    change_index: int | None = None
    step_seq: int | None = None


@dataclass(frozen=True)
class RejectedChange:
    change: ProposedChange
    issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True)
class ProposalValidationResult:
    valid_changes: tuple[ProposedChange, ...]
    rejected_changes: tuple[RejectedChange, ...]
    unresolved: tuple[UnresolvedGap, ...]
    issues: tuple[ValidationIssue, ...]
    before: ExecutabilityReport
    after: ExecutabilityReport
    testcase_id: str
    case_fingerprint: str
    valid_changes_fingerprint: str

    @property
    def status(self) -> str:
        if not self.valid_changes:
            return "VALID" if self.unresolved and not self.rejected_changes and not self.issues else "REJECTED"
        return "PARTIALLY_VALID" if self.rejected_changes or self.unresolved or self.issues else "VALID"


def validate_resolution_proposal(
    proposal: ResolutionProposal, context: ResolutionContext, case: TestCase, *,
    fixture_store: FixtureStore | None = None,
) -> ProposalValidationResult:
    """Validate one proposal against only the supplied case, context, and vocabulary.

    Changes are checked in proposal order on a private copy. ``valid_changes``
    are still proposals, not applied changes or proof of product correctness.
    """
    original = analyze_executability(case)
    fingerprint = _case_fingerprint(case)
    issues: list[ValidationIssue] = []
    working = deepcopy(case)
    origins = {step.seq: step.seq for step in case.steps}

    if proposal.testcase_id != case.id or proposal.testcase_id != context.testcase.get("id"):
        issues.append(ValidationIssue("TESTCASE_MISMATCH", "Proposal and context must name this testcase."))
    if not _context_matches_case(context, case, original):
        issues.append(ValidationIssue("CONTEXT_MISMATCH", "Context does not describe the current testcase and gaps."))
    if issues:
        rejected = tuple(RejectedChange(change, tuple(issues)) for change in proposal.changes)
        return ProposalValidationResult(
            (), rejected, (), tuple(issues), original, original, case.id, fingerprint,
            _changes_fingerprint(()),
        )

    context_gaps = Counter(_gap_key(gap.code, gap.step_seq) for gap in context.gaps)
    valid: list[ProposedChange] = []
    rejected: list[RejectedChange] = []
    change_counts = Counter(change.step_seq for change in proposal.changes)

    for index, change in enumerate(proposal.changes):
        failures: list[ValidationIssue] = []

        def fail(code: str, message: str) -> None:
            failures.append(ValidationIssue(code, message, index, change.step_seq))

        matches = [step for step in case.steps if step.seq == change.step_seq]
        if len(matches) != 1:
            fail("STEP_NOT_FOUND", "Step sequence must identify exactly one current step.")
        elif change_counts[change.step_seq] != 1:
            fail("DUPLICATE_STEP_CHANGE", "A proposal may change a step only once.")
        else:
            step = matches[0]
            if step.action != change.from_action:
                fail("ACTION_MISMATCH", "from_action differs from the current step action.")
            step_gaps = [code for code, seq in context_gaps if seq == step.seq and context_gaps[(code, seq)]]
            if not step_gaps or not change.gap_codes or any(
                context_gaps[_gap_key(code, step.seq)] == 0
                and not (code == "MISSING_ASSERTION" and context_gaps[(code, None)]
                         and step.action == "assert.unmapped")
                for code in change.gap_codes
            ):
                fail("NO_MATCHING_GAP", "Change must address listed gaps on this step.")

            if change.expansion:
                if not failures:
                    error = _validate_expansion(step, change, context, working, origins, fixture_store=fixture_store)
                    if error:
                        fail(error, "Expansion must ground and preserve every source clause in order.")
                if not failures:
                    candidate, new_origins = candidate_with_changes(case, [*valid, change])
                    before = _origin_gaps(analyze_executability(working), origins)
                    after = analyze_executability(candidate)
                    after_counts = _origin_gaps(after, new_origins)
                    new = after_counts - before
                    if new:
                        code = "UNSUPPORTED_ACTION" if any(code == "UNSUPPORTED_ACTION" for code, _ in new) else "NEW_EXECUTION_GAP"
                        fail(code, "Expansion introduces new execution blockers.")
                    elif after.validation_error is not None and original.validation_error is None:
                        fail("NEW_VALIDATION_ERROR", "Expanded candidate failed model validation.")
                    elif not after_counts[("UNMAPPED_ACTION", step.seq)] < before[("UNMAPPED_ACTION", step.seq)]:
                        fail("NO_EXECUTABILITY_PROGRESS", "Expansion removes no source-step gap.")
                    else:
                        working, origins = candidate, new_origins
                if failures:
                    rejected.append(RejectedChange(change, tuple(failures)))
                    issues.extend(failures)
                else:
                    valid.append(change)
                continue

            if change.action not in ACTION_SPECS:
                fail("UNKNOWN_ACTION", "Proposed action is outside ACTION_SPECS.")
            elif step.action not in TestCase.UNMAPPED_ACTIONS and change.action != step.action:
                fail("ACTION_REWRITE_NOT_ALLOWED", "Concrete steps may only repair arguments.")
            elif step.action == "perform.unmapped" and change.action.startswith("assert."):
                fail("ACTION_REWRITE_NOT_ALLOWED", "An action step cannot become an assertion.")
            elif step.action == "assert.unmapped" and not change.action.startswith("assert."):
                fail("ACTION_REWRITE_NOT_ALLOWED", "An expected result must remain an assertion.")

            if not failures and not isinstance(change.args, dict):
                fail("INVALID_ARGUMENTS", "Proposed arguments must be an object.")
            if not failures and step.action not in TestCase.UNMAPPED_ACTIONS:
                if any(key not in change.args or change.args[key] != value
                       for key, value in step.args.items()):
                    fail("ARGUMENT_REWRITE_NOT_ALLOWED", "Existing concrete arguments must be preserved.")
                elif any(key not in {"target", "by_name", "url", "method", "path",
                                      "expected", "pattern"}
                         for key in change.args.keys() - step.args.keys()):
                    fail("SEMANTICS_UNPROVEN", "New argument has no deterministic grounding rule.")

            if not failures and (error := _fixture_fill_error(change.action, change.args, context, fixture_store)):
                fail(error, "Fill alias is not backed by the supplied trusted fixture store.")

            if not failures:
                try:
                    Step(step.seq, step.kind, change.action, change.args, step.note).validate()
                except (ValidationError, TypeError, ValueError, AttributeError) as exc:
                    fail("INVALID_ARGUMENTS", f"Step validation rejected proposed arguments: {exc}")

            if not failures:
                probe, probe_origins = candidate_with_changes(case, [*valid, change])
                if any(gap.code == "UNSUPPORTED_ACTION" and probe_origins.get(gap.step_seq) == step.seq
                       for gap in analyze_executability(probe).gaps):
                    fail("UNSUPPORTED_ACTION", "ACTION_SPECS contains this verb but the runner has no adapter.")

            if not failures:
                references = _resolve_references(change.evidence, context)
                if references is None:
                    fail("FABRICATED_EVIDENCE", "An evidence reference is absent from the supplied context.")
                else:
                    grounding = _ground_action(change, references, context)
                    if grounding is not None:
                        fail(grounding, "Proposed action or arguments are not grounded in cited context evidence.")
                    semantics = _check_semantics(step, change, references, context, fixture_store=fixture_store)
                    if semantics is not None:
                        fail(semantics, "Original step and requirements do not prove the proposed meaning.")

            if not failures:
                before = analyze_executability(working)
                candidate, candidate_origins = candidate_with_changes(case, [*valid, change])
                after = analyze_executability(candidate)
                before_counts = _origin_gaps(before, origins)
                after_counts = _origin_gaps(after, candidate_origins)
                new = after_counts - before_counts
                if "UNSUPPORTED_ACTION" in {code for code, _ in new}:
                    fail("UNSUPPORTED_ACTION", "ACTION_SPECS contains this verb but the runner has no adapter.")
                elif new:
                    fail("NEW_EXECUTION_GAP", f"Candidate introduces gaps: {sorted(new.elements())}.")
                elif before.validation_error is None and after.validation_error is not None:
                    fail("NEW_VALIDATION_ERROR", f"Candidate becomes invalid: {after.validation_error}")
                elif not any(
                    after_counts[key] < before_counts[key]
                    for code in change.gap_codes
                    for key in ((code, step.seq), (code, None))
                    if before_counts[key]
                ):
                    fail("NO_EXECUTABILITY_PROGRESS", "Candidate removes none of its claimed gaps.")
                else:
                    working, origins = candidate, candidate_origins

        if failures:
            rejected.append(RejectedChange(change, tuple(failures)))
            issues.extend(failures)
        else:
            valid.append(change)

    remaining_gaps = _origin_gaps(analyze_executability(working), origins)
    unresolved: list[UnresolvedGap] = []
    for item in proposal.unresolved:
        key = _gap_key(item.code, item.step_seq)
        if context_gaps[key] == 0 or remaining_gaps[key] == 0:
            issues.append(ValidationIssue(
                "NO_MATCHING_GAP", "Unresolved entry does not name a remaining supplied gap.",
                step_seq=item.step_seq,
            ))
        else:
            unresolved.append(item)

    return ProposalValidationResult(
        tuple(valid), tuple(rejected), tuple(unresolved), tuple(issues),
        original, analyze_executability(working), case.id, fingerprint,
        _changes_fingerprint(valid),
    )


def _fixture_fill_error(action: str, args: dict, context: ResolutionContext,
                        fixture_store: FixtureStore | None) -> str | None:
    data = context.testcase.get("test_data", {})
    value = args.get("value")
    if action == "ui.fill" and is_alias(value) and REGISTRY in data:
        if fixture_store is None or not fixture_store.trusts(value, data[REGISTRY]):
            return "UNTRUSTED_FIXTURE"
    return None


def _origin_gaps(report: ExecutabilityReport, origins: dict[int, int]) -> Counter:
    return Counter((gap.code, origins.get(gap.step_seq, gap.step_seq)) for gap in report.gaps)


def _validate_expansion(step: Step, change: ProposedChange, context: ResolutionContext,
                        working: TestCase | None, origins: dict[int, int], *,
                        allow_single: bool = False, fixture_store: FixtureStore | None = None) -> str | None:
    if step.action not in TestCase.UNMAPPED_ACTIONS:
        return "EXPANSION_NOT_ALLOWED"
    if (not isinstance(change.expansion, (tuple, list))
            or not all(isinstance(atom, AtomicProposal) and isinstance(atom.args, dict)
                       for atom in change.expansion)
            or change.action or change.args or not (1 if allow_single else 2) <= len(change.expansion) <= 8):
        return "INVALID_EXPANSION"
    if _resolve_references(change.evidence, context) is None:
        return "FABRICATED_EVIDENCE"
    expected = expected_expansion(step, context.testcase.get("test_data", {}),
                                  min_atoms=1 if allow_single else 2, fixture_store=fixture_store)
    if expected is None or len(expected) != len(change.expansion):
        return "EXPANSION_SEMANTICS_UNPROVEN"
    for atom, meaning in zip(change.expansion, expected):
        if atom.action not in ACTION_SPECS:
            return "UNKNOWN_ACTION"
        if atom.action != meaning["action"]:
            return "EXPANSION_SEMANTICS_UNPROVEN"
        try:
            Step(step.seq, step.kind, atom.action, atom.args).validate()
        except (ValidationError, TypeError, ValueError, AttributeError):
            return "INVALID_ARGUMENTS"
        refs = _resolve_references(atom.evidence, context)
        if refs is None:
            return "FABRICATED_EVIDENCE"
        if error := _fixture_fill_error(atom.action, atom.args, context, fixture_store):
            return error
        single = replace(change, action=atom.action, args=atom.args,
                         evidence=atom.evidence, expansion=())
        if error := _ground_action(single, refs, context):
            return error
        required = dict(meaning.get("args", {}))
        if "precondition_route" in meaning:
            # _ground_action above already requires a cited trusted UI page.
            # Accept its exact absolute URL or the explicit source-relative URL.
            if not _same_route(meaning["precondition_route"], str(atom.args.get("url", ""))):
                return "EXPANSION_SEMANTICS_UNPROVEN"
            required["url"] = atom.args["url"]
        if "hint" in meaning:
            element = next((element for source, _, element in refs
                            if source == "ui-map" and element is not None
                            and atom.args.get("target") in {element.get("test_id"), element.get("id")}), None)
            if not element:
                return "UI_EVIDENCE_NOT_FOUND"
            hint = meaning["hint"]
            def matches_hint(item: dict) -> bool:
                name = item.get("name", "")
                if (atom.action == "ui.fill" and item.get("role") != "textbox"
                        and not item.get("input_type")):
                    return False
                if atom.action == "ui.fill" and hint in {"email", "password"}:
                    return (item.get("input_type") == hint or
                            hint == "email" and "email" in _norm(name).split())
                return _norm(hint) == _norm(name)
            matches = [item for page in context.observations.get("ui_pages", [])
                       for item in page.get("elements", []) if matches_hint(item)]
            if len(matches) != 1 or matches[0] is not element:
                return "EXPANSION_SEMANTICS_UNPROVEN"
            required["target"] = atom.args.get("target")
        if "value" in meaning:
            required["value"] = meaning["value"]
        if "operation" in meaning:
            method, path = meaning["operation"]
            operations = [item for source, item, _ in refs if source == "openapi"]
            if not any(item.get("method") == method and item.get("path") == path
                       and (atom.action != "assert.http_status" or
                            str(required["expected"]) in item.get("response_codes", []))
                       for item in operations):
                return "API_EVIDENCE_NOT_FOUND"
            source_name = atom.args.get("source", "res")
            requests = [item for item in working.steps
                        if origins[item.seq] < step.seq and item.action == "http.request"
                        and item.args.get("save_as", "res") == source_name]
            if not requests or (requests[-1].args.get("method", "").upper(), requests[-1].args.get("path")) != (method, path):
                return "MISSING_RESPONSE"
            if "source" in atom.args:
                required["source"] = source_name
        if "route" in meaning:
            if any((match := re.fullmatch(r"\s*URL not\s+(/\S*)\s*", text, re.I))
                   and match[1] == meaning["route"] for text in _expectation_texts(step, context)):
                return "SPECIFICATION_CONFLICT"
            if not any(source == "ui-map" and _same_route(meaning["route"], page["url"])
                       for source, page, _ in refs):
                return "UI_EVIDENCE_NOT_FOUND"
        if "by_name" in atom.args and "hint" in meaning:
            required["by_name"] = atom.args["by_name"]  # already checked against cited UI element
        if atom.args != required:
            return "EXPANSION_SEMANTICS_UNPROVEN"
        if atom.action in {"assert.visible", "assert.not_visible"}:
            prefix = "visible " if atom.action == "assert.visible" else "not visible "
            probe = Step(step.seq, step.kind, "assert.unmapped", {"expected": prefix + meaning["hint"]})
            if error := _check_semantics(probe, single, refs, context):
                return error
    return None


def _case_fingerprint(case: TestCase) -> str:
    """Bind validation to the complete serialized testcase, including step arguments."""
    payload = json.dumps(case.to_dict(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _changes_fingerprint(changes: tuple[ProposedChange, ...] | list[ProposedChange]) -> str:
    """Detect post-validation edits to nested proposal arguments or evidence."""
    payload = json.dumps([change.to_dict() for change in changes],
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _gap_key(code: str, step_seq: int | None) -> tuple[str, int | None]:
    return code, step_seq


def _gap_counts(report: ExecutabilityReport) -> Counter:
    return Counter(_gap_key(gap.code, gap.step_seq) for gap in report.gaps)


def _context_matches_case(context: ResolutionContext, case: TestCase,
                          report: ExecutabilityReport) -> bool:
    snapshot = context.testcase
    expected = {
        "id": case.id, "title": case.title, "objective": case.objective,
        "execution": case.execution, "traces_to": case.traces_to,
        "preconditions": case.preconditions, "requires": case.requires,
        "test_data": case.test_data, "source_quote": case.source_quote,
        "source_ref": case.source_ref, "steps": [step.to_dict() for step in case.steps],
    }
    return snapshot == expected and not (
        Counter(_gap_key(gap.code, gap.step_seq) for gap in context.gaps) - _gap_counts(report)
    )


def _resolve_references(references: tuple[EvidenceReference, ...],
                        context: ResolutionContext) -> list[tuple[str, dict, dict | None]] | None:
    if not references:
        return None
    resolved: list[tuple[str, dict, dict | None]] = []
    for evidence in references:
        ref = evidence.ref
        if not isinstance(ref, dict):
            return None
        if evidence.source == "requirement" and set(ref) == {"id"}:
            items = [item for item in context.specification.get("requirements", [])
                     if item.get("id") == ref["id"]]
            if len(items) == 1:
                resolved.append(("requirement", items[0], None))
                continue
        elif evidence.source == "openapi" and set(ref) <= {"operation_id", "method", "path"}:
            if not ("operation_id" in ref or {"method", "path"} <= set(ref)):
                return None
            items = [item for item in context.interface_contract.get("api_operations", [])
                     if all(item.get(key) == value for key, value in ref.items())]
            if len(items) == 1:
                resolved.append(("openapi", items[0], None))
                continue
        elif evidence.source == "ui-map" and set(ref) <= {"page", "test_id", "role", "name"}:
            page = next((item for item in context.observations.get("ui_pages", [])
                         if item.get("url") == ref.get("page")), None)
            if page is not None:
                locator = {key: value for key, value in ref.items() if key != "page"}
                elements = [item for item in page.get("elements", [])
                            if all(item.get(key) == value for key, value in locator.items())]
                if not locator or len(elements) == 1:
                    resolved.append(("ui-map", page, elements[0] if locator else None))
                    continue
        elif evidence.source == "testcase-step" and set(ref) <= {"step_seq", "action"}:
            if "step_seq" not in ref:
                return None
            items = [item for item in context.testcase.get("steps", [])
                     if item.get("seq") == ref["step_seq"]
                     and ("action" not in ref or item.get("action") == ref["action"])]
            if len(items) == 1:
                resolved.append(("testcase-step", items[0], None))
                continue
        return None
    return resolved


def _same_route(value: str, page_url: str) -> bool:
    if value == page_url:
        return True
    if not value.startswith("/") or value.startswith("//"):
        return False
    left, right = urlsplit(value), urlsplit(page_url)
    return (left.path, left.query, left.fragment) == (right.path, right.query, right.fragment)


def _ground_action(change: ProposedChange, refs: list[tuple[str, dict, dict | None]],
                   context: ResolutionContext) -> str | None:
    action, args = change.action, change.args
    ui_refs = [(page, element) for source, page, element in refs if source == "ui-map"]
    api_refs = [operation for source, operation, _ in refs if source == "openapi"]

    if action == "ui.goto":
        url = args.get("url")
        if not isinstance(url, str) or not any(_same_route(url, page["url"]) for page, _ in ui_refs):
            return "UI_EVIDENCE_NOT_FOUND"
    elif action.startswith(("ui.", "assert.")) and "target" in args:
        target = args["target"]
        if not isinstance(target, str) or not target:
            return "INVALID_ARGUMENTS"
        candidates = [(page, element) for page in context.observations.get("ui_pages", [])
                      for element in page.get("elements", [])
                      if target in {element.get("test_id"), element.get("id")}]
        if len(candidates) != 1:
            return "UI_EVIDENCE_NOT_FOUND"
        page, element = candidates[0]
        if not any(cited_page is page and cited_element is element
                   for cited_page, cited_element in ui_refs):
            return "UI_EVIDENCE_NOT_FOUND"
        if "by_name" in args and (
            not isinstance(args["by_name"], str)
            or _norm(args["by_name"]) != _norm(element.get("name", ""))
        ):
            return "UI_EVIDENCE_NOT_FOUND"
        if not element.get("test_id") and args.get("by_name") != element.get("name"):
            return "UI_EVIDENCE_NOT_FOUND"
    if action == "http.request":
        method, path = args.get("method"), args.get("path")
        if not isinstance(method, str) or not isinstance(path, str):
            return "INVALID_ARGUMENTS"
        path = path.rstrip("/") or "/"
        candidates = [item for item in context.interface_contract.get("api_operations", [])
                      if item.get("method") == method.upper()
                      and (item.get("path", "").rstrip("/") or "/") == path]
        if len(candidates) != 1 or not any(item is candidates[0] for item in api_refs):
            return "API_EVIDENCE_NOT_FOUND"
        base = args.get("base")
        if base is not None and base not in candidates[0].get("servers", []):
            return "API_EVIDENCE_NOT_FOUND"
    return None


_NEGATIVE = re.compile(r"\b(?:must\s+not\s+see|should\s+not\s+see|not\s+visible|"
                       r"not\s+shown|hidden|không\s+thấy|không\s+hiện|ẩn)\b", re.I)
_POSITIVE = re.compile(r"\b(?:visible|shown|see|appears|hiện|thấy)\b", re.I)
_ROUTE = re.compile(r"(?<!\w)(/[A-Za-z0-9_./?=&-]+)")
_NEGATED_URL = re.compile(r"^\s*URL\s+not\s+(/[A-Za-z0-9_./?=&-]+)\s*$", re.I)
_HTTP_CODE = re.compile(r"\b([1-5]\d\d)\b")


def _expectation_texts(step: Step, context: ResolutionContext) -> list[str]:
    texts = [str(step.args.get("expected") or ""), step.note]
    for requirement in context.specification.get("requirements", []):
        for key in ("statement", "then"):
            if isinstance(value := requirement.get(key), str):
                texts.append(value)
        texts.extend(value for value in requirement.get("acceptance", [])
                     if isinstance(value, str))
    return texts


def _check_semantics(step: Step, change: ProposedChange,
                     refs: list[tuple[str, dict, dict | None]],
                     context: ResolutionContext, *, fixture_store: FixtureStore | None = None) -> str | None:
    if step.action == "ui.goto" and not step.args.get("url"):
        if not _same_route(step.note.strip(), str(change.args.get("url", ""))):
            return "SEMANTICS_UNPROVEN"
    if step.action.startswith("ui.") and "target" in change.args and not step.args.get("target"):
        element = next((element for source, _, element in refs
                        if source == "ui-map" and element is not None
                        and change.args.get("target") in {
                            element.get("test_id"), element.get("id")}), None)
        name = (element or {}).get("name", "")
        hint = str(step.args.get("by_name") or step.note)
        if not name or _norm(name) not in _norm(hint):
            return "SEMANTICS_UNPROVEN"
    if step.action == "perform.unmapped" and change.action == "ui.fill":
        return _validate_expansion(step, replace(change, action="", args={}, expansion=(
            AtomicProposal(change.action, change.args, change.evidence),)), context, None, {}, allow_single=True, fixture_store=fixture_store)
    if step.action == "perform.unmapped":
        description = str(step.args.get("description") or "")
        grounded_arguments = {
            "ui.click": {"target", "by_name"},
            "http.request": {"method", "path", "base"},
            "ui.goto": {"url"},
        }
        if set(change.args) - grounded_arguments.get(change.action, set()):
            return "SEMANTICS_UNPROVEN"
        if change.action == "ui.click":
            element = next((element for source, _, element in refs
                            if source == "ui-map" and element is not None
                            and change.args.get("target") in {
                                element.get("test_id"), element.get("id")}), None)
            name = (element or {}).get("name", "")
            click = RE_CLICK.match(description)
            intent = bool(click or re.search(r"\bsubmits?\b|\bgửi\b", description, re.I))
            if not intent or not name or _norm(name) not in _norm(description):
                return "SEMANTICS_UNPROVEN"
        elif change.action == "http.request":
            match = RE_HTTP.search(description)
            if not match or (match.group(1).upper(), match.group(2).rstrip(".,;`\"')")) != (
                str(change.args.get("method", "")).upper(), change.args.get("path")
            ):
                return "SEMANTICS_UNPROVEN"
        elif change.action == "ui.goto":
            match = RE_OPEN_PATH.match(description)
            if not match or not _same_route(match.group(1), str(change.args.get("url", ""))):
                return "SEMANTICS_UNPROVEN"
        else:
            return "SEMANTICS_UNPROVEN"

    if not step.action.startswith("assert."):
        return None
    texts = _expectation_texts(step, context)
    action = change.action
    if action in {"assert.visible", "assert.not_visible"}:
        element = next((element for source, _, element in refs
                        if source == "ui-map" and element is not None
                        and change.args.get("target") in {
                            element.get("test_id"), element.get("id")}), None)
        name = (element or {}).get("name", "")
        original = f"{step.args.get('expected') or ''} {step.note}"
        if not name or _norm(name) not in _norm(original):
            return "SEMANTICS_UNPROVEN"
        relevant = [text for text in texts if name and _norm(name) in _norm(text)]
        negative = any(_NEGATIVE.search(text) for text in relevant)
        positive = any(_POSITIVE.search(text) and not _NEGATIVE.search(text) for text in relevant)
        if action == "assert.visible" and negative or action == "assert.not_visible" and positive:
            return "SPECIFICATION_CONFLICT"
        if action == "assert.visible" and not positive or action == "assert.not_visible" and not negative:
            return "SEMANTICS_UNPROVEN"
        return None
    if action == "assert.url_matches":
        pattern = change.args.get("pattern")
        if not isinstance(pattern, str):
            return "INVALID_ARGUMENTS"
        forbidden = {match.group(1) for text in texts if (match := _NEGATED_URL.fullmatch(text))}
        if pattern.removesuffix("$") in forbidden:
            return "SPECIFICATION_CONFLICT"
        routes = {route for text in texts for route in _ROUTE.findall(text)}
        pages = [page for source, page, _ in refs if source == "ui-map"]
        if not any(pattern in {route, route + "$"}
                   and any(_same_route(route, page["url"]) for page in pages)
                   for route in routes):
            return "SEMANTICS_UNPROVEN"
        return None
    if action == "assert.http_status":
        expected = change.args.get("expected")
        codes = {int(code) for text in texts for code in _HTTP_CODE.findall(text)}
        operations = [item for source, item, _ in refs if source == "openapi"]
        if type(expected) is not int or expected not in codes or not any(
            str(expected) in item.get("response_codes", []) for item in operations
        ):
            return "SEMANTICS_UNPROVEN"
        return None
    return "SEMANTICS_UNPROVEN"

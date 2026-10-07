"""Untrusted exploration plans and deterministic approval of bounded observations.

Validation never opens a browser, reads authentication files, or chooses targets.
The caller executes approved ExplorationRequest objects separately, if desired.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from urllib.parse import urljoin, urlsplit, urlunsplit

from .executability import analyze_executability
from .generate.mapper import RE_OPEN_PATH
from .proposal_validation import _context_matches_case
from .resolution_context import ResolutionContext
from .testcase import TestCase
from .ui.explore import (ExplorationAction, ExplorationRequest, MAX_EXPLORATION_ACTIONS,
                         SESSION_MODES, _origin, validate_exploration_request)


MAX_EXPLORATION_REQUESTS = 3
OBSERVATION_INTENTS = frozenset({"inspect_page", "observe_network"})


@dataclass(frozen=True)
class ExplorationPurpose:
    gap_code: str
    step_seq: int | None
    reason: str
    intent: str = "inspect_page"


@dataclass(frozen=True)
class PlannedExploration:
    target: str
    purposes: tuple[ExplorationPurpose, ...]
    session: str = "anonymous"
    actions: tuple[ExplorationAction, ...] = ()

    def to_dict(self) -> dict:
        result = {"target": self.target, "session": self.session,
                  "purposes": [asdict(purpose) for purpose in self.purposes]}
        if self.actions:
            result["actions"] = [action.to_dict() for action in self.actions]
        return result


@dataclass(frozen=True)
class ExplorationPlan:
    testcase_id: str
    requests: tuple[PlannedExploration, ...]

    def to_dict(self) -> dict:
        return {"testcase_id": self.testcase_id,
                "requests": [request.to_dict() for request in self.requests]}


@dataclass(frozen=True)
class ExplorationPlanIssue:
    code: str
    message: str
    request_index: int | None = None
    step_seq: int | None = None


@dataclass(frozen=True)
class RejectedExploration:
    request_index: int
    planned_request: PlannedExploration
    issues: tuple[ExplorationPlanIssue, ...]


@dataclass(frozen=True)
class ValidatedExplorationRequest:
    request: ExplorationRequest
    testcase_id: str
    purposes: tuple[ExplorationPurpose, ...]
    grounding: tuple[dict, ...]
    plan_indices: tuple[int, ...]
    action_fingerprint: str = ""

    @property
    def requires_auth_state(self) -> bool:
        return self.request.session == "authenticated"

    def to_dict(self) -> dict:
        return {
            "request": self.request.to_dict(), "testcase_id": self.testcase_id,
            "purposes": [asdict(purpose) for purpose in self.purposes],
            "grounding": deepcopy(list(self.grounding)), "plan_indices": list(self.plan_indices),
            "requires_auth_state": self.requires_auth_state,
            "action_fingerprint": self.action_fingerprint,
        }


@dataclass(frozen=True)
class ExplorationPlanValidationResult:
    valid_requests: tuple[ValidatedExplorationRequest, ...]
    rejected_requests: tuple[RejectedExploration, ...]
    issues: tuple[ExplorationPlanIssue, ...]

    @property
    def status(self) -> str:
        if not self.valid_requests:
            return "REJECTED"
        return "PARTIALLY_VALID" if self.issues else "VALID"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "valid_requests": [request.to_dict() for request in self.valid_requests],
            "rejected_requests": [{"request_index": rejected.request_index,
                                   "planned_request": rejected.planned_request.to_dict(),
                                   "issues": [asdict(issue) for issue in rejected.issues]}
                                  for rejected in self.rejected_requests],
            "issues": [asdict(issue) for issue in self.issues],
        }


def _normalized_target(target: str, base_url: str) -> str | None:
    resolved, issues = validate_exploration_request(ExplorationRequest(target), base_url=base_url)
    if issues:
        return None
    parts = urlsplit(resolved)
    scheme, host, port = _origin(resolved)
    host = f"[{host}]" if ":" in host else host
    if port != {"http": 80, "https": 443}[scheme]:
        host += f":{port}"
    return urlunsplit((scheme, host, parts.path or "/", parts.query, parts.fragment))


def _grounded_targets(case: TestCase, context: ResolutionContext, base_url: str) -> dict[str, list[dict]]:
    targets: dict[str, list[dict]] = {}

    def add(value: str, source: dict):
        normalized = _normalized_target(value, base_url)
        if normalized is not None and source not in targets.setdefault(normalized, []):
            targets[normalized].append(source)

    for value in (base_url, base_url.rstrip("/") + "/"):
        add(value, {"source": "application_base", "value": value})
    for step in case.steps:
        if step.action == "ui.goto" and isinstance(value := step.args.get("url"), str) and value:
            add(value, {"source": "testcase_step", "step_seq": step.seq, "field": "args.url", "value": value})
        texts = [("note", step.note)]
        if step.action in case.UNMAPPED_ACTIONS:
            texts.extend((f"args.{key}", step.args.get(key, ""))
                         for key in ("description", "expected", "expectation"))
        for field, text in texts:
            if not isinstance(text, str):
                continue
            value = text.strip()
            if match := RE_OPEN_PATH.match(value):
                value = match.group(1).strip("`\"'")
            if (value.startswith(("/", "http://", "https://"))
                    and not any(char.isspace() for char in value)):
                add(value, {"source": "testcase_step", "step_seq": step.seq,
                            "field": field, "value": value})
    from .semantic_ir import source_authorized_routes
    for url, proof in source_authorized_routes(case, context, base_url):
        add(url, proof)
    for page in context.observations.get("ui_pages", []):
        page_url = page.get("url", "")
        if not isinstance(page_url, str) or _normalized_target(page_url, base_url) is None:
            continue
        add(page_url, {"source": "ui_page", "value": page_url})
        for element in page.get("elements", []):
            href = element.get("href")
            if element.get("role") == "link" and isinstance(href, str) and href:
                add(urljoin(page_url, href), {
                    "source": "ui_link", "page": page_url,
                    "element_id": element.get("test_id") or element.get("id"), "value": href,
                })
    return targets


def _click_grounding(item, target, context, case, base_url):
    """V1: only an explicitly required empty-login submit, never a login with data.

    Names alone do not select controls. A unique stable test ID on the exact
    page must match the entire source click clause. Account provisioning and
    general-purpose/destructive controls have no approval rule here.
    """
    bindings = []
    from .source_grounding import empty_login_requirement, empty_form_contract
    requirement = empty_login_requirement(case, context)
    contract = empty_form_contract(requirement) if requirement else None
    if item.session != "anonymous" or contract is None or urlsplit(target).path != contract["route"]:
        raise ValueError("Only exact anonymous empty-form source inspection is supported")
    requirements = [requirement]
    pages = [p for p in context.observations.get("ui_pages", [])
             if _normalized_target(p.get("url", ""), base_url) == target]
    # Deduplicate identical snapshots, but conflicting metadata stays ambiguous.
    elements = []
    for page in pages:
        ids = [e.get("test_id") for e in page.get("elements", []) if e.get("test_id")]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate stable IDs on the page")
        for element in page.get("elements", []):
            if element not in elements:
                elements.append(element)
    for index, action in enumerate(item.actions):
        if any(value is not None and _normalized_target(value, base_url) != target
               for value in (action.page, action.expected_url)):
            raise ValueError("Empty-form observation cannot change pages")
        if not isinstance(action, ExplorationAction) or action.action != "ui.click":
            raise ValueError("Only ui.click is supported")
        if type(action.step_seq) is not int or not isinstance(action.target, str):
            raise ValueError("Invalid click identity")
        if not any(p.step_seq == action.step_seq and p.gap_code == "UNMAPPED_ACTION" for p in item.purposes):
            raise ValueError("Click must reference its current unmapped source step")
        steps = [s for s in case.steps if s.seq == action.step_seq and s.action in case.UNMAPPED_ACTIONS]
        matches = [e for e in elements if e.get("test_id") == action.target]
        if len(matches) != 1:
            raise ValueError("Stable target absent, ambiguous or on another page")
        element = matches[0]
        if element.get("role") != "button" or element.get("name") != contract["button"]:
            raise ValueError("Control is not an allowed empty-login submit")
        clause = f"Bấm {element['name']}"
        source_requirements = [req for req in requirements if req.get("when") == clause]
        justified = len(steps) == 1 and (
            steps[0].action == "perform.unmapped" and steps[0].args.get("description") == clause
            or steps[0].action == "assert.unmapped" and
            steps[0].args.get("expected") in {f"không gửi {contract['method']} {contract['path']}",
                                                   "Hiển thị " + contract["message"], requirement["then"]}
        )
        if not justified or not source_requirements:
            raise ValueError("Full source clause does not justify this submit")
        fields = []
        for typ in ("email", "password"):
            candidates = [e for e in elements
                          if (e.get("input_type") == "password" if typ == "password" else
                              e.get("input_type") in {"text", "email"} and e.get("name") in {
                                  "Email", "Email hoặc Số điện thoại", "Email address"})
                          and e.get("test_id") and e.get("role") in {"input", "textbox"}]
            if len(candidates) != 1:
                raise ValueError("Exact credential controls are missing or ambiguous")
            fields.append(candidates[0]["test_id"])
        operations = [op for op in context.interface_contract.get("api_operations", [])
                      if op.get("method") == contract["method"] and op.get("path") == contract["path"]]
        selectors = []
        for operation in operations:
            for server in operation.get("servers", []):
                from .response_capture import origin_of, validate_capture
                selector = {"method": "POST", "path": operation["path"],
                            "origin": origin_of(server), "timeout_ms": 2000}
                validate_capture(selector)
                if selector not in selectors:
                    selectors.append(selector)
        if len(selectors) != 1:
            raise ValueError("Exact source request observation/contract is missing or ambiguous")
        bindings.append({"source": "validated_click", "action_index": index,
                         "target": action.target, "step_seq": action.step_seq,
                         "name": element["name"],
                         "page": target, "empty_inputs": fields, "capture_requests": selectors[0],
                         "source_clause": clause,
                         "requirement_ids": [req["id"] for req in source_requirements]})
    return bindings


def _safe_planned(item, store):
    if store is None:
        return deepcopy(item)
    return replace(item, target=store.redact(item.target),
                   purposes=tuple(replace(p, reason=store.redact(p.reason)) for p in item.purposes),
                   actions=tuple(replace(a, value=store.redact(a.value) if a.value is not None else None,
                                         target=store.redact(a.target),
                                         page=store.redact(a.page) if a.page is not None else None,
                                         expected_url=store.redact(a.expected_url) if a.expected_url is not None else None)
                                 for a in item.actions))


def validate_exploration_plan(
    plan: ExplorationPlan, context: ResolutionContext, case: TestCase, base_url: str, *, fixture_store=None,
) -> ExplorationPlanValidationResult:
    """Approve grounded inspection and exact source-grounded UI interactions.

    Exact URL identity retains query/fragment and path case; no semantic matching
    or API endpoint inference occurs. Identical target/session/action sequences
    merge before the request and total-click budgets are enforced in plan order.
    """
    report = analyze_executability(case, context=context)
    global_issues: list[ExplorationPlanIssue] = []
    if plan.testcase_id != case.id or plan.testcase_id != context.testcase.get("id"):
        global_issues.append(ExplorationPlanIssue("TESTCASE_MISMATCH", "Plan must identify the supplied testcase."))
    if not _context_matches_case(context, case, report):
        global_issues.append(ExplorationPlanIssue("CONTEXT_MISMATCH", "Context does not describe current testcase/gaps."))
    _, base_issues = validate_exploration_request(ExplorationRequest("/"), base_url=base_url)
    if base_issues:
        global_issues.append(ExplorationPlanIssue("INVALID_BASE_URL", "Application base URL is invalid."))
    if not plan.requests:
        global_issues.append(ExplorationPlanIssue("EMPTY_PLAN", "Plan contains no exploration requests."))
    if global_issues:
        rejected = tuple(RejectedExploration(index, _safe_planned(item, fixture_store), tuple(
            replace(issue, request_index=index) for issue in global_issues
        )) for index, item in enumerate(plan.requests))
        return ExplorationPlanValidationResult((), rejected, tuple(global_issues))

    gaps = {(gap.code, gap.step_seq) for gap in context.gaps}
    targets = _grounded_targets(case, context, base_url)
    valid: dict[tuple, ValidatedExplorationRequest] = {}
    rejected: list[RejectedExploration] = []
    issues: list[ExplorationPlanIssue] = []
    for index, item in enumerate(plan.requests):
        failures: list[ExplorationPlanIssue] = []

        def fail(code: str, message: str, step_seq: int | None = None):
            failures.append(ExplorationPlanIssue(code, message, index, step_seq))

        if not isinstance(item.session, str) or item.session not in SESSION_MODES:
            fail("UNSUPPORTED_SESSION", "Only existing anonymous/authenticated sessions are allowed.")
        if not isinstance(item.actions, tuple) or any(not isinstance(a, ExplorationAction) for a in item.actions):
            fail("INVALID_ACTION", "Actions must be structured ordered UI requests.")
        elif len(item.actions) > MAX_EXPLORATION_ACTIONS:
            fail("ACTION_BUDGET_EXCEEDED", "At most five actions are allowed per request.")
        if (not isinstance(item.target, str) or not item.target
                or "\\" in item.target or any(char.isspace() for char in item.target)):
            fail("INVALID_TARGET", "Target must be an unambiguous URL or application path.")
        if not isinstance(item.purposes, (tuple, list)) or not item.purposes:
            fail("INVALID_PURPOSE", "Each request needs at least one current gap and reason.")
        else:
            for purpose in item.purposes:
                if (not isinstance(purpose, ExplorationPurpose) or not isinstance(purpose.gap_code, str)
                        or not purpose.gap_code or not isinstance(purpose.reason, str) or not purpose.reason.strip()
                        or purpose.step_seq is not None
                        and (type(purpose.step_seq) is not int or purpose.step_seq <= 0)):
                    fail("INVALID_PURPOSE", "Purpose requires a gap code, optional positive sequence, and reason.")
                    continue
                if not isinstance(purpose.intent, str) or purpose.intent not in OBSERVATION_INTENTS:
                    fail("UNSUPPORTED_EXPLORATION_INTENT", "Only inspection and network observation are supported.", purpose.step_seq)
                if purpose.step_seq is not None and sum(step.seq == purpose.step_seq for step in case.steps) != 1:
                    fail("STEP_NOT_FOUND", "Purpose must identify exactly one current step.", purpose.step_seq)
                if (purpose.gap_code, purpose.step_seq) not in gaps:
                    fail("GAP_NOT_FOUND", "Purpose does not reference a supplied current gap.", purpose.step_seq)

        target = None
        if not failures:
            _, target_issues = validate_exploration_request(
                ExplorationRequest(item.target, session=item.session), base_url=base_url,
            )
            for issue in target_issues:
                fail("OUT_OF_SCOPE_TARGET" if issue.code == "OUT_OF_SCOPE_TARGET" else "INVALID_TARGET", issue.message)
            if not failures:
                target = _normalized_target(item.target, base_url)
                if target not in targets:
                    fail("TARGET_NOT_GROUNDED", "No exact testcase route, selected UI page/link, or application entry grounds this target.")

        action_grounding = []
        if not failures and item.actions:
            try:
                if all(a.action == "ui.click" and a.value is None for a in item.actions):
                    try:
                        action_grounding = _click_grounding(item, target, context, case, base_url)
                    except (ValueError, TypeError, KeyError):
                        action_grounding = []
                if not action_grounding:
                    from .exploration_actions import ground_actions
                    action_grounding = ground_actions(item, target, context, case, base_url, fixture_store)
            except (ValueError, TypeError, KeyError):
                fail("UNSAFE_OR_UNGROUNDED_ACTION", "Sequence lacks exact safe controls, source clauses, values or trusted fixtures.")
        if not failures:
            key = target, item.session, item.actions
            if key not in valid and len(valid) >= MAX_EXPLORATION_REQUESTS:
                fail("REQUEST_BUDGET_EXCEEDED", "Only the first three unique valid target/session pairs are approved.")


        if failures:
            rejected.append(RejectedExploration(index, _safe_planned(item, fixture_store), tuple(failures)))
            issues.extend(failures)
            continue

        previous = valid.get(key)
        safe_purposes = tuple(replace(p, reason=fixture_store.redact(p.reason)) if fixture_store else deepcopy(p) for p in item.purposes)
        purposes = tuple(dict.fromkeys((previous.purposes if previous else ()) + safe_purposes))
        request = ExplorationRequest(
            target, session=item.session, collect_text=True,
            collect_network=any(purpose.intent == "observe_network" for purpose in purposes),
            reason="; ".join(dict.fromkeys(purpose.reason for purpose in purposes)),
            actions=tuple(deepcopy(item.actions)),
        )
        from .exploration_actions import action_fingerprint
        valid[key] = ValidatedExplorationRequest(
            request, case.id, purposes, tuple(deepcopy(targets[target] + action_grounding)),
            (previous.plan_indices if previous else ()) + (index,),
            action_fingerprint(request, action_grounding),
        )

    return ExplorationPlanValidationResult(tuple(valid.values()), tuple(rejected), tuple(issues))

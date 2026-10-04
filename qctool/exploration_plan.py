"""Untrusted exploration plans and deterministic approval of observation requests.

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
from .ui.explore import ExplorationRequest, SESSION_MODES, _origin, validate_exploration_request


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

    def to_dict(self) -> dict:
        return {"target": self.target, "session": self.session,
                "purposes": [asdict(purpose) for purpose in self.purposes]}


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

    @property
    def requires_auth_state(self) -> bool:
        return self.request.session == "authenticated"

    def to_dict(self) -> dict:
        return {
            "request": self.request.to_dict(), "testcase_id": self.testcase_id,
            "purposes": [asdict(purpose) for purpose in self.purposes],
            "grounding": deepcopy(list(self.grounding)), "plan_indices": list(self.plan_indices),
            "requires_auth_state": self.requires_auth_state,
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


def validate_exploration_plan(
    plan: ExplorationPlan, context: ResolutionContext, case: TestCase, base_url: str,
) -> ExplorationPlanValidationResult:
    """Approve only grounded navigate-and-inspect requests for supplied current gaps.

    Exact URL identity retains query/fragment and path case; no semantic matching
    or API endpoint inference occurs. Duplicate target/session pairs merge before
    the three-request budget is enforced in plan order.
    """
    report = analyze_executability(case)
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
        rejected = tuple(RejectedExploration(index, deepcopy(item), tuple(
            replace(issue, request_index=index) for issue in global_issues
        )) for index, item in enumerate(plan.requests))
        return ExplorationPlanValidationResult((), rejected, tuple(global_issues))

    gaps = {(gap.code, gap.step_seq) for gap in context.gaps}
    targets = _grounded_targets(case, context, base_url)
    valid: dict[tuple[str, str], ValidatedExplorationRequest] = {}
    rejected: list[RejectedExploration] = []
    issues: list[ExplorationPlanIssue] = []
    for index, item in enumerate(plan.requests):
        failures: list[ExplorationPlanIssue] = []

        def fail(code: str, message: str, step_seq: int | None = None):
            failures.append(ExplorationPlanIssue(code, message, index, step_seq))

        if not isinstance(item.session, str) or item.session not in SESSION_MODES:
            fail("UNSUPPORTED_SESSION", "Only existing anonymous/authenticated sessions are allowed.")
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

        if not failures:
            key = target, item.session
            if key not in valid and len(valid) >= MAX_EXPLORATION_REQUESTS:
                fail("REQUEST_BUDGET_EXCEEDED", "Only the first three unique valid target/session pairs are approved.")

        if failures:
            rejected.append(RejectedExploration(index, deepcopy(item), tuple(failures)))
            issues.extend(failures)
            continue

        previous = valid.get(key)
        purposes = tuple(dict.fromkeys((previous.purposes if previous else ()) + tuple(deepcopy(item.purposes))))
        request = ExplorationRequest(
            target, session=item.session, collect_text=True,
            collect_network=any(purpose.intent == "observe_network" for purpose in purposes),
            reason="; ".join(dict.fromkeys(purpose.reason for purpose in purposes)),
        )
        valid[key] = ValidatedExplorationRequest(
            request, case.id, purposes, tuple(deepcopy(targets[target])),
            (previous.plan_indices if previous else ()) + (index,),
        )

    return ExplorationPlanValidationResult(tuple(valid.values()), tuple(rejected), tuple(issues))

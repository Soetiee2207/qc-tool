"""Read-only diagnosis of whether a testcase can be attempted by the current runner.

Validation is reported separately: incomplete steps can have useful execution gaps
even though ``Step.validate()`` rejects their missing required arguments.
"""

from __future__ import annotations

from dataclasses import dataclass

from qctool.execute.runner import UI_VERBS
from qctool.data.fixtures import fixture_gaps
from qctool.core.testcase import ACTION_SPECS, TestCase, ValidationError


@dataclass(frozen=True)
class ExecutionGap:
    code: str
    message: str
    step_seq: int | None = None


@dataclass(frozen=True)
class ExecutabilityReport:
    executable: bool
    gaps: tuple[ExecutionGap, ...]
    validation_error: str | None = None


# These are the concrete branches of runner._run_step. UI branches come from
# UI_VERBS; ACTION_SPECS describes valid syntax, including verbs without adapters.
_NON_UI_ADAPTERS = frozenset({
    "http.request", "assert.http_status", "assert.json_schema",
    "assert.json_field", "assert.response_time", "wait",
})
_RESPONSE_ASSERTIONS = frozenset({
    "assert.http_status", "assert.json_schema", "assert.json_field",
    "assert.response_time",
})


def analyze_executability(case: TestCase, *, context=None) -> ExecutabilityReport:
    """Inspect one case without changing it or touching its execution environment.

    ``validation_error`` preserves the model's own invalid-case decision. A
    structurally valid unmapped/manual case instead has gaps with no validation
    error. Runtime availability (URL, credentials, network, page elements) cannot
    be established from a TestCase alone. Optional trusted context adds narrowly
    provable source-grounding gaps; it never infers business expectations.
    """
    try:
        case.validate()
    except ValidationError as exc:
        validation_error = str(exc)
    else:
        validation_error = None

    gaps: list[ExecutionGap] = []
    if case.execution == "manual":
        gaps.append(ExecutionGap("MANUAL_EXECUTION", "Case is marked for manual execution."))
    if case.requires:
        gaps.append(ExecutionGap("MISSING_PRECONDITION", f"Requires setup: {case.requires}"))

    gaps.extend(ExecutionGap("MISSING_FIXTURE", f"Trusted fixture unavailable: {alias}", seq)
                for alias, seq in fixture_gaps(case))
    if context is not None and getattr(context, 'data_acquisition', None):
        data = context.data_acquisition
        if data.get('testcase_id') != case.id:
            gaps.append(ExecutionGap('MISSING_TEST_DATA', 'Test-data evidence belongs to another testcase.'))
        else:
            for issue in data.get('issues', []):
                code = issue['code']
                if code == 'MISSING_FIXTURE' and any(g.code == code for g in gaps):
                    continue
                # Data blockers belong to the whole case; original step numbers
                # remain in the data audit even after an expansion renumbers IR.
                gaps.append(ExecutionGap(code, issue['message']))

    saved_responses: set[str] = set()
    captured_responses: set[str] = set()
    request_observations: set[str] = set()
    executable_assertion = False
    for step in case.steps:
        action, args = step.action, step.args
        if action not in ACTION_SPECS:
            gaps.append(ExecutionGap("INVALID_ACTION", f"Unknown action: {action}", step.seq))
            continue
        if action in case.UNMAPPED_ACTIONS:
            gaps.append(ExecutionGap("UNMAPPED_ACTION", f"Action is not mapped: {action}", step.seq))
            continue

        before = len(gaps)
        for name in ACTION_SPECS[action].required:
            # Same rule as Step.validate: `expected: ""` is a real oracle (empty field).
            if name not in args or args[name] is None or (args[name] == "" and name != "expected"):
                if name == "target" and action in UI_VERBS:
                    code, message = "MISSING_LOCATOR", "Missing UI locator: target"
                elif action == "http.request" and name == "method":
                    code, message = "MISSING_HTTP_METHOD", "Missing HTTP method"
                elif action == "http.request" and name == "path":
                    code, message = "MISSING_HTTP_PATH", "Missing HTTP path"
                elif action == "ui.goto" and name == "url":
                    code, message = "MISSING_URL", "Missing navigation URL"
                else:
                    code, message = "MISSING_ARGUMENT", f"Missing {action} argument: {name}"
                gaps.append(ExecutionGap(code, message, step.seq))

        if action not in UI_VERBS and action not in _NON_UI_ADAPTERS:
            gaps.append(ExecutionGap("UNSUPPORTED_ACTION", f"No runner adapter for {action}", step.seq))

        if action in _RESPONSE_ASSERTIONS:
            source = args.get("source", "res")
            count_source = (action == "assert.json_field" and args.get("path") == "$.request_count"
                            and source in request_observations)
            if not count_source and (source not in saved_responses or action == "assert.response_time" and source in captured_responses):
                gaps.append(ExecutionGap(
                    "MISSING_RESPONSE", f"No preceding HTTP response saved as {source!r}", step.seq
                ))

        if action == "http.request" and len(gaps) == before:
            request_observations.discard(args.get("save_as", "res"))
            saved_responses.add(args.get("save_as", "res"))
        if action == "ui.click" and "capture_requests" in args and len(gaps) == before:
            try:
                from qctool.data.capture import validate_capture
                validate_capture(args["capture_requests"])
            except (ValueError, TypeError):
                gaps.append(ExecutionGap("INVALID_ARGUMENTS", "Invalid request observation selector", step.seq))
            else:
                key = args["capture_requests"].get("save_as", "res")
                saved_responses.discard(key)
                captured_responses.discard(key)
                request_observations.add(key)
        if action == "ui.click" and "capture_response" in args and len(gaps) == before:
            from qctool.data.capture import validate_capture
            try:
                validate_capture(args["capture_response"])
            except (ValueError, TypeError):
                gaps.append(ExecutionGap("MISSING_ARGUMENT", "Invalid response capture selector", step.seq))
            else:
                key = args["capture_response"].get("save_as", "res")
                request_observations.discard(key)
                saved_responses.add(key)
                captured_responses.add(key)
        if action == "http.request":
            captured_responses.discard(args.get("save_as", "res"))
        if action.startswith("assert.") and action != "assert.screenshot" and len(gaps) == before:
            executable_assertion = True

    if not executable_assertion:
        gaps.append(ExecutionGap("MISSING_ASSERTION", "No executable assertion in testcase."))

    return ExecutabilityReport(not gaps and validation_error is None, tuple(gaps), validation_error)

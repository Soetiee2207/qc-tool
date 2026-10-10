"""Focused tests for read-only executability diagnosis."""

from qctool.core.executability import ExecutionGap, analyze_executability
from qctool.core.testcase import Step, StepKind, TestCase


def _case(*steps: Step, **changes) -> TestCase:
    fields = dict(
        id="TC_LOGIN_001", module="LOGIN", title="Login", objective="Check login",
        steps=list(steps), traces_to=["AC-1"], source_quote="Login redirects to dashboard",
    )
    return TestCase(**{**fields, **changes})


def _step(seq: int, action: str, **args) -> Step:
    return Step(seq, StepKind.THEN if action.startswith("assert.") else StepKind.WHEN,
                action, args)


def test_executable_ui_case():
    case = _case(
        _step(1, "ui.goto", url="/login"),
        _step(2, "ui.fill", target="username", value="alice"),
        _step(3, "ui.click", target="login-button"),
        _step(4, "assert.url_matches", pattern="/dashboard$"),
    )
    report = analyze_executability(case)
    assert report.executable is True
    assert report.gaps == ()
    assert report.validation_error is None


def test_valid_unmapped_case_is_not_executable_or_invalid():
    case = _case(
        _step(1, "perform.unmapped", description="Click Login"),
        _step(2, "assert.unmapped", expected="Dashboard opens"),
    )
    before = [step.to_dict() for step in case.steps]
    report = analyze_executability(case)
    assert report.executable is False
    assert report.validation_error is None
    assert report.gaps == (
        ExecutionGap("UNMAPPED_ACTION", "Action is not mapped: perform.unmapped", 1),
        ExecutionGap("UNMAPPED_ACTION", "Action is not mapped: assert.unmapped", 2),
        ExecutionGap("MISSING_ASSERTION", "No executable assertion in testcase."),
    )
    assert [step.to_dict() for step in case.steps] == before


def test_missing_ui_locator_is_reported_as_gap_and_validation_error():
    report = analyze_executability(_case(
        _step(1, "ui.click"),
        _step(2, "assert.url_matches", pattern="/dashboard$"),
    ))
    assert report.executable is False
    assert report.gaps == (ExecutionGap("MISSING_LOCATOR", "Missing UI locator: target", 1),)
    assert "thiếu tham số bắt buộc" in report.validation_error


def test_missing_navigation_url_is_reported():
    report = analyze_executability(_case(
        _step(1, "ui.goto"),
        _step(2, "assert.url_matches", pattern="/dashboard$"),
    ))
    assert report.gaps == (ExecutionGap("MISSING_URL", "Missing navigation URL", 1),)


def test_no_assertion_is_both_gap_and_schema_error():
    report = analyze_executability(_case(_step(1, "ui.click", target="login-button")))
    assert report.executable is False
    assert [gap.code for gap in report.gaps] == ["MISSING_ASSERTION"]
    assert "không có bước kiểm tra" in report.validation_error


def test_screenshot_alone_does_not_verify_a_result():
    report = analyze_executability(_case(
        _step(1, "ui.goto", url="/login"),
        _step(2, "assert.screenshot", name="login"),
    ))
    assert [gap.code for gap in report.gaps] == ["MISSING_ASSERTION"]
    assert report.validation_error is None


def test_missing_http_arguments_follow_action_spec():
    report = analyze_executability(_case(
        _step(1, "http.request"),
        _step(2, "assert.http_status", expected=200),
    ))
    assert report.executable is False
    assert [(gap.code, gap.step_seq) for gap in report.gaps] == [
        ("MISSING_HTTP_METHOD", 1), ("MISSING_HTTP_PATH", 1),
        ("MISSING_RESPONSE", 2), ("MISSING_ASSERTION", None),
    ]
    assert report.validation_error is not None


def test_requires_is_runner_blocking_setup_not_validation_error():
    report = analyze_executability(_case(
        _step(1, "http.request", method="GET", path="/private"),
        _step(2, "assert.http_status", expected=403),
        requires="Account without permission",
    ))
    assert report.executable is False
    assert report.gaps == (ExecutionGap(
        "MISSING_PRECONDITION", "Requires setup: Account without permission"
    ),)
    assert report.validation_error is None


def test_manual_case_is_not_automatically_executable():
    report = analyze_executability(_case(
        _step(1, "ui.click", target="login-button"),
        _step(2, "assert.url_matches", pattern="/dashboard$"),
        execution="manual",
    ))
    assert [gap.code for gap in report.gaps] == ["MANUAL_EXECUTION"]
    assert report.validation_error is None


def test_known_action_without_runtime_adapter_is_reported():
    report = analyze_executability(_case(
        _step(1, "db.query", sql="select 1"),
        _step(2, "assert.url_matches", pattern="/dashboard$"),
    ))
    assert report.executable is False
    assert report.gaps == (ExecutionGap(
        "UNSUPPORTED_ACTION", "No runner adapter for db.query", 1
    ),)
    assert report.validation_error is None


def test_unknown_action_remains_schema_error():
    report = analyze_executability(_case(
        _step(1, "ui.tap", target="login-button"),
        _step(2, "assert.url_matches", pattern="/dashboard$"),
    ))
    assert report.executable is False
    assert report.gaps[0].code == "INVALID_ACTION"
    assert "vocabulary đóng" in report.validation_error

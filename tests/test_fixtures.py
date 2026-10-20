"""Offline fixture trust/redaction tests; secret sentinels are fictional."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from qctool.data.fixtures import FixtureStore, FixtureUnavailable, REGISTRY
from qctool.core.executability import analyze_executability
from qctool.execute.runner import run_cases, HttpSession
from qctool.pipeline import PipelineConfig
from qctool.generation import run_generation
from qctool.ui.crawl import Element, PageMap, UIMap
from tests.fixture_samples import BASE, ACTION

SECRETS = {"ACTIVE_EMAIL": "fictional-active@example.test", "ACTIVE_PASSWORD": "FICTIONAL_ACTIVE_SECRET_7",
           "LOCKED_EMAIL": "fictional-locked@example.test", "LOCKED_PASSWORD": "FICTIONAL_LOCKED_SECRET_9"}


def store(name="active_user", missing=False):
    return FixtureStore({
        "active_user": {"email": {"env": "ACTIVE_EMAIL"}, "password": {"env": "ACTIVE_PASSWORD"}},
        "locked_user": {"email": {"env": "LOCKED_EMAIL"}, "password": {"env": "LOCKED_PASSWORD"}},
    }, {"FR-LOGIN": {"email": name + ".email", "correct_password": name + ".password"}},
        environ={} if missing else SECRETS)


class FakeBrowser:
    trace_enabled = True
    evidence_dir = Path("fictional-evidence")
    soft_failures = []

    def __init__(self, error=False):
        self.calls = []
        self.error = error
        self.evidence = type("Evidence", (), {"to_dict": lambda self: {"console": [SECRETS["ACTIVE_PASSWORD"]]}})()

    # Case điền mật khẩu: tắt TRACE (ghi nguyên văn giá trị điền); ảnh vẫn giữ vì ô bị che.
    def start_case(self, case_id):
        assert self.trace_enabled is False and self.evidence_dir == Path("fictional-evidence")

    def end_case(self, status):
        assert self.trace_enabled is False and self.evidence_dir == Path("fictional-evidence")

    def goto(self, url):
        return url

    def fill(self, args):
        self.calls.append(args.copy())
        if self.error:
            raise RuntimeError(args["value"])
        return args["value"]

    def click(self, args):
        return "Clicked"

    def url_matches(self, args):
        return True, "URL matched"


def test_config_env_only_and_missing_fields_are_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_ONLY_EMAIL", SECRETS["ACTIVE_EMAIL"])
    path = tmp_path / "config.yaml"
    path.write_text("test_fixtures:\n  fixtures:\n    active_user:\n      email: {env: FIXTURE_ONLY_EMAIL}\n      password: {env: DEFINITELY_MISSING_FIXTURE_FIELD}\n  bindings:\n    FR-LOGIN:\n      email: active_user.email\n      correct_password: active_user.password\n")
    cfg = PipelineConfig.from_file(path)
    assert cfg.fixture_store.resolve("active_user.email") == SECRETS["ACTIVE_EMAIL"]
    assert not cfg.fixture_store.to_dict()["aliases"]["active_user.password"]["available"]
    assert SECRETS["ACTIVE_EMAIL"] not in repr(cfg)


def test_json_escaped_secret_cannot_leak_into_parsed_audit():
    secret = 'FICTIONAL_"ESCAPED"_SECRET'
    trusted = FixtureStore({"active_user": {"password": {"value": secret}}})
    class Model:
        def complete(self, prompt):
            return json.dumps({"value": secret})
    response = trusted.guard_adapter(Model()).complete("safe")
    assert json.loads(response)["value"] == "[REDACTED]"
    assert secret not in response


class TraceProbe:
    """Records whether trace/evidence were live while a fixture case ran."""
    soft_failures = []

    def __init__(self, sensitive):
        self.trace_enabled, self.evidence_dir, self.trace_sensitive = True, Path("fictional-evidence"), sensitive
        self.seen = []
        self.evidence = type("Evidence", (), {"to_dict": lambda self: {}})()

    def start_case(self, case_id):
        self.seen.append((self.trace_enabled, self.evidence_dir))

    def end_case(self, status):
        pass

    def fill(self, args):
        return "filled"


def _fixture_case():
    from qctool.core.testcase import Step, StepKind, TestCase
    case = TestCase("TC_LOGIN_001", "LOGIN", "Login", "OK", traces_to=["FR-LOGIN"], source_quote="OK",
                    steps=[Step(1, StepKind.WHEN, "ui.fill", {"target": "pwd", "value": "active_user.password"})])
    return store().bind(case)


@pytest.mark.parametrize("sensitive, expected", [(False, (False, Path("fictional-evidence"))),
                                                 (True, (True, Path("fictional-evidence")))])
def test_trace_sensitive_is_explicit_opt_in(sensitive, expected):
    from qctool.execute.runner import run_case
    browser = TraceProbe(sensitive)
    run_case(_fixture_case(), HttpSession("http://fictional.test"), browser, fixture_store=store())
    assert browser.seen == [expected]
    # Settings are restored after the case either way.
    assert browser.trace_enabled is True and browser.evidence_dir == Path("fictional-evidence")


def test_trace_sensitive_config_defaults_off(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("ui: {trace: true}\n")
    assert PipelineConfig.from_file(path).ui_trace_sensitive is False
    path.write_text("ui: {trace: true, trace_sensitive: true}\n")
    assert PipelineConfig.from_file(path).ui_trace_sensitive is True

"""Offline fixture trust/redaction tests; secret sentinels are fictional."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from qctool.test_fixtures import FixtureStore, FixtureUnavailable, REGISTRY
from qctool.proposal_validation import validate_resolution_proposal
from qctool.apply_resolution import apply_validated_resolution
from qctool.executability import analyze_executability
from qctool.resolution_context import build_resolution_context
from qctool.llm_resolution import ResolutionProposal, ProposedChange, build_resolution_prompt
from qctool.execute.runner import run_cases, HttpSession
from qctool.pipeline import PipelineConfig
from qctool.generation import run_generation
from qctool.ui.crawl import Element, PageMap, UIMap
from tests.test_step_expansion import fixture, expansion, ui_ref, BASE, ACTION

SECRETS = {"ACTIVE_EMAIL": "fictional-active@example.test", "ACTIVE_PASSWORD": "FICTIONAL_ACTIVE_SECRET_7",
           "LOCKED_EMAIL": "fictional-locked@example.test", "LOCKED_PASSWORD": "FICTIONAL_LOCKED_SECRET_9"}


def store(name="active_user", missing=False):
    return FixtureStore({
        "active_user": {"email": {"env": "ACTIVE_EMAIL"}, "password": {"env": "ACTIVE_PASSWORD"}},
        "locked_user": {"email": {"env": "LOCKED_EMAIL"}, "password": {"env": "LOCKED_PASSWORD"}},
    }, {"FR-LOGIN": {"email": name + ".email", "correct_password": name + ".password"}},
        environ={} if missing else SECRETS)


def bound_fixture(name="active_user", missing=False):
    case, context = fixture(data={})
    trusted = store(name, missing)
    bound = trusted.bind(case)
    context = replace(context, testcase={**context.testcase, "test_data": deepcopy(bound.test_data)},
                      gaps=analyze_executability(bound).gaps)
    change = expansion()
    atoms = list(change.expansion)
    atoms[0] = replace(atoms[0], args={"target": "email", "value": name + ".email"})
    atoms[1] = replace(atoms[1], args={"target": "password", "value": name + ".password"})
    change = replace(change, expansion=tuple(atoms))
    return case, bound, context, change, trusted


def validate(bound, context, change, trusted):
    return validate_resolution_proposal(ResolutionProposal(bound.id, (change,), ()), context, bound,
                                        fixture_store=trusted)


@pytest.mark.parametrize("name", ["active_user", "locked_user"])
def test_named_fixture_grounds_login_aliases_without_exposing_values(name):
    original, bound, context, change, trusted = bound_fixture(name)
    snapshots = deepcopy((original, bound, context, change, trusted.to_dict()))
    result = validate(bound, context, change, trusted)
    assert result.valid_changes == (change,)
    applied = apply_validated_resolution(bound, result)
    assert not applied.issues
    assert applied.case.steps[1].args["value"] == name + ".email"
    assert applied.case.steps[2].args["value"] == name + ".password"
    payload = json.dumps([applied.case.to_dict(), context.to_dict(), change.to_dict(),
                          trusted.to_dict(), [a.to_dict() for a in applied.applied_changes]]) + repr(trusted)
    prompt = build_resolution_prompt(context)
    for secret in SECRETS.values():
        assert secret not in payload and secret not in prompt
    assert (original, bound, context, change, trusted.to_dict()) == snapshots
    assert name + ".password" in prompt
    assert trusted.resolve(name + ".password") == SECRETS["LOCKED_PASSWORD" if name == "locked_user" else "ACTIVE_PASSWORD"]


def test_locked_fixture_cannot_be_substituted_for_active_binding():
    _, bound, context, change, trusted = bound_fixture()
    atoms = list(change.expansion)
    atoms[1] = replace(atoms[1], args={"target": "password", "value": "locked_user.password"})
    result = validate(bound, context, replace(change, expansion=tuple(atoms)), trusted)
    assert not result.valid_changes


@pytest.mark.parametrize("alias", ["invented_user.password", "active_user.secret_field"])
def test_invented_alias_rejected(alias):
    _, bound, context, change, trusted = bound_fixture()
    atoms = list(change.expansion)
    atoms[1] = replace(atoms[1], args={"target": "password", "value": alias})
    assert not validate(bound, context, replace(change, expansion=tuple(atoms)), trusted).valid_changes


def test_missing_fixture_stays_unresolved():
    _, bound, context, change, trusted = bound_fixture(missing=True)
    assert "MISSING_FIXTURE" in {g.code for g in analyze_executability(bound).gaps}
    assert not validate(bound, context, change, trusted).valid_changes
    assert not analyze_executability(bound).executable
    with pytest.raises(FixtureUnavailable):
        trusted.resolve("active_user.password")


def test_availability_metadata_is_not_itself_proof_of_fixture_data():
    _, bound, context, change, trusted = bound_fixture()
    result = validate(bound, context, change, None)
    assert not result.valid_changes
    assert "UNTRUSTED_FIXTURE" in {i.code for i in result.issues}
    assert not validate(bound, context, change, store(missing=True)).valid_changes


def executable_fixture():
    _, bound, context, change, trusted = bound_fixture()
    assertion = ProposedChange(3, "assert.unmapped", ("UNMAPPED_ACTION",), "assert.url_matches",
                               {"pattern": "/login$"}, "Explicit URL", (ui_ref(),))
    validated = validate_resolution_proposal(ResolutionProposal(bound.id, (change, assertion), ()),
                                             context, bound, fixture_store=trusted)
    applied = apply_validated_resolution(bound, validated)
    assert applied.after.executable
    return applied.case, trusted


class FakeBrowser:
    trace_enabled = True
    evidence_dir = Path("fictional-evidence")
    soft_failures = []

    def __init__(self, error=False):
        self.calls = []
        self.error = error
        self.evidence = type("Evidence", (), {"to_dict": lambda self: {"console": [SECRETS["ACTIVE_PASSWORD"]]}})()

    def start_case(self, case_id):
        assert self.trace_enabled is False and self.evidence_dir is None

    def end_case(self, status):
        assert self.trace_enabled is False and self.evidence_dir is None

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


def test_runner_resolves_only_at_runtime_and_redacts_details_and_evidence():
    case, trusted = executable_fixture()
    before = deepcopy(case)
    browser = FakeBrowser()
    result = run_cases([case], HttpSession(BASE), browser=browser, fixture_store=trusted)
    assert result.cases[0].status == "Pass"
    assert browser.calls[0]["value"] == SECRETS["ACTIVE_EMAIL"]
    assert browser.calls[1]["value"] == SECRETS["ACTIVE_PASSWORD"]
    for secret in SECRETS.values():
        assert secret not in json.dumps(result.to_dict())
    assert case == before
    assert browser.trace_enabled is True and browser.evidence_dir == Path("fictional-evidence")


def test_runtime_fixture_missing_blocks_without_browser_or_fake_pass():
    case, trusted = executable_fixture()
    result = run_cases([case], HttpSession(BASE), fixture_store=store(missing=True))
    assert result.cases[0].status == "Blocked"
    assert not result.cases[0].steps


def test_runtime_error_and_model_completion_secret_are_redacted():
    case, trusted = executable_fixture()
    result = run_cases([case], HttpSession(BASE), browser=FakeBrowser(error=True), fixture_store=trusted)
    for secret in SECRETS.values():
        assert secret not in json.dumps(result.to_dict())
    class BadModel:
        def complete(self, prompt):
            return SECRETS["ACTIVE_PASSWORD"]
    assert trusted.guard_adapter(BadModel()).complete("No secrets") == "[REDACTED]"


def test_config_env_only_and_missing_fields_are_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_ONLY_EMAIL", SECRETS["ACTIVE_EMAIL"])
    path = tmp_path / "config.yaml"
    path.write_text("test_fixtures:\n  fixtures:\n    active_user:\n      email: {env: FIXTURE_ONLY_EMAIL}\n      password: {env: DEFINITELY_MISSING_FIXTURE_FIELD}\n  bindings:\n    FR-LOGIN:\n      email: active_user.email\n      correct_password: active_user.password\n")
    cfg = PipelineConfig.from_file(path)
    assert cfg.fixture_store.resolve("active_user.email") == SECRETS["ACTIVE_EMAIL"]
    assert not cfg.fixture_store.to_dict()["aliases"]["active_user.password"]["available"]
    assert SECRETS["ACTIVE_EMAIL"] not in repr(cfg)


def test_single_fill_proposal_can_ground_a_trusted_alias():
    case, context = fixture(description="fill email", data={})
    trusted = store()
    bound = trusted.bind(case)
    context = replace(context, testcase={**context.testcase, "test_data": bound.test_data})
    change = ProposedChange(2, "perform.unmapped", ("UNMAPPED_ACTION",), "ui.fill",
                            {"target": "email", "value": "active_user.email"}, "Explicit field",
                            (ui_ref("email"),))
    assert validate(bound, context, change, trusted).valid_changes


def test_generation_forwards_bindings_context_and_validator_without_secrets():
    trusted = store()
    requirements = [{"id": "FR-LOGIN", "kind": "acceptance_criterion", "title": "Login",
                     "given": "Open /login", "when": ACTION, "then": "URL vẫn ở /login"}]
    _, _, context, change, _ = bound_fixture()
    pages = context.observations["ui_pages"]
    elements = [Element(e["id"], e["role"], e["name"], "input" if e.get("input_type") else "button",
                        test_id=e.get("test_id"), input_type=e.get("input_type")) for e in pages[0]["elements"]]
    ui = UIMap(BASE, "now", [PageMap(BASE + "/login", "Login", elements=elements)])
    before = deepcopy((requirements, ui, trusted.to_dict()))
    class Model:
        def complete(self, prompt):
            data = json.loads(prompt.split("TESTCASE\n", 1)[1].split("\n\n", 1)[0])
            assert data["test_data"]["email"] == "active_user.email"
            assert all(secret not in prompt for secret in SECRETS.values())
            assertion = ProposedChange(3, "assert.unmapped", ("UNMAPPED_ACTION",), "assert.url_matches",
                                       {"pattern": "/login$"}, "Exact route", (ui_ref(),))
            return json.dumps({"testcase_id": data["id"], "changes": [change.to_dict(), assertion.to_dict()], "unresolved": []})
    result = run_generation(requirements, fixture_store=trusted, ui_map=ui, resolution_llm=Model())
    assert len(result.accepted_generated_cases) == 1
    assert analyze_executability(result.accepted_generated_cases[0]).executable
    assert (requirements, ui, trusted.to_dict()) == before
    for secret in SECRETS.values():
        assert secret not in json.dumps(result.to_dict())


def test_concrete_fill_alias_also_requires_real_store_proof():
    case, context = fixture(description="fill email", data={})
    case.steps[1].action = "ui.fill"
    case.steps[1].args = {"value": "active_user.email", "by_name": "Email hoặc Số điện thoại"}
    trusted = store()
    bound = trusted.bind(case)
    context = replace(context, testcase={**context.testcase, "test_data": bound.test_data,
                                        "steps": [s.to_dict() for s in bound.steps]},
                      gaps=analyze_executability(bound).gaps)
    change = ProposedChange(2, "ui.fill", ("MISSING_LOCATOR",), "ui.fill",
                            {**bound.steps[1].args, "target": "email"}, "Exact existing field", (ui_ref("email"),))
    assert not validate(bound, context, change, None).valid_changes
    assert validate(bound, context, change, trusted).valid_changes


def test_json_escaped_secret_cannot_leak_into_parsed_audit():
    secret = 'FICTIONAL_"ESCAPED"_SECRET'
    trusted = FixtureStore({"active_user": {"password": {"value": secret}}})
    class Model:
        def complete(self, prompt):
            return json.dumps({"value": secret})
    response = trusted.guard_adapter(Model()).complete("safe")
    assert json.loads(response)["value"] == "[REDACTED]"
    assert secret not in response

"""SalonHub-shaped expansion regressions, using offline trusted fixture data only."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from qctool.apply_resolution import apply_validated_resolution
from qctool.executability import analyze_executability
from qctool.generate.loader import load_endpoints
from qctool.llm_resolution import (
    AtomicProposal, EvidenceReference, LLMResponseError, ProposedChange,
    ResolutionProposal, parse_resolution_proposal, build_resolution_prompt,
)
from qctool.proposal_validation import validate_resolution_proposal
from qctool.resolution_context import build_resolution_context
from qctool.testcase import Step, StepKind, TestCase
from qctool.ui.crawl import Element, PageMap, UIMap
from pathlib import Path

BASE = "https://fixture.test"
ACTION = "Nhập email và mật khẩu đúng; bấm Đăng nhập"
NEGATIVE = "POST /api/auth/login trả 401; hiển thị Email, Số điện thoại hoặc mật khẩu không đúng; URL vẫn ở /login"
LOCKED = "POST /api/auth/login trả 401; hiển thị Tài khoản của bạn đã bị khóa.; URL vẫn ở /login"
HAPPY = "Đăng nhập thành công; URL chuyển tới /; POST /api/auth/login trả 200 với success=true"


def ui_ref(target=None):
    return EvidenceReference("ui-map", {"page": BASE + "/login", **({"test_id": target} if target else {})})


def atom(action, args, target=None, refs=None):
    return AtomicProposal(action, args, refs or (ui_ref(target),))


def fixture(description=ACTION, expected="URL vẫn ở /login", data=None, http=False):
    steps = [Step(1, StepKind.GIVEN, "ui.goto", {"url": "/login"}),
             Step(2, StepKind.WHEN, "perform.unmapped", {"description": description}),
             Step(3, StepKind.THEN, "assert.unmapped", {"expected": expected})]
    if http:
        steps[0] = Step(1, StepKind.WHEN, "http.request", {"method": "POST", "path": "/api/auth/login"})
    case = TestCase("TC_SALON_AUTH_007", "SALON_AUTH", "Fixture login", "Fixture", steps=steps,
                    traces_to=["FR-LOGIN"], source_quote=expected, source_ref="SRS.md#FR-LOGIN",
                    execution="manual", test_data=data if data is not None else {
                        "email": "fixture@example.test", "correct_password": "fixture-correct",
                        "wrong_password": "fixture-wrong", "non_empty_password": "fixture-nonempty",
                        "password": "fixture-correct"})
    elements = [Element("email", "textbox", "Email hoặc Số điện thoại", "input", test_id="email", input_type="text"),
                Element("password", "textbox", "Nhập mật khẩu", "input", test_id="password", input_type="password"),
                Element("login", "button", "Đăng nhập", "button", test_id="login")]
    for i, text in enumerate(["Email, Số điện thoại hoặc mật khẩu không đúng", "Tài khoản của bạn đã bị khóa."]):
        elements.append(Element(f"message-{i}", "alert", text, "div", test_id=f"message-{i}"))
    ui = UIMap(BASE, "now", [PageMap(BASE + "/login", "Login", elements=elements)])
    endpoint = load_endpoints(Path("samples/smoke/openapi.yaml"))[0][0]
    endpoint = replace(endpoint, method="POST", path="/api/auth/login", operation_id="login")
    context = build_resolution_context(case, analyze_executability(case).gaps, ui_map=ui,
                                      endpoints=[endpoint], requirements=[{"id": "FR-LOGIN", "statement": expected}])
    return case, context


def expansion(atoms=None, seq=2, assertion=False):
    if atoms is None:
        atoms = [atom("ui.fill", {"target": "email", "value": "fixture@example.test"}, "email"),
                 atom("ui.fill", {"target": "password", "value": "fixture-correct"}, "password"),
                 atom("ui.click", {"target": "login"}, "login")]
    return ProposedChange(seq, "assert.unmapped" if assertion else "perform.unmapped",
                          ("UNMAPPED_ACTION",), "", {}, "Preserve all source clauses",
                          (EvidenceReference("testcase-step", {"step_seq": seq}),), tuple(atoms))


def validate(case, context, *changes):
    return validate_resolution_proposal(ResolutionProposal(case.id, changes, ()), context, case)


def codes(result):
    return {issue.code for issue in result.issues}


def test_salonhub_action_expands_in_order_with_provenance_and_no_mutation():
    case, context = fixture()
    proposal = expansion()
    before = deepcopy((case, context, proposal))
    result = validate(case, context, proposal)
    assert result.valid_changes == (proposal,)
    validation_before = deepcopy(result)
    applied = apply_validated_resolution(case, result)
    assert not applied.issues
    assert [step.action for step in applied.case.steps] == ["ui.goto", "ui.fill", "ui.fill", "ui.click", "assert.unmapped"]
    assert [step.seq for step in applied.case.steps] == [1, 2, 3, 4, 5]
    for step in applied.case.steps[1:4]:
        provenance = json.loads(step.note.split("[resolution-expansion] ")[1])
        assert provenance["source_step"] == case.steps[1].to_dict()
        assert provenance["source_ref"] == case.source_ref
        assert provenance["traces_to"] == case.traces_to
    assert applied.case.source_quote == case.source_quote
    assert applied.applied_changes[0].to_dict()["after"]["steps"] == [a.to_dict() for a in proposal.expansion]
    assert not applied.after.executable
    assert (case, context, proposal) == before
    assert result == validation_before


@pytest.mark.parametrize("transform", [
    lambda a: a[:2],  # drop click
    lambda a: (a[1], a[0], a[2]),  # reorder
    lambda a: (*a, a[2]),  # extra click
    lambda a: (replace(a[0], args={"target": "email", "value": "invented"}), *a[1:]),
    lambda a: (replace(a[0], args={"target": "email", "value": "fixture@example.test", "extra": True}), *a[1:]),
    lambda a: (*a[:2], replace(a[2], args={"target": "imaginary"})),
    lambda a: (*a[:2], replace(a[2], evidence=(EvidenceReference("requirement", {"id": "imaginary"}),))),
])
def test_expansion_cannot_drop_reorder_add_or_fabricate(transform):
    case, context = fixture()
    proposed = replace(expansion(), expansion=tuple(transform(expansion().expansion)))
    result = validate(case, context, proposed)
    assert not result.valid_changes
    assert apply_validated_resolution(case, result).case == case


@pytest.mark.parametrize("mode,key", [("đúng", "correct_password"), ("sai", "wrong_password"), ("không trống", "non_empty_password")])
def test_salonhub_password_mode_requires_explicit_trusted_data(mode, key):
    case, context = fixture(description=f"Nhập email và mật khẩu {mode}; bấm Đăng nhập", data={})
    assert "EXPANSION_SEMANTICS_UNPROVEN" in codes(validate(case, context, expansion()))
    case, context = fixture(description=f"Nhập email và mật khẩu {mode}; bấm Đăng nhập")
    change = expansion()
    atoms = list(change.expansion)
    atoms[1] = replace(atoms[1], args={"target": "password", "value": case.test_data[key]})
    assert validate(case, context, replace(change, expansion=tuple(atoms))).valid_changes


def assertion_atoms(message, status=401):
    index = 1 if "khóa" in message else 0
    return [atom("assert.http_status", {"expected": status}, refs=(EvidenceReference("openapi", {"operation_id": "login"}),)),
            atom("assert.visible", {"target": f"message-{index}"}, f"message-{index}"),
            atom("assert.text", {"target": f"message-{index}", "expected": message, "exact": True}, f"message-{index}"),
            atom("assert.url_matches", {"pattern": "/login$"})]


@pytest.mark.parametrize("expected,message", [(NEGATIVE, "Email, Số điện thoại hoặc mật khẩu không đúng"), (LOCKED, "Tài khoản của bạn đã bị khóa.")])
def test_salonhub_compound_outcomes_require_actual_response_and_preserve_all(expected, message):
    atoms = assertion_atoms(message)
    case, context = fixture(expected=expected)
    result = validate(case, context, expansion(atoms, 3, True))
    assert "MISSING_RESPONSE" in codes(result)
    case, context = fixture(expected=expected, http=True)
    result = validate(case, context, expansion(atoms, 3, True))
    assert result.valid_changes
    assert not apply_validated_resolution(case, result).issues
    assert not validate(case, context, expansion(atoms[:-1], 3, True)).valid_changes
    assert not validate(case, context, expansion([replace(atoms[0], args={"expected": 200}), *atoms[1:]], 3, True)).valid_changes


def test_abstract_login_success_is_not_silently_dropped():
    case, context = fixture(expected=HAPPY, http=True)
    atoms = [atom("assert.url_matches", {"pattern": "/$"}),
             atom("assert.http_status", {"expected": 200}, refs=(EvidenceReference("openapi", {"operation_id": "login"}),))]
    assert "EXPANSION_SEMANTICS_UNPROVEN" in codes(validate(case, context, expansion(atoms, 3, True)))


def test_english_compound_supported_without_invented_values():
    case, context = fixture(description="fill email, fill password, click Đăng nhập")
    assert validate(case, context, expansion()).valid_changes


def test_normal_replacement_after_expansion_keeps_original_step_identity():
    case, context = fixture()
    normal = ProposedChange(3, "assert.unmapped", ("UNMAPPED_ACTION",), "assert.url_matches",
                            {"pattern": "/login$"}, "Explicit URL", (ui_ref(),))
    result = validate(case, context, expansion(), normal)
    assert len(result.valid_changes) == 2
    applied = apply_validated_resolution(case, result)
    assert applied.after.executable and applied.promoted_to_auto
    assert applied.case.steps[-1].seq == 5
    assert case.execution == "manual"


def test_duplicate_normal_and_expansion_changes_still_rejected():
    case, context = fixture()
    result = validate(case, context, expansion(), expansion())
    assert not result.valid_changes and "DUPLICATE_STEP_CHANGE" in codes(result)
    with pytest.raises(LLMResponseError, match="duplicates"):
        parse_resolution_proposal(json.dumps({"testcase_id": case.id, "changes": [expansion().to_dict()] * 2, "unresolved": []}))


def test_expansion_parser_roundtrip_and_mixed_shapes_rejected():
    case, context = fixture()
    change = expansion()
    raw = {"testcase_id": case.id, "changes": [change.to_dict()], "unresolved": []}
    assert parse_resolution_proposal(json.dumps(raw)).changes == (change,)
    raw["changes"][0]["proposed"]["action"] = "ui.click"
    with pytest.raises(LLMResponseError):
        parse_resolution_proposal(json.dumps(raw))
    prompt = build_resolution_prompt(context)
    assert "proposed" in prompt and "ordered expansion" in prompt


def test_unknown_clause_and_concrete_step_expansion_rejected():
    case, context = fixture(description=ACTION + "; create account")
    assert not validate(case, context, expansion()).valid_changes
    case, context = fixture()
    concrete = replace(expansion(), step_seq=1, from_action="ui.goto")
    assert not validate(case, context, concrete).valid_changes


@pytest.mark.parametrize("route", ["URL not /login", "URL vẫn ở /other", "URL vẫn ở /login"])
def test_assertion_route_guards_reject_negation_wrong_route_and_broad_regex(route):
    expected = "visible Đăng nhập; " + route
    case, context = fixture(expected=expected)
    atoms = [atom("assert.visible", {"target": "login"}, "login"),
             atom("assert.text", {"target": "login", "expected": "Đăng nhập", "exact": True}, "login"),
             atom("assert.url_matches", {"pattern": "/.*"})]
    assert not validate(case, context, expansion(atoms, 3, True)).valid_changes


def test_partial_proposal_and_stale_or_tampered_validation_are_safe():
    case, context = fixture(expected=HAPPY)
    result = validate(case, context, expansion(), expansion(assertion=True, seq=3))
    assert len(result.valid_changes) == 1 and len(result.rejected_changes) == 1
    assert len(apply_validated_resolution(case, result).case.steps) == 5
    changed = deepcopy(case)
    changed.steps[1].args["description"] = "different source"
    assert not apply_validated_resolution(changed, result).applied_changes
    result.valid_changes[0].expansion[0].args["value"] = "tampered"
    assert not apply_validated_resolution(case, result).applied_changes


def test_two_expansions_renumber_once_and_become_executable():
    case, context = fixture(expected="visible Đăng nhập; URL vẫn ở /login")
    assertions = [atom("assert.visible", {"target": "login"}, "login"),
                  atom("assert.text", {"target": "login", "expected": "Đăng nhập", "exact": True}, "login"),
                  atom("assert.url_matches", {"pattern": "/login$"})]
    result = validate(case, context, expansion(), expansion(assertions, 3, True))
    assert len(result.valid_changes) == 2
    applied = apply_validated_resolution(case, result)
    assert not applied.issues and applied.after.executable
    assert [s.seq for s in applied.case.steps] == list(range(1, 8))
    assert [s.kind for s in applied.case.steps[1:4]] == [StepKind.WHEN] * 3
    assert [s.kind for s in applied.case.steps[4:]] == [StepKind.THEN] * 3
    assert all('"seq": 3' in s.note for s in applied.case.steps[4:])


def test_new_runtime_blockers_reject_whole_expansion(monkeypatch):
    import qctool.executability as analyzer
    case, context = fixture()
    monkeypatch.setattr(analyzer, "UI_VERBS", analyzer.UI_VERBS - {"ui.fill"})
    result = validate(case, context, expansion())
    assert "UNSUPPORTED_ACTION" in codes(result)
    assert not result.valid_changes


def test_positive_route_cannot_override_explicit_requirement_negation():
    case, context = fixture(expected="visible Đăng nhập; URL vẫn ở /login")
    context.specification["requirements"][0]["statement"] = "URL not /login"
    atoms = [atom("assert.visible", {"target": "login"}, "login"),
             atom("assert.text", {"target": "login", "expected": "Đăng nhập", "exact": True}, "login"),
             atom("assert.url_matches", {"pattern": "/login$"})]
    result = validate(case, context, expansion(atoms, 3, True))
    assert "SPECIFICATION_CONFLICT" in codes(result)


@pytest.mark.parametrize("count", [0, 1, 9])
def test_parser_rejects_unbounded_or_empty_expansion(count):
    change = expansion().to_dict()
    change["proposed"]["steps"] = [expansion().expansion[0].to_dict()] * count
    with pytest.raises(LLMResponseError):
        parse_resolution_proposal(json.dumps({"testcase_id": "TC_SALON_AUTH_007", "changes": [change], "unresolved": []}))


def test_ambiguous_field_matching_is_unchanged():
    original = "email"
    case, context = fixture()
    page = context.observations["ui_pages"][0]
    duplicate = deepcopy(next(e for e in page["elements"] if e["test_id"] == original))
    duplicate["test_id"] = duplicate["id"] = "other-" + original
    page["elements"].append(duplicate)
    result = validate(case, context, expansion())
    assert not result.valid_changes
    assert "EXPANSION_SEMANTICS_UNPROVEN" in codes(result)


@pytest.mark.parametrize("source", [[], {}])
def test_atom_reference_wrong_source_type_is_controlled_error(source):
    change = expansion().to_dict()
    change["proposed"]["steps"][0]["evidence"][0]["source"] = source
    with pytest.raises(LLMResponseError):
        parse_resolution_proposal(json.dumps({"testcase_id": "TC_SALON_AUTH_007", "changes": [change], "unresolved": []}))


def salonhub_login_controls():
    case, context = fixture()
    page = context.observations["ui_pages"][0]
    submit = next(e for e in page["elements"] if e["test_id"] == "login")
    submit.update(test_id="login-submit-btn", id="ng_nh_p")
    nav = {"test_id": "nav-login-btn", "id": "ng_nh_p", "role": "link",
           "name": "Đăng nhập", "href": "/login"}
    page["elements"].append(nav)
    context.observations["ui_pages"].append({"url": BASE + "/", "elements": [deepcopy(nav)]})
    change = expansion()
    atoms = (*change.expansion[:2], atom("ui.click", {"target": "login-submit-btn"}, "login-submit-btn"))
    return case, context, replace(change, expansion=atoms)


def test_salonhub_unique_submit_test_id_wins_over_same_named_navigation_links():
    case, context, change = salonhub_login_controls()
    snapshot = deepcopy((case, context, change))
    result = validate(case, context, change)
    assert result.valid_changes == (change,)
    applied = apply_validated_resolution(case, result)
    assert not applied.issues
    assert applied.case.steps[3].action == "ui.click"
    assert applied.case.steps[3].args["target"] == "login-submit-btn"
    assert (case, context, change) == snapshot


@pytest.mark.parametrize("other_page", [False, True])
def test_duplicate_stable_click_test_ids_still_rejected(other_page):
    case, context, change = salonhub_login_controls()
    duplicate = deepcopy(next(e for e in context.observations["ui_pages"][0]["elements"]
                              if e.get("test_id") == "login-submit-btn"))
    duplicate["id"] = "another-submit"
    context.observations["ui_pages"][int(other_page)]["elements"].append(duplicate)
    result = validate(case, context, change)
    assert not result.valid_changes
    assert codes(result) & {"UI_EVIDENCE_NOT_FOUND", "FABRICATED_EVIDENCE"}


def test_exact_click_test_id_does_not_prove_wrong_source_meaning():
    case, context, change = salonhub_login_controls()
    submit = next(e for e in context.observations["ui_pages"][0]["elements"]
                  if e.get("test_id") == "login-submit-btn")
    submit["name"] = "Đăng ký"
    result = validate(case, context, change)
    assert not result.valid_changes
    assert "EXPANSION_SEMANTICS_UNPROVEN" in codes(result)


def test_duplicate_navigation_test_id_is_not_a_valid_alternative():
    case, context, change = salonhub_login_controls()
    last = atom("ui.click", {"target": "nav-login-btn"}, "nav-login-btn")
    result = validate(case, context, replace(change, expansion=(*change.expansion[:2], last)))
    assert not result.valid_changes
    assert "UI_EVIDENCE_NOT_FOUND" in codes(result)


def test_missing_stable_test_id_keeps_strict_name_ambiguity_rule():
    case, context = fixture()
    page = context.observations["ui_pages"][0]
    submit = next(e for e in page["elements"] if e["test_id"] == "login")
    del submit["test_id"]
    duplicate = {**submit, "id": "other-login", "role": "link"}
    page["elements"].append(duplicate)
    last = atom("ui.click", {"target": "login", "by_name": "Đăng nhập"},
                refs=(EvidenceReference("ui-map", {"page": BASE + "/login", "role": "button", "name": "Đăng nhập"}),))
    result = validate(case, context, replace(expansion(), expansion=(*expansion().expansion[:2], last)))
    assert not result.valid_changes
    assert "EXPANSION_SEMANTICS_UNPROVEN" in codes(result)


def test_different_click_name_in_by_name_is_still_rejected():
    case, context, change = salonhub_login_controls()
    last = replace(change.expansion[-1], args={"target": "login-submit-btn", "by_name": "Đăng ký"})
    result = validate(case, context, replace(change, expansion=(*change.expansion[:2], last)))
    assert not result.valid_changes
    assert "UI_EVIDENCE_NOT_FOUND" in codes(result)


def test_name_and_role_citation_cannot_hide_duplicate_test_id():
    case, context, change = salonhub_login_controls()
    page = context.observations['ui_pages'][0]
    duplicate = deepcopy(next(e for e in page['elements'] if e.get('test_id') == 'login-submit-btn'))
    duplicate.update(name='Other submit', role='link', id='another-submit')
    page['elements'].append(duplicate)
    last = replace(change.expansion[-1], evidence=(EvidenceReference('ui-map', {
        'page': BASE + '/login', 'test_id': 'login-submit-btn', 'role': 'button', 'name': 'Đăng nhập'}),))
    result = validate(case, context, replace(change, expansion=(*change.expansion[:2], last)))
    assert not result.valid_changes
    assert 'UI_EVIDENCE_NOT_FOUND' in codes(result)

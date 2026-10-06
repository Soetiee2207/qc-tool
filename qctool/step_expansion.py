"""Narrow source-clause grammar and detached step replacement mechanics.

Unknown text is never discarded. These rules describe explicit source meaning;
UI observations supply locators only, never expected business behavior.
"""

from copy import deepcopy
import json
import re

from .generate.mapper import RE_CLICK, RE_FILL, RE_HTTP
from .llm_resolution import ProposedChange
from .testcase import Step, StepKind, TestCase
from .test_fixtures import FixtureStore, trusted_value


def expected_expansion(step: Step, test_data: dict, *, min_atoms: int = 2,
                       fixture_store: FixtureStore | None = None, allow_captured_login: bool = False) -> list[dict] | None:
    text = step.args.get("description" if step.action == "perform.unmapped" else "expected")
    if not isinstance(text, str) or not text.strip():
        return None
    if step.action == "perform.unmapped" and step.kind == StepKind.GIVEN:
        empty = re.fullmatch(r"Phiên anonymous ở (/login); cả hai ô email và mật khẩu trống", text.strip())
        if empty:
            return [{"action": "ui.session", "args": {"mode": "anonymous"}},
                    {"action": "ui.goto", "args": {"url": empty[1]}, "precondition_route": empty[1]},
                    {"action": "assert.value", "hint": "email", "empty_input": True,
                     "args": {"expected": "^$", "operator": "matches"}},
                    {"action": "assert.value", "hint": "password", "empty_input": True,
                     "args": {"expected": "^$", "operator": "matches"}}]
        # Exact SalonHub source form only. Every non-runtime clause must be
        # proven against config facts and provisioned aliases, never discarded.
        precondition = re.fullmatch(
            r"Phiên anonymous ở (/[A-Za-z0-9_./?=&-]*); tài khoản customer đang hoạt động "
            r"và mật khẩu đúng do người vận hành cung cấp", text.strip())
        if precondition:
            if fixture_store is None or not fixture_store.proves_account_precondition(
                test_data, role="customer", account_state="active"):
                return None
            atoms = [{"action": "ui.session", "args": {"mode": "anonymous"}},
                     {"action": "ui.goto", "args": {"url": precondition[1]},
                      "precondition_route": precondition[1]}]
            return atoms if min_atoms <= len(atoms) <= 8 else None
    if (allow_captured_login and step.action == "assert.unmapped" and text.strip() ==
            "Đăng nhập thành công; URL chuyển tới /; POST /api/auth/login trả 200 với success=true"):
        # This exact contract expresses success with ALL explicit outcomes.
        # Conjunctive checks have no intervening actions; no clause is dropped.
        operation = ("POST", "/api/auth/login")
        return [{"action": "assert.http_status", "args": {"expected": 200}, "operation": operation},
                {"action": "assert.json_field", "args": {"path": "$.success", "expected": True}, "operation": operation},
                {"action": "assert.url_matches", "args": {"pattern": "/$"}, "route": "/"}]
    clauses = [part.strip() for part in text.split(";")]
    if re.fullmatch(r"fill email,\s*fill password,\s*click .+", text, re.I):
        clauses = [part.strip() for part in text.split(",")]
    result = []
    for clause in clauses:
        if not clause:
            return None
        if step.action == "perform.unmapped":
            pair = re.fullmatch(r"Nhập email và mật khẩu (đúng|sai|không trống)", clause, re.I)
            if pair:
                key = {"đúng": "correct_password", "sai": "wrong_password",
                       "không trống": "non_empty_password"}[pair[1].lower()]
                result.extend([{"action": "ui.fill", "hint": "email", "data_key": "email"},
                               {"action": "ui.fill", "hint": "password", "data_key": key}])
            elif match := re.fullmatch(r"fill (email|password)", clause, re.I):
                key = match[1].lower()
                result.append({"action": "ui.fill", "hint": key, "data_key": key})
            elif match := RE_FILL.fullmatch(clause):
                # Existing mapper syntax explicitly names the value and field.
                result.append({"action": "ui.fill", "hint": match[2], "value": match[1]})
            elif match := RE_CLICK.fullmatch(clause):
                result.append({"action": "ui.click", "hint": match[1]})
            elif match := RE_HTTP.fullmatch(clause):
                result.append({"action": "http.request", "args": {
                    "method": match[1].upper(), "path": match[2]}})
            else:
                return None
        elif step.action == "assert.unmapped":
            if match := re.fullmatch(r"URL\s+(?:chuyển tới|vẫn ở|==)\s+(/\S*)", clause, re.I):
                result.append({"action": "assert.url_matches", "args": {
                    "pattern": re.escape(match[1]) + "$"}, "route": match[1]})
            elif match := re.fullmatch(r"không gửi (POST) (/api/auth/login)", clause):
                result.append({"action": "assert.json_field", "args": {
                    "path": "$.request_count", "expected": 0}, "no_request": (match[1], match[2])})
            elif match := re.fullmatch(r"(GET|POST|PUT|PATCH|DELETE)\s+(/\S+)\s+trả\s+([1-5]\d\d)(?:\s+với\s+success=(true|false))?", clause, re.I):
                operation = (match[1].upper(), match[2])
                result.append({"action": "assert.http_status", "args": {"expected": int(match[3])},
                               "operation": operation})
                if match[4]:
                    result.append({"action": "assert.json_field", "args": {
                        "path": "$.success", "expected": match[4].lower() == "true"},
                        "operation": operation})
            elif match := re.fullmatch(r"(?:hiển thị|visible)\s+(.+)", clause, re.I):
                # Displayed message requires both visibility and exact text.
                result.extend([{"action": "assert.visible", "hint": match[1]},
                               {"action": "assert.text", "hint": match[1],
                                "args": {"expected": match[1], "exact": True}}])
            elif match := re.fullmatch(r"not visible\s+(.+)", clause, re.I):
                result.append({"action": "assert.not_visible", "hint": match[1]})
            else:
                return None
        else:
            return None
    for item in result:
        if "data_key" in item:
            value = trusted_value(test_data, item["data_key"])
            if not isinstance(value, str) or not value:
                return None
            item["value"] = value
    return result if min_atoms <= len(result) <= 8 else None


def candidate_with_changes(case: TestCase, changes: list[ProposedChange] | tuple[ProposedChange, ...]) -> tuple[TestCase, dict[int, int]]:
    """Apply exact payloads privately; identities always refer to original sequences.

    Renumber only when expanding. The origin map makes gap comparisons independent
    of renumbering; every inserted step carries its original source in its note.
    """
    detached = deepcopy(case)
    by_seq = {change.step_seq: change for change in changes}
    renumber = any(change.expansion for change in changes)
    out, origins = [], {}
    for original in case.steps:
        change = by_seq.get(original.seq)
        if change and change.expansion:
            steps = []
            for index, atom in enumerate(change.expansion, 1):
                source = {"type": "validated-llm-expansion", "testcase_id": case.id,
                          "source_step": original.to_dict(), "source_ref": case.source_ref,
                          "source_quote": case.source_quote, "traces_to": case.traces_to,
                          "atomic_index": index, "reason": change.reason,
                          "evidence": [ref.to_dict() for ref in atom.evidence]}
                note = original.note + "\n[resolution-expansion] " + json.dumps(source, ensure_ascii=False, sort_keys=True)
                steps.append(Step(original.seq, original.kind, atom.action, deepcopy(atom.args), note))
        else:
            item = deepcopy(original)
            if change:
                item.action, item.args = change.action, deepcopy(change.args)
            steps = [item]
        for item in steps:
            if renumber:
                item.seq = len(out) + 1
            origins[item.seq] = original.seq
            out.append(item)
    detached.steps = out
    return detached, origins

"""Exact source proofs for empty-login clauses; observations never define outcomes."""
import json
import re
from urllib.parse import urlsplit

from .response_capture import origin_of, validate_capture


SEMANTIC_GAP = "SEMANTIC_GROUNDING_MISMATCH"


def empty_login_requirement(case, context):
    if context is None:
        return None
    matches = [req for req in context.specification.get("requirements", [])
               if req.get("id") in case.traces_to
               and req.get("given") == "Phiên anonymous ở /login; cả hai ô email và mật khẩu trống"
               and req.get("when") == "Bấm Đăng nhập"
               and req.get("then") == "Hiển thị Vui lòng điền đầy đủ thông tin; không gửi POST /api/auth/login; URL vẫn ở /login"]
    return matches[0] if len(matches) == 1 else None


def source_clause(step, requirement):
    """Require preserved generator provenance, not a target's display name."""
    if not isinstance(step.note, str):
        return None
    source = []
    mapped = []
    for line in step.note.splitlines():
        for marker, records in (("[source-clause] ", source), ("[mapper-clause] ", mapped)):
            if line.startswith(marker):
                try:
                    record = json.loads(line[len(marker):])
                    if not isinstance(record, dict):
                        return None
                    records.append(record)
                except (ValueError, TypeError):
                    return None
    field = step.kind.value
    if not any(record.get("requirement_id") == requirement["id"]
               and record.get("field") == field
               and record.get("text") == requirement.get(field) for record in source):
        return None
    clause = mapped[-1].get("text") if mapped else requirement.get(field)
    if clause not in [part.strip() for part in requirement.get(field, "").split(";")]:
        return None
    return clause


def login_page(context):
    pages = [p for p in context.observations.get("ui_pages", [])
             if urlsplit(p.get("url", "")).path == "/login"]
    return pages[0] if len(pages) == 1 else None


def unique_element(page, predicate):
    if page is None:
        return None
    elements = [e for e in page.get("elements", []) if predicate(e)]
    if len(elements) != 1 or not elements[0].get("test_id"):
        return None
    identifier = elements[0]["test_id"]
    if sum(e.get("test_id") == identifier for e in page["elements"]) != 1:
        return None
    return elements[0]


def click_arguments(step, case, context):
    req = empty_login_requirement(case, context)
    if req is None or source_clause(step, req) != req["when"]:
        return None
    page = login_page(context)
    button = unique_element(page, lambda e: e.get("role") == "button" and e.get("name") == "Đăng nhập")
    operations = [op for op in context.interface_contract.get("api_operations", [])
                  if (op.get("method"), op.get("path")) == ("POST", "/api/auth/login")]
    if button is None or len(operations) != 1:
        return None
    try:
        origins = {origin_of(server) for server in operations[0].get("servers", [])}
    except (ValueError, TypeError):
        return None
    if len(origins) != 1:
        return None
    capture = {"method": "POST", "path": "/api/auth/login", "origin": origins.pop(),
               "save_as": "login_requests", "timeout_ms": 2000}
    try:
        validate_capture(capture)
    except ValueError:
        return None
    args = {"target": button["test_id"], "capture_requests": capture}
    if "by_name" in step.args:
        args["by_name"] = button["name"]
    return args


def semantic_repair_arguments(step, case, context):
    req = empty_login_requirement(case, context)
    if req is None:
        return None
    clause = source_clause(step, req)
    if step.action == "ui.click" and clause == req["when"]:
        return click_arguments(step, case, context)
    if step.action == "assert.url_matches" and clause == "URL vẫn ở /login" and login_page(context):
        return {"pattern": re.escape("/login") + "$"}
    return None


def semantic_mismatches(case, context):
    result = []
    for step in case.steps:
        desired = semantic_repair_arguments(step, case, context)
        req = empty_login_requirement(case, context)
        page = login_page(context)
        button = unique_element(page, lambda e: e.get("role") == "button" and e.get("name") == "Đăng nhập")
        wrong_control = (req is not None and step.action == "ui.click" and
                         source_clause(step, req) == req["when"] and button is not None and
                         step.args.get("target") != button["test_id"])
        if wrong_control or desired is not None and step.args != desired:
            result.append((step.seq, "Mapped arguments do not preserve the exact source login clause."))
    return result


def observed_validation(context, requirement):
    page = login_page(context)
    alert = unique_element(page, lambda e: e.get('role') == 'alert'
                           and e.get('name') == 'Vui lòng điền đầy đủ thông tin')
    button = unique_element(page, lambda e: e.get("role") == "button" and e.get("name") == requirement["when"].removeprefix("Bấm ")) if page else None
    operations = [op for op in context.interface_contract.get("api_operations", [])
                  if (op.get("method"), op.get("path")) == ("POST", "/api/auth/login")]
    if not alert or not button or len(operations) != 1:
        return None
    try:
        origins = {origin_of(server) for server in operations[0].get("servers", [])}
    except (ValueError, TypeError):
        return None
    for exploration in page.get('explorations', []):
        for action in exploration.get('action_observations', []):
            selector = action.get('selector', {})
            if (action.get('action') == 'ui.click'
                    and action.get('target') == button['test_id']
                    and action.get('credential_inputs_empty') is True
                    and type(action.get('request_count')) is int
                    and action['request_count'] >= 0
                    and selector.get('origin') in origins
                    and type(selector.get('window_ms')) is int
                    and 0 < selector['window_ms'] <= 2000
                    and urlsplit(action.get('final_url', '')).path == '/login'
                    and (selector.get('method'), selector.get('path')) == ('POST', '/api/auth/login')
                    and any(e.get('test_id') == alert['test_id'] and e.get('role') == 'alert'
                            and e.get('name') == alert['name'] for e in action.get('page', {}).get('elements', []))):
                return alert
    return None

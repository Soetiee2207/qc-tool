"""Exact empty-form source proofs; observations never define outcomes."""
import json
import re
from urllib.parse import urlsplit

from .response_capture import origin_of, validate_capture


SEMANTIC_GAP = "SEMANTIC_GROUNDING_MISMATCH"


def empty_login_requirement(case, context):
    if context is None:
        return None
    matches = [req for req in context.specification.get("requirements", [])
               if req.get("id") in case.traces_to and empty_form_contract(req) is not None]
    return matches[0] if len(matches) == 1 else None


def empty_form_contract(requirement):
    """Exact closed grammar; source supplies every route/message/operation."""
    given = re.fullmatch(r"Phiên anonymous ở (/[A-Za-z0-9_./-]*); cả hai ô email và mật khẩu trống", requirement.get("given") or "")
    when = re.fullmatch(r"Bấm (.+)", requirement.get("when") or "")
    outcome = re.fullmatch(r"Hiển thị ([^;]+); không gửi (POST) (/[A-Za-z0-9_./-]+); URL vẫn ở (/[A-Za-z0-9_./-]*)", requirement.get("then") or "")
    if not given or not when or not outcome or given[1] != outcome[4]:
        return None
    from .exploration_actions import SAFE_BUTTONS, forbidden
    from .ui.crawl import _norm
    if _norm(when[1]) not in SAFE_BUTTONS or forbidden(given[1]) or forbidden(outcome[3]):
        return None
    return {"route": given[1], "button": when[1], "message": outcome[1],
            "method": outcome[2], "path": outcome[3]}


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
    if not any((record.get("requirement_id") or record.get("source", {}).get("source_id")) == requirement["id"]
               and record.get("field") == field
               and record.get("text") == requirement.get(field) for record in source):
        return None
    clause = mapped[-1].get("text") if mapped else requirement.get(field)
    if clause != requirement.get(field) and clause not in [part.strip() for part in requirement.get(field, "").split(";")]:
        return None
    return clause


def login_page(context, requirement=None):
    if requirement is None:
        return None
    route = empty_form_contract(requirement)["route"]
    pages = [p for p in context.observations.get("ui_pages", [])
             if urlsplit(p.get("url", "")).path == route]
    if len(pages) == 1:
        return pages[0]
    # Fresh page-only inspection can coexist with a prior validated action
    # state. Select only a uniquely action-bound state proving this exact source
    # form; never collapse unrelated snapshots or choose by collection order.
    contract = empty_form_contract(requirement)
    supported = [page for page in pages if page.get("state_id") and any(
        state.get("valid") and state.get("state_id") == page["state_id"]
        for state in context.observations.get("page_states", [])) and any(
            e.get("role") == "alert" and e.get("name") == contract["message"]
            for e in page.get("elements", [])) and any(
                a.get("action") == "ui.click" and a.get("credential_inputs_empty") is True
                and (a.get("selector", {}).get("method"), a.get("selector", {}).get("path"))
                    == (contract["method"], contract["path"])
                for exploration in page.get("explorations", [])
                for a in exploration.get("action_observations", []))]
    return supported[0] if len(supported) == 1 else None


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
    page = login_page(context, req)
    button = unique_element(page, lambda e: e.get("role") == "button" and e.get("name") == empty_form_contract(req)["button"])
    operations = [op for op in context.interface_contract.get("api_operations", [])
                  if (op.get("method"), op.get("path")) == (empty_form_contract(req)["method"], empty_form_contract(req)["path"])]
    if button is None or len(operations) != 1:
        return None
    try:
        origins = {origin_of(server) for server in operations[0].get("servers", [])}
    except (ValueError, TypeError):
        return None
    if len(origins) != 1:
        return None
    capture = {"method": empty_form_contract(req)["method"], "path": empty_form_contract(req)["path"], "origin": origins.pop(),
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
    if step.action in {"ui.click", "perform.unmapped"} and clause == req["when"]:
        return click_arguments(step, case, context)
    if step.action == "assert.url_matches" and clause == "URL vẫn ở " + empty_form_contract(req)["route"] and login_page(context, req):
        return {"pattern": re.escape(empty_form_contract(req)["route"]) + "$"}
    return None


def semantic_mismatches(case, context):
    result = []
    for step in case.steps:
        if step.action in case.UNMAPPED_ACTIONS:
            continue
        desired = semantic_repair_arguments(step, case, context)
        req = empty_login_requirement(case, context)
        page = login_page(context, req)
        button = unique_element(page, lambda e: e.get("role") == "button" and e.get("name") == empty_form_contract(req)["button"]) if req else None
        wrong_control = (req is not None and step.action == "ui.click" and
                         source_clause(step, req) == req["when"] and button is not None and
                         step.args.get("target") != button["test_id"])
        if wrong_control or desired is not None and step.args != desired:
            result.append((step.seq, "Mapped arguments do not preserve the exact source login clause."))
    return result


def observed_validation(context, requirement):
    page = login_page(context, requirement)
    contract = empty_form_contract(requirement)
    alert = unique_element(page, lambda e: e.get('role') == 'alert'
                           and e.get('name') == contract['message'])
    button = unique_element(page, lambda e: e.get("role") == "button" and e.get("name") == requirement["when"].removeprefix("Bấm ")) if page else None
    operations = [op for op in context.interface_contract.get("api_operations", [])
                  if (op.get("method"), op.get("path")) == (contract["method"], contract["path"])]
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
                    and urlsplit(action.get('final_url', '')).path == contract['route']
                    and (selector.get('method'), selector.get('path')) == (contract['method'], contract['path'])
                    and any(e.get('test_id') == alert['test_id'] and e.get('role') == 'alert'
                            and e.get('name') == alert['name'] for e in action.get('page', {}).get('elements', []))):
                return alert
    return None

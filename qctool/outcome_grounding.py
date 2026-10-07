"""Exact source → operation/action → outcome proofs, without model/browser calls.

Contracts authorize response selectors, never expected response values. Page
states supply observations/locators, never the business expectation.
"""

from .response_capture import origin_of, validate_capture
from .source_grounding import source_clause
from .testcase import Step, StepKind


def outcome_requirement(step, case, context):
    matches = [r for r in context.specification.get("requirements", [])
               if r.get("id") in case.traces_to
               and isinstance(r.get("then"), str) and r["then"]
               and source_clause(step, r) == r.get("then")]
    return matches[0] if len(matches) == 1 else None


def response_binding(case, step_seq, method, path, operation, source=None):
    """Select the last actual writer, not an older matching response alias.

    A planned capture is a runtime response source, not an observed successful
    response. The runner still evaluates status/body when it executes the case.
    """
    writers = []
    for step in case.steps:
        if step.seq >= step_seq:
            continue
        if step.action == "http.request":
            selector = step.args
        elif step.action == "ui.click" and ("capture_response" in step.args or "capture_requests" in step.args):
            selector = step.args.get("capture_response") or step.args["capture_requests"]
        else:
            continue
        if not isinstance(selector, dict):
            return None
        name = selector.get("save_as", "res")
        if source is None or source == name:
            writers.append((step, selector, name))
    if not writers:
        return None
    writer, selector, name = writers[-1]
    if writer.action == "ui.click" and "capture_requests" in writer.args:
        return None  # A request counter cannot stand in for a response body.
    if not isinstance(selector.get("method"), str) or (selector["method"].upper(), selector.get("path")) != (method, path):
        return None
    try:
        if writer.action == "ui.click":
            validate_capture(selector)
            if selector["origin"] not in {origin_of(s) for s in operation.get("servers", [])}:
                return None
        elif selector.get("base") is not None and selector["base"] not in operation.get("servers", []):
            return None
    except (ValueError, TypeError, KeyError):
        return None
    return writer, name


def outcome_state(step, case, context, state_id=None, *, fixture_store=None):
    """Require the current, complete, approved action chain for this source.

    Historical states can still ground actions. Outcome assertions require the
    final state after ALL source actions; stale/intermediate states cannot prove
    an outcome just because an identical element happened to be present there.
    """
    requirement = outcome_requirement(step, case, context)
    current = context.observations.get("current_state_id")
    if requirement is None or not current or state_id not in (None, current):
        return None
    states = context.observations.get("page_states", [])
    def unique(key):
        found = [s for s in states if s.get("state_id") == key]
        return found[0] if len(found) == 1 else None
    final = unique(current)
    if not final or not final.get("valid") or final.get("testcase_id") != case.id:
        return None
    bindings = final.get("validated_actions", [])
    if not 0 < len(bindings) <= 5 or final.get("triggering_action") != len(bindings) - 1:
        return None
    from .exploration_actions import _meanings
    try:
        from .semantic_ir import source_meanings
        meanings = source_meanings(requirement["when"], 'when', context, fixture_store) or _meanings(Step(1, StepKind.WHEN, "perform.unmapped",
                                 {"description": requirement["when"]}), case.test_data)
    except (ValueError, TypeError, KeyError):
        return None
    clauses = {requirement["when"], *[m["source_clause"] for m in meanings]}
    actions = [s for s in case.steps if s.kind == StepKind.WHEN
               and source_clause(s, requirement) in clauses]
    if len(meanings) != len(bindings) or len(actions) != len(bindings):
        return None
    # Do not resolve assertions until the actual testcase performs this chain.
    outcomes = [s for s in case.steps if s.kind == StepKind.THEN
                and s.action == "assert.unmapped" and source_clause(s, requirement) == requirement["then"]]
    if len(outcomes) != 1 or any(action.seq >= outcomes[0].seq for action in actions):
        return None
    state = final
    for index in reversed(range(len(bindings))):
        binding, meaning, action = bindings[index], meanings[index], actions[index]
        previous = unique(state.get("from_state_id"))
        if (not previous or not previous.get("valid")
                or state.get("testcase_id") != case.id or previous.get("testcase_id") != case.id
                or state.get("source", {}).get("type") != "playwright_exploration"
                or not state.get("source", {}).get("observed_at")
                or binding.get("source") != "validated_action"
                or requirement["id"] not in binding.get("requirement_ids", [])
                or binding.get("action_index") != index or state.get("triggering_action") != index
                or state.get("source_step_seq") != binding.get("step_seq")
                or state.get("source_clause") != meaning["source_clause"]
                or binding.get("source_clause") != meaning["source_clause"]
                or state.get("request") != final.get("request")
                or previous.get("request") != final.get("request")
                or state.get("session") != final.get("session")
                or previous.get("session") != final.get("session")
                or previous.get("page", {}).get("url") != binding.get("page")
                or state.get("page", {}).get("url") != binding.get("expected_url")
                or action.action != meaning["action"] or binding.get("action") != action.action
                or action.args.get("target") != binding.get("target")):
            return None
        elements = [e for e in previous["page"].get("elements", [])
                    if e.get("test_id") == binding["target"]]
        if (len(elements) != 1 or elements[0].get("name") != binding.get("name")
                or elements[0].get("role") != binding.get("role")):
            return None
        from .ui.crawl import _norm
        from .semantic_ir import element_matches
        if not (element_matches(elements[0], meaning) if meaning.get('semantic') else
                _norm(elements[0].get("name", "")) == _norm(meaning.get("hint", ""))):
            return None
        if "value" in meaning and (action.args.get("value") != meaning["value"]
                                   or binding.get("value") != meaning["value"]):
            return None
        state = previous
    if state.get("triggering_action") is not None:
        return None
    if state.get("page", {}).get("url") != final.get("request", {}).get("target"):
        return None
    from .proposal_validation import _same_route
    navigation = [s for s in case.steps if s.seq < actions[0].seq and s.action == "ui.goto"]
    if not navigation or not _same_route(navigation[-1].args.get("url", ""), state["page"]["url"]):
        return None
    return final

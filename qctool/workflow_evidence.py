"""Outcome-complete evidence requests from independently validated source semantics.

These hints are not action approvals. The existing plan and proposal validators
recheck source, locators, values, operation identities and the full state chain.
"""
from urllib.parse import urlsplit


def requires_state(requirement, context, store=None):
    from .semantic_ir import source_meanings
    meanings = source_meanings((requirement.get('when') or ''), 'when', context, store) or ()
    return len(meanings) > 1 and any(m['action'] == 'ui.goto' for m in meanings)


def outcome_needs(case, context, store=None):
    from .semantic_ir import meanings_for_step, source_meanings, element_matches, observed_witnesses
    from .outcome_grounding import outcome_requirement, outcome_state
    result = []
    for gap in context.gaps:
        step = next((s for s in case.steps if s.seq == gap.step_seq and s.action == 'assert.unmapped'), None)
        if step is None:
            continue
        req = outcome_requirement(step, case, context)
        if req is None:
            continue
        meanings = meanings_for_step(step, context, store) or source_meanings(req['then'], 'then', context, store)
        if not meanings:
            continue
        state = outcome_state(step, case, context, fixture_store=store)
        routes = [m['route'] for m in meanings if m.get('route')]
        pages = ([state['page']] if state else [p for p in context.observations.get('ui_pages', [])
                 if routes and urlsplit(p['url']).path in routes])
        for index, meaning in enumerate(meanings):
            kind = None
            if requires_state(req, context, store) and state is None:
                kind = 'WORKFLOW_STATE'
            elif meaning.get('hint'):
                matches = observed_witnesses([(p, e) for p in pages for e in p.get('elements', [])
                                              if element_matches(e, meaning)], meaning['action'], state_proven=state is not None)
                if len(matches) != 1:
                    kind = 'UI_STATE'
            elif meaning.get('route') and not any(urlsplit(p['url']).path == meaning['route'] for p in pages):
                kind = 'UI_STATE'
            elif meaning.get('no_request'):
                kind = 'NETWORK_BINDING'
            if kind:
                result.append({'kind': kind, 'step_seq': step.seq, 'gap_code': gap.code,
                               'outcome_index': index, 'source_clause': meaning.get('source_clause'),
                               'requirement_id': req['id'], 'meaning': meaning,
                               'destination_routes': routes})
    # Resolved source steps cannot retain old rejection requests forever.
    current = {(g.step_seq, g.code) for g in context.gaps}
    for need in context.evidence_needs:
        if 'outcome_index' not in need and (need.get('step_seq'), need.get('gap_code')) in current and need not in result:
            result.append(need)
    return tuple(result)


def workflow_candidates(context, store=None):
    """Show the exact complete source prefix and current step identities to a planner.

    A page/control absent from evidence produces no guessed target. A goto can
    inspect an unseen route only because that ordered source clause declares it.
    """
    from .semantic_ir import source_meanings, element_matches, literals
    from .exploration_actions import workflow_prerequisites
    from .source_grounding import source_clause
    from .testcase import Step, StepKind
    steps = [Step(s['seq'], StepKind(s['kind']), s['action'], s['args'], s.get('note', '')) for s in context.testcase['steps']]
    candidates = []
    for req in context.specification.get('requirements', []):
        outcomes = [s for s in steps if s.action == 'assert.unmapped' and source_clause(s, req) == req.get('then')]
        meanings = source_meanings((req.get('when') or ''), 'when', context, store)
        if len(outcomes) != 1 or not meanings or len(meanings) > 5:
            continue
        concrete = [s for s in steps if s.kind.value == 'when' and source_clause(s, req) == req.get('when')]
        unresolved = [s for s in concrete if s.action == 'perform.unmapped']
        if unresolved:
            if len(unresolved) != 1 or len(concrete) != 1:
                continue
            source_steps = [unresolved[0]] * len(meanings)
        elif len(concrete) == len(meanings):
            source_steps = concrete
        else:
            continue
        entry = next((s.args['url'] for s in reversed(steps) if s.action == 'ui.goto' and s.seq < source_steps[0].seq), None)
        if not entry:
            continue
        current = entry; actions = []; possible = True
        for i, (step, meaning) in enumerate(zip(source_steps, meanings)):
            action = {'action': meaning['action'], 'step_seq': step.seq, 'page': current}
            if meaning['action'] == 'ui.goto':
                action['url'] = meaning['args']['url']
                current = action['url']
                if i == len(meanings)-1:
                    final = {m['route'] for m in source_meanings((req.get('then') or ''), 'then', context, store) or () if m.get('route')}
                    if len(final) == 1:
                        current = final.pop(); action['expected_url'] = current
            else:
                pages = [p for p in context.observations.get('ui_pages', []) if urlsplit(p['url']).path == urlsplit(current).path]
                matches = [(p, e) for p in pages for e in p.get('elements', []) if element_matches(e, meaning)]
                # Identical snapshots are collapsed, conflicting controls retained.
                unique = []
                for _, e in matches:
                    if e not in unique: unique.append(e)
                if len(unique) != 1 or not unique[0].get('test_id'):
                    possible = False; break
                action['target'] = unique[0]['test_id']
                if 'value' in meaning: action['value'] = meaning['value']
                if meaning['action'] == 'ui.click':
                    prefix_text = ';'.join(m['source_clause'] for m in meanings[:i+1])
                    prefixes = [p for p in workflow_prerequisites([req], context)
                                if [c.strip() for c in p['when'].split(';')] == [c.strip() for c in prefix_text.split(';')]]
                    from .semantic_ir import SemanticAtom, _safe_authorized
                    destinations = {route for p in prefixes for clause in p['then'].split(';')
                                    for route in literals(clause) if _safe_authorized(SemanticAtom('url', {'route': route}),
                                        {'field': 'then', 'source_text': clause.strip()}, context, store)}
                    if len(destinations) > 1: possible = False; break
                    if destinations:
                        current = destinations.pop(); action['expected_url'] = current
            actions.append(action)
        if possible:
            candidates.append({'target': entry, 'session': 'anonymous', 'actions': actions,
                               'purposes': [{'gap_code': g.code, 'step_seq': g.step_seq,
                                             'reason': 'Observe all source outcomes after the complete authorized workflow', 'intent': 'inspect_page'}
                                            for g in context.gaps if g.step_seq == outcomes[0].seq],
                               'requirement_id': req['id']})
    return candidates


def incomplete_outcomes(case, context):
    """A mapped subset cannot erase source outcomes already normalized in full.

    This check only rejects missing action obligations; it never authorizes a
    repair of mapped source or attempts to infer an absent expected meaning.
    """
    from collections import Counter
    from .semantic_ir import source_meanings
    from .source_grounding import source_clause
    missing = []
    for req in context.specification.get('requirements', []):
        if req.get('id') not in case.traces_to:
            continue
        meanings = source_meanings((req.get('then') or ''), 'then', context)
        steps = [s for s in case.steps if s.kind.value == 'then' and source_clause(s, req) == req.get('then')]
        if not meanings or not steps or any(s.action == 'assert.unmapped' for s in steps):
            continue
        expected = Counter(m['action'] for m in meanings)
        actual = Counter(s.action for s in steps)
        if expected - actual:
            missing.append((steps[0].seq, 'Mapped source outcome omits required assertion atoms: ' +
                            ', '.join(sorted((expected - actual).elements()))))
    return missing

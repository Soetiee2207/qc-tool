"""Read-only capability routing, never approval of a repair or browser action.

Source grammar and selected evidence identify missing inputs. Parsers and
validators remain the authorities for every proposed change and exploration.
"""
from dataclasses import dataclass

from .executability import ExecutionGap
from .exploration_plan import _grounded_targets
from .generate.mapper import RE_NAMED_VISIBLE, RE_NAMED_HIDDEN
from .step_expansion import expected_expansion
from .source_grounding import empty_login_requirement, observed_validation
from .testcase import StepKind
from .ui.crawl import _norm


@dataclass(frozen=True)
class GapClassification:
    gap: ExecutionGap
    classification: str
    reason: str


@dataclass(frozen=True)
class GapRoutingDecision:
    gap_classification: tuple[GapClassification, ...]
    selected_capability: str
    reason: str
    llm_call_skipped: tuple[str, ...]


def route_gaps(case, context, *, base_url=None, resolved_gaps=(), blocked=False, fixture_store=None):
    """Choose one useful capability; this decision never approves exploration.

    Post-action evidence takes priority over mapping, so a workflow is inspected
    before asking a model to map its unavailable outcomes. A runtime response
    capture supported by an exact API contract does not require a live response
    observation first. Routing is conservative and does not certify semantics.
    """
    entries = [GapClassification(g, 'DETERMINISTIC', 'Resolved by the existing deterministic resolver.')
               for g in resolved_gaps]
    if blocked:
        entries.extend(GapClassification(g, 'BLOCKED', 'Trusted test-data preparation is unavailable.')
                       for g in context.gaps)
        return GapRoutingDecision(tuple(entries), 'none', 'Test-data preparation blocks both model capabilities.',
                                  ('resolution', 'exploration'))
    elements = [e for p in context.observations.get('ui_pages', []) for e in p.get('elements', [])]
    operations = context.interface_contract.get('api_operations', [])
    can_inspect = bool(base_url and _grounded_targets(case, context, base_url))
    empty = empty_login_requirement(case, context)
    primary = any(g.step_seq is not None for g in context.gaps)
    normalization_required = False
    for gap in context.gaps:
        step = next((s for s in case.steps if s.seq == gap.step_seq), None)
        classification, reason = 'BLOCKED', 'No deterministically supported progress path.'
        if gap.code in {'MANUAL_EXECUTION', 'MISSING_ASSERTION'} and primary:
            # These are consequences of the unresolved clauses, not separate calls.
            classification, reason = 'BLOCKED', 'Derived blocker; route the source step gaps first.'
        elif gap.code == 'SEMANTIC_GROUNDING_MISMATCH':
            classification, reason = 'NEEDS_RESOLUTION', 'Selected source/control evidence identifies a mapping mismatch.'
        elif gap.code == 'UNMAPPED_ACTION' and step and str(step.args.get('description', step.args.get('expected', ''))).strip().upper() in {'', 'TBC'}:
            reason = 'The source clause has no explicit business meaning.'
        elif step and gap.code in {'MISSING_LOCATOR', 'UNMAPPED_ACTION'}:
            from .semantic_ir import meanings_for_step
            atoms = meanings_for_step(step, context, fixture_store) or expected_expansion(step, case.test_data, min_atoms=1)
            if empty and step.kind == StepKind.THEN and not observed_validation(context, empty):
                classification, reason = 'NEEDS_EXPLORATION', 'Explicit source outcome requires a post-action alert and bounded request observation.'
            elif atoms:
                from .semantic_ir import element_matches
                missing_ui = any(a.get('hint') and not any(element_matches(e, a) for e in elements)
                                 for a in atoms)
                missing_operation = any(a.get('operation') and not any(
                    (op.get('method'), op.get('path')) == a['operation'] for op in operations) for a in atoms)
                missing_counter = any(a.get('no_request') for a in atoms) and (not empty or not observed_validation(context, empty))
                if missing_operation:
                    reason = 'Source operation is absent from the selected interface contract.'
                elif missing_ui or missing_counter:
                    classification, reason = 'NEEDS_EXPLORATION', 'Explicit source clause lacks selected UI or post-action observation evidence.'
                else:
                    classification, reason = 'NEEDS_RESOLUTION', 'Selected evidence supports the explicit source atoms; mapping remains.'
            elif gap.code == 'MISSING_LOCATOR':
                classification = 'NEEDS_RESOLUTION' if elements else 'NEEDS_EXPLORATION'
                reason = 'Locator arguments need selected control evidence.'
            elif (context.observations.get('ui_pages') or operations) and step.action in {'perform.unmapped', 'assert.unmapped'}:
                # Retain the existing resolution boundary for single prose actions
                # with selected controls. Unknown expectations are never inferred.
                classification, reason = 'NEEDS_RESOLUTION', 'Source action and selected controls are available to the existing validator.'
            elif not elements and (step.action == 'perform.unmapped' or
                                  RE_NAMED_VISIBLE.search(step.args.get('expected', '')) or
                                  RE_NAMED_HIDDEN.search(step.args.get('expected', ''))):
                classification, reason = 'NEEDS_EXPLORATION', 'Source action has no selected page controls.'
        elif gap.code in {'MISSING_HTTP_METHOD', 'MISSING_HTTP_PATH', 'MISSING_URL', 'MISSING_ARGUMENT', 'MISSING_RESPONSE'}:
            if operations or elements:
                classification, reason = 'NEEDS_RESOLUTION', 'Selected contract or UI evidence is available for argument mapping.'
        from .semantic_ir import source_units, meanings_for_step
        if (step and step.action in case.UNMAPPED_ACTIONS
                and any(u['step_seq'] == step.seq for u in source_units(context))
                and meanings_for_step(step, context, fixture_store) is None
                and expected_expansion(step, case.test_data, min_atoms=1, fixture_store=fixture_store) is None):
            normalization_required = True
            classification, reason = 'NEEDS_RESOLUTION', 'Normalize complete source clauses before planning their evidence acquisition.'
        needs = [n for n in context.evidence_needs if n.get('step_seq') == gap.step_seq and n.get('gap_code') == gap.code]
        if any(n['kind'] in {'UI_STATE', 'WORKFLOW_STATE', 'NETWORK_BINDING'} for n in needs):
            classification, reason = 'NEEDS_EXPLORATION', 'Validator identified missing UI/state provenance; collect evidence once.'
        if classification == 'NEEDS_EXPLORATION' and not can_inspect:
            classification, reason = 'BLOCKED', 'No configured same-origin application target for inspection.'
        entries.append(GapClassification(gap, classification, reason))
    classes = {item.classification for item in entries if item.gap in context.gaps}
    selected = ('resolution' if normalization_required else 'exploration' if 'NEEDS_EXPLORATION' in classes else
                'resolution' if 'NEEDS_RESOLUTION' in classes else 'none')
    reason = {'exploration': 'Collect missing evidence before requesting a mapping.',
              'resolution': 'Trusted evidence is already selected; request mapping only.',
              'none': 'No unresolved work has a safe supported capability.'}[selected]
    return GapRoutingDecision(tuple(entries), selected, reason,
                              tuple(c for c in ('resolution', 'exploration') if c != selected))

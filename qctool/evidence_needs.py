"""Safe validator failures describe missing evidence, never authorize browser actions."""
from copy import deepcopy

KINDS = {
    'UI_EVIDENCE_NOT_FOUND': 'UI_STATE',
    'API_EVIDENCE_NOT_FOUND': 'API_CONTRACT',
    'MISSING_RESPONSE': 'NETWORK_BINDING',
    'OUTCOME_STATE_UNPROVEN': 'WORKFLOW_STATE',
    'EXPANSION_SEMANTICS_UNPROVEN': 'SEMANTIC_BINDING',
    'SEMANTICS_UNPROVEN': 'SEMANTIC_BINDING',
}


def rejection_needs(issues, context):
    out = list(deepcopy(context.evidence_needs))
    for issue in issues:
        # Unsafe proposals and unsupported expectations are not work requests.
        # A failure is actionable only after a source-authorized normalization.
        if not context.semantics:
            continue
        if issue.code not in KINDS or issue.step_seq is None:
            continue
        gaps = [g for g in context.gaps if g.step_seq == issue.step_seq]
        for gap in gaps:
            record = {'kind': KINDS[issue.code], 'step_seq': issue.step_seq,
                      'gap_code': gap.code, 'validation_code': issue.code}
            if record not in out:
                out.append(record)
    return tuple(out)

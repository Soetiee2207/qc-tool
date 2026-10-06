"""Safe live-completion field diagnostics, with no model/network calls."""
import json
from scripts.diagnose_salonhub_007 import completion_field_shape


def test_field_shape_identifies_schema_fields_but_omits_secrets():
    secret = 'FICTIONAL_SECRET_NEVER_LOG'
    raw = {'changes': [{'step_seq': 2, 'from_action': 'perform.unmapped',
                        'gap_codes': ['UNMAPPED_ACTION'], 'reason': secret, 'evidence': [],
                        'steps': [{'password': secret}], secret: secret}]}
    shapes = completion_field_shape(json.dumps(raw))
    assert shapes[0]['missing_fields'] == ['proposed']
    assert shapes[0]['extra_fields'] == ['steps']
    assert shapes[0]['redacted_extra_field_count'] == 1
    assert secret not in json.dumps(shapes)


def test_valid_field_set_and_malformed_completion_diagnostics():
    raw = {'changes': [{'step_seq': 2, 'from_action': 'perform.unmapped',
                        'gap_codes': [], 'proposed': {}, 'reason': 'why', 'evidence': []}]}
    shapes = completion_field_shape(json.dumps(raw))
    assert shapes[0]['missing_fields'] == shapes[0]['extra_fields'] == []
    assert shapes[0]['redacted_extra_field_count'] == 0
    assert completion_field_shape('not json') == []
    assert completion_field_shape('[]') == []

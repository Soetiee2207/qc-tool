"""Schema, citation and runtime support; no prose-to-action semantic grammar."""
from copy import deepcopy
from dataclasses import dataclass
import json
import re
from urllib.parse import urlsplit

from ..executability import analyze_executability
from ..testcase import ACTION_SPECS, Step, StepKind, TestCase


def source_routes(intent):
    """Literal app routes named by the source Given/When (never the expected outcome)."""
    text = ' '.join(str(intent.get(k) or '') for k in ('given', 'when'))
    return tuple(dict.fromkeys(re.findall(r'(?<![\w./:])/[A-Za-z0-9_\-][A-Za-z0-9_\-/]*', text)))


def case_schema():
    """The local schema is derived from the same action contract as Step.validate."""
    variants = []
    for name, spec in sorted(ACTION_SPECS.items()):
        if name.endswith('.unmapped'):
            continue
        variants.append({'type': 'object', 'properties': {
            'seq': {'type': 'integer'}, 'kind': {'enum': [k.value for k in StepKind]},
            'action': {'const': name},
            'args': {'type': 'object', 'properties': {k: {} for k in (*spec.required, *spec.optional)},
                     'required': list(spec.required), 'additionalProperties': False},
            'source': {'type': 'object', 'properties': {'req_id': {'type': 'string'}, 'quote': {'type': 'string'}},
                       'required': ['req_id', 'quote'], 'additionalProperties': False}},
            'required': ['seq', 'kind', 'action', 'args'], 'additionalProperties': False})
    return {'type': 'object', 'properties': {'title': {'type': 'string'},
            'steps': {'type': 'array', 'items': {'oneOf': variants}}},
            'required': ['title', 'steps'], 'additionalProperties': False}


@dataclass(frozen=True)
class GateResult:
    errors: tuple[str, ...] = ()
    review: tuple[str, ...] = ()

    @property
    def accepted(self):
        return not self.errors


def draft_case(raw, *, case_id, module, intent, fixture_store=None):
    """Construct only step IR. Caller fixes its identity, scope and source."""
    if not isinstance(raw, dict) or set(raw) != {'title', 'steps'} or not isinstance(raw['title'], str):
        raise ValueError('case requires only title:string and steps:array')
    if not isinstance(raw['steps'], list) or not 1 <= len(raw['steps']) <= 40:
        raise ValueError('case requires 1–40 steps')
    steps = []
    for index, step in enumerate(raw['steps'], 1):
        if not isinstance(step, dict) or not {'seq', 'kind', 'action', 'args'} <= set(step) or set(step) - {'seq', 'kind', 'action', 'args', 'source'}:
            raise ValueError(f'step {index}: fields must be seq,kind,action,args, optional source')
        if type(step['seq']) is not int or step['seq'] != index or not isinstance(step['args'], dict):
            raise ValueError(f'step {index}: ordered contiguous seq and object args required')
        item = Step(**{**deepcopy(step), 'kind': StepKind(step['kind'])})
        try:
            item.validate()
        except Exception as exc:
            raise ValueError(str(exc)) from None
        if not item.source and not item.action.startswith('assert.'):
            item.source = {'req_id': intent['req_id'], 'quote': intent.get('given' if item.kind == StepKind.GIVEN else 'when', ''),
                           'binding': 'original-intent; individual semantic equivalence requires review'}
        steps.append(item)
    case = TestCase(case_id, module, raw['title'], intent['expected'], steps=steps,
                    preconditions=[intent['given']] if intent.get('given') else [],
                    traces_to=[intent['req_id']], source_quote=intent['expected'],
                    source_ref=intent.get('source_ref', ''), generated_by='llm',
                    obligation_ids=[intent['id']], source_intent=deepcopy(intent))
    if fixture_store:
        case = fixture_store.bind(case)
    case.validate()
    return case


def check_case(case, intent, policy):
    errors, review = [], []
    try:
        case.validate()
        policy.check_case(case)
    except Exception as exc:
        # Safety/schema errors are controlled and redacted by the caller.
        errors.append(str(exc))
    if any(s.action.startswith('ui.') for s in case.steps) and case.steps[0].action != 'ui.session':
        errors.append('UI testcase must begin with an explicit anonymous/authenticated ui.session')
    # Every route the source Given/When opens must be performed, not just
    # asserted: a case that skips the navigation cannot test its outcome.
    performed = set()
    for step in case.steps:
        for value in (step.args.get('url'), step.args.get('path'),
                      *(step.args.get(k, {}).get('path') for k in ('capture_response', 'capture_requests')
                        if isinstance(step.args.get(k), dict))):
            if isinstance(value, str):
                performed.add(urlsplit(value).path.rstrip('/') or '/')
    for route in source_routes(intent):
        if (route.rstrip('/') or '/') not in performed:
            errors.append(f'Source action names route {route} but no step navigates to/calls it')
    report = analyze_executability(case)
    errors.extend(g.message for g in report.gaps)
    expected_clauses = [v.strip() for v in intent['expected'].split(';') if v.strip()]
    # Outcomes belong after the source WHEN. An assertion before the final action
    # (e.g. URL checked before the last navigation) cannot prove that outcome.
    last_action = max((s.seq for s in case.steps if not s.action.startswith('assert.')), default=0)
    cited, cited_after = [], []
    for step in case.steps:
        if not step.action.startswith('assert.'):
            continue
        source = step.source
        if (not isinstance(source, dict) or set(source) != {'req_id', 'quote'}
                or source['req_id'] != intent['req_id'] or not isinstance(source['quote'], str)
                or not source['quote'].strip() or source['quote'] not in intent['expected']):
            errors.append(f'step {step.seq}: every assertion needs source={{req_id, quote}} with a verbatim '
                          'substring of expected; remove assertions the source does not require')
            continue
        quote = source['quote']
        cited.append(quote)
        if step.seq > last_action:
            cited_after.append(quote)
        value = step.args.get('expected')
        if step.action == 'assert.url_matches':
            pattern = step.args.get('pattern', '')
            try:
                re.compile(pattern)
            except (re.error, TypeError):
                errors.append(f'step {step.seq}: url_matches pattern is not a valid regex')
                continue
            if not isinstance(pattern, str) or re.search(r'\s', pattern) or '/' not in pattern:
                errors.append(f'step {step.seq}: url_matches pattern must be a URL/path regex such as /profile$, '
                              'not prose; cite the clause in source.quote instead')
                continue
            value = re.sub(r'\\(.)', r'\1', pattern.removesuffix('$').removeprefix('^'))
            if value.startswith(('http://', 'https://')) and policy is not None and getattr(policy, 'origin', None) \
                    and value.startswith(policy.origin):
                value = value[len(policy.origin):] or '/'
            if re.search(r'[*+?\[\](){}|]', value):
                review.append(f'step {step.seq}: regex oracle needs review')
        if value is None and step.action in {'assert.visible', 'assert.not_visible', 'assert.enabled', 'assert.disabled'}:
            # by_name is readability metadata when target is a testid. It is NOT
            # an assertion of label text. A paired text oracle can strengthen it.
            paired = [s.args.get('expected') for s in case.steps if s.action == 'assert.text'
                      and s.args.get('target') == step.args.get('target') and s.source.get('quote') == quote]
            value = next((v for v in paired if isinstance(v, str) and v and v in quote), None)
        if value is None:
            review.append(f'step {step.seq}: presence/state oracle needs human semantic review')
        else:
            literal = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
            if not literal or literal not in quote:
                review.append(f'step {step.seq}: expected literal is not explicit in source quote')
    for clause in expected_clauses:
        if not any(clause in quote for quote in cited):
            errors.append(f'Expected clause "{clause}" has no assertion whose source.quote contains it')
        elif not any(clause in quote for quote in cited_after):
            errors.append(f'Expected clause "{clause}" must be asserted after the final action step '
                          '(outcomes are checked after the source WHEN, not before it)')
    return GateResult(tuple(dict.fromkeys(errors)), tuple(dict.fromkeys(review)))

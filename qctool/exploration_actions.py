"""Exact source proofs for bounded V2 UI exploration; no browser/model calls."""
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import re
from urllib.parse import urlsplit

from .step_expansion import expected_expansion
from .test_fixtures import REGISTRY, is_alias
from .testcase import ACTION_SPECS, Step
from .ui.crawl import _norm
from .ui.explore import _redact

ALLOWED_ACTIONS = frozenset({'ui.fill', 'ui.select', 'ui.click'})
SAFE_BUTTONS = frozenset({'login', 'sign in', 'dang nhap', 'đăng nhập', 'validate', 'check', 'search', 'filter', 'preview'})
FILL_TYPES = frozenset({'text', 'email', 'password', 'search', 'tel', 'url', 'number'})
DANGEROUS = re.compile(r'\b(delete|remove|purchase|pay|payment|admin|upload|create|update|save|send|register|logout|provision|xoa|xóa|xoá|mua|thanh toan|thanh toán|quan tri|quản trị|dang ky|đăng ký|gửi|lưu|cập nhật|charge|checkout|buy)\b')


def forbidden(value):
    return bool(DANGEROUS.search(_norm(value)))


def action_fingerprint(request, grounding):
    # Hash exact literals too, never redact the approval comparison itself.
    return hashlib.sha256(json.dumps([asdict(request), grounding], sort_keys=True).encode()).hexdigest()


def _meanings(step, data):
    result = []
    for clause in step.args.get('description', '').split(';'):
        clause = clause.strip()
        select = re.fullmatch(r'(?:select|Chọn)\s+["\']?(.+?)["\']?\s+(?:in|trong)\s+["\']?(.+?)["\']?', clause, re.I)
        literal = re.fullmatch(r'(?:fill|enter|Nhập)\s+("(?:[^"\\]|\\.)*")\s+(?:into|vào)\s+(.+)', clause, re.I)
        if literal:
            meanings = [{'action': 'ui.fill', 'hint': literal[2], 'value': json.loads(literal[1])}]
        elif select:
            meanings = [{'action': 'ui.select', 'hint': select[2], 'value': select[1]}]
        else:
            probe = Step(step.seq, step.kind, step.action, {'description': clause})
            meanings = expected_expansion(probe, data, min_atoms=1)
        if not meanings:
            raise ValueError('Unknown source action')
        result.extend({**meaning, 'source_clause': clause} for meaning in meanings)
    return result


def ground_actions(item, target, context, case, base_url, store):
    from .exploration_plan import _normalized_target
    pages = [p for p in context.observations.get('ui_pages', [])
             if _normalized_target(p.get('url', ''), base_url) == target
             and p.get('session') in (None, item.session)]
    if len(pages) != 1:
        raise ValueError('Ambiguous current page')
    page = pages[0]
    elements = page.get('elements', [])
    ids = Counter(e.get('test_id') for e in elements if e.get('test_id'))
    positions, bindings = {}, []
    last_step = 0
    for index, action in enumerate(item.actions):
        if (action.action not in ALLOWED_ACTIONS or type(action.step_seq) is not int
                or action.step_seq < last_step or not isinstance(action.target, str)):
            raise ValueError('Unsupported or unordered action')
        last_step = action.step_seq
        if not any(p.step_seq == action.step_seq and p.gap_code == 'UNMAPPED_ACTION' for p in item.purposes):
            raise ValueError('Unrelated gap')
        steps = [s for s in case.steps if s.seq == action.step_seq and s.action == 'perform.unmapped' and s.kind.value == 'when']
        if len(steps) != 1:
            raise ValueError('Only current unresolved source actions')
        step = steps[0]
        text = step.args.get('description', '')
        requirements = [r for r in context.specification.get('requirements', [])
                        if r.get('id') in case.traces_to and (r.get('when') == text or
                            text in [c.strip() for c in r.get('when', '').split(';')])]
        if not requirements or forbidden(text):
            raise ValueError('No exact safe requirement clause')
        meanings = _meanings(step, case.test_data)
        position = positions.get(step.seq, 0)
        if position >= len(meanings):
            raise ValueError('Repeated action beyond source')
        meaning = meanings[position]
        positions[step.seq] = position + 1
        matches = [e for e in elements if e.get('test_id') == action.target]
        if ids[action.target] != 1 or len(matches) != 1:
            raise ValueError('Unstable target')
        element = matches[0]
        if element.get('disabled') or forbidden(element.get('name', '')) or forbidden(action.target):
            raise ValueError('Unsafe control')
        if action.action != meaning['action'] or _norm(element.get('name', '')) != _norm(meaning.get('hint', '')):
            raise ValueError('Source/control mismatch')
        args = {'target': action.target}
        binding = {'source': 'validated_action', 'action_index': index, 'action': action.action,
                   'target': action.target, 'step_seq': step.seq, 'page': target,
                   'name': element['name'], 'role': element['role'],
                   'tag': element.get('tag') or {'input': 'input', 'textbox': 'input', 'combobox': 'select', 'button': 'button'}.get(element['role']),
                   'input_type': element.get('input_type') or ('text' if element.get('role') in {'input', 'textbox'} and element.get('tag') != 'textarea' else None), 'source_clause': meaning['source_clause'],
                   'requirement_ids': [r['id'] for r in requirements]}
        if action.action in {'ui.fill', 'ui.select'}:
            value = meaning.get('value')
            if action.value != value or not isinstance(value, str) or len(value) > 160:
                raise ValueError('Unproven value')
            if re.search(r'javascript:|data:|file:|<script|onerror\s*=|onload\s*=', value, re.I):
                raise ValueError('Unsafe literal syntax')
            args['value'] = value
            binding['value'] = value  # Only alias or source-proven public literal.
            if action.action == 'ui.fill':
                if binding['tag'] not in {'input', 'textarea'} or binding['tag'] == 'input' and element.get('input_type', 'text') not in FILL_TYPES:
                    raise ValueError('Unsupported fill control')
                if is_alias(value):
                    registry = context.testcase.get('test_data', {}).get(REGISTRY, {})
                    if (store is None or value not in case.test_data.values() or not store.trusts(value, registry)):
                        raise ValueError('Untrusted fixture')
                    binding['fixture_metadata'] = registry[value]
                elif (element.get('input_type') == 'password' or re.search(r'password|secret|token|api.?key|credential', _norm(element['name']))
                      or _redact(value) != value or store and store.redact(value) != value):
                    raise ValueError('Secret literal')
            else:
                if binding['tag'] != 'select' or is_alias(value) or _redact(value) != value or forbidden(value) or store and store.redact(value) != value:
                    raise ValueError('Only public native select options')
                options = element.get('options', [])
                if options and sum(o.get('value') == value and not o.get('disabled') for o in options) != 1:
                    raise ValueError('Unknown option')
                binding['option_source'] = 'ui-map' if options else 'requirement'
        else:
            if action.value is not None or binding['tag'] != 'button' or _norm(element['name']) not in SAFE_BUTTONS:
                raise ValueError('Unsupported click')
            if _norm(element['name']) in {'login', 'sign in', 'dang nhap', 'đăng nhập'}:
                from .response_capture import origin_of
                operations = [op for op in context.interface_contract.get('api_operations', [])
                              if (op.get('method'), op.get('path')) == ('POST', '/api/auth/login')]
                origins = {origin_of(server) for op in operations for server in op.get('servers', [])}
                if len(operations) != 1 or len(origins) != 1:
                    raise ValueError('Ambiguous login contract')
                binding['capture_requests'] = {'method': 'POST', 'path': '/api/auth/login', 'origin': origins.pop(), 'timeout_ms': 2000}
        if action.action not in ACTION_SPECS:
            raise ValueError('Unknown action')
        Step(step.seq, step.kind, action.action, args).validate()
        bindings.append(binding)
    return bindings

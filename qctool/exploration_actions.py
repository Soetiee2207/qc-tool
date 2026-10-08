"""Exact source proofs for bounded stateful UI exploration; no browser/model calls."""
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import re
from threading import Lock
from urllib.parse import urljoin, urlsplit

from .step_expansion import expected_expansion
from .test_fixtures import REGISTRY, is_alias
from .testcase import ACTION_SPECS, Step
from .ui.crawl import _norm
from .ui.explore import _redact

ALLOWED_ACTIONS = frozenset({'ui.fill', 'ui.select', 'ui.click', 'ui.goto'})
SAFE_BUTTONS = frozenset({'login', 'sign in', 'dang nhap', 'đăng nhập', 'validate', 'check', 'search', 'filter', 'preview'})
FILL_TYPES = frozenset({'text', 'email', 'password', 'search', 'tel', 'url', 'number'})
DANGEROUS = re.compile(r'\b(delete|remove|purchase|pay|payment|admin|upload|create|update|save|send|register|logout|provision|xoa|xóa|xoá|mua|thanh toan|thanh toán|quan tri|quản trị|dang ky|đăng ký|gửi|lưu|cập nhật|charge|checkout|buy)\b')

# Reviewed permissions are config, never model output. High-risk actions remain
# excluded even when a caller enables bounded creation/update workflows.
HIGH_RISK = re.compile(r'\b(delete|remove|admin|seed|upload|logout|register|provision|charge|payment|pay|xóa|xoá|quản trị|đăng ký)\b')


def high_risk(value):
    # Match risk words in paths/IDs as well as human labels (admin_users,
    # deleteRecord). This does not infer business meaning or permit new actions.
    return bool(HIGH_RISK.search(_norm(re.sub(r'([a-z])([A-Z])', r'\1 \2', value).replace('_', ' '))))


def mutation_policy(config=None, *, fixture_store=None):
    """Strict public, non-secret permissions; disabled unless explicitly enabled."""
    from copy import deepcopy
    from .response_capture import validate_capture
    if config is None:
        return {}
    if not isinstance(config, dict) or set(config) - {'enabled', 'environment', 'allowed_environment', 'application_origin', 'rules'}:
        raise ValueError('Invalid exploration mutation policy')
    if type(config.get('enabled', False)) is not bool:
        raise ValueError('Mutation enabled must be boolean')
    if not config.get('enabled', False):
        return {}
    required = {'enabled', 'environment', 'allowed_environment', 'application_origin', 'rules'}
    if (set(config) != required or not isinstance(config['environment'], str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', config['environment'])
            or config['environment'] != config['allowed_environment']):
        raise ValueError('Mutation requires an exact approved environment')
    validate_capture({'method': 'GET', 'path': '/', 'origin': config['application_origin']})
    rules = config['rules']
    if not isinstance(rules, list) or not 1 <= len(rules) <= 8:
        raise ValueError('Mutation policy needs one to eight exact rules')
    ids = set()
    for rule in rules:
        keys = {'id', 'requirement_id', 'page', 'target', 'expected_url', 'max_attempts'}
        if not isinstance(rule, dict) or set(rule) not in (keys, keys | {'operation'}):
            raise ValueError('Invalid mutation rule fields')
        if any(not isinstance(rule[k], str) or not rule[k].strip() for k in keys - {'max_attempts'}):
            raise ValueError('Mutation rule identifiers must be nonempty')
        if rule['id'] in ids or type(rule['max_attempts']) is not int or not 1 <= rule['max_attempts'] <= 3:
            raise ValueError('Mutation rule IDs/budgets must be unique and bounded')
        ids.add(rule['id'])
        for key in ('page', 'expected_url'):
            value = rule[key]
            if not value.startswith('/') or value.startswith('//') or urlsplit(value).query or urlsplit(value).fragment or '\\' in value or any(c.isspace() or ord(c) < 32 for c in value):
                raise ValueError('Mutation pages must be exact application paths')
        if any(high_risk(rule[k]) for k in ('page', 'expected_url', 'target')):
            raise ValueError('High-risk mutation is unsupported')
        op = rule.get('operation')
        if op is not None:
            if not isinstance(op, dict) or set(op) != {'operation_id', 'method', 'path', 'origin', 'required_json', 'allowed_json_fields'}:
                raise ValueError('Invalid mutation operation fields')
            if op['method'] not in {'POST', 'PUT', 'PATCH'} or not isinstance(op['operation_id'], str) or not op['operation_id']:
                raise ValueError('Only reviewed create/update operations are supported')
            validate_capture({k: op[k] for k in ('method', 'path', 'origin')})
            if high_risk(op['path']):
                raise ValueError('High-risk operation is unsupported')
            fields = op['allowed_json_fields']
            values = op['required_json']
            if (not isinstance(fields, list) or not fields or any(not isinstance(k, str) or not k for k in fields)
                    or len(set(fields)) != len(fields) or not isinstance(values, dict) or not set(values) <= set(fields)
                    or any(re.search(r'password|secret|token|credential|authorization|cookie', k, re.I) for k in fields)
                    or any(type(v) not in {str, bool, int, float, type(None)} or isinstance(v, str) and (_redact(v) != v or is_alias(v)) for v in values.values())):
                raise ValueError('Mutation body policy must contain only public constraints')
    def public(value):
        if isinstance(value, dict):
            return all(public(k) and public(v) for k, v in value.items())
        if isinstance(value, list):
            return all(public(v) for v in value)
        return not isinstance(value, str) or _redact(value) == value
    if not public(config):
        raise ValueError('Secret-bearing mutation policy')
    if fixture_store and fixture_store.redact(json.dumps(config, ensure_ascii=False)) != json.dumps(config, ensure_ascii=False):
        raise ValueError('Fixture credentials cannot be policy literals')
    try:
        json.dumps(config, allow_nan=False)
    except ValueError:
        raise ValueError('Mutation constraints must be finite JSON values') from None
    return deepcopy(config)


class MutationBudget:
    """Run-owned attempt budget. Copies share this ledger; no persistent cache."""
    def __init__(self):
        self._counts = {}
        self._lock = Lock()

    def __deepcopy__(self, memo):
        return self

    def claim(self, permission):
        key = permission['fingerprint'], permission['rule']['id']
        with self._lock:
            count = self._counts.get(key, 0)
            if count >= permission['rule']['max_attempts']:
                return False
            self._counts[key] = count + 1
            return True


def mutation_permission(policy, *, page, target, destination, requirement_ids, base_url):
    from .exploration_plan import _normalized_target
    from .response_capture import origin_of
    policy = mutation_policy(policy)
    if not policy or origin_of(base_url) != policy['application_origin']:
        return None
    matches = [r for r in policy['rules'] if r['requirement_id'] in requirement_ids
               and r['target'] == target and _normalized_target(r['page'], base_url) == page
               and _normalized_target(r['expected_url'], base_url) == destination]
    if len(matches) != 1:
        return None
    return {'fingerprint': hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest(),
            'environment': policy['environment'], 'rule': matches[0]}


def source_mutation_authorized(atom, unit, context):
    """Permission permits considering meaning; DOM/contract proof remains later."""
    policy = context.mutation_permissions
    if not policy or high_risk(unit['source_text']):
        return False
    requirements = [r for r in context.specification.get('requirements', [])
                    if r.get('id') in context.testcase.get('traces_to', [])
                    and unit['source_text'] in [c.strip() for c in r.get('when', '').split(';')]]
    for rule in policy['rules']:
        if not any(r['id'] == rule['requirement_id'] for r in requirements):
            continue
        if atom.kind == 'navigate' and atom.args['route'] in {rule['page'], rule['expected_url']}:
            return True
        if atom.kind == 'activate':
            pages = [p for p in context.observations.get('ui_pages', []) if urlsplit(p['url']).path == rule['page']]
            if any(e.get('test_id') == rule['target'] and _norm(e.get('name', '')) == _norm(atom.args['label'])
                   for p in pages for e in p.get('elements', [])):
                return True
    return False


def forbidden(value):
    return bool(DANGEROUS.search(_norm(value)))


def navigation_forbidden(url):
    """Read-only source navigation never authorizes destructive endpoint names.

    An admin access-denial page is distinct from an admin control/action; its
    approved redirect is checked separately against the final source outcome.
    """
    path = _norm(urlsplit(url).path)
    return bool(re.search(r'\bseed\b', path) or any(
        match.group() != 'admin' for match in DANGEROUS.finditer(path)))


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


def ground_actions(item, target, context, case, base_url, store, policy=None):
    from .exploration_plan import _normalized_target
    positions, bindings = {}, []
    # Exact contract-only read permissions, not guessed endpoints or outcomes.
    from .response_capture import origin_of
    read_requests = []
    for operation in context.interface_contract.get('background_reads', []):
        if operation.get('method') not in {'GET', 'HEAD'} or forbidden(operation.get('path', '')):
            continue
        for server in operation.get('servers', []):
            selector = {'method': operation['method'], 'path': operation['path'], 'origin': origin_of(server)}
            if selector not in read_requests:
                read_requests.append(selector)
    last_step = 0
    current_page = target
    for index, action in enumerate(item.actions):
        if store and any(store.redact(value) != value for value in (action.page, action.expected_url) if value is not None):
            raise ValueError('Secret-bearing page reference')
        if action.page is not None and _normalized_target(action.page, base_url) != current_page:
            raise ValueError('Action belongs to a different workflow state')
        pages = [p for p in context.observations.get('ui_pages', [])
                 if _normalized_target(p.get('url', ''), base_url) == current_page
                 and p.get('session') in (None, item.session)]
        if len(pages) > 1:
            signatures = {json.dumps(sorted(p.get('elements', []), key=lambda e: json.dumps(e, sort_keys=True)), sort_keys=True) for p in pages}
            if len(signatures) == 1:
                pages = pages[:1]
        if action.action != 'ui.goto' and len(pages) != 1:
            raise ValueError('Ambiguous or unobserved current page')
        page = pages[0] if len(pages) == 1 else {}
        elements = page.get('elements', [])
        ids = Counter(e.get('test_id') for e in elements if e.get('test_id'))
        if (action.action not in ALLOWED_ACTIONS or type(action.step_seq) is not int
                or action.step_seq < last_step or not isinstance(action.target, str)):
            raise ValueError('Unsupported or unordered action')
        last_step = action.step_seq
        source_steps = [s for s in case.steps if s.seq==action.step_seq and s.kind.value=='when']
        replay = len(source_steps)==1 and source_steps[0].action != 'perform.unmapped'
        if replay:
            step,requirements,meaning = _replay_meaning(action,item,context,case,store,positions)
            text = requirements[0]['when']
            from .semantic_ir import element_matches
        else:
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
            if not requirements:
                raise ValueError('No exact safe requirement clause')
            from .semantic_ir import meanings_for_step, element_matches
            meanings = meanings_for_step(step, context, store) or _meanings(step, case.test_data)
            position = positions.get(step.seq, 0)
            if position >= len(meanings):
                raise ValueError('Repeated action beyond source')
            meaning = meanings[position]
            positions[step.seq] = position + 1
        if action.action == 'ui.goto':
            from .response_capture import origin_of
            destination = _normalized_target(action.url or '', base_url)
            source_url = meaning.get('args', {}).get('url')
            route_permission = origin_of(base_url) == (policy or {}).get('application_origin') and any(r['requirement_id'] in [r['id'] for r in requirements]
                                   and destination in {_normalized_target(r['page'], base_url), _normalized_target(r['expected_url'], base_url)}
                                   for r in (policy or {}).get('rules', []))
            if destination is None or navigation_forbidden(destination) and not route_permission:
                raise ValueError('Unsafe navigation operation')
            expected = _normalized_target(action.expected_url, base_url) if action.expected_url else destination
            if forbidden(destination) and expected == destination and not route_permission:
                raise ValueError('Admin inspection requires an explicit access-denial outcome')
            if expected != destination:
                from .semantic_ir import source_meanings
                routes = {m['route'] for r in requirements for m in source_meanings(r['then'], 'then', context, store) or () if m.get('route')}
                if index != len(item.actions) - 1 or expected not in {_normalized_target(route, base_url) for route in routes}:
                    raise ValueError('Navigation redirect needs an exact final source outcome')
            if (meaning['action'] != 'ui.goto' or not source_url
                    or destination != _normalized_target(source_url, base_url)
                    or action.value is not None or action.target):
                raise ValueError('Navigation must be the exact ordered source route')
            binding = {'source': 'validated_action', 'action_index': index, 'action': 'ui.goto',
                       'step_seq': step.seq, 'page': current_page, 'url': destination,
                       'source_clause': meaning['source_clause'], 'requirement_ids': [r['id'] for r in requirements],
                       'expected_url': expected, 'transition': {'from': current_page, 'to': expected,
                       'source': 'requirement_route'}}
            Step(step.seq, step.kind, 'ui.goto', {'url': destination}).validate()
            bindings.append(binding)
            current_page = expected
            continue
        matches = [e for e in elements if e.get('test_id') == action.target]
        if ids[action.target] != 1 or len(matches) != 1:
            raise ValueError('Unstable target')
        element = matches[0]
        destination = _normalized_target(action.expected_url, base_url) if action.expected_url else current_page
        permission = mutation_permission(policy, page=current_page, target=action.target,
                                         destination=destination, requirement_ids=[r['id'] for r in requirements], base_url=base_url) if action.action == 'ui.click' else None
        if element.get('disabled') or (forbidden(meaning['source_clause']) or forbidden(element.get('name', '')) or forbidden(action.target)) and not permission:
            raise ValueError('Unsafe control')
        if permission and (high_risk(element.get('name', '')) or high_risk(meaning['source_clause'])):
            raise ValueError('High-risk control')
        if action.action != meaning['action'] or not (element_matches(element, meaning) if meaning.get('semantic') else _norm(element.get('name', '')) == _norm(meaning.get('hint', ''))):
            raise ValueError('Source/control mismatch')
        if meaning.get('semantic') and sum(element_matches(e, meaning) for e in elements)!=1:
            raise ValueError('Ambiguous semantic control')
        args = {'target': action.target}
        binding = {'source': 'validated_action', 'action_index': index, 'action': action.action,
                   'target': action.target, 'step_seq': step.seq, 'page': current_page,
                   'name': element['name'], 'role': element['role'],
                   'tag': element.get('tag') or {'input': 'input', 'textbox': 'input', 'combobox': 'select', 'button': 'button', 'link': 'a'}.get(element['role']),
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
            authority = requirements + workflow_prerequisites(requirements, context)
            if action.value is not None or binding['tag'] not in {'button', 'a'} or _norm(element['name']) not in SAFE_BUTTONS and not permission:
                raise ValueError('Unsupported click')
            if permission:
                binding['mutation_permission'] = permission
                operation = permission['rule'].get('operation')
                if operation:
                    from .response_capture import origin_of
                    operations = [op for op in context.interface_contract.get('api_operations', [])
                                  if all(op.get(k) == operation[k] for k in ('operation_id', 'method', 'path'))
                                  and operation['origin'] in {origin_of(s) for s in op.get('servers', [])}]
                    if len(operations) != 1 or not any(re.search(r'(?<!\w)' + re.escape(operation['method']) + r'\s+' + re.escape(operation['path']) + r'(?=\s|;|$)', r.get('then', '')) for r in requirements):
                        raise ValueError('Mutation operation lacks exact source/contract proof')
                    binding['capture_requests'] = {k: operation[k] for k in ('method', 'path', 'origin')}
                    binding['capture_requests']['timeout_ms'] = 10000
            if binding['tag'] == 'a' and not action.expected_url:
                raise ValueError('Navigation link needs an approved destination')
            if _norm(element['name']) in {'login', 'sign in', 'dang nhap', 'đăng nhập'}:
                from .response_capture import origin_of
                operations = [op for op in context.interface_contract.get('api_operations', [])
                              if op.get('method') == 'POST' and any(
                                  re.search(r'(?<!\w)POST\s+' + re.escape(op.get('path', '')) + r'(?=\s|;|$)', r.get('then', ''))
                                  for r in authority)]
                origins = {origin_of(server) for op in operations for server in op.get('servers', [])}
                if operations:
                    if len(operations) != 1 or len(origins) != 1 or forbidden(operations[0]["path"]):
                        raise ValueError('Ambiguous source request contract')
                    binding['capture_requests'] = {'method': 'POST', 'path': operations[0]['path'], 'origin': origins.pop(), 'timeout_ms': 10000 if workflow_prerequisites(requirements, context) else 2000}
        destination = current_page
        if action.expected_url is not None:
            destination = _normalized_target(action.expected_url, base_url)
            if destination is None or forbidden(destination) and not permission:
                raise ValueError('Unsafe transition')
            href = element.get('href')
            if binding['tag'] == 'a' and (not href or _normalized_target(urljoin(current_page, href), base_url) != destination):
                raise ValueError('Link destination differs from the approved transition')
            explicit = destination in authorized_transition_routes(requirements, context, base_url, store)
            if not (href and _normalized_target(urljoin(current_page, href), base_url) == destination or explicit):
                raise ValueError('Destination is not tied to source or clicked href')
            binding['transition'] = {'from': current_page, 'to': destination,
                                     'source': 'ui_href' if href and _normalized_target(urljoin(current_page, href), base_url) == destination else 'requirement_route'}
            binding['href'] = href
        binding['expected_url'] = destination
        current_page = destination
        if action.action not in ACTION_SPECS:
            raise ValueError('Unknown action')
        Step(step.seq, step.kind, action.action, args).validate()
        bindings.append(binding)
    if read_requests:
        for binding in bindings:
            binding['read_requests'] = read_requests
    return bindings


def _replay_meaning(action, item, context, case, store, positions):
    """A current outcome gap may inspect its already validated source prefix.

    No arbitrary executable step can be reopened. Source IR, complete concrete
    prefix, purpose linkage, exact args and the normal DOM/safety checks all apply.
    """
    from .source_grounding import source_clause
    from .semantic_ir import source_meanings
    candidates = []
    for req in context.specification.get('requirements', []):
        if req.get('id') not in case.traces_to or not req.get('when') or not req.get('then'):
            continue
        outcomes = [s for s in case.steps if s.action=='assert.unmapped' and source_clause(s,req)==req['then']
                    and any(p.step_seq==s.seq and p.gap_code=='UNMAPPED_ACTION' for p in item.purposes)]
        if len(outcomes)!=1:
            continue
        meanings = source_meanings(req['when'],'when',context,store)
        steps = [s for s in case.steps if s.kind.value=='when' and source_clause(s,req)==req['when']]
        if not meanings or len(meanings)!=len(steps) or any(s.action not in ALLOWED_ACTIONS for s in steps):
            continue
        index = positions.get(('replay',req['id']),0)
        if index>=len(steps) or steps[index].seq!=action.step_seq:
            continue
        # The whole concrete prefix still agrees with its semantic source.
        if any(s.action!=m['action'] or 'value' in m and s.args.get('value')!=m['value'] for s,m in zip(steps,meanings)):
            continue
        step=steps[index]
        if step.action!=action.action or (step.action=='ui.goto' and step.args.get('url')!=action.url) or (step.action!='ui.goto' and step.args.get('target')!=action.target) or action.value!=step.args.get('value'):
            continue
        candidates.append((step,req,meanings[index]))
    if len(candidates)!=1:
        raise ValueError('No complete unique source prefix for this outcome gap')
    step,req,meaning=candidates[0]
    positions[('replay',req['id'])]=positions.get(('replay',req['id']),0)+1
    return step,[req],meaning


def workflow_prerequisites(requirements, context):
    """Recheck exact source-prefix authority; metadata alone never authorizes it."""
    found = []
    for current in requirements:
        full = [c.strip() for c in current.get('when', '').split(';') if c.strip()]
        for prefix in context.specification.get('prerequisites', []):
            clauses = [c.strip() for c in prefix.get('when', '').split(';') if c.strip()]
            if (current.get('given') and prefix.get('given') == current['given']
                    and 0 < len(clauses) < len(full) and clauses == full[:len(clauses)]
                    and prefix.get('then') and prefix.get('evidence', {}).get('for_requirement') == current.get('id')):
                if prefix not in found:
                    found.append(prefix)
    return found


def authorized_transition_routes(requirements, context, base_url, store=None):
    """Positive source route claims only; literal mentions/negation are not proof."""
    from .exploration_plan import _normalized_target
    from .semantic_ir import SemanticAtom, _safe_authorized, literals
    out = set()
    for req in requirements + workflow_prerequisites(requirements, context):
        for field in ('given', 'when', 'then'):
            for clause in req.get(field, '').split(';'):
                unit = {'field': field, 'source_text': clause.strip()}
                for route in literals(clause):
                    atom = SemanticAtom('url' if field == 'then' else 'navigate', {'route': route})
                    if _safe_authorized(atom, unit, context, store):
                        normalized = _normalized_target(route, base_url)
                        if normalized: out.add(normalized)
    return out

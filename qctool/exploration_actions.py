"""Exact source proofs for bounded stateful UI exploration; no browser/model calls."""
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import re
from threading import Lock
from urllib.parse import urljoin, urlsplit

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
    from urllib.parse import urljoin
    def _normalized_target(value, base):
        return urljoin(base.rstrip("/") + "/", value) if isinstance(value, str) else None
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

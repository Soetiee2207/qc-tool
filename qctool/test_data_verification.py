"""Explicit, bounded verification of existing fixtures; never provisioning.

Rules are trusted operator policy, not model output. Only their stated implications
become facts. Runtime receipts cannot be replaced with a config evidence dictionary.
"""
from copy import deepcopy
from dataclasses import dataclass, asdict, field, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import hmac
import http.client
import json
import os
import re
import time
from urllib.parse import urlsplit

from .config import ConfigError
from .test_fixtures import is_alias, FixtureUnavailable
from .test_data_acquisition import _facts, _name, _SAFE_ID

MAX_VERIFICATION_CALLS = 3
MAX_RESPONSE_BYTES = 65536
MAX_TIMEOUT_SECONDS = 10
_DENIED = re.compile(r'(^|[/_.-])(admin|seed|register|registration|signup|otp|delete|remove|purchase|payment|reset|upload|create|update)([/_.-]|$)', re.I)
_PUBLIC_PATHS = {'$.success', '$.account_exists', '$.account_state', '$.role', '$.password_valid', '$.entity_exists'}
_KEY = os.urandom(32)
_SEAL = object()


class VerificationStatus(str, Enum):
    VERIFIED = 'VERIFIED'
    INVALID = 'INVALID'
    UNVERIFIED = 'UNVERIFIED'
    UNSAFE_TO_VERIFY = 'UNSAFE_TO_VERIFY'
    AMBIGUOUS = 'AMBIGUOUS'


@dataclass(frozen=True)
class VerificationRule:
    fixture: str
    operation_id: str
    body_aliases: dict
    expected: dict
    proves: dict
    policy: dict
    source_ref: str


@dataclass(frozen=True)
class VerificationObservation:
    fixture: str
    operation_id: str
    outcome: VerificationStatus
    code: str
    status: int | None = None
    facts: dict | None = None
    source: dict | None = None
    attempted: bool = False


def parse_verification_rules(records):
    """Strict config contract; no literals/secrets or inferred safety approval."""
    if not isinstance(records, list) or len(records) > MAX_VERIFICATION_CALLS:
        raise ConfigError('Verification allows at most three explicit rules')
    rules = []
    for record in records:
        fields = {'fixture', 'operation_id', 'body_aliases', 'expected', 'proves', 'policy', 'source_ref'}
        if not isinstance(record, dict) or set(record) != fields:
            raise ConfigError('Invalid verification rule fields')
        _name(record['fixture']); _facts(record['proves'])
        if not record['proves'] or 'entity_id' in record['proves']:
            raise ConfigError('Verification requires explicit public fact implications')
        for key in ('operation_id', 'source_ref'):
            if not isinstance(record[key], str) or not _SAFE_ID.fullmatch(record[key]):
                raise ConfigError('Verification requires exact public operation/source IDs')
        aliases = record['body_aliases']
        if not isinstance(aliases, dict) or any(
            not isinstance(k, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', k)
            or not is_alias(v) or v.split('.')[0] != record['fixture'] for k, v in aliases.items()
        ):
            raise ConfigError('Verification request data must use same-fixture aliases')
        expected = record['expected']
        if not isinstance(expected, dict) or set(expected) != {'status', 'json'} or type(expected['status']) is not int or not 200 <= expected['status'] < 300:
            raise ConfigError('Verification requires an explicit successful status and public JSON predicates')
        if not isinstance(expected['json'], dict) or not expected['json'] or set(expected['json']) - _PUBLIC_PATHS:
            raise ConfigError('Verification predicates allow approved public response fields only')
        for path, value in expected['json'].items():
            if path == '$.success':
                if type(value) is not bool:
                    raise ConfigError('Success predicate must be boolean')
            else:
                _facts({path[2:]: value})
        policy = record['policy']
        if not isinstance(policy, dict) or set(policy) != {'approved', 'test_data_mutation', 'side_effects'} or any(type(policy[k]) is not bool for k in ('approved', 'test_data_mutation')) or not isinstance(policy['side_effects'], list) or any(not isinstance(v, str) for v in policy['side_effects']):
            raise ConfigError('Verification requires explicit approval, mutation and side-effect policy')
        rules.append(VerificationRule(**deepcopy(record)))
    return tuple(rules)


def _stamp(store):
    # Private ephemeral HMAC, never exported: receipts expire if credentials change.
    return hmac.new(_KEY, json.dumps(store._values, sort_keys=True).encode(), hashlib.sha256).digest()


class _Receipt:
    def __init__(self, case, store, observations):
        self.seal = _SEAL
        self.case_id = case.id
        self.requirements = deepcopy(case.test_data.get('_data_requirements', []))
        self.store = store
        self.stamp = _stamp(store)
        self.metadata = store.to_dict()
        self.observations = deepcopy(observations)

    def __repr__(self):
        return '<private verification receipt>'

    def validate(self, case, store, observations):
        if self.seal is not _SEAL or self.store is not store or self.case_id != case.id or self.requirements != case.test_data.get('_data_requirements', []) or self.metadata != store.to_dict() or self.stamp != _stamp(store) or self.observations != observations:
            raise ConfigError('Runtime receipt is stale or belongs to different data')


@dataclass(frozen=True)
class VerificationResult:
    observations: tuple[VerificationObservation, ...]
    _receipt: object = field(default=None, repr=False, compare=False)

    @property
    def status(self):
        outcomes = {r.outcome for r in self.observations if r.code != 'REDUNDANT_RULE_SKIPPED'}
        for status in (VerificationStatus.AMBIGUOUS, VerificationStatus.UNSAFE_TO_VERIFY,
                       VerificationStatus.INVALID, VerificationStatus.UNVERIFIED):
            if status in outcomes:
                return status
        return VerificationStatus.VERIFIED if outcomes else VerificationStatus.UNVERIFIED

    def to_dict(self):
        return {'status': self.status.value, 'observations': [asdict(r) for r in self.observations],
                'calls': sum(r.attempted for r in self.observations),
                'provisioning_performed': False}

    def evidence_for(self, case, store):
        receipt = self._receipt
        if not isinstance(receipt, _Receipt):
            raise ConfigError('Verification receipt is absent, stale or belongs to different data')
        receipt.validate(case, store, self.observations)
        return tuple({'fixture': r.fixture, 'facts': deepcopy(r.facts),
                      'assurance': 'VERIFIED', 'source': deepcopy(r.source)}
                     for r in self.observations if r.outcome in {VerificationStatus.VERIFIED, VerificationStatus.AMBIGUOUS} and r.facts)


def _once(method, url, body, timeout):
    """One connection, one request, no redirects/retries, bounded response bytes.

    Unlike executor HttpSession, this deliberately never retries a stale socket.
    Headers, cookies and raw response content never escape this transport.
    """
    from .execute.runner import USER_AGENT
    parts = urlsplit(url)
    cls = http.client.HTTPSConnection if parts.scheme == 'https' else http.client.HTTPConnection
    conn = cls(parts.hostname, parts.port, timeout=timeout)
    deadline = time.monotonic() + timeout
    try:
        payload = json.dumps(body).encode() if body else None
        if payload and len(payload) > 4096:
            return {'error': 'REQUEST_LIMIT'}
        conn.request(method, parts.path or '/', body=payload,
                     headers={'User-Agent': USER_AGENT, 'Content-Type': 'application/json'})
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        sock = conn.sock
        sock.settimeout(remaining)
        response = conn.getresponse()
        chunks, size = [], 0
        while size <= MAX_RESPONSE_BYTES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            # Response owns the socket when the server closes keep-alive.
            sock.settimeout(remaining)
            chunk = response.read1(min(4096, MAX_RESPONSE_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        raw = b''.join(chunks)
        if len(raw) > MAX_RESPONSE_BYTES:
            return {'status': response.status, 'error': 'RESPONSE_LIMIT'}
        try:
            parsed = json.loads(raw)
        except (ValueError, UnicodeError):
            parsed = None
        return {'status': response.status, 'body': parsed}
    finally:
        conn.close()


def validate_verification_rule(rule, acquisition, store, endpoints, base_url):
    """Shared deterministic gate; never resolve aliases or contact a provider."""
    operations = [op for op in endpoints if op.operation_id == rule.operation_id]
    if len(operations) != 1:
        return None, 'AMBIGUOUS' if operations else 'OPERATION_NOT_FOUND'
    op = operations[0]
    try:
        parts = urlsplit(base_url)
        parts.port
    except (ValueError, TypeError, AttributeError):
        return None, 'UNSAFE_ORIGIN'
    policy = rule.policy
    if parts.scheme not in {'https', 'http'} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or '%' in parts.path or '\\' in parts.path or '..' in parts.path.split('/') or any(ord(c) < 33 for c in base_url):
        return None, 'UNSAFE_ORIGIN'
    if not re.fullmatch(r'/[A-Za-z0-9_./~-]*', op.path) or '..' in op.path.split('/') or op.path.startswith('//'):
        return None, 'UNSAFE_OPERATION'
    method = op.method.upper()
    operation_words = re.sub(r'([a-z])([A-Z])', r'\1_\2', op.operation_id)
    if not policy['approved'] or policy['test_data_mutation'] or set(policy['side_effects']) - {'session_creation'} or _DENIED.search(op.path) or _DENIED.search(operation_words) or op.requires_auth or method not in {'GET', 'HEAD', 'POST'} or method == 'POST' and '201' in op.responses:
        return None, 'UNAPPROVED_EFFECTS'
    if method in {'GET', 'HEAD'} and (policy['side_effects'] or rule.body_aliases):
        return None, 'UNAPPROVED_EFFECTS'
    servers = op.servers or op.contract_servers
    if servers and base_url.rstrip('/') not in [s.rstrip('/') for s in servers]:
        return None, 'CONTRACT_SERVER_MISMATCH'
    if str(rule.expected['status']) not in op.responses:
        return None, 'RESPONSE_NOT_IN_CONTRACT'
    if any(p.get('required') for p in op.parameters):
        return None, 'UNSUPPORTED_PARAMETERS'
    if rule.body_aliases:
        schema = op.request_body or {}
        if schema.get('type') != 'object' or set(rule.body_aliases) - set(schema.get('properties', {})) or set(op.request_required) - set(rule.body_aliases) or any(schema['properties'][k].get('type') != 'string' for k in rule.body_aliases):
            return None, 'INVALID_REQUEST_CONTRACT'
    elif op.request_required:
        return None, 'INVALID_REQUEST_CONTRACT'
    findings = [f for f in acquisition.findings if f.requirement.fixture == rule.fixture]
    needed = {f.fact for finding in findings for f in finding.facts}
    if not findings or not set(rule.proves) <= needed:
        return None, 'UNRELATED_FACTS'
    metadata = store.to_dict()['aliases']
    bound = {a['alias'] for f in findings for a in f.aliases}
    if any(a not in bound or not metadata.get(a, {}).get('available') for a in rule.body_aliases.values()):
        return None, 'MISSING_FIXTURE'
    return (method, base_url.rstrip('/') + op.path), None


def verify_test_data(acquisition, *, fixture_store, endpoints=(), base_url,
                     timeout=MAX_TIMEOUT_SECONDS, transport=None, rule_indices=None):
    """Validate configured rules, then resolve aliases and make <=3 calls, once each.

    No implicit invocation from acquisition/pipeline. ``transport`` is a trusted
    test seam returning status/body; it never receives unvalidated requests.
    """
    if type(timeout) not in {int, float} or not 0 < timeout <= MAX_TIMEOUT_SECONDS:
        raise ConfigError('Verification timeout must be positive and at most ten seconds')
    rules = parse_verification_rules(fixture_store.acquisition_config.get('verification', []))
    if rule_indices is not None:
        if not isinstance(rule_indices, tuple) or len(rule_indices) > MAX_VERIFICATION_CALLS or any(
            type(i) is not int or not 0 <= i < len(rules) for i in rule_indices
        ) or len(set(rule_indices)) != len(rule_indices):
            raise ConfigError('Verification selection requires bounded configured rule indices')
        rules = tuple(rules[i] for i in rule_indices)
    # Prefer explicitly approved read-only operations; do not probe a write
    # operation again once all its implications have already been established.
    readonly = {op.operation_id for op in endpoints if op.method.upper() in {'GET', 'HEAD'}}
    rules = tuple(sorted(rules, key=lambda r: r.operation_id not in readonly))
    initial_stamp, initial_metadata = _stamp(fixture_store), fixture_store.to_dict()
    records = []
    seen = set()
    proven = {}
    for rule in rules:
        source = {'type': 'live_verification', 'operation_id': rule.operation_id,
                  'policy_ref': rule.source_ref, 'observed_at': datetime.now(timezone.utc).isoformat()}
        approved, error = validate_verification_rule(rule, acquisition, fixture_store, endpoints, base_url)
        if error:
            outcome = VerificationStatus.AMBIGUOUS if error == 'AMBIGUOUS' else (VerificationStatus.UNVERIFIED if error in {'MISSING_FIXTURE', 'OPERATION_NOT_FOUND', 'UNRELATED_FACTS'} else VerificationStatus.UNSAFE_TO_VERIFY)
            records.append(VerificationObservation(rule.fixture, rule.operation_id, outcome, error, source=source))
            continue
        signature = json.dumps(asdict(rule), sort_keys=True)
        satisfied = all(proven.get((rule.fixture, fact)) == value for fact, value in rule.proves.items())
        if signature in seen or satisfied:
            records.append(VerificationObservation(rule.fixture, rule.operation_id, VerificationStatus.UNVERIFIED,
                                                  'REDUNDANT_RULE_SKIPPED', source=source))
            continue
        seen.add(signature)
        method, url = approved
        source.update(method=method, path=next(op.path for op in endpoints if op.operation_id == rule.operation_id))
        try:
            # The only alias resolution is below the complete safety gate.
            body = {key: fixture_store.resolve(alias) for key, alias in rule.body_aliases.items()}
        except FixtureUnavailable:
            records.append(VerificationObservation(rule.fixture, rule.operation_id, VerificationStatus.UNVERIFIED, 'MISSING_FIXTURE', source=source))
            continue
        try:
            response = (transport or _once)(method, url, body, timeout)
            status = response.get('status')
            if type(status) is not int or not 100 <= status <= 599:
                status = None
            parsed = response.get('body')
            if response.get('error') or status is None or status >= 500 or status in {408, 429} or 300 <= status < 400:
                outcome, code, facts = VerificationStatus.UNVERIFIED, 'INCONCLUSIVE_RESPONSE', {}
            elif 400 <= status < 500:
                outcome, code, facts = VerificationStatus.INVALID, 'EXPECTED_SIGNATURE_NOT_MET', {}
            elif status != rule.expected['status'] or not isinstance(parsed, dict) or any(path[2:] not in parsed for path in rule.expected['json']):
                outcome, code, facts = VerificationStatus.UNVERIFIED, 'INCOMPLETE_SIGNATURE', {}
            elif any(type(parsed[path[2:]]) is not type(value) or parsed[path[2:]] != value for path, value in rule.expected['json'].items()):
                outcome, code, facts = VerificationStatus.INVALID, 'EXPECTED_SIGNATURE_NOT_MET', {}
            else:
                facts = deepcopy(rule.proves)
                conflicts = any(f.fact in facts and any(e['value'] != facts[f.fact] for e in f.evidence) for finding in acquisition.findings if finding.requirement.fixture == rule.fixture for f in finding.facts)
                outcome, code = (VerificationStatus.AMBIGUOUS, 'CONFLICTING_EVIDENCE') if conflicts else (VerificationStatus.VERIFIED, 'SIGNATURE_MATCHED')
                # Keep both sources as conflict evidence; acquisition never overwrites.
        except Exception:
            # Never include exception text, URL, request body or provider content.
            outcome, code, status, facts = VerificationStatus.UNVERIFIED, 'TRANSPORT_FAILED', None, {}
        if initial_stamp != _stamp(fixture_store) or initial_metadata != fixture_store.to_dict():
            outcome, code, facts = VerificationStatus.UNVERIFIED, 'FIXTURE_CHANGED', {}
        if outcome == VerificationStatus.VERIFIED:
            proven.update({(rule.fixture, name): value for name, value in facts.items()})
        records.append(VerificationObservation(rule.fixture, rule.operation_id, outcome, code, status, facts, source, True))
    values = {}
    for record in records:
        for name, value in (record.facts or {}).items():
            values.setdefault((record.fixture, name), set()).add(value)
    observations = tuple(
        replace(r, outcome=VerificationStatus.AMBIGUOUS, code='CONFLICTING_EVIDENCE')
        if any(len(values[(r.fixture, name)]) > 1 for name in (r.facts or {})) else r
        for r in records)
    result = VerificationResult(observations, _Receipt(acquisition.case, fixture_store, observations))
    if fixture_store.redact(result.to_dict()) != result.to_dict():
        raise ConfigError('Verification metadata contains a fixture secret')
    return result

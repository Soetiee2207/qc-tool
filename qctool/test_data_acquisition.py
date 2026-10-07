"""Offline discovery of trusted test data and declared provisioning paths.

No HTTP/browser/database access. Config/seed declarations never become live
verification. Only a separately validated runtime verification receipt proves facts.
"""
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from enum import Enum
import json
import re

from .config import ConfigError
from .test_fixtures import FixtureStore, PUBLIC_FACT_VALUES, is_alias
from .testcase import TestCase

DATA_REQUIREMENTS = '_data_requirements'
MAX_DATA_REQUIREMENTS = 8
MAX_EVIDENCE_RECORDS = 32
MAX_PROVISIONING_PATHS = 8

PUBLIC_FACTS = {**PUBLIC_FACT_VALUES, 'account_exists': {True, False},
                'password_valid': {True, False}, 'entity_exists': {True, False}}
_SAFE_ID = re.compile(r'^[A-Za-z0-9_./:#-]{1,160}$')
_UNSAFE_PATH = re.compile(r'(^|[/_-])(admin|seed|delete|remove|payment|purchase|provision|reset)([/_-]|$)', re.I)


class DataStatus(str, Enum):
    AVAILABLE = 'AVAILABLE'
    PROVISIONABLE = 'PROVISIONABLE'
    MISSING_TEST_DATA = 'MISSING_TEST_DATA'
    AMBIGUOUS = 'AMBIGUOUS'
    UNSAFE_TO_PROVISION = 'UNSAFE_TO_PROVISION'


@dataclass(frozen=True)
class DataRequirement:
    fixture: str | None
    aliases: tuple[str, ...] = ()
    facts: dict = field(default_factory=dict)
    require_verified: bool = True
    step_seq: int | None = None
    source_ref: str = ''


@dataclass(frozen=True)
class FactFinding:
    fact: str
    expected: str | bool
    status: str
    evidence: tuple[dict, ...]


@dataclass(frozen=True)
class DataFinding:
    requirement: DataRequirement
    status: DataStatus
    aliases: tuple[dict, ...]
    facts: tuple[FactFinding, ...]
    provisioning: tuple[dict, ...]


@dataclass(frozen=True)
class DataAcquisitionResult:
    case: TestCase = field(repr=False)
    findings: tuple[DataFinding, ...] = ()
    issues: tuple[dict, ...] = ()
    verification: dict = field(default_factory=dict)
    provisioning: dict = field(default_factory=dict)

    @property
    def status(self):
        if any(i['code']=='AMBIGUOUS_TEST_DATA' for i in self.issues):
            return DataStatus.AMBIGUOUS
        if any(i['code']=='MISSING_TEST_DATA' for i in self.issues):
            return DataStatus.MISSING_TEST_DATA
        statuses = {item.status for item in self.findings}
        for status in (DataStatus.AMBIGUOUS, DataStatus.UNSAFE_TO_PROVISION,
                       DataStatus.MISSING_TEST_DATA, DataStatus.PROVISIONABLE):
            if status in statuses:
                return status
        return DataStatus.AVAILABLE

    def to_dict(self):
        # Deliberately never serialize TestCase values or a runtime FixtureStore.
        payload = {'testcase_id': self.case.id, 'status': self.status.value,
                'live_verification_performed': bool(self.verification.get('calls')), 'provisioning_performed': bool(self.provisioning.get('calls')),
                'findings': [asdict(item) for item in self.findings],
                'issues': deepcopy(list(self.issues))}
        if self.verification:
            payload['verification'] = deepcopy(self.verification)
        if self.provisioning:
            payload['provisioning'] = deepcopy(self.provisioning)
        return payload


def _facts(values):
    if not isinstance(values, dict):
        raise ConfigError('Test-data facts must be a mapping')
    for name, value in values.items():
        if name == 'entity_id':
            valid = isinstance(value, str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value))
        else:
            allowed = PUBLIC_FACTS.get(name)
            valid = allowed is not None and type(value) in {str, bool} and value in allowed
        if not valid:
            raise ConfigError('Test-data facts require approved public labels, booleans or explicit entity IDs')


def validate_acquisition_config(config):
    """Strict public metadata only; no credentials, payloads, or commands."""
    if not isinstance(config, dict) or set(config) - {'requirements', 'evidence', 'provisioning', 'verification', 'provisioning_rules'}:
        raise ConfigError('Acquisition config allows requirements, evidence, provisioning and verification only')
    if 'verification' in config:
        from .test_data_verification import parse_verification_rules
        parse_verification_rules(config['verification'])
    if 'provisioning_rules' in config:
        from .test_data_provisioning import parse_provisioning_rules
        parse_provisioning_rules(config['provisioning_rules'])
    if not isinstance(config.get('requirements', {}), dict) or any(not isinstance(config.get(k, []), list) for k in ('evidence','provisioning')):
        raise ConfigError('Acquisition requires a requirement mapping and evidence/provisioning lists')
    if len(config.get('evidence', []))>MAX_EVIDENCE_RECORDS or len(config.get('provisioning', []))>MAX_PROVISIONING_PATHS:
        raise ConfigError('Acquisition evidence/provisioning budget exceeded')
    for source, records in config.get('requirements', {}).items():
        if not isinstance(source, str) or not _SAFE_ID.fullmatch(source) or not isinstance(records, list):
            raise ConfigError('Acquisition requirements must map source IDs to lists')
        for record in records:
            _requirement(record)
    for record in config.get('evidence', []):
        if not isinstance(record, dict) or set(record) != {'fixture', 'facts', 'assurance', 'source_ref'}:
            raise ConfigError('Fact evidence requires fixture, facts, assurance and source_ref')
        _name(record['fixture']); _facts(record['facts'])
        if record['assurance'] not in {'DECLARED', 'REQUIREMENT_LITERAL'} or not isinstance(record['source_ref'], str) or not _SAFE_ID.fullmatch(record['source_ref']):
            raise ConfigError('Unsupported public evidence assurance/reference')
        if record['assurance']=='REQUIREMENT_LITERAL' and set(record['facts']) != {'entity_id'}:
            raise ConfigError('Requirement literals may identify an entity, not prove backend state')
    for record in config.get('provisioning', []):
        if not isinstance(record, dict) or set(record) != {'fixture', 'operation_id', 'provides', 'external_interaction'}:
            raise ConfigError('Provisioning metadata requires fixture, operation_id, provides and external_interaction')
        _name(record['fixture']); _facts(record['provides'])
        if not isinstance(record['operation_id'], str) or not _SAFE_ID.fullmatch(record['operation_id']) or type(record['external_interaction']) is not bool:
            raise ConfigError('Invalid provisioning metadata')
    return deepcopy(config)


def _name(name):
    if not is_alias(f'{name}.field'):
        raise ConfigError('Invalid test-data fixture name')


def _requirement(record):
    if not isinstance(record, dict) or set(record) - {'fixture', 'aliases', 'facts', 'require_verified', 'step_seq', 'source_ref'} or 'fixture' not in record:
        raise ConfigError('Invalid test-data requirement structure')
    if record['fixture'] is not None:
        _name(record['fixture'])
    _facts(record.get('facts', {}))
    aliases = record.get('aliases', ())
    if not isinstance(aliases, (tuple, list)) or any(not is_alias(a) or a.split('.')[0] != record['fixture'] for a in aliases):
        raise ConfigError('Required aliases must belong to the specified fixture')
    if type(record.get('require_verified', True)) is not bool or record.get('step_seq') is not None and (type(record['step_seq']) is not int or record['step_seq'] < 1):
        raise ConfigError('Invalid fact assurance or step sequence')
    source = record.get('source_ref', '')
    if not isinstance(source, str) or source and not _SAFE_ID.fullmatch(source):
        raise ConfigError('Invalid public source reference')
    return DataRequirement(record['fixture'], tuple(aliases), deepcopy(record.get('facts', {})),
                           record.get('require_verified', True), record.get('step_seq'), source)


def _source_needs(case):
    """Only complete explicit Given shapes; never infer from testcase IDs/names."""
    needs = []
    patterns = [
        (r'Phiên anonymous ở /[A-Za-z0-9_./?=&-]*; tài khoản customer đang hoạt động và mật khẩu đúng do người vận hành cung cấp', 'correct_password', {'account_exists': True, 'role': 'customer', 'account_state': 'active', 'password_valid': True}),
        (r'Phiên anonymous ở /[A-Za-z0-9_./?=&-]*; email của tài khoản hoạt động và mật khẩu sai đã xác nhận', 'wrong_password', {'account_exists': True, 'account_state': 'active', 'password_valid': False}),
        (r'Phiên anonymous ở /[A-Za-z0-9_./?=&-]*; tài khoản có isActive=false đã được chuẩn bị bởi người vận hành', 'non_empty_password', {'account_exists': True, 'account_state': 'locked'}),
    ]
    source_texts = []
    for step in case.steps:
        if step.kind.value != 'given':
            continue
        source_texts.append((step.seq, step.args.get('description', '')))
        for line in step.note.splitlines():
            for marker in ('[source-clause] ', '[mapper-clause] ', '[resolution-expansion] '):
                if not line.startswith(marker):
                    continue
                try:
                    record = json.loads(line[len(marker):])
                    if record.get('testcase_id', case.id) != case.id:
                        continue
                    if marker == '[source-clause] ' and record.get('field') == 'given':
                        source_texts.append((step.seq, record.get('text', '')))
                    elif marker == '[mapper-clause] ':
                        source_texts.append((record.get('source_step_seq', step.seq), record.get('source_text', '')))
                    elif marker == '[resolution-expansion] ' and record.get('source_step', {}).get('kind') == 'given':
                        original = record['source_step']
                        source_texts.append((original['seq'], original.get('args', {}).get('description', '')))
                except (ValueError, TypeError, AttributeError, KeyError):
                    continue
    seen = set()
    for seq, text in source_texts:
        if not isinstance(text, str) or text in seen:
            continue
        seen.add(text)
        for pattern, password_key, facts in patterns:
            if not isinstance(text, str) or not re.fullmatch(pattern, text):
                continue
            aliases = (case.test_data.get('email'), case.test_data.get(password_key))
            if all(is_alias(a) for a in aliases):
                name = aliases[0].split('.')[0]
                if all(a.split('.')[0] == name for a in aliases):
                    needs.append(DataRequirement(name, aliases, facts, step_seq=seq, source_ref=f'testcase-step:{seq}'))
                else:
                    needs.append(DataRequirement(None, facts=facts, step_seq=seq, source_ref=f'testcase-step:{seq}'))
            else:
                needs.append(DataRequirement(None, facts=facts, step_seq=seq, source_ref=f'testcase-step:{seq}'))
    return needs


def has_test_data_requirements(case, fixture_store=None):
    """Cheap exact-signal gate; no binding, acquisition or network work."""
    if case.test_data.get(DATA_REQUIREMENTS) or _source_needs(case):
        return True
    if any(is_alias(v) for v in case.test_data.values()) or any(
        s.action == 'ui.fill' and is_alias(s.args.get('value')) for s in case.steps
    ):
        return True
    if fixture_store:
        sources = (*case.traces_to, case.id)
        metadata = fixture_store.to_dict()
        return any(metadata['bindings'].get(source) or
                   fixture_store.acquisition_config.get('requirements', {}).get(source)
                   for source in sources)
    return False


def acquire_test_data(case, *, fixture_store: FixtureStore | None = None,
                      requirements=None, sources: dict | None = None, endpoints=(),
                      verification=None, provisioning=None):
    """Bind only existing config aliases into a detached copy, then inspect evidence.

    Explicit needs/config IDs take priority over narrow source Given extraction.
    Config/seed facts remain declarations, even if an operator labels them verified.
    Verification is explicit and separate; this function never makes network calls.
    PROVISIONABLE never satisfies executability.
    """
    config = validate_acquisition_config(sources if sources is not None else
                                         fixture_store.acquisition_config if fixture_store else {})
    try:
        bound = fixture_store.bind(case) if fixture_store else deepcopy(case)
    except ConfigError:
        return DataAcquisitionResult(deepcopy(case), (), ({'code':'AMBIGUOUS_TEST_DATA', 'message':'Conflicting trusted fixture bindings.'},))
    needs = list(requirements) if requirements is not None else [
        _requirement({**record, 'source_ref':record.get('source_ref') or source}) for source in (*case.traces_to, case.id)
        for record in config.get('requirements', {}).get(source, [])]
    if not needs:
        needs = [_requirement(record) for record in bound.test_data.get(DATA_REQUIREMENTS, [])]
    if not needs:
        needs = _source_needs(bound)
    needs = [_requirement(asdict(n)) if isinstance(n, DataRequirement) else _requirement(n) for n in needs]
    # Alias use itself is an explicit data need even without a state obligation.
    used = {v for v in bound.test_data.values() if is_alias(v)}
    used.update(s.args['value'] for s in bound.steps if s.action == 'ui.fill' and is_alias(s.args.get('value')))
    covered = {a for n in needs for a in n.aliases}
    for alias in sorted(used - covered):
        needs.append(DataRequirement(alias.split('.')[0], (alias,)))
    if len(needs)>MAX_DATA_REQUIREMENTS:
        return DataAcquisitionResult(bound, (), ({'code':'MISSING_TEST_DATA', 'message':'Data acquisition requirement budget exceeded.'},))
    if needs:
        # A later step expansion must not erase the original data obligation.
        bound.test_data[DATA_REQUIREMENTS] = [{**asdict(n), 'aliases': list(n.aliases)} for n in needs]
    live_evidence = ()
    verification_audit = {}
    provisioning_audit = {}
    if verification is not None:
        from .test_data_verification import VerificationResult
        if not isinstance(verification, VerificationResult) or fixture_store is None:
            raise ConfigError('Acquisition requires a runtime verification receipt')
        live_evidence = verification.evidence_for(bound, fixture_store)
        verification_audit = verification.to_dict()
    if provisioning is not None:
        from .test_data_provisioning import ProvisioningResult
        if not isinstance(provisioning, ProvisioningResult) or fixture_store is None:
            raise ConfigError('Acquisition requires a runtime provisioning receipt')
        live_evidence += provisioning.evidence_for(bound, fixture_store, endpoints)
        provisioning_audit = provisioning.to_dict()
    metadata = fixture_store.to_dict() if fixture_store else {'aliases':{}, 'facts':{}}
    findings, issues = [], []
    for need in needs:
        evidence = []
        declared = metadata.get('facts', {}).get(need.fixture)
        if declared:
            evidence.append({'facts':declared['values'], 'assurance':'DECLARED', 'source':declared['source']})
        literal = bound.test_data.get('entity_id')
        if isinstance(literal, str) and need.facts.get('entity_id') == literal:
            _facts({'entity_id':literal})
            evidence.append({'facts':{'entity_id':literal}, 'assurance':'REQUIREMENT_LITERAL',
                             'source':{'type':'testcase_literal','testcase_id':bound.id,'field':'test_data.entity_id'}})
        evidence.extend({'facts':r['facts'], 'assurance':r['assurance'],
                         'source':{'type':'trusted_metadata', 'ref':r['source_ref']}}
                        for r in config.get('evidence', []) if r['fixture']==need.fixture)
        evidence.extend(r for r in live_evidence if r['fixture'] == need.fixture)
        aliases = tuple({'alias':a, 'available':bool(fixture_store and metadata['aliases'].get(a, {}).get('available')),
                         'source':deepcopy(metadata['aliases'].get(a, {}).get('source', {'type':'missing-fixture'}))} for a in need.aliases)
        facts = []
        for name, expected in need.facts.items():
            items = tuple({'value':r['facts'][name], 'assurance':r['assurance'], 'source':r['source']}
                          for r in evidence if name in r['facts'])
            values = {r['value'] for r in items}
            if len(values)>1 or values and expected not in values:
                status = 'CONFLICT'
            elif name=='entity_id' and any(r['assurance']=='REQUIREMENT_LITERAL' for r in items):
                status = 'LITERAL'
            elif any(r['assurance']=='VERIFIED' for r in items):
                status = 'VERIFIED'
            elif items:
                status = 'DECLARED'
            else:
                status = 'UNVERIFIED'
            facts.append(FactFinding(name, expected, status, items))
        missing = [f for f in facts if f.status not in ({'LITERAL','VERIFIED'} if need.require_verified else {'LITERAL','VERIFIED','DECLARED'})]
        paths = []
        for path in config.get('provisioning', []):
            if path['fixture'] != need.fixture or any(path['provides'].get(f.fact) != f.expected for f in missing):
                continue
            operations = [op for op in endpoints if op.operation_id==path['operation_id']]
            if len(operations)!=1:
                continue
            op = operations[0]
            reviewed = [r for r in config.get('provisioning_rules', [])
                        if r['fixture']==need.fixture and r['operation_id']==op.operation_id]
            whitelisted = len(reviewed)==1 and reviewed[0]['policy']['approved'] and (
                reviewed[0]['policy']['mutation_type']=='create_fixture' and
                op.operation_id in reviewed[0]['policy']['whitelisted_operations'])
            unsafe = op.requires_auth or (bool(_UNSAFE_PATH.search(op.path)) and not whitelisted) or op.method.upper()!='POST' or path['external_interaction']
            # POST + declared 201 is a narrow creation contract, not a prose match.
            if not unsafe and '201' not in op.responses:
                continue
            paths.append({'method':op.method, 'path':op.path, 'operation_id':op.operation_id,
                          'provides':deepcopy(path['provides']), 'safe_candidate':not bool(unsafe),
                          'execution_allowed':False, 'source':{'type':'openapi', 'operation_id':op.operation_id},
                          'metadata_source':{'type':'config','fixture':need.fixture,'field':'acquisition.provisioning'}})
        live_conflict = any(r['fixture'] == need.fixture and r['outcome'] == 'AMBIGUOUS'
                            for r in verification_audit.get('observations', []))
        if any(f.status=='CONFLICT' for f in facts) or live_conflict:
            status = DataStatus.AMBIGUOUS
        elif all(a['available'] for a in aliases) and not missing:
            status = DataStatus.AVAILABLE
        elif any(p['safe_candidate'] for p in paths):
            status = DataStatus.PROVISIONABLE
        elif paths:
            status = DataStatus.UNSAFE_TO_PROVISION
        else:
            status = DataStatus.MISSING_TEST_DATA
        findings.append(DataFinding(need,status,aliases,tuple(facts),tuple(paths)))
        if status != DataStatus.AVAILABLE:
            code = 'MISSING_FIXTURE' if any(not a['available'] for a in aliases) and status==DataStatus.MISSING_TEST_DATA else (
                'UNVERIFIED_TEST_DATA' if missing and status==DataStatus.MISSING_TEST_DATA else status.value)
            issues.append({'code':code, 'fixture':need.fixture, 'step_seq':need.step_seq,
                           'message':('Data remains unproven after provisioning.' if provisioning_audit.get('calls')
                                      else 'Data is not proven available; no provisioning performed.')})
    result = DataAcquisitionResult(bound,tuple(findings),tuple(issues),verification_audit,provisioning_audit)
    # All public facts/references must be independent of resolved credential values.
    if fixture_store and fixture_store.redact(result.to_dict()) != result.to_dict():
        raise ConfigError('Test-data evidence contains a fixture secret')
    return result

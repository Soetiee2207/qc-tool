"""One explicitly approved fixture creation in a declared test environment.

No model selection, credential generation, retries, redirects or cleanup execution.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from urllib.parse import urlsplit

from qctool.config import ConfigError
from qctool.data.fixtures import is_alias, FixtureUnavailable
from qctool.data.acquisition import DataStatus, _facts, _name, _SAFE_ID
from qctool.data.verification import (
    _Receipt, _stamp, _once, parse_verification_rules, MAX_TIMEOUT_SECONDS,
)

MAX_PROVISIONING_RULES = 8
_TEST_ENVIRONMENTS = {'local', 'test', 'staging'}
_RESTRICTED = re.compile(r'(^|[/_.-])(admin|seed|delete|remove|payment|purchase|upload|reset)([/_.-]|$)', re.I)
_EXTERNAL = re.compile(r'(^|[/_.-])(register|registration|signup|otp)([/_.-]|$)', re.I)
_SECRET_FIELD = re.compile(r'password|secret|token|credential|authorization|cookie|email|phone|api[_-]?key|private[_-]?key', re.I)


class ProvisioningStatus(str, Enum):
    PROVISIONED = 'PROVISIONED'
    FAILED = 'FAILED'
    UNSAFE_TO_PROVISION = 'UNSAFE_TO_PROVISION'
    AMBIGUOUS = 'AMBIGUOUS'
    NEEDS_EXTERNAL_INTERACTION = 'NEEDS_EXTERNAL_INTERACTION'


@dataclass(frozen=True)
class ProvisioningRule:
    fixture: str
    operation_id: str
    inputs: dict
    expected: dict
    establishes: dict
    verification_required: bool
    cleanup: dict
    policy: dict
    source_ref: str


def parse_provisioning_rules(records):
    if not isinstance(records, list) or len(records) > MAX_PROVISIONING_RULES:
        raise ConfigError('Provisioning requires a bounded list of reviewed rules')
    rules = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {
            'fixture','operation_id','inputs','expected','establishes','verification_required','cleanup','policy','source_ref'
        }:
            raise ConfigError('Invalid provisioning rule fields')
        _name(record['fixture']); _facts(record['establishes'])
        if type(record['verification_required']) is not bool:
            raise ConfigError('Provisioning requires explicit post-verification policy')
        policy = record['policy']
        if not isinstance(policy, dict) or set(policy) != {
            'approved','allowed_environment','allowed_base_urls','mutation_type','external_interaction','whitelisted_operations'
        } or any(type(policy[k]) is not bool for k in ('approved','external_interaction')):
            raise ConfigError('Invalid provisioning environment/mutation policy')
        if not isinstance(policy['allowed_environment'], str) or not isinstance(policy['mutation_type'], str):
            raise ConfigError('Invalid provisioning environment/mutation labels')
        for key in ('allowed_base_urls', 'whitelisted_operations'):
            if not isinstance(policy[key], list) or any(not isinstance(v, str) for v in policy[key]) or len(policy[key]) > 8:
                raise ConfigError('Provisioning policy requires bounded URL/operation lists')
        for key in ('operation_id','source_ref'):
            if not isinstance(record[key], str) or not _SAFE_ID.fullmatch(record[key]):
                raise ConfigError('Provisioning requires exact public operation/source references')
        inputs = record['inputs']
        if not isinstance(inputs, dict) or len(inputs) > 16:
            raise ConfigError('Provisioning requires bounded JSON input fields')
        for key, spec in inputs.items():
            if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', key) or not isinstance(spec, dict):
                raise ConfigError('Invalid provisioning input')
            if set(spec) == {'alias'}:
                if not is_alias(spec['alias']) or spec['alias'].split('.')[0] != record['fixture']:
                    raise ConfigError('Provisioning aliases must belong to the required fixture')
            elif set(spec) == {'literal'}:
                value = spec['literal']
                if _SECRET_FIELD.search(key) or type(value) not in {str,int,bool} or isinstance(value,str) and (len(value)>80 or not re.fullmatch(r'[A-Za-z0-9_ .-]*',value)):
                    raise ConfigError('Provisioning literals must be bounded public values')
            else:
                raise ConfigError('Provisioning inputs allow exact aliases or public literals only')
        cleanup = record['cleanup']
        if not isinstance(cleanup,dict) or set(cleanup) - {'operation_id','source_ref'} or any(not isinstance(v,str) or not _SAFE_ID.fullmatch(v) for v in cleanup.values()):
            raise ConfigError('Cleanup is public operation/reference metadata only')
        # Reuse closed public signatures/facts; no token/body/header predicates.
        parse_verification_rules([{
            'fixture':record['fixture'],'operation_id':record['operation_id'],
            'body_aliases':{}, 'expected':record['expected'],
            'proves':record['establishes'],
            'policy':{'approved':False,'test_data_mutation':False,'side_effects':[]},
            'source_ref':record['source_ref'],
        }])
        rules.append(ProvisioningRule(**deepcopy(record)))
    return tuple(rules)


@dataclass(frozen=True)
class ProvisioningObservation:
    fixture: str | None
    operation_id: str | None
    outcome: ProvisioningStatus
    code: str
    attempted: bool = False
    status: int | None = None
    facts: dict = field(default_factory=dict)
    source: dict = field(default_factory=dict)
    cleanup: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProvisioningResult:
    observation: ProvisioningObservation
    _receipt: object = field(default=None,repr=False,compare=False)

    @property
    def status(self):
        return self.observation.outcome

    def to_dict(self):
        return {'status':self.status.value, 'calls':int(self.observation.attempted),
                'observation':asdict(self.observation)}

    def evidence_for(self, case, store, endpoints):
        if not isinstance(self._receipt, _Receipt):
            raise ConfigError('Provisioning requires an authentic runtime receipt')
        self._receipt.validate(case, store, (self.observation,))
        operations = [op for op in endpoints if op.operation_id == self.observation.operation_id]
        if len(operations) != 1 or asdict(operations[0]) != getattr(self._receipt,'provisioning_contract',None):
            raise ConfigError('Provisioning receipt contract is stale or absent')
        return ({'fixture':self.observation.fixture, 'facts':deepcopy(self.observation.facts),
                 'assurance':'VERIFIED', 'source':deepcopy(self.observation.source)},) if (
                     self.status == ProvisioningStatus.PROVISIONED and self.observation.facts) else ()


def validate_provisioning_rule(rule, acquisition, store, endpoints, base_url, environment):
    """No alias resolution or HTTP. Only explicit reviewed metadata permits mutation."""
    policy = rule.policy
    words = re.sub(r'([a-z])([A-Z])',r'\1_\2',rule.operation_id)
    if policy['external_interaction'] or _EXTERNAL.search(words):
        return None, ProvisioningStatus.NEEDS_EXTERNAL_INTERACTION, 'EXTERNAL_INTERACTION'
    if not policy['approved'] or environment not in _TEST_ENVIRONMENTS or policy['allowed_environment'] != environment or policy['mutation_type'] != 'create_fixture':
        return None, ProvisioningStatus.UNSAFE_TO_PROVISION, 'ENVIRONMENT_POLICY_DENIED'
    operations = [op for op in endpoints if op.operation_id == rule.operation_id]
    if len(operations) != 1:
        return None, ProvisioningStatus.AMBIGUOUS, 'OPERATION_NOT_UNIQUE'
    op = operations[0]
    if _EXTERNAL.search(op.path):
        return None, ProvisioningStatus.NEEDS_EXTERNAL_INTERACTION, 'EXTERNAL_INTERACTION'
    try:
        parts = urlsplit(base_url); parts.port
    except (ValueError,TypeError,AttributeError):
        return None, ProvisioningStatus.UNSAFE_TO_PROVISION, 'INVALID_BASE_URL'
    if parts.scheme not in {'http','https'} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or any(ord(c)<33 for c in base_url) or '%' in parts.path or '\\' in parts.path or '..' in parts.path.split('/'):
        return None, ProvisioningStatus.UNSAFE_TO_PROVISION, 'INVALID_BASE_URL'
    if base_url.rstrip('/') not in [u.rstrip('/') for u in policy['allowed_base_urls']]:
        return None, ProvisioningStatus.UNSAFE_TO_PROVISION, 'BACKEND_NOT_ALLOWED'
    servers = op.servers or op.contract_servers
    if servers and base_url.rstrip('/') not in [s.rstrip('/') for s in servers]:
        return None, ProvisioningStatus.UNSAFE_TO_PROVISION, 'CONTRACT_SERVER_MISMATCH'
    if not re.fullmatch(r'/[A-Za-z0-9_./~-]*',op.path) or op.path.startswith('//') or '..' in op.path.split('/') or op.method.upper()!='POST' or op.requires_auth or any(p.get('required') for p in op.parameters):
        return None, ProvisioningStatus.UNSAFE_TO_PROVISION, 'UNSUPPORTED_CREATION_CONTRACT'
    if (_RESTRICTED.search(op.path) or _RESTRICTED.search(words)) and op.operation_id not in policy['whitelisted_operations']:
        return None, ProvisioningStatus.UNSAFE_TO_PROVISION, 'OPERATION_NOT_WHITELISTED'
    if rule.expected['status'] != 201 or '201' not in op.responses:
        return None, ProvisioningStatus.UNSAFE_TO_PROVISION, 'CREATION_SIGNATURE_REQUIRED'
    findings = [f for f in acquisition.findings if f.requirement.fixture == rule.fixture]
    required_values = {}
    for finding in findings:
        for fact in finding.facts:
            required_values.setdefault(fact.fact,set()).add(fact.expected)
    if any(len(values)>1 for values in required_values.values()):
        return None, ProvisioningStatus.AMBIGUOUS, 'CONFLICTING_REQUIRED_FACTS'
    required = {f.fact:f.expected for finding in findings for f in finding.facts}
    if not findings or any(required.get(k) != v for k,v in rule.establishes.items()):
        return None, ProvisioningStatus.UNSAFE_TO_PROVISION, 'UNRELATED_FACTS'
    if any(not a['available'] for finding in findings for a in finding.aliases):
        return None, ProvisioningStatus.UNSAFE_TO_PROVISION, 'MISSING_REQUIRED_ALIAS'
    schema = op.request_body or {}
    properties = schema.get('properties',{})
    if schema.get('type')!='object' or set(rule.inputs)-set(properties) or set(op.request_required)-set(rule.inputs):
        return None, ProvisioningStatus.UNSAFE_TO_PROVISION, 'INVALID_REQUEST_CONTRACT'
    bound = {a['alias'] for f in findings for a in f.aliases}
    metadata = store.to_dict()['aliases']
    for key,spec in rule.inputs.items():
        prop = properties[key]
        if 'alias' in spec:
            alias = spec['alias']
            if prop.get('type')!='string' or alias not in bound or not metadata.get(alias,{}).get('available'):
                return None, ProvisioningStatus.UNSAFE_TO_PROVISION, 'MISSING_REQUIRED_ALIAS'
        else:
            value = spec['literal']
            types = {str:'string',int:'integer',bool:'boolean'}
            if prop.get('type') != types[type(value)] or 'enum' in prop and value not in prop['enum']:
                return None, ProvisioningStatus.UNSAFE_TO_PROVISION, 'INVALID_LITERAL'
    return (op,base_url.rstrip('/')+op.path), None, None


def provision_test_data(acquisition, *, fixture_store, endpoints=(), base_url=None,
                        environment=None, enabled=False, timeout=MAX_TIMEOUT_SECONDS, transport=None):
    """Select exactly one configured rule and perform at most one approved call."""
    def blocked(status,code,rule=None):
        return ProvisioningResult(ProvisioningObservation(rule.fixture if rule else None,
                                  rule.operation_id if rule else None,status,code))
    if enabled is not True:
        return blocked(ProvisioningStatus.UNSAFE_TO_PROVISION,'PROVISIONING_DISABLED')
    if type(timeout) not in {int,float} or not 0<timeout<=MAX_TIMEOUT_SECONDS:
        raise ConfigError('Provisioning timeout must be positive and at most ten seconds')
    rules = parse_provisioning_rules(fixture_store.acquisition_config.get('provisioning_rules',[]))
    candidates = {(f.requirement.fixture,p['operation_id']) for f in acquisition.findings for p in f.provisioning}
    matches = [r for r in rules if (r.fixture,r.operation_id) in candidates]
    if len(matches)!=1:
        return blocked(ProvisioningStatus.AMBIGUOUS if matches else ProvisioningStatus.UNSAFE_TO_PROVISION,
                       'MULTIPLE_RULES' if matches else 'NO_REVIEWED_RULE')
    rule = matches[0]
    approved,status,code = validate_provisioning_rule(rule,acquisition,fixture_store,endpoints,base_url,environment)
    if not approved:
        return blocked(status,code,rule)
    if acquisition.status != DataStatus.PROVISIONABLE:
        return blocked(ProvisioningStatus.UNSAFE_TO_PROVISION,'NOT_PROVISIONABLE',rule)
    stamp,metadata = _stamp(fixture_store),fixture_store.to_dict()
    op,url = approved
    try:
        body = {k:fixture_store.resolve(v['alias']) if 'alias' in v else v['literal'] for k,v in rule.inputs.items()}
    except FixtureUnavailable:
        return blocked(ProvisioningStatus.UNSAFE_TO_PROVISION,'MISSING_REQUIRED_ALIAS',rule)
    source = {'type':'live_provisioning','operation_id':op.operation_id,'method':op.method,
              'path':op.path,'policy_ref':rule.source_ref,'environment':environment,
              'base_url':base_url.rstrip('/'),
              'observed_at':datetime.now(timezone.utc).isoformat(),
              'verification_required':rule.verification_required,
              'aliases':[v['alias'] for v in rule.inputs.values() if 'alias' in v]}
    facts = {}
    try:
        response = (transport or _once)('POST',url,body,timeout)
        http_status = response.get('status')
        if type(http_status) is not int or not 100<=http_status<=599:
            http_status = None
        data = response.get('body')
        matched = not response.get('error') and http_status==rule.expected['status'] and isinstance(data,dict) and all(
            path[2:] in data and type(data[path[2:]]) is type(value) and data[path[2:]]==value
            for path,value in rule.expected['json'].items())
        outcome,code = (ProvisioningStatus.PROVISIONED,'SIGNATURE_MATCHED') if matched else (ProvisioningStatus.FAILED,'SIGNATURE_NOT_MET')
        if matched and not rule.verification_required:
            facts = deepcopy(rule.establishes)
    except Exception:
        outcome,code,http_status = ProvisioningStatus.FAILED,'TRANSPORT_FAILED',None
    if stamp != _stamp(fixture_store) or metadata != fixture_store.to_dict():
        outcome,code,facts = ProvisioningStatus.FAILED,'FIXTURE_CHANGED',{}
    observation = ProvisioningObservation(rule.fixture,rule.operation_id,outcome,code,True,http_status,facts,source,deepcopy(rule.cleanup))
    receipt = _Receipt(acquisition.case,fixture_store,(observation,))
    receipt.provisioning_contract = deepcopy(asdict(op))
    result = ProvisioningResult(observation,receipt)
    if fixture_store.redact(result.to_dict()) != result.to_dict():
        raise ConfigError('Provisioning metadata contains a fixture secret')
    return result

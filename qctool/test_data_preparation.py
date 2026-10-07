"""One acquisition -> approved verification -> reacquisition attempt.

Only trusted config selects operations and implications. Provisioning is opt-in;
no model selection, retry loop or verification from credential presence alone.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from enum import Enum

from .config import ConfigError
from .test_data_acquisition import (
    DataAcquisitionResult, DataStatus, acquire_test_data, has_test_data_requirements,
)
from .test_data_verification import (
    VerificationResult, VerificationStatus, parse_verification_rules,
    validate_verification_rule, verify_test_data,
)
from .testcase import TestCase
from .test_data_provisioning import ProvisioningResult, ProvisioningStatus, provision_test_data


class PreparationStatus(str, Enum):
    NO_DATA_REQUIRED = 'NO_DATA_REQUIRED'
    AVAILABLE = 'AVAILABLE'
    MISSING_FIXTURE = 'MISSING_FIXTURE'
    UNVERIFIED_TEST_DATA = 'UNVERIFIED_TEST_DATA'
    INVALID_TEST_DATA = 'INVALID_TEST_DATA'
    UNSAFE_TO_VERIFY = 'UNSAFE_TO_VERIFY'
    AMBIGUOUS = 'AMBIGUOUS'
    PROVISIONABLE = 'PROVISIONABLE'
    UNSAFE_TO_PROVISION = 'UNSAFE_TO_PROVISION'
    PROVISIONING_FAILED = 'PROVISIONING_FAILED'
    NEEDS_EXTERNAL_INTERACTION = 'NEEDS_EXTERNAL_INTERACTION'


@dataclass(frozen=True)
class PreparationStage:
    stage: str
    status: str
    reason: str


@dataclass(frozen=True)
class TestDataPreparationResult:
    case: TestCase = field(repr=False)
    status: PreparationStatus
    initial: DataAcquisitionResult | None
    final: DataAcquisitionResult | None
    verification: VerificationResult | None = field(default=None, repr=False)
    verification_attempted: bool = False
    verification_reason: str = ''
    blockers: tuple[dict, ...] = ()
    stages: tuple[PreparationStage, ...] = ()
    rule_decisions: tuple[dict, ...] = ()
    provisioning: ProvisioningResult | None = field(default=None, repr=False)
    provisioning_reason: str = 'PROVISIONING_DISABLED'

    @property
    def available(self):
        return self.status in {PreparationStatus.AVAILABLE, PreparationStatus.NO_DATA_REQUIRED}

    @property
    def provisioning_attempted(self):
        return bool(self.provisioning and self.provisioning.observation.attempted and
                    self.provisioning_reason != 'PROVISIONING_RECEIPT_REUSED')

    def to_dict(self):
        # Never export the private receipt or arbitrary testcase test_data values.
        return {'testcase_id': self.case.id, 'status': self.status.value,
                'initial': self.initial.to_dict() if self.initial else None,
                'final': self.final.to_dict() if self.final else None,
                'verification': self.verification.to_dict() if self.verification else None,
                'verification_attempted': self.verification_attempted,
                'verification_reason': self.verification_reason,
                'blockers': deepcopy(list(self.blockers)),
                'stages': [asdict(s) for s in self.stages],
                'rule_decisions': deepcopy(list(self.rule_decisions)),
                'provisioning': self.provisioning.to_dict() if self.provisioning else None,
                'provisioning_attempted': self.provisioning_attempted,
                'provisioning_reason': self.provisioning_reason}

    def context_data(self):
        if self.final is None:
            return {}
        data = self.final.to_dict()
        data['issues'] = deepcopy(list(self.blockers))
        data['preparation'] = self.to_dict()
        return data


def _status(acquisition, blockers):
    codes = {b['code'] for b in blockers}
    if codes & {'AMBIGUOUS', 'AMBIGUOUS_TEST_DATA', 'AMBIGUOUS_VERIFICATION'}:
        return PreparationStatus.AMBIGUOUS
    if 'NEEDS_EXTERNAL_INTERACTION' in codes:
        return PreparationStatus.NEEDS_EXTERNAL_INTERACTION
    if 'PROVISIONING_FAILED' in codes:
        return PreparationStatus.PROVISIONING_FAILED
    if codes & {'UNSAFE_TO_PROVISION','PROVISIONING_RECEIPT_REJECTED'}:
        return PreparationStatus.UNSAFE_TO_PROVISION
    if 'INVALID_TEST_DATA' in codes:
        return PreparationStatus.INVALID_TEST_DATA
    if acquisition.status == DataStatus.PROVISIONABLE:
        return PreparationStatus.PROVISIONABLE
    if acquisition.status == DataStatus.UNSAFE_TO_PROVISION:
        return PreparationStatus.UNSAFE_TO_PROVISION
    if 'MISSING_FIXTURE' in codes:
        return PreparationStatus.MISSING_FIXTURE
    if 'UNSAFE_TO_VERIFY' in codes:
        return PreparationStatus.UNSAFE_TO_VERIFY
    if acquisition.status == DataStatus.AVAILABLE and not blockers:
        return PreparationStatus.AVAILABLE
    return PreparationStatus.UNVERIFIED_TEST_DATA


def prepare_test_data(case, *, fixture_store=None, endpoints=(), base_url=None,
                      requirements=None, verification=None, transport=None,
                      allow_provisioning=False, environment=None,
                      provisioning_transport=None, provisioning_receipt=None):
    """Prepare a detached testcase once, making <=3 calls only for missing facts.

    ``verification`` is optional backward compatibility for a runtime receipt;
    an invalid/stale receipt blocks the attempt rather than triggering new calls.
    Contract servers supply the backend URL when there is one exact common server;
    the frontend base URL is used only when the contract has no servers or matches.
    Blocked copies are manual so context-free coverage/runner paths cannot accept
    an otherwise mapped case. Source steps, expectations and provenance stay intact.
    """
    original = deepcopy(case)
    if requirements is None and verification is None and provisioning_receipt is None and not has_test_data_requirements(case, fixture_store):
        return TestDataPreparationResult(original, PreparationStatus.NO_DATA_REQUIRED, None, None,
                                        verification_reason='NO_DATA_REQUIRED',
                                        stages=(PreparationStage('acquisition', 'SKIPPED', 'NO_DATA_REQUIRED'),
                                                PreparationStage('verification', 'SKIPPED', 'NO_DATA_REQUIRED')))
    stages, decisions, extra = [], [], []
    initial = acquire_test_data(case, fixture_store=fixture_store, endpoints=endpoints, requirements=requirements)
    stages.append(PreparationStage('acquisition', 'COMPLETED', initial.status.value))
    final, receipt = initial, None
    provision = None
    provision_reason = ('ALREADY_AVAILABLE' if initial.status == DataStatus.AVAILABLE else 'NOT_PROVISIONABLE') if allow_provisioning is True else 'PROVISIONING_DISABLED'
    verification_input = initial
    provision_blocked = False
    if provisioning_receipt is not None:
        try:
            if allow_provisioning is not True or not isinstance(provisioning_receipt, ProvisioningResult) or provisioning_receipt.status != ProvisioningStatus.PROVISIONED or provisioning_receipt.observation.source.get('environment') != environment:
                raise ConfigError('Provisioning receipt environment mismatch')
            if base_url is not None and base_url.rstrip('/') != provisioning_receipt.observation.source.get('base_url'):
                raise ConfigError('Provisioning receipt backend mismatch')
            final = acquire_test_data(initial.case, fixture_store=fixture_store, endpoints=endpoints,
                                      provisioning=provisioning_receipt)
            provision = provisioning_receipt
            verification_input = final
            provision_reason = 'PROVISIONING_RECEIPT_REUSED'
        except ConfigError:
            provision_blocked = True
            provision_reason = 'PROVISIONING_RECEIPT_REJECTED'
            extra.append({'code':provision_reason, 'message':'Provisioning receipt absent, stale or environment mismatched; no call made.'})
    elif allow_provisioning is True and initial.status in {DataStatus.PROVISIONABLE, DataStatus.UNSAFE_TO_PROVISION} and fixture_store:
        provision = provision_test_data(initial, fixture_store=fixture_store, endpoints=endpoints,
                                        base_url=base_url, environment=environment, enabled=True,
                                        transport=provisioning_transport)
        provision_reason = provision.observation.code
        if provision.status == ProvisioningStatus.PROVISIONED:
            try:
                final = acquire_test_data(initial.case, fixture_store=fixture_store, endpoints=endpoints,
                                          provisioning=provision)
                verification_input = final
            except ConfigError:
                provision_blocked = True
                extra.append({'code':'PROVISIONING_RECEIPT_REJECTED','message':'Provisioning receipt could not be accepted.'})
        else:
            provision_blocked = True
            code = 'PROVISIONING_FAILED' if provision.status == ProvisioningStatus.FAILED else provision.status.value
            extra.append({'code':code,'message':f'Provisioning stopped: {provision.observation.code}.'})
    if allow_provisioning is True or provisioning_receipt is not None:
        stages.append(PreparationStage('provisioning', provision.status.value if provision else 'SKIPPED', provision_reason))
    reason = 'NO_REVIEWED_RULE'
    attempted = False
    if provision_blocked:
        reason = 'PROVISIONING_BLOCKED'
    elif verification is not None:
        try:
            final = acquire_test_data(initial.case, fixture_store=fixture_store, endpoints=endpoints,
                                      verification=verification, provisioning=provision)
            receipt = verification
            reason = 'RECEIPT_REUSED'
        except ConfigError:
            reason = 'RECEIPT_REJECTED'
            extra.append({'code': 'VERIFICATION_RECEIPT_REJECTED',
                          'message': 'Absent, stale or mismatched runtime receipt; no verification call made.'})
    elif verification_input.status == DataStatus.AVAILABLE:
        reason = 'ALREADY_AVAILABLE'
    elif verification_input.status == DataStatus.AMBIGUOUS:
        reason = 'AMBIGUOUS_DATA'
    elif fixture_store:
        rules = parse_verification_rules(fixture_store.acquisition_config.get('verification', []))
        relevant = []
        for index, rule in enumerate(rules):
            findings = [f for f in verification_input.findings if f.requirement.fixture == rule.fixture]
            missing_facts = {fact.fact for f in findings for fact in f.facts
                             if fact.status not in ({'VERIFIED','LITERAL'} if f.requirement.require_verified
                                                    else {'VERIFIED','LITERAL','DECLARED'})}
            if not set(rule.proves) & missing_facts:
                continue  # Credential-only data is never a verification trigger.
            if any(not a['available'] for f in findings for a in f.aliases):
                decisions.append({'fixture':rule.fixture, 'operation_id':rule.operation_id,
                                  'code':'MISSING_VALUES'})
                continue
            relevant.append((index, rule))
        # Select a backend only from the exact operation's declared servers.
        # Unsafe alternatives must not prevent an independently approved rule.
        approved_rules = []
        for index, rule in relevant:
            operations = [op for op in endpoints if op.operation_id == rule.operation_id]
            backend = base_url.rstrip('/') if isinstance(base_url, str) else None
            ambiguous_server = False
            if len(operations) == 1:
                declared = {s.rstrip('/') for s in (operations[0].servers or operations[0].contract_servers)}
                if declared and backend not in declared:
                    backend = next(iter(declared)) if len(declared) == 1 else None
                    ambiguous_server = backend is None
            approved, error = validate_verification_rule(rule, verification_input, fixture_store, endpoints, backend)
            if ambiguous_server:
                approved, error = None, 'AMBIGUOUS_BASE_URL'
            elif backend is None and error == 'UNSAFE_ORIGIN':
                error = 'BASE_URL_REQUIRED'
            decisions.append({'fixture':rule.fixture, 'operation_id':rule.operation_id,
                              'code':error or 'APPROVED'})
            if approved:
                approved_rules.append((index, rule, backend))
            else:
                code = ('AMBIGUOUS_VERIFICATION' if error in {'AMBIGUOUS','AMBIGUOUS_BASE_URL'}
                        else 'UNVERIFIED_TEST_DATA' if error in {'MISSING_FIXTURE','OPERATION_NOT_FOUND','UNRELATED_FACTS','BASE_URL_REQUIRED'}
                        else 'UNSAFE_TO_VERIFY')
                extra.append({'code':code, 'fixture':rule.fixture,
                              'message':f'No verification call: {error}.'})
        origins = {backend for _, _, backend in approved_rules}
        if len(origins) > 1:
            extra.extend({'code':'AMBIGUOUS_VERIFICATION', 'fixture':r.fixture,
                          'message':'Approved rules require multiple backends; no call made.'}
                         for _, r, _ in approved_rules)
            selected = []
        else:
            selected = [index for index, _, _ in approved_rules]
            backend = next(iter(origins)) if origins else None
        if selected:
            try:
                receipt = verify_test_data(verification_input, fixture_store=fixture_store, endpoints=endpoints,
                                           base_url=backend, transport=transport, rule_indices=tuple(selected))
                attempted = bool(receipt.to_dict()['calls'])
                final = acquire_test_data(initial.case, fixture_store=fixture_store,
                                          endpoints=endpoints, verification=receipt, provisioning=provision)
                reason = 'VERIFICATION_COMPLETED'
            except ConfigError:
                # Never log config values, exception strings, request or response bodies.
                receipt = None
                reason = 'VERIFICATION_FAILED'
                extra.append({'code':'VERIFICATION_FAILED', 'message':'Verification receipt could not be accepted.'})
        elif relevant:
            reason = 'NO_SAFE_RULE'
        elif decisions:
            reason = 'MISSING_VALUES'
    stages.append(PreparationStage('verification', 'ATTEMPTED' if attempted else 'SKIPPED', reason))
    if provision is not None and provision.status == ProvisioningStatus.PROVISIONED and provision.observation.source.get('verification_required') and receipt is None:
        extra.append({'code':'UNVERIFIED_TEST_DATA', 'message':'Provisioning succeeded; required independent verification is missing.'})
    if receipt:
        for observation in receipt.observations:
            if observation.outcome not in {VerificationStatus.INVALID, VerificationStatus.AMBIGUOUS,
                                           VerificationStatus.UNSAFE_TO_VERIFY}:
                continue
            code = {VerificationStatus.INVALID:'INVALID_TEST_DATA', VerificationStatus.AMBIGUOUS:'AMBIGUOUS_VERIFICATION',
                    VerificationStatus.UNSAFE_TO_VERIFY:'UNSAFE_TO_VERIFY'}[observation.outcome]
            extra.append({'code':code, 'fixture':observation.fixture,
                          'message':f'Existing data verification: {observation.code}; no cause inferred.'})
    provisioned_fixture = provision.observation.fixture if provision is not None and provision.status == ProvisioningStatus.PROVISIONED else None
    if provisioned_fixture is not None and any(f.requirement.fixture == provisioned_fixture and f.status != DataStatus.AVAILABLE for f in final.findings):
        extra.append({'code':'UNVERIFIED_TEST_DATA', 'fixture':provisioned_fixture,
                      'message':'Creation completed; required data facts remain unproven. Do not retry creation.'})
    # Ignore skipped alternative methods only when the required facts are proven.
    unavailable = {f.requirement.fixture for f in final.findings if f.status != DataStatus.AVAILABLE}
    extras = [i for i in extra if i.get('fixture') in unavailable or 'fixture' not in i]
    invalid = {i['fixture'] for i in extras if i['code']=='INVALID_TEST_DATA'}
    blockers = tuple(i for i in deepcopy(final.issues) if not (
        i.get('fixture') in invalid and i['code']=='UNVERIFIED_TEST_DATA') and not (
        provisioned_fixture is not None and i.get('fixture') == provisioned_fixture and i['code']=='PROVISIONABLE')) + tuple(extras)
    status = _status(final, blockers)
    if provision is not None and provision.status == ProvisioningStatus.PROVISIONED and status == PreparationStatus.PROVISIONABLE:
        status = PreparationStatus.UNVERIFIED_TEST_DATA
    working = deepcopy(final.case)
    if blockers:
        working.execution = 'manual'
    stages.append(PreparationStage('reacquisition', 'COMPLETED' if receipt else 'SKIPPED', status.value))
    return TestDataPreparationResult(working, status, initial, final, receipt, attempted, reason,
                                    blockers, tuple(stages), tuple(decisions), provision, provision_reason)

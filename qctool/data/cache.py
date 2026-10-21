"""Bounded runtime preparation reuse; no persisted or model-supplied receipts.

Identity is an ephemeral keyed digest of exact data requirements and all trust
inputs. Source/case IDs are provenance, not data identity. This cache is owned by
one generation run by default; verified facts are never generalized to subsets.
"""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import hmac
import json
import math
import secrets
import time
from enum import Enum

from qctool.config import ConfigError

_KEY = secrets.token_bytes(32)
_SEAL = object()


def _enum(value):
    if isinstance(value, Enum):
        return value.value
    raise TypeError('Unsupported trusted identity value')


def preparation_identity(acquisition, store, endpoints, base_url, environment, enabled):
    needs = []
    for finding in acquisition.findings:
        requirement = asdict(finding.requirement)
        requirement.pop('source_ref', None)
        requirement.pop('step_seq', None)
        requirement['aliases'] = sorted(requirement['aliases'])
        needs.append(requirement)
    # Full config/contract is deliberately conservative. Credentials never leave
    # this keyed digest, which cannot be replayed across process boundaries.
    payload = {'requirements': sorted(needs, key=lambda n: json.dumps(n, sort_keys=True)),
               'config': store.to_dict() if store else None,
               'credentials': store._values if store else None,
               'contract': sorted((asdict(op) for op in endpoints),
                                  key=lambda op: json.dumps(op, sort_keys=True, default=_enum)),
               'backend': base_url, 'environment': environment, 'mutation_enabled': enabled}
    return hmac.new(_KEY, json.dumps(payload, sort_keys=True, separators=(',', ':'), default=_enum).encode(),
                    hashlib.sha256).hexdigest()


class _Entry:
    def __init__(self, identity, result, store, created):
        self.seal, self.identity, self.result, self.store = _SEAL, identity, result, store
        self.source_case_id = result.initial.case.id
        self.created = created


class PreparationCache:
    """Private authentic history; bounded to 128 data identities per run.

    No import/export API. Live assurance expires independently of creation
    history. Freshness is monotonic and configurable by the run owner.
    """
    def __init__(self, *, freshness_seconds=300, clock=time.monotonic):
        if (isinstance(freshness_seconds, bool)
                or not isinstance(freshness_seconds, (int, float))
                or not 0 < freshness_seconds < float('inf')):
            raise ConfigError("Preparation freshness must be positive finite seconds")
        self.freshness_seconds = freshness_seconds
        self._clock = clock
        self._entries = {}

    def _remember(self, identity, result, store, endpoints):
        from qctool.data.preparation import PreparationStatus
        from qctool.data.provisioning import ProvisioningStatus
        # Retain authenticated creation history even when subsequent verification
        # fails. It is not available proof and must not trigger another creation.
        created = result.provisioning and result.provisioning.status == ProvisioningStatus.PROVISIONED
        if not created and (result.status != PreparationStatus.AVAILABLE or result.blockers):
            return
        self._authenticate(result, store, endpoints)
        if len(self._entries) < 128 or identity in self._entries:
            entry = _Entry(identity, result, store, self._clock())
            self._entries[identity] = entry

    @staticmethod
    def _authenticate(result, store, endpoints):
        # Authentication only: expired facts are never acquired through this path.
        from qctool.data.acquisition import DataAcquisitionResult
        from qctool.data.verification import VerificationResult
        from qctool.data.provisioning import ProvisioningResult, ProvisioningStatus
        if not isinstance(result.initial, DataAcquisitionResult):
            raise ConfigError('Preparation history has no authentic acquisition')
        if result.verification is not None and not isinstance(result.verification, VerificationResult):
            raise ConfigError('Preparation history has no authentic verification')
        if result.provisioning is not None and (
                not isinstance(result.provisioning, ProvisioningResult)
                or result.provisioning.status != ProvisioningStatus.PROVISIONED):
            raise ConfigError('Preparation history has no successful provisioning')
        if result.verification:
            result.verification.evidence_for(result.initial.case, store)
        if result.provisioning:
            result.provisioning.evidence_for(result.initial.case, store, endpoints)

    def _reuse(self, identity, acquisition, store, endpoints, **kwargs):
        from qctool.data.verification import _Receipt, VerificationResult
        from qctool.data.provisioning import ProvisioningResult
        from qctool.data.preparation import PreparationStage, TestDataPreparationResult
        entry = self._entries.get(identity)
        if entry is None:
            return None
        now = self._clock()
        if (not isinstance(entry, _Entry) or entry.seal is not _SEAL
                or entry.identity != identity or entry.store is not store
                or type(entry.created) not in (int, float)
                or not math.isfinite(entry.created) or now < entry.created):
            raise ConfigError('Preparation entry is not authentic')
        previous = entry.result
        if not isinstance(previous, TestDataPreparationResult) or previous.initial is None:
            raise ConfigError('Preparation entry contains no authenticated history')
        self._authenticate(previous, store, endpoints)
        # Rebind only after exact identity equality AND authentic original proof.
        # Lower-level evidence_for still checks current case, store and contract.
        case = acquisition.case
        verification, provisioning = None, None
        live_assurance = bool(previous.verification or (previous.provisioning and previous.provisioning.observation.facts))
        stale = live_assurance and now - entry.created > self.freshness_seconds
        if previous.verification and not stale:
            observations = deepcopy(previous.verification.observations)
            verification = VerificationResult(observations, _Receipt(case, store, observations))
        if previous.provisioning:
            observation = deepcopy(previous.provisioning.observation)
            if stale:
                observation = replace(observation, facts={})
            receipt = _Receipt(case, store, (observation,))
            receipt.provisioning_contract = deepcopy(previous.provisioning._receipt.provisioning_contract)
            provisioning = ProvisioningResult(observation, receipt)
        from qctool.data.preparation import _prepare_test_data
        options = dict(kwargs, fixture_store=store, endpoints=endpoints)
        if provisioning:
            options['provisioning_receipt'] = provisioning
        if verification:
            options['verification'] = verification
        if stale:
            # No expired assurance is forwarded; only the creation event survives.
            # Existing preparation selects and validates safe verification rules.
            if provisioning is None:
                # Expiry is not evidence that an existing entity disappeared.
                # Refresh only; never create merely to recover expired assurance.
                options['allow_provisioning'] = False
            result = _prepare_test_data(case, **options)
            mode = ('REVERIFIED' if result.available and result.verification_attempted
                    else 'PREPARED' if result.available else 'UNVERIFIED')
            result = replace(result, preparation_mode=mode, preparation_identity=identity,
                             reused_from_testcase=entry.source_case_id,
                             stages=(PreparationStage('preparation', 'STALE', identity),
                                     PreparationStage('provisioning_history', 'REUSED' if provisioning else 'SKIPPED', identity)) + result.stages +
                                    (PreparationStage('preparation', mode if result.available else 'BLOCKED', result.status.value),))
            self._remember(identity, result, store, endpoints)
            return result
        result = _prepare_test_data(case, **options)
        if result.verification_attempted:
            result = replace(result, preparation_identity=identity,
                             reused_from_testcase=entry.source_case_id,
                             preparation_mode='REVERIFIED' if result.available else 'UNVERIFIED',
                             stages=(PreparationStage('provisioning_history', 'REUSED', identity),) + result.stages)
            self._remember(identity, result, store, endpoints)
            return result
        return replace(result, verification_reason=(
                           'RECEIPT_REUSED' if verification and result.available
                           else 'PREVIOUS_VERIFICATION_FAILED' if verification
                           else result.verification_reason),
                       preparation_mode='REUSED' if result.available else 'UNVERIFIED', preparation_identity=identity,
                       reused_from_testcase=entry.source_case_id,
                       stages=(PreparationStage('acquisition', 'COMPLETED', acquisition.status.value),
                               PreparationStage('preparation', 'REUSED' if result.available else 'BLOCKED', identity)))

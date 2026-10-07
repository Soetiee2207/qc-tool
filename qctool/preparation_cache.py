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
import secrets
import time
from enum import Enum

from .config import ConfigError

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
    def __init__(self, identity, result, store):
        self.seal, self.identity, self.result, self.store = _SEAL, identity, result, store
        self.source_case_id = result.initial.case.id
        self.created = time.monotonic()


class PreparationCache:
    """Private authentic receipts only; bounded to 128 successful preparations.

    No import/export API. Entries expire after five minutes and require the
    original trusted store object as well as identical semantic inputs.
    """
    def __init__(self):
        self._entries = {}

    def _remember(self, identity, result, store, endpoints):
        from .test_data_preparation import PreparationStatus
        from .test_data_verification import VerificationStatus
        from .test_data_provisioning import ProvisioningStatus
        if result.status != PreparationStatus.AVAILABLE or result.blockers:
            return
        if result.verification and result.verification.status != VerificationStatus.VERIFIED:
            return
        if result.provisioning and result.provisioning.status != ProvisioningStatus.PROVISIONED:
            return
        # Authenticate the private runtime evidence before admitting it.
        self._authenticate(result, store, endpoints)
        if len(self._entries) < 128 or identity in self._entries:
            self._entries[identity] = _Entry(identity, result, store)

    @staticmethod
    def _authenticate(result, store, endpoints):
        from .test_data_acquisition import acquire_test_data, DataStatus
        proof = acquire_test_data(result.initial.case, fixture_store=store, endpoints=endpoints,
                                  verification=result.verification, provisioning=result.provisioning)
        if proof.status != DataStatus.AVAILABLE or proof.issues:
            raise ConfigError('Preparation proof is absent or stale')
        return proof

    def _reuse(self, identity, acquisition, store, endpoints):
        from .test_data_acquisition import acquire_test_data, DataStatus
        from .test_data_verification import _Receipt, VerificationResult
        from .test_data_provisioning import ProvisioningResult
        from .test_data_preparation import PreparationStage, TestDataPreparationResult, PreparationStatus
        entry = self._entries.get(identity)
        if entry is None:
            return None
        if not isinstance(entry, _Entry) or entry.seal is not _SEAL or entry.identity != identity or entry.store is not store or not 0 <= time.monotonic() - entry.created <= 300:
            raise ConfigError('Preparation entry is stale or not authentic')
        previous = entry.result
        if not isinstance(previous, TestDataPreparationResult) or previous.status != PreparationStatus.AVAILABLE or previous.blockers or previous.initial is None:
            raise ConfigError('Preparation entry contains no successful proof')
        self._authenticate(previous, store, endpoints)
        # Rebind only after exact identity equality AND authentic original proof.
        # Lower-level evidence_for still checks current case, store and contract.
        case = acquisition.case
        verification, provisioning = None, None
        if previous.verification:
            observations = deepcopy(previous.verification.observations)
            verification = VerificationResult(observations, _Receipt(case, store, observations))
        if previous.provisioning:
            observation = deepcopy(previous.provisioning.observation)
            receipt = _Receipt(case, store, (observation,))
            receipt.provisioning_contract = deepcopy(previous.provisioning._receipt.provisioning_contract)
            provisioning = ProvisioningResult(observation, receipt)
        final = acquire_test_data(case, fixture_store=store, endpoints=endpoints,
                                  verification=verification, provisioning=provisioning)
        if final.status != DataStatus.AVAILABLE or final.issues:
            raise ConfigError('Preparation proof does not satisfy current requirements')
        return replace(previous, case=deepcopy(final.case), initial=acquisition, final=final,
                       verification=verification, provisioning=provisioning,
                       verification_attempted=False, verification_reason='RECEIPT_REUSED',
                       provisioning_reason='PROVISIONING_RECEIPT_REUSED' if provisioning else 'NOT_REQUIRED',
                       preparation_mode='REUSED', preparation_identity=identity,
                       reused_from_testcase=entry.source_case_id,
                       stages=(PreparationStage('acquisition', 'COMPLETED', acquisition.status.value),
                               PreparationStage('preparation', 'REUSED', identity)))

"""Offline checks for the source-derived seven-intent customer input fixture."""
from pathlib import Path

import yaml

from qctool.coverage import analyze_coverage
from qctool.generate.loader import load_endpoints
from qctool.ingest import ingest_feature
from qctool.test_fixtures import FixtureStore

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'samples/customer'


def test_customer_contract_excludes_mutations_and_registration():
    endpoints, warnings, _ = load_endpoints(DOCS / 'openapi.yaml')
    assert not warnings
    assert {(e.method.upper(), e.path) for e in endpoints} == {
        ('POST', '/api/auth/login'), ('GET', '/api/auth/profile'),
        ('GET', '/api/orders/my-orders'), ('GET', '/api/appointments/my-appointments'),
    }
    assert len({e.operation_id for e in endpoints}) == 4


def test_customer_policy_uses_only_env_and_does_not_claim_role_verification():
    config = yaml.safe_load((ROOT / 'qctool.customer.e2e.yaml').read_text())
    assert config['feature'] == 'customer'
    assert config['generation']['profile'] == 'agent'
    assert config['auth']['mode'] == 'manual'
    assert config['provisioning']['enabled'] is False
    assert config['llm']['enabled'] is False
    policy = config['test_fixtures']
    assert policy['fixtures']['active_user']['email'] == {'env': 'QCTOOL_USERNAME'}
    assert policy['fixtures']['active_user']['password'] == {'env': 'QCTOOL_PASSWORD'}
    assert set(policy['bindings']) == {f'AC-customer-001-{n}' for n in (1, 3, 4, 5, 6)}
    store = FixtureStore(policy['fixtures'], policy['bindings'], environ={},
                         acquisition=policy['acquisition'])
    assert not store.to_dict()['aliases']['active_user.password']['available']
    assert not policy['acquisition'].get('verification')
    assert all(not row['require_verified'] for rows in policy['acquisition']['requirements'].values()
               for row in rows)
    evidence, = policy['acquisition']['evidence']
    assert evidence['assurance'] == 'DECLARED'
    assert evidence['facts']['password_valid'] is True
    assert not policy['acquisition'].get('provisioning_rules')

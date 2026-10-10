"""Offline checks for the source-derived seven-intent customer input fixture."""
from pathlib import Path

import yaml

from qctool.core.coverage import analyze_coverage
from qctool.generate.loader import load_endpoints
from qctool.ingest import ingest_feature
from qctool.data.fixtures import FixtureStore

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'projects/salonhub/customer'


def test_customer_contract_excludes_mutations_and_registration():
    endpoints, warnings, _ = load_endpoints(DOCS / 'openapi.yaml')
    assert not warnings
    assert {(e.method.upper(), e.path) for e in endpoints} == {
        ('POST', '/api/auth/login'), ('GET', '/api/auth/profile'),
        ('GET', '/api/orders/my-orders'), ('GET', '/api/appointments/my-appointments'),
    }
    assert len({e.operation_id for e in endpoints}) == 4


def test_customer_policy_uses_only_env_and_does_not_claim_role_verification():
    from qctool.config import expand_project
    path = ROOT / 'projects' / 'salonhub' / 'customer' / 'qctool.yaml'
    config = expand_project(yaml.safe_load(path.read_text()), path, ROOT)
    assert config['feature'] == 'customer'
    assert config['auth']['mode'] == 'browser'  # agent cần macro đăng nhập
    assert not (config.get('provisioning') or {}).get('enabled', False)
    assert config['llm']['enabled'] is True                         # từ project.yaml
    assert config['web_url'] == 'https://salonhub-soe.vercel.app'     # từ project.yaml
    assert config['docs_dir'] == '.' and config['out']['dir'] == 'artifacts'
    assert config['test_fixtures']['fixtures']['active_user']['facts']['role'] == 'customer'
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


def test_account_shorthand_binds_only_listed_acceptance_criteria(tmp_path):
    from qctool.config import expand_project
    path = tmp_path / 'shop' / 'qctool.yaml'
    config = expand_project({'docs': 'docs', 'account': {'login_for': ['001-1', 'AC-shop-002-1']}}, path, tmp_path)
    assert config['module'] == 'SHOP' and config['auth']['mode'] == 'browser'
    policy = config['test_fixtures']
    assert set(policy['bindings']) == {'AC-shop-001-1', 'AC-shop-002-1'}
    assert policy['acquisition']['requirements']['AC-shop-002-1'][0]['source_ref'] == 'shop/docs/urd.md:AC-002-1'
    assert expand_project({'account': {'login_for': []}, 'auth': {'mode': 'manual'}}, path)['auth']['mode'] == 'manual'


def test_yaml_evidence_off_is_not_silently_on_fail(tmp_path):
    from qctool.pipeline import PipelineConfig
    path = tmp_path / 'qctool.yaml'
    path.write_text('ui:\n  evidence: off\n')
    assert PipelineConfig.from_file(path).ui_evidence == 'off'

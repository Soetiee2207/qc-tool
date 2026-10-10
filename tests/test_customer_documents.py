"""Offline checks cho input SalonHub (projects/salonhub/) — viết từ source thật."""
from pathlib import Path
import re

import pytest
import yaml

from qctool.config import expand_project
from qctool.generate.loader import load_endpoints
from qctool.ingest import ingest_feature
from qctool.data.fixtures import FixtureStore

ROOT = Path(__file__).resolve().parents[1]
SALONHUB = ROOT / 'projects/salonhub'
FEATURES = sorted(p.parent for p in SALONHUB.glob('*/qctool.yaml'))


def test_salonhub_has_customer_features():
    assert {f.name for f in FEATURES} >= {'auth', 'profile', 'services', 'products', 'cart_checkout',
                                          'appointments', 'orders', 'addresses', 'notifications', 'contact', 'home'}


@pytest.mark.parametrize('feature', FEATURES, ids=lambda p: p.name)
def test_openapi_write_operations_are_observe_only(feature):
    """API ghi trên production chỉ ở dạng observe-only: generator không sinh case gọi chúng,
    agent chỉ gửi khi `mode: write` đã được xác nhận."""
    from qctool.generate import generate_all
    endpoints, warnings, _ = load_endpoints(feature / 'openapi.yaml')
    assert endpoints and not warnings
    for e in endpoints:
        assert e.method.upper() == 'GET' or e.observe_only or (e.method.upper(), e.path) == ('POST', '/api/auth/login'), e
    cases, _, _ = generate_all(None, feature / 'openapi.yaml', 'M')
    observe = {(e.method.upper(), e.path) for e in endpoints if e.observe_only}
    sent = {(str(st.args.get('method', '')).upper(), st.args.get('path')) for c in cases for st in c.steps}
    assert not observe & sent


@pytest.mark.parametrize('feature', FEATURES, ids=lambda p: p.name)
def test_login_bindings_match_docs_and_use_env_only(feature):
    path = feature / 'qctool.yaml'
    config = expand_project(yaml.safe_load(path.read_text()) or {}, path, ROOT)
    urd = (feature / 'urd.md').read_text()
    acs = set(re.findall(r'^\| AC-(\d{3}-\d+) \|', urd, re.M))
    assert acs == {r['id'].split(f"AC-{feature.name}-")[1] for r in ingest_feature(feature, feature.name)['requirements']
                   if r['kind'] == 'acceptance_criterion'}
    needs_account = {ac for ac in acs if re.search(rf'^\| AC-{ac} \|[^|]*fixture active_user', urd, re.M)}
    raw_account = (yaml.safe_load(path.read_text()) or {}).get('account') or {}
    fake = {f'AC-{feature.name}-{ac}' for ac in raw_account.get('test_values', {})}
    policy = config.get('test_fixtures')
    if not needs_account and not fake:
        assert policy is None and (config.get('auth') or {}).get('mode') != 'browser'
        return
    assert set(policy['bindings']) == {f'AC-{feature.name}-{ac}' for ac in needs_account} | fake
    if not needs_account:
        return
    assert config['auth']['mode'] == 'browser'
    assert policy['fixtures']['active_user']['email'] == {'env': 'QCTOOL_USERNAME'}
    assert policy['fixtures']['active_user']['facts']['role'] == 'customer'
    store = FixtureStore(policy['fixtures'], policy['bindings'], environ={}, acquisition=policy['acquisition'])
    assert not store.to_dict()['aliases']['active_user.password']['available']


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


def test_project_account_role_without_login_for_means_anonymous_feature(tmp_path):
    from qctool.config import expand_project
    (tmp_path / 'project.yaml').write_text('account:\n  role: customer\n')
    path = tmp_path / 'contact' / 'qctool.yaml'
    path.parent.mkdir()
    config = expand_project({}, path, tmp_path)
    assert 'test_fixtures' not in config and 'auth' not in config


def test_test_values_become_per_ac_fixtures_and_merge_with_explicit_fixtures(tmp_path):
    path = tmp_path / 'shop' / 'auth' / 'qctool.yaml'
    config = expand_project({'account': {'role': 'customer', 'login_for': ['001-1'],
                                         'test_values': {'001-3': {'password': 'Sai123'}}},
                             'test_fixtures': {'fixtures': {'extra': {'token': {'value': 'tok-QC-extra-9'}}}}}, path, tmp_path)
    policy = config['test_fixtures']
    assert set(policy['fixtures']) == {'active_user', 'ac_001_3', 'extra'}      # merge sâu, không ghi đè
    assert policy['bindings']['AC-auth-001-3'] == {'password': 'ac_001_3.password'}
    store = FixtureStore(policy['fixtures'], policy['bindings'], environ={}, acquisition=policy['acquisition'])
    assert store.resolve('ac_001_3.password') == 'Sai123'

"""Login-only smoke scope; no network, registration, or provisioning calls."""
from copy import deepcopy
from pathlib import Path
import secrets

import yaml

from qctool.coverage import analyze_coverage
from qctool.coverage_plan import plan_coverage
from qctool.executability import analyze_executability
from qctool.generate.loader import load_endpoints
from qctool.ingest import ingest_one
from qctool.pipeline import PipelineConfig
from qctool.resolve import resolve_deterministically
from qctool.ui.crawl import UIMap, PageMap

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / 'samples/smoke'


def test_registration_exclusion_is_explicit_and_not_a_coverage_obligation():
    frontmatter = yaml.safe_load((SMOKE/'URD.md').read_text().split('---', 2)[1])
    exclusion = frontmatter['smoke_scope']['excluded']
    assert exclusion == [{
        'id': 'SMOKE-REGISTRATION-OTP', 'status': 'OUT_OF_SCOPE_FOR_SMOKE',
        'reason': 'requires external OTP/mailbox interaction',
        'operations': ['POST /api/auth/register', 'POST /api/auth/verify-registration-otp'],
        'coverage_claim': False,
    }]
    manifest = ingest_one(SMOKE, 'salonhub-smoke')
    report = analyze_coverage(manifest['requirements'], [])
    obligations = report.missing_obligations
    assert {o.source.source_id for o in obligations} == {
        f'AC-salonhub-smoke-001-{i}' for i in range(1, 5)}
    assert len(obligations) == 4
    assert not any(r.requirement_id == exclusion[0]['id'] for r in report.requirements)
    plan = plan_coverage(report, module='SALON_AUTH')
    assert len(plan.cases) == 4
    assert all('register' not in s.args.get('description', '').lower()
               and 'otp' not in s.args.get('description', '').lower()
               for case in plan.cases for s in case.steps)
    endpoints, _, _ = load_endpoints(SMOKE/'openapi.yaml')
    assert [(e.method, e.path) for e in endpoints] == [('POST', '/api/auth/login')]


def test_unverified_credentials_do_not_become_trusted_active_smoke_data(monkeypatch):
    # Even available env credentials are not a verified active account. The
    # fixture is intentionally absent, while its logical bindings remain intact.
    monkeypatch.setenv('QCTOOL_USERNAME', 'unverified-smoke@example.test')
    monkeypatch.setenv('QCTOOL_PASSWORD', secrets.token_urlsafe(24))
    cfg = PipelineConfig.from_file(ROOT/'qctool.smoke.yaml')
    manifest = ingest_one(SMOKE, 'salonhub-smoke')
    plan = plan_coverage(analyze_coverage(manifest['requirements'], []), module='SALON_AUTH')
    happy = next(c for c in plan.cases if c.traces_to == ['AC-salonhub-smoke-001-1'])
    before = deepcopy(happy)
    bound = cfg.fixture_store.bind(happy)
    assert bound.test_data['email'] == 'active_user.email'
    assert bound.test_data['correct_password'] == 'active_user.password'
    assert not bound.test_data['_fixture_refs']['active_user.email']['available']
    assert not bound.test_data['_fixture_refs']['active_user.password']['available']
    assert not cfg.fixture_store.proves_account_precondition(bound.test_data, role='customer', account_state='active')
    result = resolve_deterministically(bound, fixture_store=cfg.fixture_store,
        ui_map=UIMap('https://salonhub-soe.vercel.app', 'offline', [
            PageMap('https://salonhub-soe.vercel.app/login', 'Login')]))
    assert result.case == bound and not result.changes
    assert not result.after.executable
    assert any(g.code == 'MISSING_FIXTURE' for g in result.after.gaps)
    assert happy == before

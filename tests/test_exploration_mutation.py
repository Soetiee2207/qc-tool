"""Reviewed mutation permissions on a disposable local application only."""
from copy import deepcopy
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest

from qctool.executability import analyze_executability
from qctool.exploration_actions import mutation_policy, MutationBudget
from qctool.exploration_execution import execute_validated_exploration
from qctool.exploration_plan import ExplorationPlan, PlannedExploration, ExplorationPurpose, validate_exploration_plan
from qctool.generate.from_openapi import IdAllocator
from qctool.generate.from_requirements import generate_from_acceptance
from qctool.llm_exploration import build_exploration_prompt
from qctool.pipeline import PipelineConfig
from qctool.resolution_context import build_resolution_context
from qctool.semantic_ir import parse_semantics, validate_semantics
from qctool.ui.crawl import Element, PageMap, UIMap
from qctool.ui.explore import ExplorationAction, explore_page


def inputs(base='https://store.example.test'):
    req = {'id': 'AC-PURCHASE', 'kind': 'acceptance_criterion', 'given': 'Open /basket',
           'when': 'click Checkout; click Create item',
           'then': 'POST /api/items returns 201 with success=true; URL /done'}
    case = generate_from_acceptance([req], IdAllocator(), 'STORE').cases[0]
    ui = UIMap(base, 'recorded', [
        PageMap(base + '/basket', 'Basket', elements=[Element('next', 'link', 'Checkout', 'a', test_id='next', href='/checkout')]),
        PageMap(base + '/checkout', 'Checkout', elements=[Element('submit', 'button', 'Create item', 'button', test_id='submit')]),
    ])
    context = build_resolution_context(case, analyze_executability(case).gaps, requirements=[req], ui_map=ui)
    context.observations['ui_pages'] = [p.to_dict() for p in ui.pages]
    context.interface_contract['api_operations'] = [{'operation_id': 'createItem', 'method': 'POST', 'path': '/api/items', 'servers': [base]}]
    policy = mutation_policy({'enabled': True, 'environment': 'local', 'allowed_environment': 'local',
        'application_origin': base, 'rules': [
            {'id': 'open-checkout', 'requirement_id': req['id'], 'page': '/basket', 'target': 'next',
             'expected_url': '/checkout', 'max_attempts': 1},
            {'id': 'create-item', 'requirement_id': req['id'], 'page': '/checkout', 'target': 'submit',
             'expected_url': '/done', 'max_attempts': 1,
             'operation': {'operation_id': 'createItem', 'method': 'POST', 'path': '/api/items', 'origin': base,
                           'required_json': {'mode': 'offline'}, 'allowed_json_fields': ['mode', 'reference']}}
        ]})
    context = replace(context, mutation_permissions=deepcopy(policy))
    plan = ExplorationPlan(case.id, (PlannedExploration('/basket',
        (ExplorationPurpose('UNMAPPED_ACTION', 2, 'Observe required creation', 'observe_network'),),
        actions=(ExplorationAction('next', 2, page='/basket', expected_url='/checkout'),
                 ExplorationAction('submit', 2, page='/checkout', expected_url='/done'))),))
    return case, context, ui, policy, plan


def approve(case, context, ui, policy, plan):
    return validate_exploration_plan(plan, context, case, ui.base_url, mutation_policy=policy)


def test_default_off_and_exact_permission_immutable():
    case, context, ui, policy, plan = inputs()
    before = deepcopy((case, context, ui, policy, plan))
    assert not validate_exploration_plan(plan, context, case, ui.base_url).valid_requests
    result = approve(case, context, ui, policy, plan)
    assert result.status == 'VALID', result.issues
    bindings = [g for g in result.valid_requests[0].grounding if g['source'] == 'validated_action']
    assert bindings[-1]['capture_requests']['path'] == '/api/items'
    assert bindings[-1]['mutation_permission']['rule']['operation']['required_json'] == {'mode': 'offline'}
    assert (case, context, ui, policy, plan) == before
    assert 'REVIEWED MUTATION PERMISSIONS' in build_exploration_prompt(context)


@pytest.mark.parametrize('change', ['origin', 'requirement', 'target', 'page', 'destination', 'ambiguous', 'contract', 'operation_id', 'source_operation', 'method'])
def test_reject_scope_or_grounding_mismatch(change):
    case, context, ui, policy, plan = inputs()
    if change == 'origin': policy['application_origin'] = 'https://foreign.example.test'
    if change == 'requirement': policy['rules'][0]['requirement_id'] = 'OTHER'
    if change == 'target': policy['rules'][0]['target'] = 'invented'
    if change == 'page': policy['rules'][0]['page'] = '/other'
    if change == 'destination': policy['rules'][0]['expected_url'] = '/other'
    if change == 'ambiguous': context.observations['ui_pages'][0]['elements'] *= 2
    if change == 'contract': context.interface_contract['api_operations'] = []
    if change == 'operation_id': context.interface_contract['api_operations'][0]['operation_id'] = 'other'
    if change == 'source_operation': context.specification['requirements'][0]['then'] = 'URL /done'
    if change == 'method': context.interface_contract['api_operations'][0]['method'] = 'PUT'
    assert not approve(case, context, ui, policy, plan).valid_requests


@pytest.mark.parametrize('change', ['environment', 'admin', 'seed', 'delete', 'payment', 'secret_field', 'secret_value', 'budget', 'unknown_field', 'bad_origin'])
def test_reject_invalid_or_high_risk_policy(change):
    _, _, _, policy, _ = inputs()
    if change == 'environment': policy['environment'] = 'production'
    if change in {'admin', 'seed', 'delete', 'payment'}: policy['rules'][1]['operation']['path'] = '/api/' + change
    if change == 'secret_field': policy['rules'][1]['operation']['allowed_json_fields'].append('password')
    if change == 'secret_value': policy['rules'][1]['operation']['required_json']['mode'] = 'Bearer PRIVATE_KEY'
    if change == 'budget': policy['rules'][1]['max_attempts'] = 0
    if change == 'unknown_field': policy['all_access'] = True
    if change == 'bad_origin': policy['application_origin'] = 'file://localhost'
    with pytest.raises(ValueError): mutation_policy(policy)


def test_source_semantics_require_reviewed_permission_not_just_untrusted_ir():
    case, context, _, policy, _ = inputs()
    normalization = parse_semantics({'clauses': [
        {'step_seq': 2, 'clause_index': 0, 'source_text': 'click Checkout',
         'atoms': [{'kind': 'activate', 'args': {'label': 'Checkout', 'role': 'link'}}]},
        {'step_seq': 2, 'clause_index': 1, 'source_text': 'click Create item',
         'atoms': [{'kind': 'activate', 'args': {'label': 'Create item', 'role': 'button'}}]},
    ]})
    validated, issues = validate_semantics(normalization, context)
    assert validated.clauses and not any(i.step_seq == 2 for i in issues), issues
    blocked, issues = validate_semantics(normalization, replace(context, mutation_permissions={}))
    assert not blocked.clauses and issues


def test_config_default_off_and_enabled_preflight(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('feature: unit\n')
    assert not PipelineConfig.from_file(path).exploration_mutation
    _, _, _, policy, _ = inputs()
    import yaml
    path.write_text(yaml.safe_dump({'feature': 'unit', 'exploration': {'mutation': policy}}))
    assert PipelineConfig.from_file(path).exploration_mutation == policy
    policy['environment'] = 'wrong'
    path.write_text(yaml.safe_dump({'exploration': {'mutation': policy}}))
    from qctool.config import ConfigError
    with pytest.raises(ConfigError): PipelineConfig.from_file(path)


def test_fixture_credential_cannot_be_a_public_policy_constraint():
    from qctool.test_fixtures import FixtureStore
    _, _, _, policy, _ = inputs()
    store = FixtureStore({'user': {'email': {'env': 'USER_EMAIL'}}}, {},
                         environ={'USER_EMAIL': 'PRIVATE_FIXTURE@example.test'})
    policy['rules'][1]['operation']['required_json']['mode'] = 'PRIVATE_FIXTURE@example.test'
    with pytest.raises(ValueError, match='Fixture credentials') as error:
        mutation_policy(policy, fixture_store=store)
    assert 'PRIVATE_FIXTURE@example.test' not in str(error.value)


def test_mutation_requires_reapproved_runtime_policy_before_browser(monkeypatch):
    case, context, ui, policy, plan = inputs()
    approved = approve(case, context, ui, policy, plan).valid_requests[0]
    monkeypatch.setattr('qctool.ui.explore.BrowserSession', lambda *a, **k: pytest.fail('Browser must not open'))
    result = explore_page(approved, base_url=ui.base_url)
    assert result.issues[0].code == 'MUTATION_NOT_AUTHORIZED'
    other = deepcopy(policy); other['rules'][0]['max_attempts'] = 2
    result = explore_page(approved, base_url=ui.base_url, mutation_policy=other, mutation_budget=MutationBudget())
    assert result.issues[0].code == 'MUTATION_NOT_AUTHORIZED'


def test_pipeline_forwards_trusted_policy_and_generation_owns_budget(monkeypatch, tmp_path):
    from tests.test_pipeline_generation import setup, route_case
    import qctool.pipeline as pipeline
    import qctool.generation as generation
    _, _, _, policy, _ = inputs()
    cfg = setup(monkeypatch, tmp_path, cases=[route_case()], exploration_mutation=policy)
    calls = []
    original = generation.run_coverage_loop
    def spy(*args, **kwargs):
        calls.append((deepcopy(kwargs['mutation_policy']), kwargs['mutation_budget']))
        return original(*args, **kwargs)
    monkeypatch.setattr(generation, 'run_coverage_loop', spy)
    result = pipeline.run_pipeline(cfg)
    assert result.ok
    assert calls[0][0] == policy and isinstance(calls[0][1], MutationBudget)
    assert deepcopy(calls[0][1]) is calls[0][1]
    second = pipeline.run_pipeline(cfg)
    assert second.ok and calls[1][1] is not calls[0][1]


@pytest.fixture
def app():
    counts = {'writes': 0, 'wrong': 0}
    state = {'mode': 'offline', 'duplicate': False, 'wrong_path': False, 'extra_field': False, 'redirect': False, 'bootstrap': False}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', '0')))
            counts['writes' if self.path == '/api/items' else 'wrong'] += 1
            if state['redirect']:
                self.send_response(307); self.send_header('Location', '/api/other'); self.end_headers(); return
            self.send_response(201); self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(b'{"success":true,"token":"SECRET_RESPONSE"}')
        def do_GET(self):
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
            if self.path == '/basket':
                html = '<a data-testid="next" href="/checkout">Checkout</a>'
                if state['bootstrap']:
                    html += '<script>fetch("/api/items", {method:"POST",body:"{}"}).catch(()=>{});</script>'
            elif self.path == '/checkout':
                payload = {'mode': state['mode'], 'reference': 'public'}
                if state['extra_field']: payload['unexpected'] = 'no'
                body = json.dumps(json.dumps(payload))
                endpoint = '/api/other' if state['wrong_path'] else '/api/items'
                twice = f"await fetch('{endpoint}', opts);" if state['duplicate'] else ''
                html = f'''<button data-testid="submit">Create item</button><script>
                document.querySelector('button').onclick=async()=>{{
                  const opts={{method:'POST',headers:{{'Content-Type':'application/json'}},body:{body}}};
                  try {{ await fetch('{endpoint}', opts); {twice} location.href='/done'; }} catch(e){{}}
                }};</script>'''
            else: html = '<h1>Created</h1>'
            self.wfile.write(html.encode())
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield f'http://127.0.0.1:{server.server_port}', counts, state
    server.shutdown(); server.server_close(); thread.join()


@pytest.mark.playwright
def test_approved_creation_real_chromium_once_and_run_budget(app):
    base, counts, _ = app
    case, context, ui, policy, plan = inputs(base)
    before = deepcopy((case, context, ui, policy, plan))
    validation = approve(case, context, ui, policy, plan)
    assert validation.status == 'VALID', validation.issues
    budget = MutationBudget()
    result = execute_validated_exploration(validation, context, base_url=base, mutation_policy=policy, mutation_budget=budget)
    assert result.successful_requests, result.issues
    assert counts == {'writes': 1, 'wrong': 0}
    observation = result.exploration_results[0].action_observations[-1]
    assert observation['request_count'] == 1
    assert observation['mutation']['rule_id'] == 'create-item'
    assert result.exploration_results[0].final_url == base + '/done'
    assert any(r['status'] == 201 for r in result.exploration_results[0].network)
    assert 'SECRET_RESPONSE' not in json.dumps(result.to_dict())
    again = execute_validated_exploration(validation, context, base_url=base, mutation_policy=policy, mutation_budget=budget)
    assert any(i.code == 'MUTATION_BUDGET_EXCEEDED' for i in again.issues)
    assert counts == {'writes': 1, 'wrong': 0}
    assert (case, context, ui, policy, plan) == before


@pytest.mark.playwright
@pytest.mark.parametrize('bad', ['mode', 'wrong_path', 'extra_field', 'duplicate', 'redirect', 'bootstrap'])
def test_runtime_blocks_nonapproved_write_and_never_retries(app, bad):
    base, counts, state = app
    if bad == 'mode': state['mode'] = 'online'
    else: state[bad] = True
    case, context, ui, policy, plan = inputs(base)
    validation = approve(case, context, ui, policy, plan)
    result = execute_validated_exploration(validation, context, base_url=base, mutation_policy=policy, mutation_budget=MutationBudget())
    assert result.failed_requests
    assert any(i.code in {'MUTATION_REQUEST_BLOCKED', 'MUTATION_REDIRECT_BLOCKED', 'UNSAFE_NETWORK_REQUEST'} for i in result.issues), result.issues
    assert counts['wrong'] == 0
    assert counts['writes'] == (1 if bad in {'duplicate', 'redirect'} else 0)

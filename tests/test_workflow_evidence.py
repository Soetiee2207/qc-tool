"""Generic authenticated-prefix/destination evidence; no product constants."""
from copy import deepcopy
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest

from qctool.apply_resolution import apply_validated_resolution
from qctool.executability import analyze_executability
from qctool.exploration_execution import execute_validated_exploration
from qctool.exploration_plan import validate_exploration_plan
from qctool.gap_routing import route_gaps
from qctool.llm_exploration import parse_exploration_plan, build_exploration_prompt
from qctool.llm_resolution import ResolutionProposal, EvidenceReference, AtomicProposal, ProposedChange
from qctool.outcome_grounding import outcome_state
from qctool.proposal_validation import validate_resolution_proposal
from qctool.resolution_context import build_resolution_context
from qctool.resolution_cycle import run_resolution_cycle
from qctool.semantic_ir import parse_semantics, validate_semantics, grounded_proposal
from qctool.testcase import Step, StepKind, TestCase
from qctool.test_fixtures import FixtureStore
from qctool.ui.crawl import Element, PageMap, UIMap
from qctool.workflow_evidence import outcome_needs, workflow_candidates
from tests.test_outcome_grounding import note

BASE = 'https://workflow.example.test'


def inputs(base=BASE, denied=False):
    when = 'Fill email; Fill password; Click Login; Open /destination'
    expected = 'Show Profile heading; Show Customer; URL /destination'
    if denied:
        when = when.replace('/destination', '/admin')
        expected = 'URL /home'
    req = {'id': 'AC-FLOW', 'given': 'Open /entry', 'when': when, 'then': expected}
    prefix = {'id': 'AC-ENTRY', 'given': req['given'], 'when': '; '.join(when.split('; ')[:3]),
              'then': 'POST /api/session returns 200 with success=true; URL /home'}
    case = TestCase('TC_UNIT_001', 'UNIT', 'Source workflow', 'Observe source outcomes', execution='manual',
        traces_to=[req['id']], source_quote=expected, source_ref='fixture:source', steps=[Step(1, StepKind.GIVEN, 'ui.goto', {'url': '/entry'}),
        Step(2, StepKind.WHEN, 'perform.unmapped', {'description': when}, note(req, 'when')),
        Step(3, StepKind.THEN, 'assert.unmapped', {'expected': expected}, note(req, 'then'))])
    store = FixtureStore({'customer': {'email': {'env': 'USER'}, 'password': {'env': 'PASS'}}},
                         {'AC-FLOW': {'email': 'customer.email', 'password': 'customer.password'}},
                         environ={'USER': 'private@example.test', 'PASS': 'PRIVATE_PASSWORD'})
    case = store.bind(case)
    ui = UIMap(base, 'recorded', [PageMap(base + '/entry', 'Entry', elements=[
        Element('email', 'input', 'Email', 'input', input_type='email', test_id='email'),
        Element('password', 'input', 'Password', 'input', input_type='password', test_id='password'),
        Element('submit', 'button', 'Login', 'button', test_id='submit')])])
    context = build_resolution_context(case, analyze_executability(case).gaps, requirements=[req, prefix], ui_map=ui)
    context.interface_contract['api_operations'] = [{'method': 'POST', 'path': '/api/session', 'servers': [base]}]
    clauses = []
    for i, (text, kind, args) in enumerate(zip(when.split('; '), ['fill', 'fill', 'activate', 'navigate'],
            [{'field': 'email', 'value': 'customer.email'}, {'field': 'password', 'value': 'customer.password'},
             {'label': 'Login', 'role': 'button'}, {'route': '/admin' if denied else '/destination'}])):
        clauses.append({'step_seq': 2, 'clause_index': i, 'source_text': text, 'atoms': [{'kind': kind, 'args': args}]})
    for i, text in enumerate(expected.split('; ')):
        kind, args = ('url', {'route': '/home' if denied else '/destination'}) if text.startswith('URL') else (
            'visible', {'text': 'Profile', 'role': 'heading'} if i == 0 else {'text': 'Customer'})
        clauses.append({'step_seq': 3, 'clause_index': i, 'source_text': text, 'atoms': [{'kind': kind, 'args': args}]})
    semantic, issues = validate_semantics(parse_semantics({'clauses': clauses}), context, store)
    assert not issues, issues
    context = replace(context, semantics=semantic.to_dict())
    proposal = grounded_proposal(case, context, store)
    validated = validate_resolution_proposal(proposal, context, case, fixture_store=store)
    assert len(validated.valid_changes) == 1, validated.issues
    case = apply_validated_resolution(case, validated).case
    context = replace(context, testcase=build_resolution_context(case, ()).testcase,
                      gaps=analyze_executability(case).gaps)
    return case, context, ui, store


def plan_for(context, store):
    candidate = workflow_candidates(context, store)[0]
    return parse_exploration_plan(json.dumps({'testcase_id': context.testcase['id'],
        'requests': [{k: v for k, v in candidate.items() if k != 'requirement_id'}]}))


def test_complete_needs_route_to_exploration_not_equivalent_resolution():
    case, context, _, store = inputs()
    before = deepcopy((case, context))
    needs = outcome_needs(case, context, store)
    assert len(needs) == 5
    assert {n['kind'] for n in needs} == {'WORKFLOW_STATE'}
    assert [n['outcome_index'] for n in needs] == [0, 1, 2, 3, 4]
    routed = route_gaps(case, replace(context, evidence_needs=needs), base_url=BASE, fixture_store=store)
    assert routed.selected_capability == 'exploration'
    assert (case, context) == before


def test_one_context_complete_prefix_and_unseen_destination():
    case, context, ui, store = inputs()
    before = deepcopy((case, context, ui))
    plan = plan_for(context, store)
    actions = plan.requests[0].actions
    assert len(actions) == 4
    assert [a.step_seq for a in actions] == [2, 3, 4, 5]
    assert actions[-1].action == 'ui.goto' and actions[-1].url == '/destination'
    approved = validate_exploration_plan(plan, context, case, BASE, fixture_store=store)
    assert approved.status == 'VALID', approved.issues
    assert approved.valid_requests[0].request.collect_network  # prerequisite response metadata, even inspect-only
    bindings = approved.valid_requests[0].grounding
    assert bindings[-2]['capture_requests']['path'] == '/api/session'
    assert bindings[-2]['expected_url'] == BASE + '/home'
    assert bindings[-1]['page'] == BASE + '/home'
    assert bindings[-1]['expected_url'] == BASE + '/destination'
    prompt = build_exploration_prompt(context, fixture_store=store)
    assert 'SOURCE-AUTHORIZED WORKFLOW CANDIDATES' in prompt and '"ui.goto"' in prompt
    assert 'PRIVATE_PASSWORD' not in prompt and 'private@example.test' not in prompt
    assert (case, context, ui) == before


@pytest.mark.parametrize('bad', ['fake_route', 'ambiguous', 'wrong_page', 'wrong_given', 'wrong_prefix', 'foreign', 'negated_transition'])
def test_missing_or_ambiguous_source_chain_rejected(bad):
    case, context, ui, store = inputs()
    plan = plan_for(context, store)
    actions = list(plan.requests[0].actions)
    if bad == 'fake_route': actions[-1] = replace(actions[-1], url='/invented')
    if bad == 'foreign': actions[-1] = replace(actions[-1], url='https://foreign.invalid/destination')
    if bad == 'wrong_page': actions[-1] = replace(actions[-1], page='/entry')
    if bad == 'ambiguous':
        context.observations['ui_pages'][0]['elements'].append({'test_id': 'other', 'name': 'Login', 'role': 'button', 'tag': 'button'})
    if bad == 'wrong_given': context.specification['prerequisites'][0]['given'] = 'Different actor'
    if bad == 'wrong_prefix': context.specification['prerequisites'][0]['when'] = 'Click Login'
    if bad == 'negated_transition': context.specification['prerequisites'][0]['then'] = 'URL not /home'
    plan = replace(plan, requests=(replace(plan.requests[0], actions=tuple(actions)),))
    assert not validate_exploration_plan(plan, context, case, BASE, fixture_store=store).valid_requests


def test_unauthorized_role_route_is_readonly_source_authorized_not_admin_action():
    case, context, _, store = inputs(denied=True)
    plan = plan_for(context, store)
    assert plan.requests[0].actions[-1].url == '/admin'
    assert plan.requests[0].actions[-1].expected_url == '/home'
    approved = validate_exploration_plan(plan, context, case, BASE, fixture_store=store)
    assert approved.status == 'VALID', approved.issues
    assert all(a.action != 'ui.click' or a.target == 'submit' for a in approved.valid_requests[0].request.actions)
    # Merely observing /home cannot prove the source denial workflow.
    assert not grounded_proposal(case, context, store).changes


def test_identical_rejected_planner_state_does_not_repeat_call():
    case, context, _, store = inputs()
    class Planner:
        calls = 0
        def complete(self, prompt):
            self.calls += 1
            return json.dumps({'testcase_id': case.id, 'requests': []})
    planner = Planner()
    first = run_resolution_cycle(case, context, fixture_store=store, base_url=BASE, exploration_llm=planner)
    second = run_resolution_cycle(first.case, first.context, fixture_store=store, base_url=BASE, exploration_llm=planner)
    assert planner.calls == 1
    assert any(i.code == 'NO_NEW_EVIDENCE' for i in second.issues)


@pytest.fixture
def authenticated_app(request):
    counts = {'posts': 0, 'destination': 0}
    background = getattr(request, 'param', None)
    crowded_home = background == 'crowded_home'
    slow_login = background == 'slow_login'
    if crowded_home or slow_login:
        background = None
    foreign = None
    if background:
        counts['foreign_requests'] = 0
        class ForeignHandler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                counts['foreign_requests'] += 1
                self.send_response(200); self.send_header('Access-Control-Allow-Origin', '*'); self.end_headers()
            do_POST = do_GET
        foreign = ThreadingHTTPServer(('127.0.0.1', 0), ForeignHandler)
        foreign_thread = threading.Thread(target=foreign.serve_forever, daemon=True)
        foreign_thread.start()
        counts['foreign_origin'] = f'http://127.0.0.1:{foreign.server_port}'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            counts['posts'] += 1
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            if slow_login:
                import time
                time.sleep(0.6)
            self.send_response(200); self.send_header('Set-Cookie', 'auth=1; Path=/')
            self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(b'{"success":true,"token":"PRIVATE_RESPONSE"}')
        def do_GET(self):
            if self.path == '/destination' and 'auth=1' not in self.headers.get('Cookie', ''):
                self.send_response(302); self.send_header('Location', '/entry'); self.end_headers(); return
            if self.path == '/destination': counts['destination'] += 1
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
            if self.path == '/entry':
                html = '''<label>Email<input type=email data-testid=email></label>
                <label>Password<input type=password data-testid=password></label><button data-testid=submit>Login</button>
                <script>document.querySelector('button').onclick=async()=>{await fetch('/api/session',{method:'POST',body:document.querySelector('[data-testid=password]').value});location.href='/home'};</script>'''
            elif self.path == '/destination':
                html = '<h1>Profile</h1><span>Customer</span><button data-testid=tab>All</button>'
            else: html = '<h1>Home</h1>'
            if self.path == '/home' and crowded_home:
                from qctool.ui.explore import MAX_ELEMENTS
                html += ''.join(f'<span>Unrelated content {i}</span>' for i in range(MAX_ELEMENTS + 20))
            if self.path == '/home' and background:
                method, path = background
                html += f"<script>fetch('http://127.0.0.1:{foreign.server_port}{path}?token=PRIVATE_QUERY',{{method:'{method}'}}).catch(()=>{{}})</script>"
            self.wfile.write(html.encode())
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield f'http://127.0.0.1:{server.server_port}', counts
    server.shutdown(); server.server_close(); thread.join()
    if foreign:
        foreign.shutdown(); foreign.server_close(); foreign_thread.join()


@pytest.mark.playwright
@pytest.mark.parametrize('authenticated_app', [('GET', '/background'), ('POST', '/background'), ('GET', '/delete')], indirect=True)
def test_denied_background_read_does_not_discard_approved_workflow(authenticated_app, request):
    base, counts = authenticated_app
    case, context, ui, store = inputs(base)
    before = deepcopy((case, context, ui))
    approved = validate_exploration_plan(plan_for(context, store), context, case, base, fixture_store=store)
    execution = execute_validated_exploration(approved, context, base_url=base, fixture_store=store, render_wait_ms=0)
    method, path = request.node.callspec.params['authenticated_app']
    assert counts['foreign_requests'] == 0  # No additional network permission.
    codes = [issue.code for issue in execution.issues]
    if method == 'GET' and path == '/background':
        assert codes == ['BACKGROUND_REQUEST_BLOCKED']
        assert counts['destination'] == 1
        assert execution.successful_requests
        assert outcome_state(case.steps[-1], case, execution.context, fixture_store=store)
        proposal = grounded_proposal(case, execution.context, store)
        validation = validate_resolution_proposal(proposal, execution.context, case, fixture_store=store)
        assert apply_validated_resolution(case, validation).after.executable
    else:
        assert 'UNSAFE_NETWORK_REQUEST' in codes
        assert counts['destination'] == 0
        assert not execution.successful_requests
        assert not outcome_state(case.steps[-1], case, execution.context, fixture_store=store)
    assert 'PRIVATE_QUERY' not in json.dumps(execution.to_dict())
    assert (case, context, ui) == before


@pytest.mark.playwright
@pytest.mark.parametrize('authenticated_app', [('GET', '/background')], indirect=True)
def test_exact_contract_read_permission_is_sealed_and_observable(authenticated_app):
    base, counts = authenticated_app
    case, context, ui, store = inputs(base)
    context.interface_contract['background_reads'] = [{'method': 'GET', 'path': '/background',
                                                     'servers': [counts['foreign_origin']]}]
    approved = validate_exploration_plan(plan_for(context, store), context, case, base, fixture_store=store)
    before = deepcopy((case, context, ui, approved))
    execution = execute_validated_exploration(approved, context, base_url=base, fixture_store=store, render_wait_ms=0)
    assert not execution.issues, execution.to_dict()
    assert counts['foreign_requests'] == 1
    assert counts['destination'] == 1
    assert any(n['method'] == 'GET' and n['url'] == counts['foreign_origin'] + '/background'
               for n in execution.exploration_results[0].network)
    assert outcome_state(case.steps[-1], case, execution.context, fixture_store=store)
    assert (case, context, ui, approved) == before
    tampered = deepcopy(approved.valid_requests[0])
    next(g for g in tampered.grounding if g.get('source') == 'validated_action')['read_requests'].append(
        {'method': 'POST', 'path': '/invented', 'origin': counts['foreign_origin']})
    from qctool.ui.explore import explore_page
    result = explore_page(tampered, base_url=base, fixture_store=store)
    assert [i.code for i in result.issues] == ['ACTION_NOT_VALIDATED']
    assert counts['foreign_requests'] == 1


@pytest.mark.playwright
@pytest.mark.parametrize('authenticated_app', ['crowded_home'], indirect=True)
def test_prior_page_truncation_cannot_poison_complete_destination(authenticated_app):
    base, _ = authenticated_app
    case, context, ui, store = inputs(base)
    approved = validate_exploration_plan(plan_for(context, store), context, case, base, fixture_store=store)
    execution = execute_validated_exploration(approved, context, base_url=base, fixture_store=store, render_wait_ms=0)
    observed = execution.exploration_results[0]
    assert not execution.issues
    assert 'elements' in observed.truncated  # Aggregate audit still reports omissions.
    assert 'elements' in observed.states[-2]['truncated']
    assert observed.states[-1]['truncated'] == []
    final = execution.context.observations['page_states'][-1]
    assert final['truncated'] == []
    validation = validate_resolution_proposal(grounded_proposal(case, execution.context, store),
        execution.context, case, fixture_store=store)
    assert apply_validated_resolution(case, validation).after.executable


@pytest.mark.playwright
@pytest.mark.parametrize('authenticated_app', ['slow_login'], indirect=True)
@pytest.mark.parametrize('timeout_ms,expected_status', [(3000, 'Pass'), (200, 'Blocked')])
def test_real_runner_waits_for_click_write_before_navigation(authenticated_app, timeout_ms, expected_status):
    from qctool.execute.browser import BrowserSession
    from qctool.execute.runner import HttpSession, run_cases
    base, counts = authenticated_app
    case, context, _, store = inputs(base)
    approved = validate_exploration_plan(plan_for(context, store), context, case, base, fixture_store=store)
    execution = execute_validated_exploration(approved, context, base_url=base, fixture_store=store, render_wait_ms=0)
    validation = validate_resolution_proposal(grounded_proposal(case, execution.context, store),
        execution.context, case, fixture_store=store)
    applied = apply_validated_resolution(case, validation).case
    before = deepcopy(applied)
    with BrowserSession(base, timeout_ms=timeout_ms) as browser:
        result = run_cases([applied], HttpSession(base), browser=browser, fixture_store=store)
    assert result.cases[0].status == expected_status, (result.cases[0].blocked_reason, result.cases[0].actual)
    if expected_status == 'Pass':
        assert all(step.ok for step in result.cases[0].steps)
        assert result.cases[0].steps[-1].action == 'assert.url_matches'
    else:
        assert 'UI_ACTION_RESPONSE_TIMEOUT' in result.cases[0].blocked_reason
        assert result.cases[0].steps[-1].issue_code == 'UI_ACTION_RESPONSE_TIMEOUT'
    assert applied == before
    assert 'PRIVATE_PASSWORD' not in json.dumps(result.to_dict())


@pytest.mark.playwright
def test_authenticated_prefix_collects_all_unseen_destination_outcomes(authenticated_app):
    base, counts = authenticated_app
    case, context, ui, store = inputs(base)
    before = deepcopy((case, context, ui))
    plan = plan_for(context, store)
    approved = validate_exploration_plan(plan, context, case, base, fixture_store=store)
    assert approved.status == 'VALID', approved.issues
    execution = execute_validated_exploration(approved, context, base_url=base, fixture_store=store, render_wait_ms=0)
    assert not execution.issues, execution.to_dict()
    result = execution.exploration_results[0]
    assert counts == {'posts': 1, 'destination': 1}
    assert [s['page']['url'].removeprefix(base) for s in result.states] == ['/entry', '/entry', '/entry', '/home', '/destination']
    assert outcome_state(case.steps[-1], case, execution.context, fixture_store=store)
    assert not outcome_needs(case, execution.context, store)
    proposal = grounded_proposal(case, execution.context, store)
    assert len(proposal.changes) == 1
    validated = validate_resolution_proposal(proposal, execution.context, case, fixture_store=store)
    assert len(validated.valid_changes) == 1, validated.issues
    assert apply_validated_resolution(case, validated).after.executable
    assert (case, context, ui) == before
    serialized = json.dumps(execution.to_dict())
    assert not any(secret in serialized for secret in ('PRIVATE_PASSWORD', 'PRIVATE_RESPONSE', 'private@example.test'))
    # URL evidence remains, but removing either source text witness keeps ALL outcomes unresolved.
    missing = deepcopy(execution.context)
    current = missing.observations['current_state_id']
    for page in missing.observations['ui_pages']:
        if page.get('state_id') == current:
            page['elements'] = [e for e in page['elements'] if e.get('name') != 'Profile']
    for state in missing.observations['page_states']:
        if state['state_id'] == current:
            state['page']['elements'] = [e for e in state['page']['elements'] if e.get('name') != 'Profile']
    needs = outcome_needs(case, missing, store)
    assert any(n['meaning'].get('hint') == 'Profile' for n in needs)
    assert not grounded_proposal(case, missing, store).changes
    assert route_gaps(case, replace(missing, evidence_needs=needs), base_url=base, fixture_store=store).selected_capability == 'exploration'
    # A same-name navigation entry cannot supply a destination heading.
    wrong = deepcopy(execution.context)
    wrong.observations['current_state_id'] = wrong.observations['page_states'][0]['state_id']
    assert outcome_state(case.steps[-1], case, wrong, fixture_store=store) is None
    ambiguous = deepcopy(execution.context)
    for state in ambiguous.observations['page_states']:
        if state['state_id'] == current:
            heading = next(e for e in state['page']['elements'] if e.get('name') == 'Profile')
            state['page']['elements'].append({**heading, 'id': 'other-heading'})
    assert any(n['meaning'].get('hint') == 'Profile' for n in outcome_needs(case, ambiguous, store))
    for page in ambiguous.observations['ui_pages']:
        if page.get('state_id') == current:
            page['elements'] = deepcopy(next(s['page']['elements'] for s in ambiguous.observations['page_states'] if s['state_id'] == current))
    assert not grounded_proposal(case, ambiguous, store).changes


def test_mapped_url_subset_does_not_complete_source_outcomes():
    case, context, _, store = inputs()
    case.execution = 'auto'
    source = case.steps[-1].note
    case.steps[-1] = Step(case.steps[-1].seq, StepKind.THEN, 'assert.url_matches', {'pattern': '/destination$'}, source)
    report = analyze_executability(case, context=context)
    assert not report.executable
    assert any(g.code == 'SOURCE_OUTCOME_INCOMPLETE' for g in report.gaps)


def test_prefix_contract_selection_keeps_own_outcomes_separate(tmp_path):
    from qctool.generate.loader import load_endpoints
    import yaml
    case, context, _, _ = inputs()
    path = tmp_path / 'contract.yaml'
    path.write_text(yaml.safe_dump({'openapi': '3.0.3', 'servers': [{'url': BASE}], 'paths': {
        '/api/session': {'post': {'operationId': 'session', 'responses': {'200': {'description': 'ok'}}}},
        '/api/unrelated': {'post': {'operationId': 'unrelated', 'responses': {'200': {'description': 'ok'}}}}}}))
    requirements = context.specification['requirements'] + context.specification['prerequisites']
    before = deepcopy((case, requirements))
    rebuilt = build_resolution_context(case, analyze_executability(case).gaps, requirements=requirements,
                                       endpoints=load_endpoints(path)[0])
    assert [op['path'] for op in rebuilt.interface_contract['api_operations']] == ['/api/session']
    assert [r['id'] for r in rebuilt.specification['requirements']] == ['AC-FLOW']
    assert rebuilt.specification['requirements'][0]['then'] == context.specification['requirements'][0]['then']
    assert rebuilt.specification['prerequisites'][0]['evidence']['relation'] == 'exact_workflow_prefix'
    assert (case, requirements) == before


def test_background_contract_reads_are_permissions_not_assertion_authority(tmp_path):
    from qctool.generate.loader import load_endpoints
    from qctool.llm_resolution import _evidence_catalog
    import yaml
    case, context, _, _ = inputs()
    spec = tmp_path / 'contract.yaml'
    spec.write_text(yaml.safe_dump({'openapi': '3.0.3', 'servers': [{'url': 'https://api.example.test'}], 'paths': {
        '/api/session': {'post': {'operationId': 'session', 'responses': {'200': {'description': 'ok'}}}},
        '/api/declared-read': {'get': {'operationId': 'read', 'responses': {'200': {'description': 'ok'}}}},
        '/api/unrelated-write': {'post': {'operationId': 'write', 'responses': {'200': {'description': 'ok'}}}},
        '/api/external': {'get': {'x-external': True, 'operationId': 'external', 'responses': {'200': {'description': 'ok'}}}},
    }}))
    endpoints = load_endpoints(spec)[0]
    before = deepcopy((case, endpoints))
    packet = build_resolution_context(case, context.gaps,
        requirements=context.specification['requirements'] + context.specification['prerequisites'], endpoints=endpoints)
    assert [op['path'] for op in packet.interface_contract['api_operations']] == ['/api/session']
    reads = packet.interface_contract['background_reads']
    assert [(op['method'], op['path'], op['servers']) for op in reads] == [
        ('GET', '/api/declared-read', ['https://api.example.test'])]
    assert reads[0]['evidence'] == {'type': 'openapi', 'operation_id': 'read'}
    assert 'declared-read' not in json.dumps(_evidence_catalog(packet.to_dict()))
    assert (case, endpoints) == before


@pytest.mark.parametrize('route', ['/delete-record', '/payment', '/upload', '/seed'])
def test_source_navigation_never_authorizes_destructive_operation(route):
    from qctool.exploration_actions import navigation_forbidden
    assert navigation_forbidden(route)


def test_known_outcome_ir_selects_missing_witnesses_not_unrelated_dom():
    from qctool.llm_prompt import select_prompt_context
    case, context, _, store = inputs()
    context.observations['ui_pages'][0]['elements'].append({'test_id': 'ad', 'name': 'Unrelated advertisement', 'role': 'link'})
    view = select_prompt_context(context)
    assert not any(e.get('test_id') == 'ad' for p in view['observations']['ui_pages'] for e in p['elements'])
    assert context.specification['requirements'][0]['then'] in json.dumps(view, ensure_ascii=False)
    assert context.observations['ui_pages'][0]['elements'][-1]['test_id'] == 'ad'


def test_available_fixture_precondition_does_not_retrieve_unrelated_dom():
    from qctool.llm_prompt import select_prompt_context
    case, context, _, _ = inputs()
    context.testcase['steps'].insert(0, {
        'seq': 0, 'kind': 'given', 'action': 'perform.unmapped',
        'args': {'description': 'Existing customer account is active'}, 'note': '',
    })
    context.data_acquisition['findings'] = [{
        'requirement': {'fixture': 'customer'}, 'status': 'AVAILABLE',
    }]
    context.observations['ui_pages'][0]['elements'].extend([
        {'test_id': 'ad', 'name': 'Unrelated advertisement', 'role': 'link'},
        {'test_id': 'other-submit', 'name': 'Login', 'role': 'button'},
    ])
    before = deepcopy(context)
    view = select_prompt_context(context)
    elements = [e for p in view['observations']['ui_pages'] for e in p['elements']]
    assert not any(e.get('test_id') == 'ad' for e in elements)
    assert {'submit', 'other-submit'} <= {e.get('test_id') for e in elements}
    assert 'Existing customer account is active' in json.dumps(view)
    assert context == before


def test_session_provenance_does_not_make_all_page_elements_relevant():
    from qctool.llm_prompt import select_prompt_context
    _, context, _, _ = inputs()
    context.testcase['steps'].insert(0, {
        'seq': 0, 'kind': 'given', 'action': 'ui.session',
        'args': {'mode': 'anonymous'}, 'note': 'Original active actor enters application',
    })
    context.observations['ui_pages'][0]['elements'].append({
        'test_id': 'ad', 'name': 'Unrelated advertisement', 'role': 'link',
    })
    view = select_prompt_context(context)
    assert not any(e.get('test_id') == 'ad' for p in view['observations']['ui_pages'] for e in p['elements'])
    assert view['testcase']['steps'][0]['args'] == {'mode': 'anonymous'}
    assert view['testcase']['steps'][0]['note'] == 'Original active actor enters application'


def test_nested_action_observations_project_elements_preserving_provenance():
    from qctool.llm_prompt import select_prompt_context
    _, context, _, _ = inputs()
    page = deepcopy(context.observations['ui_pages'][0])
    page['elements'].extend([
        {'test_id': 'ad', 'name': 'Unrelated advertisement', 'role': 'link'},
        {'test_id': 'other-submit', 'name': 'Login', 'role': 'button'},
    ])
    observation = {'state_id': 'state-1', 'from_state_id': 'state-0', 'action_index': 0,
                   'source_clause': 'Fill email', 'valid_transition': True, 'page': page}
    context.observations['ui_pages'][0]['explorations'] = [{
        'source': {'type': 'playwright_exploration'}, 'action_observations': [observation],
    }]
    before = deepcopy(context)
    view = select_prompt_context(context)
    projected = view['observations']['ui_pages'][0]['explorations'][0]['action_observations'][0]
    assert {k:v for k,v in projected.items() if k != 'page'} == {k:v for k,v in observation.items() if k != 'page'}
    ids = {e.get('test_id') for e in projected['page']['elements']}
    assert 'ad' not in ids and {'submit', 'other-submit'} <= ids
    assert context == before

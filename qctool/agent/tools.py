"""Runtime tools. Model sees redacted observations, never assertion evaluations."""
from copy import deepcopy
import json
import re
from urllib.parse import urlsplit, urlunsplit

from qctool.execute.browser import BrowserSession
from qctool.execute.runner import _run_ui_step, _run_step, HttpSession
from qctool.data.fixtures import is_alias
from qctool.agent.gate import draft_case, check_case
from qctool.agent.safety import SafetyError


def public(value, store=None):
    if store:
        value = store.redact(value)
    if isinstance(value, str):
        value = re.sub(r'\bBearer\s+[^\s"<>]+', 'Bearer [REDACTED]', value, flags=re.I)
        value = re.sub(r'\beyJ[\w-]+\.[\w-]+\.[\w-]+', '[REDACTED]', value)
        value = re.sub(r'(?i)((?:password|secret|token|authorization|cookie)\s*[:=]\s*)[^\s"<>]+', r'\1[REDACTED]', value)
        return value
    if isinstance(value, dict):
        return {k: public(v, store) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [public(v, store) for v in value]
    return value


def safe_url(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc.rsplit('@', 1)[-1], p.path, '', ''))


def locator(page, args):
    # Exact uniqueness on LIVE DOM; never .first() or name fallback from a testid.
    result = page.get_by_test_id(args['target'])
    if result.count() == 0:
        from qctool.execute.browser import _looks_like_test_id
        if args.get('role') and (args.get('by_name', args['target']) == args['target'] or not _looks_like_test_id(args['target'])):
            # ASCII accessible names (e.g. Email) are not automatically test IDs.
            result = page.get_by_role(args['role'], name=args.get('by_name', args['target']), exact=True)
            result.wait_for(state='attached', timeout=15000)
        elif _looks_like_test_id(args['target']):
            # React may not have rendered yet; never substitute a weaker name.
            result.wait_for(state='attached', timeout=15000)
        elif args.get('by_name'):
            result = page.get_by_text(args['by_name'], exact=True)
            result.wait_for(state='attached', timeout=15000)
    if result.count() != 1:
        raise SafetyError('Locator must resolve to exactly one current element')
    return result


class AgentTools:
    def __init__(self, intent, case_id, module, policy, *, storage_state=None,
                 headless=True, knowledge=None, timeout_ms=15000, on_progress=None):
        self.intent, self.case_id, self.module, self.policy = deepcopy(intent), case_id, module, policy
        self.storage_state, self.headless, self.knowledge = storage_state, headless, knowledge
        self.timeout_ms = timeout_ms
        self.on_progress = on_progress or (lambda *_: None)
        self.browser = None
        self.candidate = None
        self.ready = None
        self.audit = []
        self.observations = []
        # What the tool was doing when an exception escaped: turned into feedback
        # the model can act on instead of a bare class name.
        self.phase = None

    def close(self):
        if self.browser:
            self.browser.close()
            self.browser = None

    def _open(self):
        if self.browser is None:
            self.browser = BrowserSession(self.policy.base_url, headless=self.headless,
                timeout_ms=self.timeout_ms, storage_state=None,
                authenticated=False, trace=False, evidence_dir=None)
            self.browser.start()
            self.browser.start_case(self.case_id)
            self.browser.storage_state = self.storage_state  # explicit authenticated session may restore later
            self.browser._capture_private = True
            self.browser.set_session({"mode": "anonymous"})
            self.policy.filled_aliases = {}
            self.policy.active = None
            self.policy.attach(self.browser._context)
        return self.browser

    def snapshot(self, browser=None):
        b = browser or self._open()
        url = self.policy.url(b.page.url)
        snapshot = public(b.page.locator('body').aria_snapshot(), self.policy.store)
        # Input values never leave runtime, even a non-fixture value.
        snapshot = re.sub(r'(^\s*- (?:textbox|combobox|spinbutton)[^\n]*):[^\n]*', r'\1', snapshot, flags=re.M)
        ids = b.page.locator('[data-testid]').evaluate_all('els => els.filter(e => e.getClientRects().length).map(e => ({target:e.getAttribute("data-testid"),tag:e.tagName.toLowerCase(),role:e.getAttribute("role"),type:e.getAttribute("type")}))')
        result = public({'url': safe_url(url), 'aria': snapshot[:16000],
                         'blocked_background_reads': self.policy.blocked_requests,
                         'stable_locators': ids[:160], 'truncated': len(snapshot) > 16000 or len(ids) > 160}, self.policy.store)
        self.observations.append(result)
        if self.knowledge:
            self.knowledge.observe(result)
        return result

    def act(self, action, args, *, browser=None, dry_run=False):
        target = args.get('target') or args.get('url') or args.get('mode') or ''
        self.phase = f"{'dry-run ' if dry_run else ''}{action} {target}".strip()
        b = browser or self._open()
        args = deepcopy(args)
        if action in {'ui.click', 'ui.fill', 'ui.select'}:
            element = locator(b.page, args)
            if not element.is_visible() or not element.is_enabled():
                raise SafetyError('Control is not currently visible/enabled')
            tag = element.evaluate('e => e.tagName.toLowerCase()')
            name = element.inner_text() if tag not in {'input', 'textarea'} else element.get_attribute('aria-label') or ''
            from qctool.agent.exploration_actions import high_risk, DANGEROUS
            reviewed = self.policy.control_reviewed(args.get('target', ''))
            if high_risk(name) and not reviewed:
                raise SafetyError('Destructive/admin/payment control is forbidden '
                                  '(enable `mode: write` or exploration.safe_controls)')
            if action == 'ui.click' and DANGEROUS.search(name) and not self.policy.mutation and not reviewed:
                raise SafetyError('State-changing control needs explicit reviewed mutation policy '
                                  '(or `mode: write`)')
            if action == 'ui.fill':
                if tag not in {'input', 'textarea'} or element.get_attribute('type') in {'file', 'hidden', 'submit', 'button'}:
                    raise SafetyError('Unsupported fill control')
                if element.get_attribute('type') == 'password' and not is_alias(args.get('value')):
                    raise SafetyError('Password must use a trusted fixture alias')
                original = args['value']
                args['value'] = self.policy.value(original, '\n'.join(self.intent.get(k, '') for k in ('given', 'when', 'expected')))
                args['_fixture_alias'] = original
                if is_alias(original):
                    self.policy.filled_aliases[original.split('.')[1]] = original
            if action == 'ui.select':
                self.policy.value(args['value'], '\n'.join(self.intent.get(k, '') for k in ('given', 'when', 'expected')))
                if tag != 'select' or element.locator('option').evaluate_all('es => es.map(e => e.value)').count(args['value']) != 1:
                    raise SafetyError('Select option must exist uniquely on the live control')
        self.policy.approve_action(b.page.url, action, args, dry_run=dry_run)
        before = self.policy.blocked_critical
        if action == 'ui.goto':
            b.goto(self.policy.url(args['url']))
        elif action == 'ui.session':
            b.set_session(args)
        elif action == 'ui.click':
            if 'capture_response' in args:
                return b.click_and_capture(args, 0)
            if 'capture_requests' in args:
                return b.click_and_observe_requests(args, 0)
            b.click(args)
        elif action == 'ui.fill':
            b.fill(args)
        elif action == 'ui.select':
            b.select(args)
        else:
            raise SafetyError('Unsupported agent browser action')
        if action not in {'ui.goto', 'ui.session'} and self.policy.blocked_critical != before:
            raise SafetyError('Browser requested a forbidden origin or unreviewed write')
        if action != 'ui.session':
            self.policy.url(b.page.url)
        return {'ok': True}

    def dry_run(self):
        if self.candidate is None:
            raise ValueError('draft_case must succeed before dry_run')
        check = check_case(self.candidate, self.intent, self.policy)
        if not check.accepted:
            return {'ok': False, 'errors': list(check.errors), 'review': list(check.review)}
        self.phase = 'dry-run browser setup (fresh context; not caused by your draft)'
        try:
            self.close()
            b = self._open()  # fresh isolated context, never authoring state
        except Exception as exc:
            self.browser = None
            return {'ok': False, 'phase': 'setup', 'retryable': True,
                    'error': f'Dry-run browser setup failed ({type(exc).__name__}); '
                             'environment issue, resubmit the same draft unchanged'}
        self.policy.authentication_observed = False
        saved = {}
        results = []
        self.policy.dry_run, self.policy.write_reached = True, False
        stopped_at = None
        for step in self.candidate.steps:
            if step.action == 'http.request' and str(step.args.get('method', 'GET')).upper() not in {'GET', 'HEAD'}:
                stopped_at = step.seq          # write mode: runner sends it once, dry-run never does
                break
            try:
                if step.action.startswith('assert.'):
                    # Only adapter/locator availability. Never invoke assertion or
                    # disclose actual text/value/status/URL/network counts.
                    if 'target' in step.args:
                        locator(b.page, step.args)
                    if 'source' in step.args and step.args['source'] not in saved:
                        raise ValueError('Response source is unavailable')
                    results.append({'seq': step.seq, 'ok': True, 'check': 'adapter/locator only'})
                    continue
                if step.action.startswith('ui.'):
                    response = self.act(step.action, step.args, browser=b, dry_run=True)
                    if self.policy.write_reached:
                        results.append({'seq': step.seq, 'ok': True, 'check': 'write reached; not sent in dry-run'})
                        stopped_at = step.seq
                        break
                    for capture in ('capture_response', 'capture_requests'):
                        if capture in step.args:
                            saved[step.args[capture].get('save_as', 'res')] = response
                elif step.action == 'http.request':
                    self.policy.check_case(self.candidate)
                    session = HttpSession(step.args.get('base', self.policy.base_url))
                    try:
                        _run_step(step, session, saved)
                    finally:
                        session.close()
                elif step.action == 'wait':
                    raise SafetyError('Explicit waits are unnecessary in agent dry-run')
                else:
                    raise SafetyError('Unsupported dry-run action')
                results.append({'seq': step.seq, 'ok': True})
            except Exception as exc:
                # No snapshot or arbitrary browser error at an assertion point.
                error = (str(exc) if isinstance(exc, (SafetyError, ValueError))
                         else 'timed out: element missing, hidden or page still loading'
                         if type(exc).__name__ == 'TimeoutError' else type(exc).__name__)
                window = max((s.args['capture_requests'].get('timeout_ms', 10000) for s in self.candidate.steps
                              if s.seq < step.seq and isinstance(s.args.get('capture_requests'), dict)), default=0)
                if step.action.startswith('assert.') and window > 3000 and 'timed out' in error:
                    error += (f'; an earlier capture_requests step blocked for {window} ms, so a transient '
                              'message may already be gone: use "timeout_ms": 2000')
                result = {'ok': False, 'steps': results, 'failed_step': step.seq,
                          'error': public(error, self.policy.store),
                          'failed_action': step.action, 'failed_target': step.args.get('target')}
                if not step.action.startswith('assert.'):
                    try:
                        result['snapshot'] = self.snapshot(b)
                    except Exception:
                        pass
                self.policy.dry_run = False
                return result
        self.policy.dry_run = False
        review = list(check.review)
        if stopped_at is not None:
            review.append(f'WRITE_NOT_DRY_RUN: bước ≥{stopped_at} chưa thử (ghi thật chỉ chạy ở runner)')
        self.candidate.generation_status = 'needs_review' if review else 'ready'
        self.candidate.review_reasons = review
        self.ready = deepcopy(self.candidate)
        if self.knowledge and self.policy.authentication_observed:
            prefix = []
            fixture = None
            for step in self.ready.steps:
                if step.action.startswith('assert.'):
                    break
                prefix.append({'action': step.action, 'args': deepcopy(step.args)})
                if step.action == 'ui.fill' and is_alias(step.args.get('value')) and step.args['value'].endswith('.password'):
                    fixture = step.args['value'].split('.')[0]
                if fixture and step.action == 'ui.click':
                    self.knowledge.remember('authenticate:' + fixture, prefix)
                    break
        return {'ok': True, 'steps': results, 'generation_status': self.ready.generation_status,
                'review': review, 'assertion_values': 'not evaluated/not disclosed'}

    def call(self, name, arguments):
        try:
            if name == 'read_docs':
                result = deepcopy(self.intent)
            elif name == 'list_api':
                result = [{'method': e.method, 'path': e.path, 'operation_id': e.operation_id,
                           'servers': e.contract_servers or e.servers} for e in self.policy.endpoints]
            elif name == 'browser_observe':
                if not arguments.get('url') and self._open().page.url == 'about:blank':
                    self.act('ui.goto', {'url': self.policy.base_url})
                if arguments.get('url'):
                    self.act('ui.goto', {'url': arguments['url']})
                result = self.snapshot()
            elif name == 'browser_act':
                self.act(arguments['action'], arguments['args'])
                if arguments['action'] == 'ui.session':
                    result = {'ok': True, 'session': arguments['args']['mode']}
                elif arguments['action'] in {'ui.fill', 'ui.select'}:
                    # Action acknowledgement suffices; explicit observe is available
                    # for dynamic form state. Never resend a page just for a fill.
                    result = {'ok': True, 'target': arguments['args']['target'], 'value': '[RUNTIME_ONLY]'}
                else:
                    result = self.snapshot()
            elif name == 'draft_case':
                self.candidate = draft_case(arguments, case_id=self.case_id, module=self.module,
                    intent=self.intent, fixture_store=self.policy.store)
                gate = check_case(self.candidate, self.intent, self.policy)
                result = self.dry_run() if gate.accepted else {'ok': False, 'errors': list(gate.errors), 'review': list(gate.review)}
            elif name == 'dry_run':
                result = self.dry_run()
            elif name == 'use_macro':
                macro = self.knowledge.macro(arguments['name']) if self.knowledge else None
                if not macro:
                    raise ValueError('Macro unavailable')
                for step in macro:
                    self.act(step['action'], step['args'])
                result = {'ok': True, 'url': safe_url(self._open().page.url), 'expanded_steps': macro,
                          'logged_in': True,
                          'next': 'Already logged in: do NOT fill the login form again. Navigate to the '
                                  'source route (browser_observe url=...) and include expanded_steps in draft_case.'}
            else:
                raise ValueError('Unknown tool')
        except Exception as exc:
            # Controlled codes (e.g. ResponseCaptureError.code) are safe feedback;
            # arbitrary browser/transport text is not.
            message = (str(exc) if isinstance(exc, (SafetyError, ValueError))
                       else getattr(exc, 'code', None) or type(exc).__name__)
            if type(exc).__name__ == 'TimeoutError':
                # Raw Playwright text may hold URLs/queries; phase is our own label.
                message = (f'{name}: timed out during {self.phase or "browser operation"} '
                           f'(element missing, hidden or page still loading). Observe current page before retrying.')
            result = {'ok': False, 'error': public(message, self.policy.store)}
        if isinstance(result, dict) and not result.get('ok', True) and self.policy.store:
            bindings = self.policy.store.to_dict().get('bindings', {})
            result['allowed_value_aliases'] = sorted({a for req in self.policy.req_ids for a in bindings.get(req, {}).values()})
            result['alias_format'] = 'Exact alias string only: no {{ }}, @, fixture: or interpolation'
        result = public(result, self.policy.store)
        if not isinstance(result, dict):
            result = {'items': result}
        self.audit.append({'tool': name, 'ok': result.get('ok', True), 'error': result.get('error'),
                           'failed_step': result.get('failed_step')})
        self.on_progress('agent', f'{self.case_id}: {name} → {"OK" if result.get("ok", True) else "cần sửa"}')
        return result

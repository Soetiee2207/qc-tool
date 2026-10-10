"""Run-owned safety enforced inside every browser/HTTP tool, not by prose."""
from copy import deepcopy
import json
from urllib.parse import urljoin, urlsplit

from qctool.data.capture import origin_of
from qctool.agent.exploration_actions import mutation_policy, MutationBudget, mutation_permission, high_risk
from qctool.data.fixtures import is_alias


class SafetyError(ValueError):
    pass


class SafetyPolicy:
    def __init__(self, base_url, *, endpoints=(), fixture_store=None, mutation=None,
                 req_ids=(), budget=None, auth_operations=(), source_routes=()):
        self.base_url = base_url.rstrip('/')
        self.origin = origin_of(base_url)
        self.endpoints = tuple(endpoints)
        self.store = fixture_store
        self.req_ids = tuple(req_ids)
        self.mutation = mutation_policy(mutation, fixture_store=fixture_store)
        self.budget = budget if budget is not None else MutationBudget()
        self.auth_operations = tuple(deepcopy(auth_operations))
        # Routes the source Given/When names literally may be opened read-only
        # even if they look high-risk (access-denial tests). Expected URLs are
        # expectations, not authority; writes/controls stay separately guarded.
        self.source_routes = frozenset(r.rstrip('/') or '/' for r in source_routes)
        self.filled_aliases = {}
        self.active = None
        self.blocked_requests = 0
        self.blocked_critical = 0
        self.redirect_url = None
        self.writes = 0
        self.authentication_observed = False
        self.operations = {(e.method.upper(), e.path): e for e in self.endpoints}
        self.origins = {self.origin}
        self.origins.update(origin_of(url) for e in self.endpoints for url in (e.contract_servers or e.servers) if url.startswith(("http://", "https://")))

    def risky_path(self, path):
        return high_risk(path) and (path.rstrip('/') or '/') not in self.source_routes

    def url(self, value):
        if not isinstance(value, str) or '\\' in value or any(ord(c) < 32 for c in value):
            raise SafetyError('Invalid navigation target')
        target = urljoin(self.base_url + '/', value)
        parts = urlsplit(target)
        if (parts.scheme not in {'http', 'https'} or parts.username or parts.password
                or origin_of(target) != self.origin or self.risky_path(parts.path)):
            raise SafetyError('Foreign origin or high-risk navigation is not permitted')
        return target

    def value(self, value, source):
        if is_alias(value):
            metadata = self.store.to_dict()['aliases'] if self.store else {}
            if value not in metadata or not metadata[value]['available']:
                raise SafetyError('Fixture alias is absent/unavailable')
            assignments = self.store.to_dict().get('bindings', {})
            allowed = {a for req in self.req_ids for a in assignments.get(req, {}).values()}
            if value not in allowed:
                raise SafetyError('Fixture alias is not bound to this source intent')
            return self.store.resolve(value)
        if not isinstance(value, str) or not value or value not in source:
            raise SafetyError('Fill/select value needs an explicit source literal or bound alias')
        return value

    def check_case(self, case):
        for step in case.steps:
            action, args = step.action, step.args
            if action == 'ui.goto':
                self.url(args['url'])
            if action == 'ui.fill':
                self.value(args['value'], '\n'.join((case.source_intent.get('given', ''),
                           case.source_intent.get('when', ''), case.source_quote)))
            if action == 'http.request':
                operation = self.operations.get((str(args['method']).upper(), args['path']))
                if operation is None or args['method'].upper() not in {'GET', 'HEAD'}:
                    raise SafetyError('HTTP authoring requires an exact read operation; writes require reviewed policy')
                base = args.get('base') or self.base_url
                if origin_of(base) not in self.origins:
                    raise SafetyError('Foreign HTTP origin')
            for capture in ('capture_response', 'capture_requests'):
                if capture in args:
                    spec = args[capture]
                    if (spec['method'], spec['path']) not in self.operations or origin_of(spec.get('origin', self.base_url)) not in self.origins:
                        raise SafetyError('Capture is not grounded in the exact API contract')

    def approve_action(self, page, action, args, *, dry_run=False):
        if action not in {'ui.goto', 'ui.click', 'ui.fill', 'ui.select', 'ui.session'}:
            raise SafetyError('Unsupported browser action')
        if action == 'ui.goto':
            self.url(args['url'])
        self.active = None
        if action != 'ui.click':
            return
        target = args.get('target', '')
        if high_risk(target):
            raise SafetyError('High-risk control is not permitted')
        permission = mutation_permission(self.mutation, page=page, target=target,
                                        destination=args.get("expected_url"), requirement_ids=self.req_ids, base_url=self.base_url)
        # dry_run must never create the entity which runner would create again.
        if permission and permission['rule'].get('operation'):
            if dry_run:
                raise SafetyError('Mutation cannot be dry-run twice; requires review/single execution')
            if not self.budget.claim(permission):
                raise SafetyError("Reviewed mutation attempt budget exhausted")
        self.active = permission
        # Password aliases from trusted config plus explicit runtime bootstrap
        # endpoint authority. Credential existence alone grants no endpoint.
        if not permission and self.auth_operations and 'password' in self.filled_aliases and len(self.filled_aliases) >= 2:
            self.active = 'authentication'
        self.writes = 0

    def attach(self, context):
        context.route('**/*', self._route)
        # New tabs are not part of this intent: prevent unguarded popup redirect
        # chains before the agent can interact with them.
        existing = tuple(context.pages)
        context.on('page', lambda page: page.close() if page not in existing else None)
        # Playwright routing skips redirected hops; Chromium Fetch guards them.
        for page in context.pages:
            cdp = context.new_cdp_session(page)
            def guard(event, cdp=cdp):
                req = event['request']
                allowed = origin_of(req['url']) in self.origins
                if event.get('resourceType') == 'Document':
                    allowed = origin_of(req['url']) == self.origin and not self.risky_path(urlsplit(req['url']).path)
                if event.get('redirectedRequestId') and req['method'] not in {'GET', 'HEAD', 'OPTIONS'}:
                    allowed = False
                if not allowed:
                    self.blocked_requests += 1
                    if event.get('resourceType') == 'Document':
                        self.redirect_url = req['url']
                    if event.get('resourceType') == 'Document' or req['method'] not in {'GET', 'HEAD', 'OPTIONS'}:
                        self.blocked_critical += 1
                    cdp.send('Fetch.failRequest', {'requestId': event['requestId'], 'errorReason': 'BlockedByClient'})
                else:
                    cdp.send('Fetch.continueRequest', {'requestId': event['requestId']})
            cdp.on('Fetch.requestPaused', guard)
            cdp.send('Fetch.enable', {'patterns': [{'requestStage': 'Request'}]})

    def _route(self, route):
        req = route.request
        try:
            parts = urlsplit(req.url)
            if parts.scheme not in {'http', 'https'} or origin_of(req.url) not in self.origins:
                raise SafetyError('Foreign network origin')
            if req.is_navigation_request() and (origin_of(req.url) != self.origin or self.risky_path(parts.path)):
                raise SafetyError('Foreign or high-risk document navigation')
            if req.method not in {'GET', 'HEAD', 'OPTIONS'}:
                auth = next((o for o in self.auth_operations if (req.method, parts.path, origin_of(req.url)) == (o['method'], o['path'], o['origin'])), None)
                if auth and self.active == 'authentication' and not self.writes:
                    raw = req.post_data or ''
                    if len(raw.encode()) > 65536:
                        raise SafetyError('Authentication body too large')
                    body = json.loads(raw)
                    values = [self.store.resolve(a) for a in self.filled_aliases.values()] if self.store else []
                    if not isinstance(body, dict) or sorted(body) != auth['fields'] or not values or not all(v in body.values() for v in values) or req.redirected_from:
                        raise SafetyError('Authentication body is not the trusted submitted fixture')
                    self.writes += 1
                    self.authentication_observed = True
                    route.continue_()
                    return
                if not self.active or self.active == 'authentication' or self.writes:
                    raise SafetyError('Write is not reviewed or attempt already consumed')
                op = self.active['rule'].get('operation')
                if not op or (req.method, parts.path, origin_of(req.url)) != (op['method'], op['path'], op['origin']):
                    raise SafetyError('Write operation does not match reviewed policy')
                if (req.method, parts.path) not in self.operations or req.redirected_from:
                    raise SafetyError('Write is absent from contract or redirected')
                raw = req.post_data or ''
                if len(raw.encode()) > 65536:
                    raise SafetyError('Write body too large')
                body = json.loads(raw)
                if (not isinstance(body, dict) or set(body) - set(op['allowed_json_fields'])
                        or any(type(body.get(k)) is not type(v) or body.get(k) != v
                               for k, v in op['required_json'].items())):
                    raise SafetyError('Write body outside reviewed scope')
                self.writes += 1
            route.continue_()
        except Exception:
            self.blocked_requests += 1
            if req.is_navigation_request() and origin_of(req.url) != self.origin:
                self.redirect_url = req.url
            if req.method not in {'GET', 'HEAD', 'OPTIONS'} or req.is_navigation_request():
                self.blocked_critical += 1
            route.abort('blockedbyclient')

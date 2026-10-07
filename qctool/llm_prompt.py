"""Detached, lossless source/evidence views and content-free prompt accounting.

A prompt view is NOT a validation context. Validators retain the original packet.
Token estimates use UTF-8 bytes / 4, not a provider tokenizer; actual usage is
reported separately by the provider. Budgets block before any network call.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import hashlib
from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from .resolution_context import ResolutionContext
from .testcase import Step, StepKind
from .ui.crawl import _norm

MAX_PROMPT_TOKENS = 12000  # deterministic estimate, equivalent to 48,000 bytes
_COMPOSITION = ContextVar('prompt_composition', default=None)
COMPONENTS = ('protocol_schema', 'requirement_source', 'openapi', 'ui_state_evidence',
              'fixture_data_metadata', 'testcase_gap')


class PromptBudgetError(ValueError):
    code = 'PROMPT_BUDGET_EXCEEDED'
    def __init__(self, composition=None, maximum=None):
        self.diagnostics = {'category': 'PROMPT_BUDGET_EXCEEDED', 'path': '$.prompt',
                            'prompt_composition': composition, 'maximum_estimated_tokens': maximum}
        super().__init__('Required source/evidence exceeds prompt budget; no completion requested.')


def describe_prompt(prompt):
    """Return counts only: never content, identifiers, credentials or snippets."""
    sizes = dict.fromkeys(COMPONENTS, 0)
    parts = prompt.split('\n\n')
    for index, part in enumerate(parts):
        header, _, body = part.partition('\n')
        group = ('requirement_source' if (header.startswith('SPECIFICATION') or header.startswith('STABLE PROJECT SPECIFICATION')) else
                 'openapi' if (header.startswith('INTERFACE CONTRACT') or header.startswith('STABLE PROJECT INTERFACE CONTRACT')) else
                 'ui_state_evidence' if header.startswith('CURRENT UI OBSERVATION') else
                 'fixture_data_metadata' if header.startswith('TEST DATA EVIDENCE') else
                 'testcase_gap' if header in ('TESTCASE', 'EXECUTION GAPS', 'UNRESOLVED EXECUTION GAPS')
                 or header.startswith('TESTCASE —') else 'protocol_schema')
        sizes[group] += len(part.encode('utf-8')) + (2 if index else 0)
    return {'measurement': 'utf8_bytes_divided_by_4_estimate',
            'components': {k: {'bytes': v, 'estimated_tokens': (v + 3) // 4} for k, v in sizes.items()},
            'prompt_bytes': sum(sizes.values()), 'estimated_prompt_tokens': (sum(sizes.values()) + 3) // 4}


def check_prompt_budget(prompt, maximum=MAX_PROMPT_TOKENS):
    if type(maximum) is not int or maximum < 1:
        raise ValueError('Prompt budget must be a positive integer')
    counts = describe_prompt(prompt)
    if counts['estimated_prompt_tokens'] > maximum:
        raise PromptBudgetError(counts, maximum)
    return prompt


@contextmanager
def prompt_accounting(prompt):
    token = _COMPOSITION.set(describe_prompt(prompt))
    try:
        yield
    finally:
        _COMPOSITION.reset(token)


def current_prompt_composition():
    return deepcopy(_COMPOSITION.get())


def _unique(records):
    """Only exact duplicates; differing values/identities remain conflicts."""
    out = []
    for record in records:
        if record not in out:
            out.append(record)
    return out


def _source_note(note, authority=None):
    out = []
    for line in note.splitlines():
        if line.startswith(('[resolution-expansion] ', '[resolution-application] ')):
            try:
                record = json.loads(line.split(' ', 1)[1])
            except (ValueError, IndexError):
                out.append(line)  # Unknown provenance cannot safely be trimmed.
                continue
            original = record.get('source_step')
            if original:
                reduced = {k: deepcopy(original[k]) for k in ('seq', 'kind', 'action', 'args') if k in original}
                if original.get('note'):
                    reduced['note'] = _source_note(original['note'], authority)
                out.append('[original-step] ' + json.dumps(reduced, ensure_ascii=False, sort_keys=True))
                origin = {k: record[k] for k in ('source_ref', 'source_quote', 'traces_to')
                          if record.get(k) and (authority is None or record[k] != authority.get(k))}
                if origin:
                    out.append('[source-origin] ' + json.dumps(origin, ensure_ascii=False, sort_keys=True))
            else:
                out.append(line)
        else:
            out.append(line)
    return '\n'.join(_unique(out))


def _route(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme and parsed.scheme not in {'http', 'https'}:
        return None
    if not (value.startswith('/') or parsed.scheme):
        return None
    return (parsed.path or '/', parsed.query, parsed.fragment)


def select_prompt_context(context: ResolutionContext, *, gaps=None):
    """Project directly related evidence; never truncate a relevant conflict.

    Retain every source clause, all testcase steps and current state ancestry.
    Unrecognized prose retains every element of its explicitly related pages.
    Audit snapshots/receipts stay in the original context, outside model input.
    """
    from .step_expansion import expected_expansion
    data = context.to_dict()
    if gaps is not None:
        from dataclasses import asdict
        data['gaps'] = [asdict(g) for g in gaps]
    case = data['testcase']
    traces = set(case.get('traces_to', []))
    requirements = [r for r in data['specification'].get('requirements', []) if r.get('id') in traces]
    data['specification']['requirements'] = _unique(requirements)
    for step in case['steps']:
        step.setdefault('args', {})
        step['note'] = _source_note(step.get('note', ''), case)
    # Final findings preserve every declared/verified/conflicting fact with its
    # assurance and source. Private receipts and recursive preparation snapshots
    # do not authorize an LLM repair and are retained by deterministic validation.
    acquisition = data.get('data_acquisition', {})
    data['data_acquisition'] = {k: deepcopy(acquisition[k]) for k in (
        'testcase_id', 'status', 'findings', 'issues', 'live_verification_performed',
        'provisioning_performed', 'verification', 'provisioning') if k in acquisition}

    texts = [case.get('source_quote', ''), *case.get('preconditions', [])]
    texts.extend(r.get(k, '') for r in requirements for k in ('given', 'when', 'then', 'statement', 'source_quote'))
    texts.extend(s.get('note', '') for s in case['steps'])
    texts.extend(s['args'].get(k, '') for s in case['steps'] for k in ('description', 'expected', 'expectation'))
    texts = [t for t in texts if isinstance(t, str)]
    routes, targets, hints, operations, operation_ids = set(), set(), set(), set(), set()
    unknown = False
    for text in texts:
        routes.update(_route(t.strip('`\"\'')) for t in re.findall(r'https?://[^\s;\"\']+|(?<!\w)/[^\s;\"\']*', text))
        operations.update((m.upper(), p.rstrip(';,')) for m, p in re.findall(
            r'\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/[^\s;\"\']+)', text, re.I))
    for step in case['steps']:
        args = step['args']
        if args.get('target'):
            targets.add(args['target'])
        hints.update(_norm(args[k]) for k in ('by_name', 'name') if isinstance(args.get(k), str))
        if step['action'] == 'ui.goto':
            routes.add(_route(args.get('url')))
        if step['action'] == 'http.request':
            operations.add((str(args.get('method', '')).upper(), args.get('path')))
        for key in ('capture_response', 'capture_requests'):
            if isinstance(args.get(key), dict):
                selector = args[key]
                operations.add((selector.get('method'), selector.get('path')))
        if step['action'].startswith('ui.') and not args.get('target') and step.get('note'):
            probe = expected_expansion(Step(step['seq'], StepKind.WHEN, 'perform.unmapped',
                                           {'description': step['note']}), case.get('test_data', {}), min_atoms=1)
            if probe:
                hints.update(_norm(a['hint']) for a in probe if a.get('hint'))
            elif step['action'] != 'ui.goto':
                unknown = True
        if step['action'] in {'perform.unmapped', 'assert.unmapped'}:
            atoms = expected_expansion(Step(step['seq'], StepKind(step['kind']), step['action'], args),
                                       case.get('test_data', {}), min_atoms=1)
            if atoms is None:
                # Select grammar has its own authoritative source parser.
                if step['action'] == 'perform.unmapped':
                    from .exploration_actions import _meanings
                    try:
                        atoms = _meanings(Step(step['seq'], StepKind(step['kind']), step['action'], args), case.get('test_data', {}))
                    except (ValueError, KeyError, TypeError):
                        pass
            if atoms is None:
                unknown = True
            else:
                hints.update(_norm(a['hint']) for a in atoms if a.get('hint'))
                routes.update(_route(a['route']) for a in atoms if a.get('route'))
                operations.update(a['operation'] for a in atoms if a.get('operation'))
                operations.update(a['no_request'] for a in atoms if a.get('no_request'))
    if case.get('source_ref', '').startswith('openapi:'):
        operation_ids.add(case['source_ref'].split(':', 1)[1].split('#', 1)[0])
    tokens = {token.strip('`\"\';,') for text in texts for token in text.split()}
    operation_ids.update(op.get('operation_id') for op in data['interface_contract'].get('api_operations', [])
                         if op.get('operation_id') in tokens)
    data['interface_contract']['api_operations'] = _unique([
        op for op in data['interface_contract'].get('api_operations', [])
        if op.get('operation_id') in operation_ids or (op.get('method'), op.get('path')) in operations
        or any(path == op.get('path') and not method for method, path in operations)])
    observations = data['observations']
    states = observations.get('page_states', [])
    roots = {observations.get('current_state_id')}
    # Explicit state references in source/provenance remain available too.
    for text in texts:
        roots.update(re.findall(r'"state_id"\s*:\s*"([^"\n]+)"', text))
    wanted = set()
    pending = [key for key in roots if key]
    while pending:
        key = pending.pop()
        if key in wanted:
            continue
        wanted.add(key)
        pending.extend(s.get('from_state_id') for s in states if s.get('state_id') == key and s.get('from_state_id'))
    selected_states = [s for s in states if s.get('state_id') in wanted]
    # Legacy V1 state records lack a state_id; their action observations are
    # supplied from related UI pages, not used as a guessed modern state chain.
    for state in selected_states:
        routes.add(_route(state.get('page', {}).get('url')))
        for binding in state.get('validated_actions', []):
            targets.add(binding.get('target'))
            routes.add(_route(binding.get('page')))
            routes.add(_route(binding.get('expected_url')))
    routes.discard(None)

    def page_view(page):
        result = deepcopy(page)
        elements = result.get('elements', [])
        if not unknown:
            relevant = [e for e in elements if e.get('test_id') in targets or e.get('id') in targets
                        or _norm(e.get('name', '')) in hints or e.get('input_type') in hints
                        or hints and e.get('role') in {'alert', 'status'}]
            # Keep all siblings of selected stable IDs/names, even when metadata
            # conflicts. Do not turn an ambiguous selector into a unique one.
            ids = {e.get('test_id') for e in relevant if e.get('test_id')}
            names = {_norm(e.get('name', '')) for e in relevant if e.get('name')}
            elements = [e for e in elements if e in relevant or e.get('test_id') in ids or _norm(e.get('name', '')) in names]
        result['elements'] = elements  # Preserve multiplicity; validator may count duplicates.
        if 'explorations' in result:
            result['explorations'] = [{k: v for k, v in e.items() if k != 'previous_snapshot'}
                                      for e in result['explorations']]
        return result

    observations['ui_pages'] = _unique([page_view(p) for p in observations.get('ui_pages', [])
                                        if _route(p.get('url')) in routes or not routes and any(
                                            e.get('test_id') in targets or e.get('id') in targets for e in p.get('elements', []))])
    # Full chronological links, action bindings and source identities stay intact.
    # Drop recursive earlier snapshots, not required action/state provenance.
    observations['page_states'] = []
    action_chains = []
    for state in selected_states:
        reduced = deepcopy(state)
        reduced['page'] = page_view(reduced['page'])
        if reduced.get('validated_actions'):
            chain = {k: reduced.pop(k) for k in ('validated_actions', 'request', 'purposes') if k in reduced}
            if chain not in action_chains:
                action_chains.append(chain)
            reduced['action_chain'] = action_chains.index(chain)
        observations['page_states'].append(reduced)
    if action_chains:
        observations['action_chains'] = action_chains
    if context.semantics:
        data['semantics'] = deepcopy(context.semantics)
    if context.evidence_needs:
        data['evidence_needs'] = deepcopy(context.evidence_needs)
    return data


PROTOCOL_VERSIONS = {'resolution': '3', 'exploration': '3'}
DYNAMIC_MARKER = 'DYNAMIC TESTCASE / CYCLE EVIDENCE'


def canonical_json(value):
    """Sort maps only; lists preserve source/action/step/state chronology."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _project_authority(value):
    """Move provenance/origin volatility to the full dynamic evidence, never drop it.

    IDs identifying requirements/operations remain semantic. Runtime states and
    fixtures never enter this prefix. Actual server origins remain in the tail.
    """
    if isinstance(value, dict):
        return {k: _project_authority(v) for k, v in value.items() if k not in {
            'source', 'evidence', 'servers', 'observed_at', 'crawled_at', 'created_at',
            'updated_at', 'audit_id', 'request_id', 'generated_at'}}
    if isinstance(value, list):
        return [_project_authority(v) for v in value]
    return value


@dataclass(frozen=True)
class PromptLayout:
    cache_family: str
    protocol_version: str
    protocol: str
    project: str
    dynamic_tail: str

    @property
    def stable_prefix(self):
        return self.protocol + '\n\n' + self.project + '\n\n'

    @property
    def prompt(self):
        return self.stable_prefix + DYNAMIC_MARKER + '\n\n' + self.dynamic_tail

    def diagnostics(self):
        digest = lambda text: hashlib.sha256(text.encode('utf-8')).hexdigest()
        return {'cache_family': self.cache_family, 'capability': self.cache_family,
                'protocol_version': self.protocol_version,
                'stable_prefix_fingerprint': digest(self.stable_prefix),
                'dynamic_tail_fingerprint': digest(self.dynamic_tail),
                'protocol_fingerprint': digest(self.protocol),
                'stable_prefix_bytes': len(self.stable_prefix.encode('utf-8')),
                'dynamic_tail_bytes': len(self.dynamic_tail.encode('utf-8'))}


def assemble_cached_prompt(family, parts, data, schemas, *, protocol_version=None):
    """No response cache: reorder existing instructions/evidence into a stable prefix.

    Project authority is the already selected source/contract, not a new retrieval
    of all repository data. Different selected authority legitimately changes the
    project suffix; the preceding family protocol stays identical.
    """
    static_headers = ('ALLOWED ACTIONS', 'ALLOWED OBSERVATION INTENTS', 'SESSION MODES',
                      'REQUEST BUDGET', 'CONSTRAINTS', 'CONTEXT CONSTRAINTS', 'EVIDENCE REFERENCE SCHEMA',
                      'CAPTURE_RESPONSE JSON SHAPE')
    protocol, dynamic = [], []
    for part in parts:
        header, separator, body = part.partition('\n')
        if not separator or header.startswith(static_headers):
            protocol.append(part)
        else:
            dynamic.append(part)
    version = protocol_version or PROTOCOL_VERSIONS[family]
    protocol.insert(0, 'QC ' + family.upper() + ' PROTOCOL v' + version)
    for title, schema in schemas:
        protocol.append(title + '\n' + canonical_json(schema))
    project = '\n\n'.join([
        'STABLE PROJECT SPECIFICATION — REQUIREMENTS\n' + canonical_json(_project_authority(data['specification'])),
        'STABLE PROJECT INTERFACE CONTRACT — OPENAPI\n' + canonical_json(_project_authority(data['interface_contract'])),
    ])
    return PromptLayout(family, version, '\n\n'.join(protocol), project, '\n\n'.join(dynamic))


def prompt_cache_diagnostics(prompt):
    """Extract only hashes/counts from a constructed prompt, never persist text."""
    prefix, marker, tail = prompt.partition(DYNAMIC_MARKER + '\n\n')
    first = prompt.split('\n', 1)[0].split()
    if not marker or len(first) != 4 or first[:1] != ['QC'] or first[2] != 'PROTOCOL':
        return {}
    family = first[1].lower()
    if family not in PROTOCOL_VERSIONS:
        return {}
    protocol = prefix.split('\n\nSTABLE PROJECT SPECIFICATION', 1)[0]
    digest = lambda text: hashlib.sha256(text.encode('utf-8')).hexdigest()
    return {'capability': family, 'cache_family': family, 'protocol_version': first[3].removeprefix('v'),
            'stable_prefix_fingerprint': digest(prefix), 'dynamic_tail_fingerprint': digest(tail),
            'protocol_fingerprint': digest(protocol), 'stable_prefix_bytes': len(prefix.encode('utf-8')),
            'dynamic_tail_bytes': len(tail.encode('utf-8'))}

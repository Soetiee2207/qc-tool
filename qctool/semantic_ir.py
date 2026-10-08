"""Extractive semantic normalization, independently checked before grounding.

The model chooses concepts, never source authority. Literal slots, polarity,
ordered clause coverage, fixture bindings and interaction intent are checked
again by consumers. Unknown interpretations abstain. No product vocabulary.
"""
from copy import deepcopy
from dataclasses import dataclass
import re
import unicodedata
from urllib.parse import urlsplit

from .ui.crawl import _norm

# Concept-level lexical cues, not sentence/phrase patterns or DOM-name matching.
# They bound what deterministic validation can establish from cited source.
CUES = {
    'fill': {'fill', 'enter', 'type', 'nhap', 'dien'},
    'activate': {'click', 'activate', 'press', 'submit', 'bam', 'nhan'},
    'navigate': {'open', 'visit', 'navigate', 'mo', 'truy'},
    'visible': {'visible', 'shown', 'show', 'see', 'display', 'hien', 'thi'},
    'empty': {'empty', 'blank', 'trong'},
    'url': {'url', 'route', 'location'},
}
NEGATIVE = {'not', 'never', 'no', 'khong', 'cannot', 'without'}
KINDS = frozenset({'session', 'precondition', 'fill', 'activate', 'navigate',
                   'visible', 'url', 'api', 'no_request', 'empty'})
FIELDS = {
    'session': ({'mode'}, set()),
    'precondition': ({'fixture', 'facts'}, set()),
    'fill': ({'field', 'value'}, set()),
    'activate': ({'label'}, {'role'}),
    'navigate': ({'route'}, set()),
    'visible': ({'text'}, {'role'}),
    'url': ({'route'}, set()),
    'api': ({'method', 'path', 'status'}, {'json'}),
    'no_request': ({'method', 'path'}, set()),
    'empty': ({'fields'}, set()),
}
MAX_CLAUSES = 24
MAX_ATOMS = 32


@dataclass(frozen=True)
class SemanticAtom:
    kind: str
    args: dict


@dataclass(frozen=True)
class SemanticClause:
    step_seq: int
    clause_index: int
    source_text: str
    atoms: tuple[SemanticAtom, ...]


@dataclass(frozen=True)
class SemanticNormalization:
    clauses: tuple[SemanticClause, ...]

    def to_dict(self):
        return {'clauses': [{'step_seq': c.step_seq, 'clause_index': c.clause_index, 'source_text': c.source_text, 'atoms': [{'kind': a.kind, 'args': deepcopy(a.args)} for a in c.atoms]} for c in self.clauses]}


@dataclass(frozen=True)
class SemanticIssue:
    code: str
    step_seq: int
    clause_index: int


def concept_text(text):
    return ''.join(c for c in unicodedata.normalize('NFD', _norm(text).replace('đ', 'd'))
                   if unicodedata.category(c) != 'Mn')


def words(text):
    return set(re.findall(r'[\w]+', concept_text(text)))


def literals(text):
    """URI identifiers only; this does not infer a business expectation."""
    tokens = re.findall(r'https?://[^\s;"`<>]+|(?<![\w/])/[^\s;"`<>]*', text)
    return [token for token in tokens if re.fullmatch(r'(?:https?://)?[A-Za-z0-9_./?=&%~:#@+-]+', token)]


def _has(text, value):
    return isinstance(value, str) and bool(value.strip()) and _norm(value) in _norm(text)


def source_units(context):
    """Enumerate original source clauses; no successful sibling is discarded."""
    units = []
    requirements = context.specification.get('requirements', [])
    for step in context.testcase.get('steps', []):
        if step['action'] not in {'perform.unmapped', 'assert.unmapped'}:
            continue
        field = step['kind']
        text = step['args'].get('expected' if field == 'then' else 'description', '')
        matches = [r for r in requirements if r.get('id') in context.testcase['traces_to']
                   and r.get(field) == text]
        if len(matches) != 1:
            continue
        for index, clause in enumerate(text.split(';')):
            units.append({'step_seq': step['seq'], 'clause_index': index,
                          'source_text': clause.strip(), 'field': field,
                          'requirement_id': matches[0]['id']})
    return units


def parse_semantics(raw):
    from .llm_resolution import LLMResponseError, _fields, _list, _positive_int, _nonempty
    _fields(raw, {'clauses'}, 'semantic')
    records = _list(raw['clauses'], 'semantic.clauses')
    if len(records) > MAX_CLAUSES:
        raise LLMResponseError('Semantic clause budget exceeded', category='ARRAY_LENGTH', path='semantic.clauses')
    out = []
    for i, record in enumerate(records):
        where = f'semantic.clauses[{i}]'
        _fields(record, {'step_seq', 'clause_index', 'source_text', 'atoms'}, where)
        seq = _positive_int(record['step_seq'], where + '.step_seq')
        index = record['clause_index']
        if type(index) is not int or index < 0:
            raise LLMResponseError('Invalid clause index', category='INTEGER_REQUIRED', path=where + '.clause_index')
        atoms = []
        for j, item in enumerate(_list(record['atoms'], where + '.atoms')):
            _fields(item, {'kind', 'args'}, where + f'.atoms[{j}]')
            kind = item['kind']
            if not isinstance(kind, str) or kind not in KINDS:
                raise LLMResponseError('Unknown semantic kind', category='SEMANTIC_KIND', path=where + f'.atoms[{j}].kind')
            required, optional = FIELDS[kind]
            if (not isinstance(item['args'], dict) or not required <= item['args'].keys()
                    or item['args'].keys() - required - optional):
                raise LLMResponseError('Invalid semantic arguments', category='FIELD_SET', path=where + f'.atoms[{j}].args')
            atoms.append(SemanticAtom(kind, deepcopy(item['args'])))
        out.append(SemanticClause(seq, index, _nonempty(record['source_text'], where + '.source_text'), tuple(atoms)))
    if sum(len(c.atoms) for c in out) > MAX_ATOMS:
        raise LLMResponseError('Semantic atom budget exceeded', category='ARRAY_LENGTH', path='semantic.clauses')
    return SemanticNormalization(tuple(out))


def _atom_authorized(atom, unit, context, store):
    """Prove bounded extractive claims; a quoted clause alone is never proof."""
    text, kind, args = unit['source_text'], atom.kind, atom.args
    tokens = words(text)
    expected = unit['field'] == 'then'
    if (kind in {'visible', 'url', 'api', 'no_request'} and not expected
            or kind in {'fill', 'activate'} and unit['field'] != 'when'
            or kind in {'session', 'precondition'} and unit['field'] != 'given'):
        return False
    # A negative source must not become a positive action/outcome. Negation
    # inside an exact literal message is data, not an operator.
    residual = text
    for key in ('text', 'label'):
        if isinstance(args.get(key), str):
            residual = residual.replace(args[key], '')
    if kind not in {'session', 'precondition', 'no_request', 'empty'} and words(residual) & NEGATIVE:
        return False
    if kind == 'session':
        return args['mode'] == 'anonymous' and bool(tokens & {'anonymous', 'unauthenticated', 'chua'})
    if kind == 'precondition':
        if tokens & NEGATIVE:
            return False
        fixture, facts = args['fixture'], args['facts']
        if store is None or not isinstance(fixture, str) or not isinstance(facts, dict) or not facts:
            return False
        metadata = store.to_dict()
        bound = context.testcase.get('test_data', {})
        if not any(isinstance(v, str) and v.startswith(fixture + '.') for v in bound.values()):
            return False
        declared = metadata.get('facts', {}).get(fixture, {}).get('values', {})
        acquisition = context.data_acquisition.get('findings', [])
        provided = dict(declared)
        for finding in acquisition:
            if finding.get('requirement', {}).get('fixture') == fixture:
                for item in finding.get('facts', []):
                    if item.get('status') in {'DECLARED', 'VERIFIED', 'LITERAL'}:
                        provided[item['fact']] = item['expected']
        # Every required fact is checked. Credentials alone are never proof.
        required = {k: v for f in acquisition if f.get('requirement', {}).get('fixture') == fixture
                    for k, v in f['requirement'].get('facts', {}).items()}
        if not required:
            return False  # Config declarations alone do not authorize source facts.
        return (bool(required) and all(k in facts and type(facts[k]) is type(v) and facts[k] == v for k, v in required.items())
                and all(k in provided and type(provided[k]) is type(v) and provided[k] == v for k, v in facts.items())
                and (fixture in text or all(str(v) in text for k, v in facts.items() if k == 'role')))
    if kind == 'fill':
        field, value = args['field'], args['value']
        if not tokens & CUES['fill'] or not _has(text, field) or not isinstance(value, str):
            return False
        from .test_fixtures import REGISTRY, is_alias
        data = context.testcase.get('test_data', {})
        if is_alias(value):
            return (store is not None and data.get(field) == value
                    and store.trusts(value, data.get(REGISTRY, {})))
        # Public literals must be explicitly quoted; secrets are aliases only.
        return (('"' + value + '"' in text or "'" + value + "'" in text)
                and (store is None or store.redact(value) == value)
                and not words(field) & {'password', 'secret', 'token'})
    if kind == 'activate':
        return (bool(words(text.replace(args['label'], '')) & CUES['activate']) and _has(text, args['label'])
                and args.get('role', 'button') in {'button', 'link'})
    if kind == 'navigate':
        return (not expected and args['route'] in literals(text)
                and (bool(tokens & CUES['navigate']) or unit['field'] == 'given'))
    if kind == 'visible':
        return (bool(tokens & CUES['visible']) and _has(text, args['text'])
                and args.get('role') in {None, 'button', 'link', 'heading', 'alert', 'textbox'})
    if kind == 'url':
        return bool(tokens & CUES['url']) and args['route'] in literals(text)
    if kind == 'empty':
        fields = args['fields']
        return (bool(tokens & CUES['empty']) and isinstance(fields, list) and 1 <= len(fields) <= 4
                and len(set(fields)) == len(fields) and all(_has(text, f) for f in fields))
    if kind in {'api', 'no_request'}:
        method, path = args['method'], args['path']
        if method not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD'} or method not in text or path not in literals(text):
            return False
        if not any(o.get('method') == method and o.get('path') == path
                   for o in context.interface_contract.get('api_operations', [])):
            return False
        if kind == 'no_request':
            return bool(tokens & NEGATIVE) and bool(tokens & {'request','requests','send','sent','gui','called','call','goi','occur','occurs'})
        status = args['status']
        if type(status) is not int or str(status) not in re.findall(r'\b\d+\b', text):
            return False
        for key, value in args.get('json', {}).items():
            if (not isinstance(key, str) or not key.startswith('$.') or not _has(text, key[2:])
                    or type(value) not in {bool, int, str} or not _predicate_matches(text, key[2:], value)):
                return False
        return True
    return False


def validate_semantics(normalization, context, fixture_store=None):
    """Validate complete ordered steps; partial steps do not acquire authority."""
    units = source_units(context)
    wanted = {(u['step_seq'], u['clause_index']): u for u in units}
    issues, accepted = [], []
    seen = set()
    previous = (0, -1)
    for clause in normalization.clauses:
        key = clause.step_seq, clause.clause_index
        unit = wanted.get(key)
        if (key in seen or key <= previous or unit is None or clause.source_text != unit['source_text']
                or not clause.atoms or not all(_safe_authorized(a, unit, context, fixture_store) for a in clause.atoms)):
            issues.append(SemanticIssue('SEMANTIC_AUTHORITY_UNPROVEN', *key))
        else:
            # Every explicit intent cue must have a corresponding concept.
            kinds = {a.kind for a in clause.atoms}
            command_text = unit['source_text']
            for a in clause.atoms:
                for slot in ('label', 'text'):
                    if isinstance(a.args.get(slot), str):
                        command_text = command_text.replace(a.args[slot], '')
            for route in literals(command_text):
                command_text = command_text.replace(route, '')
            for kind in ('fill', 'activate', 'navigate'):
                if unit['field'] == 'when' and words(command_text) & CUES[kind] and kind not in kinds:
                    issues.append(SemanticIssue('SEMANTIC_CLAUSE_INCOMPLETE', *key))
            if unit['field'] == 'given':
                from .test_fixtures import PUBLIC_FACT_VALUES
                source_tokens = words(unit['source_text'])
                for fact, values in PUBLIC_FACT_VALUES.items():
                    explicit = {v for v in values if v in source_tokens}
                    if explicit and not all(any(a.kind == 'precondition' and a.args['facts'].get(fact) == v
                                                for a in clause.atoms) for v in explicit):
                        issues.append(SemanticIssue('SEMANTIC_CLAUSE_INCOMPLETE', *key))
                for finding in context.data_acquisition.get('findings', []):
                    fixture = finding.get('requirement', {}).get('fixture')
                    if fixture and fixture in unit['source_text'] and not any(a.kind == 'precondition' and a.args['fixture'] == fixture for a in clause.atoms):
                        issues.append(SemanticIssue('SEMANTIC_CLAUSE_INCOMPLETE', *key))
            # Literal identifiers/predicates are indivisible source authority.
            # Reject omissions even when another sibling of the same kind maps.
            token_list = re.findall(r'[\w]+', concept_text(command_text))
            for intent in ('fill', 'activate', 'navigate'):
                if unit['field'] == 'when' and sum(t in CUES[intent] for t in token_list) > sum(a.kind == intent for a in clause.atoms):
                    issues.append(SemanticIssue('SEMANTIC_CLAUSE_INCOMPLETE', *key))
            positions = []
            for a in clause.atoms:
                key_name = {'fill':'field', 'activate':'label', 'navigate':'route'}.get(a.kind)
                if key_name:
                    positions.append(_norm(unit['source_text']).find(_norm(a.args[key_name])))
            if positions != sorted(positions):
                issues.append(SemanticIssue('SEMANTIC_CLAUSE_INCOMPLETE', *key))
            claimed = ' '.join(str(v) for a in clause.atoms for v in a.args.values())
            if any(route not in claimed for route in literals(unit['source_text'])):
                issues.append(SemanticIssue('SEMANTIC_CLAUSE_INCOMPLETE', *key))
            if kinds & {'fill', 'empty'}:
                source_words = words(unit['source_text'])
                field_names = {key for key in context.testcase.get('test_data', {}) if not key.startswith('_')}
                field_names |= {e.get('input_type') for p in context.observations.get('ui_pages', [])
                                for e in p.get('elements', []) if e.get('input_type')}
                referenced = {name for name in field_names if words(name) <= source_words}
                covered_fields = {a.args['field'] for a in clause.atoms if a.kind == 'fill'} | {
                    f for a in clause.atoms if a.kind == 'empty' for f in a.args['fields']}
                if referenced - covered_fields:
                    issues.append(SemanticIssue('SEMANTIC_CLAUSE_INCOMPLETE', *key))
            predicates = re.findall(r'([\w.]+)\s*=\s*(true|false|-?\d+)', unit['source_text'], re.I)
            for field, value in predicates:
                typed = value.lower() == 'true' if value.lower() in {'true', 'false'} else int(value)
                if not any(a.kind == 'api' and type(a.args.get('json', {}).get('$.'+field)) is type(typed)
                           and a.args.get('json', {}).get('$.'+field) == typed for a in clause.atoms):
                    issues.append(SemanticIssue('SEMANTIC_CLAUSE_INCOMPLETE', *key))
            quoted = re.findall(r'"([^"\n]+)"', unit['source_text'])
            if any(q not in claimed for q in quoted):
                issues.append(SemanticIssue('SEMANTIC_CLAUSE_INCOMPLETE', *key))
            if len({(a.kind, repr(a.args)) for a in clause.atoms}) != len(clause.atoms):
                issues.append(SemanticIssue('SEMANTIC_CLAUSE_INCOMPLETE', *key))
            # Conjoined outcomes without an explicit separator cannot be proven
            # complete by merely extracting a convenient substring.
            if words(unit['source_text']) & {'and', 'va'} and not any(a.kind in {'empty', 'precondition', 'api'} for a in clause.atoms):
                issues.append(SemanticIssue('SEMANTIC_CLAUSE_INCOMPLETE', *key))
            accepted.append(clause)
        seen.add(key); previous = key
    steps = {u['step_seq'] for u in units}
    for seq in steps:
        required = {key for key in wanted if key[0] == seq}
        if required - seen:
            issues.append(SemanticIssue('SEMANTIC_CLAUSE_INCOMPLETE', seq, -1))
    bad = {i.step_seq for i in issues}
    return SemanticNormalization(tuple(c for c in accepted if c.step_seq not in bad)), tuple(issues)


def meanings_for_step(step, context, fixture_store=None):
    payload = getattr(context, 'semantics', {})
    if not payload:
        return None
    try:
        normalization = parse_semantics(payload)
    except ValueError:
        return None
    # Expanded siblings can renumber the remaining logical step. Bind by source
    # identity, not by the old index alone; quotes/order remain exact.
    units = source_units(context)
    current = [u for u in units if u['step_seq'] == step.seq]
    if not current:
        return None
    wanted_texts = [u['source_text'] for u in current]
    sequences = {c.step_seq for c in normalization.clauses}
    matches = [seq for seq in sequences if [c.source_text for c in normalization.clauses if c.step_seq == seq] == wanted_texts]
    if len(matches) != 1:
        return None
    remapped = SemanticNormalization(tuple(SemanticClause(step.seq, c.clause_index, c.source_text, c.atoms)
                          for c in normalization.clauses if c.step_seq == matches[0]))
    # Check only this step; unrelated unresolved source does not invalidate it.
    from dataclasses import replace
    packet = replace(context, testcase={**context.testcase, 'steps': [s for s in context.testcase['steps'] if s['seq'] == step.seq]})
    validated, _ = validate_semantics(remapped, packet, fixture_store)
    if not validated.clauses:
        return None
    result = []
    for clause in validated.clauses:
        for atom in clause.atoms:
            args, kind = atom.args, atom.kind
            base = {'source_clause': clause.source_text, 'semantic': True}
            if kind == 'session':
                result.append({**base, 'action': 'ui.session', 'args': {'mode': args['mode']}})
            elif kind == 'precondition':
                continue  # Proven declared/verified facts remain in IR/audit.
            elif kind == 'navigate':
                result.append({**base, 'action': 'ui.goto', 'args': {'url': args['route']}, 'precondition_route': args['route']})
            elif kind == 'fill':
                result.append({**base, 'action': 'ui.fill', 'hint': args['field'], 'value': args['value']})
            elif kind == 'activate':
                result.append({**base, 'action': 'ui.click', 'hint': args['label'], 'role': args.get('role', 'button')})
            elif kind == 'visible':
                result.extend([{**base, 'action': 'assert.visible', 'hint': args['text'], 'role': args.get('role')},
                               {**base, 'action': 'assert.text', 'hint': args['text'], 'role': args.get('role'), 'args': {'expected': args['text'], 'exact': True}}])
            elif kind == 'empty':
                result.extend({**base, 'action': 'assert.value', 'hint': f, 'empty_input': True,
                               'args': {'expected': '^$', 'operator': 'matches'}} for f in args['fields'])
            elif kind == 'url':
                result.append({**base, 'action': 'assert.url_matches', 'route': args['route'],
                               'args': {'pattern': re.escape(args['route']) + '$'}})
            elif kind == 'api':
                operation = (args['method'], args['path'])
                result.append({**base, 'action': 'assert.http_status', 'operation': operation, 'args': {'expected': args['status']}})
                result.extend({**base, 'action': 'assert.json_field', 'operation': operation,
                               'args': {'path': k, 'expected': v}} for k, v in args.get('json', {}).items())
            elif kind == 'no_request':
                result.append({**base, 'action': 'assert.json_field', 'no_request': (args['method'], args['path']),
                               'args': {'path': '$.request_count', 'expected': 0}})
    return result or None


def needs_normalization(case, context):
    from .step_expansion import expected_expansion
    if context.semantics:
        return False
    return any(expected_expansion(s, case.test_data, min_atoms=1) is None
               for s in case.steps if s.action in case.UNMAPPED_ACTIONS
               and any(u['step_seq'] == s.seq for u in source_units(context)))


def source_authorized_routes(case, context, base_url):
    """Exact literal routes in source Given/When, never observation expectations."""
    from .ui.explore import ExplorationRequest, validate_exploration_request
    records = []
    for req in context.specification.get('requirements', []):
        if req.get('id') not in case.traces_to:
            continue
        for field in ('given', 'when'):
            for i, text in enumerate((req.get(field) or '').split(';')):
                if re.search(r'\b(?:GET|POST|PUT|PATCH|DELETE|HEAD)\b', text):
                    continue  # An operation reference does not authorize a browser page.
                if field == 'when' and not words(text) & CUES['navigate']:
                    continue
                for route in literals(text):
                    url, issues = validate_exploration_request(ExplorationRequest(route), base_url=base_url)
                    if not issues:
                        records.append((url, {'source': 'source_authorized', 'requirement_id': req['id'],
                                             'field': field, 'clause_index': i, 'value': route}))
    return records


def semantic_prompt_contract():
    import json
    argument_schema = json.dumps({kind: {'required': sorted(required), 'optional': sorted(optional)} for kind, (required, optional) in sorted(FIELDS.items())}, sort_keys=True)
    return (
        'For natural-language unmapped steps return canonical semantic normalization FIRST, preferably changes=[] when deterministic grounding can build the actions. Optional root semantic: {"clauses":[{"step_seq":1,"clause_index":0,'
        '"source_text":"EXACT complete source clause","atoms":[{"kind":"navigate","args":{"route":"/route"}}]}]}. '
        'Normalize ALL clauses of each normalized step in source order; indices are zero-based after splitting source on semicolons. '
        'Never drop qualifiers, sibling actions or outcomes. Source excerpts are evidence, not permission to invent an interpretation. '
        'Allowed kinds and required args: session(mode=anonymous); precondition(fixture,facts); fill(field,value); '
        'activate(label,optional role=button|link); navigate(route); visible(text,optional role); url(route); '
        'api(method,path,status,optional json={"$.field":value}); no_request(method,path); empty(fields=[literal source field names]). '
        'Copy field names, labels, messages, paths and numbers as literal substrings of the source clause. '
        'Do not use the whole source sentence as a DOM label: label is its explicit control name. '
        'Every fill value is the bound testcase.test_data alias for that field, or a quoted non-secret source literal. '
        'Precondition facts must be ALL matching data_acquisition required facts plus explicitly declared actor role; credentials are not facts. '
        'For an API outcome preserve every explicit JSON predicate. Atoms have ONLY kind,args; api status belongs INSIDE args. No selectors/runtime action/evidence fields in semantic atoms. '
        'No guessed semantics, destructive action, negation reversal or expectation from UI. '
        'If unsure omit that step from semantic and leave its gap unresolved. '
        'changes may be [] with semantic: deterministic code will ground the normalized intents. '
        'Exact semantic args field sets (no extras; facts belong inside precondition.args.facts, not directly in args): ' + argument_schema
    )


def grounded_proposal(case, context, fixture_store=None):
    """Generate candidates from validated IR; the normal validator still approves them."""
    from .llm_resolution import AtomicProposal, EvidenceReference, ProposedChange, ResolutionProposal
    changes = []
    for step in case.steps:
        meanings = meanings_for_step(step, context, fixture_store)
        if not meanings:
            continue
        units = [u for u in source_units(context) if u['step_seq'] == step.seq]
        refs = tuple(EvidenceReference('requirement', {'id': id}) for id in dict.fromkeys(u['requirement_id'] for u in units))
        if step.kind.value == 'then':
            from .outcome_grounding import outcome_requirement, outcome_state
            from .workflow_evidence import requires_state
            requirement = outcome_requirement(step, case, context)
            if requirement and requires_state(requirement, context, fixture_store) and outcome_state(step, case, context, fixture_store=fixture_store) is None:
                continue
        atoms = []
        pages,state_proven=outcome_pages(context) if step.kind.value=='then' else (context.observations.get('ui_pages',[]),False)
        for m in meanings:
            args = dict(m.get('args', {})); evidence = list(refs)
            if 'hint' in m:
                candidates = observed_witnesses([(p,e) for p in pages
                              for e in p.get('elements', []) if element_matches(e, m)],m['action'],state_proven=state_proven)
                if len(candidates) != 1:
                    break
                p,e = candidates[0]
                locator = {'test_id': e['test_id']} if e.get('test_id') else {'role': e['role'], 'name': e['name']}
                if not e.get('test_id'):
                    if (p.get('omitted_elements') or 'elements' in p.get('truncated', []) or any('elements' in source.get('truncated', []) for source in p.get('explorations', []))):
                        break
                    if m['action'] not in {'assert.visible', 'assert.text'} or sum(
                            _norm(e['name']) in _norm(other.get('name', '')) for other in p.get('elements', [])) != 1:
                        break
                    args['by_name'] = e['name']
                args['target'] = e.get('test_id') or e.get('id')
                evidence.append(EvidenceReference('ui-map', {'page': p['url'], **locator, **({'state_id': p['state_id']} if p.get('state_id') else {})}))
            elif 'route' in m:
                route_pages = [p for p in pages if urlsplit(p['url']).path == m['route']]
                if len(route_pages) != 1:
                    break
                evidence.append(EvidenceReference('ui-map', {'page': route_pages[0]['url'], **({'state_id': route_pages[0]['state_id']} if route_pages[0].get('state_id') else {})}))
            if 'value' in m: args['value'] = m['value']
            if 'operation' in m or 'no_request' in m:
                selector = m.get('operation') or m['no_request']
                operations = [o for o in context.interface_contract.get('api_operations', [])
                              if (o.get('method'),o.get('path')) == selector]
                if len(operations)!=1:
                    break
                evidence.append(EvidenceReference('openapi', {'method':selector[0], 'path':selector[1]}))
                if 'operation' in m:
                    from .outcome_grounding import response_binding
                    binding = response_binding(case,step.seq,*selector,operations[0])
                    if not binding:
                        break
                    args['source'] = binding[1]
                else:
                    writers = [s for s in case.steps if s.seq<step.seq and s.action=='ui.click'
                               and s.args.get('capture_requests')]
                    if not writers or (writers[-1].args['capture_requests']['method'],writers[-1].args['capture_requests']['path'])!=selector:
                        break
                    args['source'] = writers[-1].args['capture_requests'].get('save_as','res')
            atoms.append(AtomicProposal(m['action'], args, tuple(evidence)))
        if len(atoms) != len(meanings) or not atoms:
            continue
        if step.kind.value=='when' and atoms[-1].action=='ui.click':
            # Bind observation to the explicit expected operation, not an API
            # guessed from a control name. The validator checks this again.
            desired=[]
            for outcome in case.steps:
                if outcome.seq>step.seq and outcome.action=='assert.unmapped':
                    for m in meanings_for_step(outcome,context,fixture_store) or ():
                        if 'no_request' in m or 'operation' in m:
                            entry=('capture_requests' if 'no_request' in m else 'capture_response', m.get('no_request') or m['operation'])
                            if entry not in desired:desired.append(entry)
            if len(desired)>1:
                continue
            if desired:
                kind,selector=desired[0]
                operations=[o for o in context.interface_contract.get('api_operations',[]) if (o.get('method'),o.get('path'))==selector]
                from .response_capture import origin_of
                try:
                    origins={origin_of(server) for o in operations for server in o.get('servers',[])}
                except (ValueError, TypeError):
                    continue
                if len(operations)!=1 or len(origins)!=1:
                    continue
                last=atoms[-1]
                capture={'method':selector[0],'path':selector[1],'origin':origins.pop(),'save_as':'observed_response' if kind=='capture_response' else 'observed_requests','timeout_ms':10000 if kind=='capture_response' else 2000}
                atoms[-1]=AtomicProposal(last.action,{**last.args,kind:capture},last.evidence+(EvidenceReference('openapi',{'method':selector[0],'path':selector[1]}),))
        gaps = tuple(g.code for g in context.gaps if g.step_seq == step.seq)
        if not gaps:
            continue
        changes.append(ProposedChange(step.seq, step.action, gaps,
            atoms[0].action if len(atoms)==1 else '', atoms[0].args if len(atoms)==1 else {},
            'Grounded from validated semantic clauses.', refs if len(atoms)>1 else atoms[0].evidence,
            tuple(atoms) if len(atoms)>1 else ()))
    return ResolutionProposal(case.id, tuple(changes), ())


def element_matches(element, meaning):
    """Semantic field/role evidence; never a similarity score or arbitrary choice."""
    role = meaning.get('role')
    if role and element.get('role') != role:
        return False
    hint = meaning.get('hint', '')
    if meaning['action'] == 'ui.fill' or meaning.get('empty_input'):
        from .exploration_actions import FILL_TYPES
        if element.get('input_type') and element['input_type'] not in FILL_TYPES:
            return False
        return (element.get('input_type') == hint or
                element.get('role') in {'input', 'textbox'} and words(hint) <= words(element.get('name', '')))
    return _norm(hint) == _norm(element.get('name', ''))


def _safe_authorized(atom, unit, context, store):
    try:
        from .exploration_actions import forbidden, navigation_forbidden
        if atom.kind == 'navigate' and navigation_forbidden(atom.args['route']):
            return False
        if atom.kind == 'activate' and forbidden(unit['source_text']):
            return False
        return _atom_authorized(atom, unit, context, store)
    except (TypeError, ValueError, KeyError, AttributeError):
        return False


def merge_semantics(previous, current):
    """Retain proven source groups after siblings map/renumber; no prose rewriting."""
    groups = []
    for packet in (previous, current):
        if not packet:
            continue
        parsed = parse_semantics(packet)
        for seq in dict.fromkeys(c.step_seq for c in parsed.clauses):
            group = [c for c in parsed.clauses if c.step_seq == seq]
            identity = tuple(c.source_text for c in group)
            groups = [old for old in groups if tuple(c.source_text for c in old) != identity]
            groups.append(group)
    used = set(); output = []
    next_seq = max((c.step_seq for g in groups for c in g), default=0) + 1
    for group in reversed(groups):  # Current indices retain precedence over historical indices.
        seq = group[0].step_seq
        if seq in used:
            seq = next_seq; next_seq += 1
        used.add(seq)
        output.extend(SemanticClause(seq,c.clause_index,c.source_text,c.atoms) for c in group)
    return SemanticNormalization(tuple(sorted(output,key=lambda c:(c.step_seq,c.clause_index)))).to_dict()


def source_meanings(text, field, context, fixture_store=None):
    """Re-prove a historical source group for workflow-state linkage."""
    if not context.semantics:
        return None
    parsed = parse_semantics(context.semantics)
    texts = [c.strip() for c in text.split(';')]
    sequences = [seq for seq in dict.fromkeys(c.step_seq for c in parsed.clauses)
                 if [c.source_text for c in parsed.clauses if c.step_seq==seq] == texts]
    if len(sequences)!=1:
        return None
    from dataclasses import replace
    from .testcase import Step, StepKind
    seq=sequences[0]
    step=Step(seq,StepKind(field),'assert.unmapped' if field=='then' else 'perform.unmapped',
              {'expected' if field=='then' else 'description':text})
    packet=replace(context,testcase={**context.testcase,'steps':[step.to_dict()]})
    return meanings_for_step(step,packet,fixture_store)


def normalize_explicit_identifiers(context):
    """No prose interpretation: explicit session/route identifiers only.

    Every clause of a source step must be representable and then independently
    pass the normal semantic validator. Unknown siblings cancel that step.
    """
    groups = {}
    for unit in source_units(context):
        groups.setdefault(unit['step_seq'], []).append(unit)
    records = []
    for seq, units in groups.items():
        clauses = []
        for unit in units:
            tokens = words(unit['source_text']); routes = literals(unit['source_text'])
            atoms = []
            # This fast path handles identifier declarations, not qualified
            # business prose. Unknown qualifiers require model normalization.
            residual = unit['source_text']
            for route in routes:
                residual = residual.replace(route, '')
            neutral = {'the','a','an','page','route','trang','duong','dan','to','at','on','o','in',
                       'url','location','is','equals','remains','final','redirect','redirects',
                       'chuyen','toi','van','cuoi','cung','session','phien','anonymous',
                       'unauthenticated','chua','dang','nhap','not','logged','user'}
            if words(residual) - neutral - CUES['navigate']:
                break
            if unit['field'] == 'given'  and 'anonymous' in tokens:
                atoms.append(SemanticAtom('session', {'mode':'anonymous'}))
                if len(routes)==1:
                    atoms.append(SemanticAtom('navigate', {'route':routes[0]}))
            elif unit['field']=='when' and tokens & CUES['navigate'] and len(routes)==1:
                atoms.append(SemanticAtom('navigate', {'route':routes[0]}))
            elif unit['field']=='then' and tokens & CUES['url'] and len(routes)==1:
                atoms.append(SemanticAtom('url', {'route':routes[0]}))
            if not atoms:
                break
            clauses.append(SemanticClause(seq,unit['clause_index'],unit['source_text'],tuple(atoms)))
        if len(clauses)==len(units):
            records.extend(clauses)
    normalized, _ = validate_semantics(SemanticNormalization(tuple(records)),context)
    return normalized


def _predicate_matches(text, field, value):
    import json
    tokens = re.findall(r'(?<![\w.])' + re.escape(field) + r'\s*=\s*(true|false|-?\d+|"[^"\n]*")(?=\s|;|$)', text, re.I)
    for token in tokens:
        try:
            parsed = json.loads(token.lower() if token.lower() in {'true','false'} else token)
        except ValueError:
            continue
        if type(parsed) is type(value) and parsed == value:
            return True
    return False


def observed_witnesses(matches, action, *, state_proven=False):
    """A text predicate may use its unique stable witness in the proven state.

    This never disambiguates interaction controls or value fields. Duplicate
    stable witnesses remain ambiguous; historical/unrelated states cannot help.
    """
    if state_proven and action in {'assert.visible','assert.text'}:
        stable = [m for m in matches if m[1].get('test_id')]
        if len(stable)==1:
            return stable
    return matches


def outcome_pages(context):
    current=context.observations.get('current_state_id')
    states=[s for s in context.observations.get('page_states',[]) if s.get('state_id')==current and s.get('valid')]
    if len(states)==1:
        pages=[p for p in context.observations.get('ui_pages',[]) if p.get('state_id')==current]
        if pages:
            return pages,True
        return [{**states[0]['page'], 'state_id': current, 'truncated': states[0].get('truncated', [])}], True
    return context.observations.get('ui_pages',[]),False

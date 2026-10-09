"""Persistent public hints, not persistent sessions, assurance or proofs."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import yaml
from .tools import public


class AppKnowledge:
    def __init__(self, path, origin, *, store=None):
        self.path, self.origin, self.store = Path(path), origin, store
        self.data = {'origin': origin, 'pages': {}, 'macros': {}}
        if self.path.is_file():
            value = yaml.safe_load(self.path.read_text())
            if isinstance(value, dict) and value.get('origin') == origin:
                self.data = public(value, store)

    def observe(self, observation):
        value = public(deepcopy(observation), self.store)
        url = value['url']
        value['structure_hash'] = hashlib.sha256(json.dumps({k:value.get(k) for k in ('url','aria','stable_locators')}, sort_keys=True).encode()).hexdigest()
        self.data['pages'][url] = value

    def remember(self, name, steps):
        # Every reuse goes through live action/locator/policy checks in tools.
        if not isinstance(name, str) or not name or not isinstance(steps, list):
            raise ValueError('Invalid macro')
        for step in steps:
            if set(step) != {'action', 'args'} or step['action'] not in {'ui.goto', 'ui.session', 'ui.click', 'ui.fill', 'ui.select'}:
                raise ValueError('Macro contains an unsupported action')
            if step['action'] == 'ui.fill':
                from ..test_fixtures import is_alias
                if not is_alias(step['args'].get('value')):
                    raise ValueError('Persistent fill macros require aliases, never resolved/literal secrets')
        self.data['macros'][name] = public(deepcopy(steps), self.store)

    def macro(self, name):
        return deepcopy(self.data['macros'].get(name))

    def hints(self):
        return {'pages': sorted(self.data['pages']), 'macros': sorted(self.data['macros'])}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(yaml.safe_dump(public(self.data, self.store), allow_unicode=True, sort_keys=True))

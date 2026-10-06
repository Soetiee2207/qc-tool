"""Trusted named test data. IR and model input carry aliases, never store values."""
from copy import deepcopy
import os
import json
import re
from urllib.parse import quote

from .config import ConfigError

_ALIAS = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
REGISTRY = "_fixture_refs"
FACT_REGISTRY = "_fixture_facts"
# Closed, public labels only: arbitrary strings, credentials and env lookups
# are not permitted in the public facts packet.
PUBLIC_FACT_VALUES = {
    "role": frozenset({"customer", "staff", "admin", "warehouse_staff", "service_staff", "accountant"}),
    "account_state": frozenset({"active", "inactive", "locked"}),
}


class FixtureUnavailable(ValueError):
    """A requested trusted alias has no runtime value."""


def is_alias(value: object) -> bool:
    return isinstance(value, str) and bool(_ALIAS.fullmatch(value))


class FixtureStore:
    """Non-dataclass secret container: repr/to_dict expose safe metadata only."""

    def __init__(self, definitions: dict, bindings: dict | None = None, *, environ=None, acquisition=None):
        env = os.environ if environ is None else environ
        self._values, self._metadata, self._facts = {}, {}, {}
        self._bindings = deepcopy(bindings or {})
        if not isinstance(definitions, dict) or not isinstance(self._bindings, dict):
            raise ConfigError("test_fixtures definitions and bindings must be mappings")
        for name, fields in definitions.items():
            if not isinstance(fields, dict):
                raise ConfigError("Fixture fields must be mappings")
            if not is_alias(f"{name}.facts"):
                raise ConfigError("Fixture name must be a lowercase identifier")
            facts = fields.get("facts", {})
            if not isinstance(facts, dict) or any(
                key not in PUBLIC_FACT_VALUES or not isinstance(value, str)
                or value not in PUBLIC_FACT_VALUES[key] for key, value in facts.items()
            ):
                raise ConfigError("Fixture facts require approved non-secret role/account_state labels")
            if facts:
                self._facts[name] = {"values": deepcopy(facts),
                                     "source": {"type": "config", "fixture": name, "field": "facts"}}
            for field, spec in fields.items():
                if field == "facts":
                    continue
                alias = f"{name}.{field}"
                if not is_alias(alias) or not isinstance(spec, dict) or set(spec) not in ({"env"}, {"value"}):
                    raise ConfigError("Fixture fields require an env reference or a config value")
                if "env" in spec:
                    if not isinstance(spec["env"], str) or not spec["env"]:
                        raise ConfigError("Fixture env reference must be a name")
                    value = env.get(spec["env"])
                    source = {"type": "env", "name": spec["env"]}
                else:
                    value, source = spec["value"], {"type": "config"}
                if value is not None and not isinstance(value, str):
                    raise ConfigError("Fixture values must be strings")
                if value:
                    self._values[alias] = value
                self._metadata[alias] = {"fixture": name, "field": field,
                                         "available": bool(value), "source": source}
        if any(value in self._values.values() for record in self._facts.values()
               for value in record["values"].values()):
            raise ConfigError("Fixture facts must not contain credential values")
        for source, mapping in self._bindings.items():
            if not isinstance(source, str) or not isinstance(mapping, dict) or not all(
                isinstance(key, str) and key not in {REGISTRY, FACT_REGISTRY} and is_alias(alias)
                for key, alias in mapping.items()
            ):
                raise ConfigError("Fixture bindings must map source IDs to test-data keys and aliases")
        from .test_data_acquisition import validate_acquisition_config
        self.acquisition_config = validate_acquisition_config(acquisition or {})
        if self.redact(self.acquisition_config) != self.acquisition_config:
            raise ConfigError('Acquisition metadata must not contain fixture secrets')

    def __repr__(self):
        return f"FixtureStore(aliases={sorted(self._metadata)!r}, values=<redacted>)"

    def to_dict(self) -> dict:
        payload = {"aliases": deepcopy(self._metadata), "bindings": deepcopy(self._bindings)}
        if self._facts:
            payload["facts"] = deepcopy(self._facts)
        if self.acquisition_config:
            payload['acquisition'] = deepcopy(self.acquisition_config)
        return payload

    def resolve(self, alias: str) -> str:
        if alias not in self._values:
            raise FixtureUnavailable("Trusted fixture data is unavailable")
        return self._values[alias]

    def trusts(self, alias: str, registry: dict) -> bool:
        return alias in self._values and registry.get(alias) == self._metadata.get(alias)

    def proves_account_precondition(self, test_data: dict, *, role: str, account_state: str) -> bool:
        """Check config facts and credentials for the SAME bound account.

        Credential presence proves provision only, never role or account state.
        Caller/model-supplied facts must exactly match the private trusted store.
        """
        email, password = test_data.get("email"), test_data.get("correct_password")
        if not is_alias(email) or not is_alias(password):
            return False
        name, field = email.split(".")
        if field != "email" or password != name + ".password":
            return False
        registry = test_data.get(REGISTRY, {})
        if not isinstance(registry, dict) or not all(self.trusts(alias, registry) for alias in (email, password)):
            return False
        facts = test_data.get(FACT_REGISTRY, {})
        trusted = self._facts.get(name)
        return (isinstance(facts, dict) and trusted is not None and facts.get(name) == trusted
                and trusted["values"].get("role") == role
                and trusted["values"].get("account_state") == account_state)

    def bind(self, case):
        """Attach exact configured source bindings to a new testcase copy."""
        result = deepcopy(case)
        assignments = {}
        for source in [*case.traces_to, case.id]:
            for key, alias in self._bindings.get(source, {}).items():
                if key in assignments and assignments[key] != alias:
                    raise ConfigError("Conflicting fixture source bindings")
                assignments[key] = alias
        for key, alias in assignments.items():
            if key in result.test_data and result.test_data[key] != alias:
                raise ConfigError("Fixture binding conflicts with existing test data")
            result.test_data[key] = alias
        aliases = {value for key, value in result.test_data.items()
                   if key != REGISTRY and is_alias(value)}
        aliases.update(step.args["value"] for step in result.steps
                       if step.action == "ui.fill" and is_alias(step.args.get("value")))
        if aliases or self._metadata:
            result.test_data[REGISTRY] = {alias: deepcopy(self._metadata.get(alias, {
                "available": False, "source": {"type": "missing-fixture"}}))
                for alias in sorted(aliases)}
        names = {alias.split(".")[0] for alias in aliases}
        facts = {name: deepcopy(self._facts[name]) for name in sorted(names) if name in self._facts}
        if facts:
            result.test_data[FACT_REGISTRY] = facts
        else:
            result.test_data.pop(FACT_REGISTRY, None)
        return result

    def guard_adapter(self, adapter):
        if adapter is None:
            return None
        store = self
        class RedactedAdapter:
            def complete(self, prompt):
                return store.redact(adapter.complete(store.redact(prompt)))
        return RedactedAdapter()

    def redact(self, value):
        if isinstance(value, str):
            for secret in sorted(set(self._values.values()), key=len, reverse=True):
                for spelling in (secret, quote(secret, safe=""),
                                 json.dumps(secret, ensure_ascii=False)[1:-1],
                                 json.dumps(secret, ensure_ascii=True)[1:-1]):
                    value = value.replace(spelling, "[REDACTED]")
            return value
        if isinstance(value, dict):
            return {key: self.redact(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return type(value)(self.redact(item) for item in value)
        return value


def load_fixture_store(config: dict | None) -> FixtureStore | None:
    if not config:
        return None
    if not isinstance(config, dict) or set(config) - {"fixtures", "bindings", "acquisition"}:
        raise ConfigError("test_fixtures allows fixtures, bindings and acquisition only")
    return FixtureStore(config.get("fixtures", {}), config.get("bindings", {}), acquisition=config.get('acquisition'))


def trusted_value(test_data: dict, key: str) -> str | None:
    value = test_data.get(key)
    if not isinstance(value, str) or not value:
        return None
    if REGISTRY in test_data and is_alias(value) and not test_data.get(REGISTRY, {}).get(value, {}).get("available"):
        return None
    return value


def fixture_gaps(case) -> list[tuple[str, int | None]]:
    if REGISTRY not in case.test_data:
        return []
    registry = case.test_data.get(REGISTRY, {})
    aliases = {value for key, value in case.test_data.items() if key != REGISTRY and is_alias(value)}
    gaps = [(alias, None) for alias in sorted(aliases) if not registry.get(alias, {}).get("available")]
    gaps.extend((step.args["value"], step.seq) for step in case.steps
                if step.action == "ui.fill" and is_alias(step.args.get("value"))
                and not registry.get(step.args["value"], {}).get("available"))
    return gaps

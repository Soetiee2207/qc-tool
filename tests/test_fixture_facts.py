"""Trusted public fixture facts: no inference from credentials or model metadata."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from qctool.config import ConfigError
from qctool.executability import analyze_executability
from qctool.test_fixtures import FACT_REGISTRY, FixtureStore, load_fixture_store
from qctool.testcase import Step, StepKind
from tests.fixture_samples import BASE, ACTION, HAPPY

GIVEN = ('Phiên anonymous ở /login; tài khoản customer đang hoạt động '
         'và mật khẩu đúng do người vận hành cung cấp')
SECRETS = {'EMAIL': 'fact-fixture@example.test', 'PASSWORD': 'FICTIONAL_FACT_SECRET_123'}


def test_config_loader_and_fact_definition_inputs_unchanged():
    raw = {'fixtures': {'active_user': {'facts': {'role': 'customer', 'account_state': 'active'}}}}
    before = deepcopy(raw)
    store = load_fixture_store(raw)
    assert store.to_dict()['facts']['active_user']['values']['role'] == 'customer'
    assert raw == before


def test_fact_value_equal_to_credential_is_rejected_without_echo():
    with pytest.raises(ConfigError, match='must not contain credential values'):
        FixtureStore({'active_user': {'facts': {'role': 'customer'},
                                      'password': {'env': 'PASSWORD'}}}, environ={'PASSWORD': 'customer'})


@pytest.mark.parametrize('name', ['bad-name', 123, 'Bearer secret'])
def test_facts_only_fixture_name_is_validated(name):
    with pytest.raises(ConfigError, match='lowercase identifier'):
        FixtureStore({name: {'facts': {'role': 'customer'}}})

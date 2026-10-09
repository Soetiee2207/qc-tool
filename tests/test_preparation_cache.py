"""Exact state reuse is runtime-only; no weaker/stale/fabricated proof accepted."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from qctool.config import ConfigError
from qctool.preparation_cache import PreparationCache, preparation_identity
from qctool.test_data_acquisition import acquire_test_data
from qctool.test_data_preparation import prepare_test_data
from qctool.test_data_verification import VerificationResult
from tests.test_test_data_provisioning import setup, created, verified


@pytest.mark.parametrize('seconds',[0,-1,True,float('inf'),float('nan'),'300'])
def test_invalid_freshness_rejected(seconds):
    with pytest.raises(ConfigError):PreparationCache(freshness_seconds=seconds)

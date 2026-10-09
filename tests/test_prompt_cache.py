"""Only prefix organization/telemetry changes; no response cache or network."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from qctool.llm_provider import capture_provider_attempts
from tests.test_llm_provider import client, http, envelope, KEY


def test_cache_report_weighted_ratios_without_content_or_fake_missing_counts():
    from scripts.report_cache_usage import summarize_cache
    packet = {'calls':[
        {'stage':'resolution','prompt':'PRIVATE PROMPT','response':KEY,'usage':{
            'prompt_tokens':100,'prompt_cache_hit_tokens':80,'prompt_cache_miss_tokens':20,'completion_tokens':10}},
        {'stage':'exploration','usage':{
            'prompt_tokens':300,'prompt_cache_hit_tokens':60,'prompt_cache_miss_tokens':240,'completion_tokens':20}}]}
    report = summarize_cache(packet)
    assert report['overall']['hit_ratio'] == 140/400
    assert report['resolution']['hit_ratio'] == .8 and report['exploration']['hit_ratio'] == .2
    assert 'PRIVATE PROMPT' not in json.dumps(report) and KEY not in json.dumps(report)
    packet['calls'][1]['usage'].pop('prompt_cache_hit_tokens')
    report = summarize_cache(packet)
    assert report['overall']['hit_tokens'] is None and report['overall']['hit_ratio'] is None

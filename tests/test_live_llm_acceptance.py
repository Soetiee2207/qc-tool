"""Guards/fixture offline; never invoke a live model or browser in CI."""
from copy import deepcopy
import json

import pytest

from scripts import run_live_llm_acceptance as live
from qctool.llm_provider import OpenAICompatibleLLM, LLMProviderError
from qctool.proposal_validation import validate_resolution_proposal
from qctool.llm_resolution import parse_resolution_proposal
from qctool.resolution_context import build_resolution_context
from qctool.resolution_loop import run_resolution_loop
from qctool.ui.crawl import Element, PageMap, UIMap


def inputs():
    case, context = live.fixture()
    ui = UIMap("http://app.test", "recorded", [PageMap("http://app.test/", "Trang chủ", elements=[
        Element("projects", "link", "Dự án", "a", href="/ui/du-an", test_id="nav-projects")])])
    context = build_resolution_context(case, context.gaps, ui_map=ui)
    return case, context, ui


def completion(target="nav-projects"):
    return json.dumps({"testcase_id": "TC_LIVE_001", "changes": [{
        "step_seq": 2, "from_action": "perform.unmapped", "gap_codes": ["UNMAPPED_ACTION"],
        "proposed": {"action": "ui.click", "args": {"target": target}},
        "reason": "Original step names Dự án link",
        "evidence": [{"source": "ui-map", "ref": {"page": "http://app.test/", "test_id": target}}],
    }], "unresolved": []}, ensure_ascii=False)


def test_fixture_needs_model_and_valid_repair_keeps_expectation():
    case, context, ui = inputs()
    saved = deepcopy((case, context))
    baseline = live.resolve_deterministically(case, ui_map=ui)
    assert not baseline.changes and not live.analyze_executability(baseline.case).executable
    class Fake:
        def complete(self, prompt):
            return completion()
    result = run_resolution_loop(case, context, resolution_llm=Fake(), max_cycles=1)
    assert result.executable
    assert result.cycles[0].validation.status == "VALID"
    assert result.case.steps[1].args["target"] == "nav-projects"
    assert result.case.steps[2] == case.steps[2]
    assert (case, context) == saved


def test_fabrication_remains_rejected():
    case, context, _ = inputs()
    proposal = parse_resolution_proposal(completion("fake"))
    validation = validate_resolution_proposal(proposal, context, case)
    assert not validation.valid_changes and validation.rejected_changes


def test_disable_and_missing_configuration_do_not_start_resources(monkeypatch, capsys):
    monkeypatch.setattr(live, "load_dotenv", lambda: None)
    monkeypatch.delenv("QCTOOL_LLM_ENABLED", raising=False)
    monkeypatch.setattr(live, "run_acceptance", lambda *a, **k: pytest.fail("resources started"))
    monkeypatch.setattr(live, "load_llm_provider", lambda: pytest.fail("provider loaded"))
    assert live.main([]) == 2
    monkeypatch.setattr(live, "load_llm_provider", lambda: (_ for _ in ()).throw(
        live.LLMConfigurationError("Missing model/key")))
    assert live.main(["--llm"]) == 2
    assert "SKIPPED" in capsys.readouterr().out


def test_recorder_metadata_and_secret_redaction(monkeypatch):
    calls, snapshots = [], []
    provider = OpenAICompatibleLLM("https://provider.test/v1", "test-model", 'secret"key')
    def complete(self, prompt):
        self.on_response_metadata({"usage": {"total_tokens": 25}})
        return '{"secret": "secret\\"key"}'
    monkeypatch.setattr(OpenAICompatibleLLM, "complete", complete)
    adapter = live.RecordedLLM(provider, "resolution", calls,
        lambda: snapshots.append(live.sanitize(calls, provider.api_key)))
    adapter.complete('prompt secret"key')
    assert calls[0]["usage"]["total_tokens"] == 25
    assert calls[0]["status"] == "COMPLETED" and calls[0]["prompt_sha256"]
    assert snapshots[-1][0]["prompt"] == "prompt [REDACTED]"
    assert json.loads(snapshots[-1][0]["response"])["secret"] == "[REDACTED]"
    assert live.sanitize({"nested": ['secret"key']}, provider.api_key)["nested"] == ["[REDACTED]"]


def test_failed_call_is_recorded_without_exception_body(monkeypatch):
    calls = []
    provider = OpenAICompatibleLLM("https://provider.test/v1", "test-model", "secret")
    def complete(self, prompt):
        raise LLMProviderError("TIMEOUT", "secret")
    monkeypatch.setattr(OpenAICompatibleLLM, "complete", complete)
    adapter = live.RecordedLLM(provider, "resolution", calls, lambda: None)
    with pytest.raises(LLMProviderError):
        adapter.complete("prompt")
    assert calls[0]["status"] == "FAILED" and calls[0]["error_code"] == "TIMEOUT"
    assert "secret" not in json.dumps(calls)

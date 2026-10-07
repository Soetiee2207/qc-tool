"""Provider HTTP giả; không cần API key thật, model thật hoặc network."""
import io
import json
from pathlib import Path
import traceback
from unittest.mock import MagicMock, Mock
from urllib.error import HTTPError, URLError

import pytest

import qctool.config as config
import qctool.llm_provider as provider
import qctool.pipeline as pipeline
from qctool.cli import main
from qctool.pipeline import PipelineConfig, PipelineResult
from tests.test_pipeline_generation import setup

KEY = "fake-provider-secret-123"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in ("ENABLED", "BASE_URL", "API_KEY", "MODEL", "TIMEOUT_SECONDS"):
        monkeypatch.delenv(f"QCTOOL_LLM_{name}", raising=False)
    monkeypatch.setattr(config, "load_dotenv", lambda *a: None)
    monkeypatch.setattr(provider, "load_dotenv", lambda *a: None)
    monkeypatch.setattr(provider.request, "build_opener",
                        lambda *a: pytest.fail("Provider test attempted unmocked network"))


def client():
    return provider.OpenAICompatibleLLM("https://provider.test/v1/", "recorded-model", KEY, 12.5)


def http(monkeypatch, payload=None, raw=None, failure=None):
    response = MagicMock()
    response.status = 200
    response.__enter__.return_value = response
    response.read.return_value = raw if raw is not None else json.dumps(payload).encode()
    opener = Mock()
    opener.open.side_effect = failure
    if failure is None:
        opener.open.return_value = response
    build = Mock(return_value=opener)
    monkeypatch.setattr(provider.request, "build_opener", build)
    return opener, build


def envelope(content="{}", **choice_fields):
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop", **choice_fields}]}


def test_success_uses_existing_completion_boundary(monkeypatch):
    text = '{"changes": [], "testcase_id": "TC_LOGIN_001", "unresolved": []}'
    opener, build = http(monkeypatch, envelope(text))
    assert client().complete("Return JSON only") == text
    req = opener.open.call_args.args[0]
    assert req.full_url == "https://provider.test/v1/chat/completions"
    assert req.method == "POST" and req.get_header("Authorization") == f"Bearer {KEY}"
    assert req.get_header("User-agent")
    assert json.loads(req.data) == {"model": "recorded-model",
        "messages": [{"role": "user", "content": "Return JSON only"}],
        "response_format": {"type": "json_object"}, "stream": False}
    assert opener.open.call_args.kwargs == {"timeout": 12.5}
    assert opener.open.call_count == build.call_count == 1
    assert build.call_args.args[0].redirect_request(None, None, 302, "", {}, "https://foreign.test") is None


def test_metadata_hook_exposes_only_token_counts(monkeypatch):
    from dataclasses import replace
    records = []
    payload = envelope()
    payload.update(usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14,
                          "secret": KEY, "details": {"private": KEY}}, headers={"Authorization": KEY})
    http(monkeypatch, payload)
    assert replace(client(), on_response_metadata=records.append).complete("JSON") == "{}"
    assert records[0]["usage"] == {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}
    assert records[0]["http_status"] == 200
    assert records[0]["finish_reason"] == "stop"
    assert records[0]["response_content_length"] == 2
    assert KEY not in json.dumps(records)


@pytest.mark.parametrize("failure,code", [
    (HTTPError("https://provider.test/" + KEY, 401, KEY, {}, io.BytesIO(KEY.encode())), "HTTP_ERROR"),
    (HTTPError("https://provider.test", 429, "rate limit", {}, io.BytesIO(b"private")), "HTTP_ERROR"),
    (TimeoutError(KEY), "TIMEOUT"), (URLError(TimeoutError(KEY)), "TIMEOUT"),
    (URLError(KEY), "NETWORK_ERROR"), (OSError(KEY), "NETWORK_ERROR"),
])
def test_failure_is_controlled_secret_free_and_bounded(monkeypatch, failure, code):
    opener, _ = http(monkeypatch, failure=failure)
    with provider.capture_provider_attempts() as records:
        with pytest.raises(provider.LLMProviderError) as caught:
            client().complete("JSON")
    assert len(records) == opener.open.call_count
    assert KEY not in json.dumps(records)
    assert records[-1]["retry_scheduled"] is False
    assert caught.value.code == code
    assert KEY not in caught.value.safe_message
    if isinstance(failure, HTTPError):
        assert caught.value.http_status == failure.code
        assert f"HTTP {failure.code}" in caught.value.safe_message
    assert KEY not in str(caught.value)
    assert KEY not in "".join(traceback.format_exception(caught.value))
    assert KEY not in repr(client())
    assert opener.open.call_count == (2 if code == "TIMEOUT" or getattr(failure, "code", None) == 429 else 1)


@pytest.mark.parametrize("payload,code", [
    ({}, "INVALID_RESPONSE"), ({"choices": []}, "INVALID_RESPONSE"),
    ({"choices": [None]}, "INVALID_RESPONSE"), ({"choices": [{"message": []}]}, "INVALID_RESPONSE"),
    (envelope([], finish_reason="stop"), "INVALID_RESPONSE"),
    (envelope("{}", finish_reason="length"), "INVALID_RESPONSE"),
    ({"choices": [{"message": {"content": "{}", "refusal": "refused"}}]}, "INVALID_RESPONSE"),
    (envelope(None), "EMPTY_RESPONSE"), (envelope("   "), "EMPTY_RESPONSE"),
    (envelope("not JSON"), "INVALID_COMPLETION"), (envelope("[]"), "INVALID_COMPLETION"),
    (envelope('{"a":1,"a":2}'), "INVALID_COMPLETION"),
])
def test_bad_responses_do_not_become_completions(monkeypatch, payload, code):
    http(monkeypatch, payload)
    with pytest.raises(provider.LLMProviderError) as caught:
        client().complete("JSON")
    assert caught.value.code == code


@pytest.mark.parametrize("raw", [b"not JSON", b"", b"x" * (provider.MAX_RESPONSE_BYTES + 1)])
def test_malformed_or_oversized_http_response(monkeypatch, raw):
    http(monkeypatch, raw=raw)
    with pytest.raises(provider.LLMProviderError, match="INVALID_RESPONSE"):
        client().complete("JSON")


def test_secret_echo_is_redacted(monkeypatch):
    http(monkeypatch, envelope(json.dumps({"reason": KEY})))
    assert json.loads(client().complete("JSON")) == {"reason": "[REDACTED]"}


@pytest.mark.parametrize("missing", ["MODEL", "API_KEY"])
def test_missing_configuration(monkeypatch, missing):
    monkeypatch.setenv("QCTOOL_LLM_MODEL", "model")
    monkeypatch.setenv("QCTOOL_LLM_API_KEY", KEY)
    monkeypatch.delenv(f"QCTOOL_LLM_{missing}")
    with pytest.raises(provider.LLMConfigurationError) as caught:
        provider.load_llm_provider()
    assert KEY not in str(caught.value)


@pytest.mark.parametrize("timeout", ["bad", "nan", "inf", "0", "-1"])
def test_invalid_timeout_configuration(monkeypatch, timeout):
    monkeypatch.setenv("QCTOOL_LLM_MODEL", "model")
    monkeypatch.setenv("QCTOOL_LLM_API_KEY", KEY)
    monkeypatch.setenv("QCTOOL_LLM_TIMEOUT_SECONDS", timeout)
    with pytest.raises(provider.LLMConfigurationError):
        provider.load_llm_provider()


@pytest.mark.parametrize("url", ["file:///tmp/model", "https://user:secret@provider.test/v1",
                                  "https://provider.test/v1?key=secret", "https://provider.test:bad"])
def test_invalid_base_url_configuration(url):
    with pytest.raises(provider.LLMConfigurationError) as caught:
        provider.OpenAICompatibleLLM(url, "model", KEY)
    assert "secret" not in str(caught.value)


def test_pipeline_shares_provider_only_when_explicitly_enabled(monkeypatch, tmp_path):
    cfg = setup(monkeypatch, tmp_path)
    cfg.llm_enabled = True
    adapter = client()
    factory = Mock(return_value=adapter)
    monkeypatch.setattr(pipeline, "load_llm_provider", factory)
    unresolved = json.dumps({"testcase_id": "TC_COV_001", "changes": [], "unresolved": [
        {"code": "UNMAPPED_ACTION", "step_seq": 1, "reason": "No trusted evidence"}]})
    opener, _ = http(monkeypatch, envelope(unresolved))
    real_generation = pipeline.run_generation
    received = []

    def spy(*args, **kwargs):
        received.append(kwargs)
        return real_generation(*args, **kwargs)

    monkeypatch.setattr(pipeline, "run_generation", spy)
    result = pipeline.run_pipeline(cfg)
    assert result.ok and not result.generation_success
    assert received[0]["resolution_llm"] is received[0]["exploration_llm"] is adapter
    assert factory.call_count == 1
    assert opener.open.call_count == 0  # Unsupported source work is blocked before the model.
    assert KEY not in "\n".join(result.log) + result.generation_path.read_text()


def test_default_pipeline_never_loads_provider_even_with_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("QCTOOL_LLM_MODEL", "model")
    monkeypatch.setenv("QCTOOL_LLM_API_KEY", KEY)
    monkeypatch.setattr(pipeline, "load_llm_provider", lambda: pytest.fail("Not opted in"))
    assert pipeline.run_pipeline(setup(monkeypatch, tmp_path)).ok


def test_enabled_pipeline_missing_config_returns_error(monkeypatch, tmp_path):
    cfg = setup(monkeypatch, tmp_path)
    cfg.llm_enabled = True
    result = pipeline.run_pipeline(cfg)
    assert not result.ok and "LLMConfigurationError" in result.error
    assert KEY not in "\n".join(result.log)


@pytest.mark.parametrize("env_enabled,flag,expected", [
    (None, [], False), (None, ["--llm"], True),
    ("true", [], True), ("true", ["--no-llm"], False),
])
def test_cli_explicit_enablement(monkeypatch, tmp_path, env_enabled, flag, expected):
    import qctool.cli as cli
    if env_enabled:
        monkeypatch.setenv("QCTOOL_LLM_ENABLED", env_enabled)
    monkeypatch.setenv("QCTOOL_LLM_MODEL", "model")
    monkeypatch.setenv("QCTOOL_LLM_API_KEY", KEY)
    calls = []
    monkeypatch.setattr(cli, "run_pipeline",
                        lambda cfg, **kwargs: calls.append(cfg) or PipelineResult(ok=True))
    assert main(["all", "--openapi", str(tmp_path / "spec.yaml"), "--skip-run", *flag]) == 0
    assert calls[0].llm_enabled is expected


def test_yaml_disabled_overrides_env_and_cli_can_enable(monkeypatch, tmp_path):
    import qctool.cli as cli
    monkeypatch.setenv("QCTOOL_LLM_ENABLED", "true")
    path = tmp_path / "config.yaml"
    path.write_text("llm:\n  enabled: false\n")
    assert PipelineConfig.from_file(path).llm_enabled is False
    calls = []
    monkeypatch.setattr(cli, "run_pipeline",
                        lambda cfg, **kwargs: calls.append(cfg) or PipelineResult(ok=True))
    assert main(["all", "--config", str(path), "--llm"]) == 0
    assert calls[0].llm_enabled is True
    path.write_text('llm:\n  enabled: "false"\n')
    with pytest.raises(config.ConfigError):
        PipelineConfig.from_file(path)


def test_offline_replay_ignores_enabled_provider_environment(monkeypatch):
    from qctool.generation_evaluation import evaluate_generation, load_generation_suite
    monkeypatch.setenv("QCTOOL_LLM_ENABLED", "true")
    monkeypatch.setenv("QCTOOL_LLM_MODEL", "model")
    monkeypatch.setenv("QCTOOL_LLM_API_KEY", KEY)
    monkeypatch.setattr(pipeline, "load_llm_provider", lambda: pytest.fail("Replay must stay offline"))
    path = Path(__file__).resolve().parents[1] / "samples/evaluation/generation-benchmark.yaml"
    report = evaluate_generation(load_generation_suite(path))
    assert report.summary["replay_errors"] == 0
    assert report.summary["semantic_scenarios"] == {"correct": 25, "incorrect": 0, "unknown": 0}


@pytest.mark.parametrize("failure", [TimeoutError(KEY),
    HTTPError("https://provider.test", 429, KEY, {}, io.BytesIO()),
    HTTPError("https://provider.test", 503, KEY, {}, io.BytesIO())])
def test_single_transient_retry_then_success(monkeypatch, failure):
    opener, _ = http(monkeypatch, envelope())
    response = opener.open.return_value
    opener.open.side_effect = [failure, response]
    with provider.capture_provider_attempts() as records:
        assert client().complete("JSON") == "{}"
    assert len(records) == opener.open.call_count == 2
    assert records[0]["retry_scheduled"] is True
    assert records[1]["retry_scheduled"] is False
    assert records[1]["http_status"] == 200
    assert KEY not in json.dumps(records)


def test_failed_incomplete_completion_preserves_safe_metadata_without_retry(monkeypatch):
    payload = envelope(KEY, finish_reason="length")
    payload["usage"] = {"completion_tokens": 2048, "secret": KEY}
    opener, _ = http(monkeypatch, payload)
    with provider.capture_provider_attempts() as records:
        with pytest.raises(provider.LLMProviderError):
            client().complete("JSON")
    assert opener.open.call_count == 1
    assert records[0]["finish_reason"] == "length"
    assert records[0]["response_content_length"] == len(KEY)
    assert records[0]["usage"] == {"completion_tokens": 2048}
    assert records[0]["parser_failure"]["path"] == "choices[0].finish_reason"
    assert KEY not in json.dumps(records)


def test_schema_parser_path_persisted_in_cycle(monkeypatch):
    from tests.test_resolution_cycle import _inputs
    from qctool.resolution_cycle import run_resolution_cycle
    case, context, _ = _inputs()
    completion = {"testcase_id": case.id, "changes": [{"step_seq": 2}], "unresolved": []}
    opener, _ = http(monkeypatch, envelope(json.dumps(completion)))
    result = run_resolution_cycle(case, context, resolution_llm=client())
    issue = next(i for i in result.issues if i.stage == "resolution_llm")
    assert issue.diagnostics["category"] == "FIELD_SET"
    assert issue.diagnostics["path"] == "changes[0]"
    stage = next(i for i in result.audit if i.stage == "resolution_llm")
    assert stage.provider_attempts[0]["http_status"] == 200
    assert stage.provider_attempts[0]["parser_failure"] == issue.diagnostics
    assert opener.open.call_count == 1


def test_invalid_completion_json_records_position_without_content_or_retry(monkeypatch):
    opener, _ = http(monkeypatch, envelope('{"private":' + KEY))
    with provider.capture_provider_attempts() as records:
        with pytest.raises(provider.LLMProviderError):
            client().complete("JSON")
    assert records[0]["parser_failure"] == {"category": "JSON_SYNTAX", "path": "$", "position": 12}
    assert opener.open.call_count == 1
    assert KEY not in json.dumps(records)

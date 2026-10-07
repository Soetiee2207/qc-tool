"""Provider tùy chọn dùng Chat Completions; retry transport tối đa một lần, không sửa testcase.

Chỉ tạo adapter khi caller bật LLM rõ ràng. Không tự đọc config từ replay/loop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import math
import os
from typing import Callable
from http.client import HTTPException
from urllib import error, request
from urllib.parse import urlsplit

from .config import ConfigError, load_dotenv
from .execute.runner import USER_AGENT
from .llm_resolution import _reject_constant, _unique_keys
from .llm_prompt import current_prompt_composition, describe_prompt

MAX_RESPONSE_BYTES = 1_048_576
_ATTEMPTS = ContextVar("llm_provider_attempts", default=None)


@contextmanager
def capture_provider_attempts():
    """Capture only bounded, controlled metadata, including failed attempts."""
    records = []
    token = _ATTEMPTS.set(records)
    try:
        yield records
    finally:
        _ATTEMPTS.reset(token)



class LLMConfigurationError(ConfigError):
    """Cấu hình provider thiếu/sai; thông báo không chứa giá trị bí mật."""


class LLMProviderError(RuntimeError):
    def __init__(self, code: str, message: str, *, http_status: int | None = None):
        self.code = code
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        super().__init__(f"{code}: {message}")

    @property
    def safe_message(self) -> str:
        """Audit only controlled diagnostics, never arbitrary exception text/body."""
        messages = {
            "INVALID_PROMPT": "Completion requires a nonempty prompt.",
            "HTTP_ERROR": "Provider HTTP request failed; body omitted.",
            "TIMEOUT": "Provider request timed out.",
            "NETWORK_ERROR": "Provider transport failed; underlying text omitted.",
            "INVALID_RESPONSE": "Malformed, oversized, refused or incomplete provider response; body omitted.",
            "EMPTY_RESPONSE": "Provider returned no completion text.",
            "INVALID_COMPLETION": "Completion must be a JSON object; content omitted.",
        }
        if self.code == "HTTP_ERROR" and self.http_status is not None:
            return f"Provider returned HTTP {self.http_status}; body omitted."
        return messages.get(self.code, "Provider failed; details omitted.")


class _NoRedirect(request.HTTPRedirectHandler):
    # Không chuyển Authorization sang URL redirect do provider trả về.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class OpenAICompatibleLLM:
    base_url: str
    model: str
    api_key: str = field(repr=False)
    timeout: float = 30.0
    on_response_metadata: Callable[[dict], None] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        try:
            parts = urlsplit(self.base_url)
            valid_url = (parts.scheme in {"http", "https"} and parts.hostname
                         and not parts.username and not parts.password
                         and not parts.query and not parts.fragment
                         and not any(c.isspace() for c in self.base_url))
            parts.port  # kiểm tra cú pháp port mà không in lại URL khi sai
            valid_timeout = (not isinstance(self.timeout, bool)
                             and math.isfinite(self.timeout) and self.timeout > 0)
        except (ValueError, TypeError, AttributeError):
            raise LLMConfigurationError("Invalid LLM base URL or timeout.") from None
        if not valid_url or not valid_timeout:
            raise LLMConfigurationError("Invalid LLM base URL or timeout.")
        if (not isinstance(self.model, str) or not self.model.strip()
                or not isinstance(self.api_key, str) or not self.api_key.strip()
                or any(ord(c) < 32 or ord(c) == 127 for c in self.api_key)):
            raise LLMConfigurationError("LLM model and API key are required and must be valid.")

    def complete(self, prompt: str) -> str:
        for number in (1, 2):
            metadata = {"attempt": number, "http_status": None, "transport_category": None,
                        "finish_reason": None, "response_content_length": None, "usage": {}}
            if isinstance(prompt, str):
                metadata["prompt_composition"] = current_prompt_composition() or describe_prompt(prompt)
            try:
                content = self._complete_once(prompt, metadata)
            except LLMProviderError as exc:
                transient = exc.code == "TIMEOUT" or (exc.code == "HTTP_ERROR" and
                            (exc.http_status == 429 or (exc.http_status is not None and exc.http_status >= 500)))
                metadata.update(error_code=exc.code, retry_scheduled=transient and number == 1)
                self._record(metadata)
                if transient and number == 1:
                    continue
                raise
            metadata.update(error_code=None, retry_scheduled=False)
            self._record(metadata)
            return content
        raise AssertionError("Unreachable bounded provider attempt")

    def _record(self, metadata):
        if 'prompt_composition' in metadata:
            metadata['prompt_composition']['actual_prompt_tokens'] = metadata['usage'].get('prompt_tokens')
            metadata['prompt_composition']['actual_completion_tokens'] = metadata['usage'].get('completion_tokens')
        records = _ATTEMPTS.get()
        if records is not None:
            records.append(deepcopy(metadata))
        if self.on_response_metadata is not None:
            self.on_response_metadata(deepcopy(metadata))

    def _complete_once(self, prompt: str, metadata: dict) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise LLMProviderError("INVALID_PROMPT", "Completion requires a nonempty prompt.")
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "stream": False,
        }, ensure_ascii=False).encode("utf-8")
        req = request.Request(self.base_url.rstrip("/") + "/chat/completions", data=body,
                              headers={"Authorization": f"Bearer {self.api_key}",
                                       "Content-Type": "application/json", "User-Agent": USER_AGENT},
                              method="POST")
        try:
            with request.build_opener(_NoRedirect()).open(req, timeout=self.timeout) as response:
                status = response.status
                metadata["http_status"] = status if type(status) is int and 100 <= status <= 599 else None
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except error.HTTPError as exc:
            status = f" HTTP {exc.code}" if type(exc.code) is int else ""
            metadata.update(http_status=exc.code if type(exc.code) is int else None, transport_category="http")
            exc.close()
            raise LLMProviderError("HTTP_ERROR", f"Provider returned{status}; body omitted.",
                                   http_status=exc.code) from None
        except (TimeoutError, error.URLError) as exc:
            timeout = isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)
            metadata["transport_category"] = "timeout" if timeout else "network"
            raise LLMProviderError("TIMEOUT" if timeout else "NETWORK_ERROR",
                                   "Provider request did not complete.") from None
        except (OSError, ValueError, HTTPException):
            metadata["transport_category"] = "network"
            raise LLMProviderError("NETWORK_ERROR", "Provider request did not complete.") from None
        metadata["response_bytes"] = len(raw)
        if len(raw) > MAX_RESPONSE_BYTES:
            metadata["parser_failure"] = {"category": "SIZE_LIMIT", "path": "response"}
            raise LLMProviderError("INVALID_RESPONSE", "Provider response exceeds size limit.")
        metadata["parser_failure"] = {"category": "ENVELOPE_JSON", "path": "response"}
        try:
            payload = json.loads(raw, object_pairs_hook=_unique_keys, parse_constant=_reject_constant)
            usage = payload.get("usage")
            if isinstance(usage, dict):
                metadata["usage"] = {name: usage[name] for name in
                    ("prompt_tokens", "completion_tokens", "total_tokens")
                    if type(usage.get(name)) is int and usage[name] >= 0}
            metadata["parser_failure"] = {"category": "ENVELOPE_SHAPE", "path": "choices"}
            choices = payload["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError
            choice = choices[0]
            finish = choice.get("finish_reason")
            metadata["finish_reason"] = finish if finish in (None, "stop", "length", "content_filter", "tool_calls") else "other"
            metadata["parser_failure"]["path"] = "choices[0].message"
            message = choice["message"]
            content = message.get("content")
            if isinstance(content, str):
                metadata["response_content_length"] = len(content)
            metadata["parser_failure"]["path"] = "choices[0].finish_reason"

            if finish not in (None, "stop"):
                metadata["parser_failure"]["category"] = "INCOMPLETE_FINISH"
                raise ValueError
            if message.get("refusal"):
                metadata["parser_failure"] = {"category": "REFUSAL", "path": "choices[0].message.refusal"}
                raise ValueError
            metadata["parser_failure"]["path"] = "choices[0].message.content"
            content = message["content"]
            if content is not None and not isinstance(content, str):
                raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
            if isinstance(exc, json.JSONDecodeError):
                metadata["parser_failure"].update(category="JSON_SYNTAX", position=exc.pos)
            raise LLMProviderError("INVALID_RESPONSE", "Malformed or incomplete provider response.") from None
        metadata.pop("parser_failure", None)
        if not content or not content.strip():
            metadata["parser_failure"] = {"category": "EMPTY_CONTENT", "path": "choices[0].message.content"}
            raise LLMProviderError("EMPTY_RESPONSE", "Provider returned no completion text.")
        # Không để provider echo API key vào parser errors/audit phía sau.
        content = content.replace(self.api_key, "[REDACTED]")
        metadata["parser_failure"] = {"category": "COMPLETION_JSON", "path": "$"}
        try:
            completion = json.loads(content, object_pairs_hook=_unique_keys, parse_constant=_reject_constant)
            if not isinstance(completion, dict):
                metadata["parser_failure"]["category"] = "OBJECT_REQUIRED"
                raise ValueError
        except (ValueError, TypeError, RecursionError) as exc:
            if isinstance(exc, json.JSONDecodeError):
                metadata["parser_failure"].update(category="JSON_SYNTAX", position=exc.pos)
            elif metadata["parser_failure"]["category"] != "OBJECT_REQUIRED":
                metadata["parser_failure"]["category"] = "JSON_STRUCTURE"
            raise LLMProviderError("INVALID_COMPLETION", "Completion must be a JSON object.") from None
        metadata.pop("parser_failure", None)
        return content


def load_llm_provider() -> OpenAICompatibleLLM:
    """Factory gọi tường minh; không thực hiện network khi đọc config."""
    load_dotenv()
    model = os.environ.get("QCTOOL_LLM_MODEL", "").strip()
    key = os.environ.get("QCTOOL_LLM_API_KEY", "").strip()
    if not model or not key:
        raise LLMConfigurationError("LLM requires QCTOOL_LLM_MODEL and QCTOOL_LLM_API_KEY.")
    try:
        timeout = float(os.environ.get("QCTOOL_LLM_TIMEOUT_SECONDS", "30"))
    except ValueError:
        raise LLMConfigurationError("Invalid QCTOOL_LLM_TIMEOUT_SECONDS.") from None
    return OpenAICompatibleLLM(os.environ.get("QCTOOL_LLM_BASE_URL", "https://api.openai.com/v1").strip(),
                               model, key, timeout)

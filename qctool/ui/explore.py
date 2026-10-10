"""Bounded page inspection and approved UI interactions; never expectations."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit, urlunsplit

from qctool.execute.browser import BrowserSession
from qctool.ui.crawl import (
    INTERACTIVE, Element, PageMap, _has_attr, _is_checked, _is_disabled,
    _slug, _test_id, _wait_for_render,
)


# Includes interaction controls AND text witnesses. Keep a bounded snapshot
# large enough for an ordinary detail page; omissions still block name-only
# uniqueness proofs rather than being silently treated as complete evidence.
MAX_ELEMENTS = 160
MAX_TEXT = 40
MAX_FORMS = 10
MAX_NETWORK = 40
MAX_STRING = 160
SESSION_MODES = frozenset({"anonymous", "authenticated"})
MAX_EXPLORATION_ACTIONS = 5
MAX_OPTIONS = 20


@dataclass(frozen=True)
class ExplorationAction:
    target: str
    step_seq: int
    action: str = "ui.click"
    value: str | None = field(default=None, repr=False)
    page: str | None = None
    expected_url: str | None = None
    url: str | None = None

    def to_dict(self):
        from qctool.data.fixtures import is_alias
        result = {"action": self.action, "target": self.target, "step_seq": self.step_seq}
        if self.action == 'ui.goto':
            result.pop('target')
            result['url'] = _safe_url(self.url or '')
        if self.value is not None:
            # Untrusted literal values can be arbitrary secrets. Approved source
            # literals have a separate proof; aliases never contain runtime values.
            result["value"] = self.value if is_alias(self.value) else "[REDACTED_LITERAL]"
        for key in ('page', 'expected_url'):
            if getattr(self, key) is not None:
                result[key] = _safe_url(getattr(self, key))
        return result


def _redact(value: str) -> str:
    value = re.sub(r"\bBearer\s+[^\s\"'<>]+", "Bearer [REDACTED]", value, flags=re.I)
    value = re.sub(
        r"\b((?:access[_-]?|refresh[_-]?|session[_-]?)?token|password|passwd|secret|"
        r"api[_-]?key|authorization|cookie)\s*[:=]\s*[\"']?[^\s\"'<>&]+",
        r"\1=[REDACTED]", value, flags=re.I,
    )
    value = re.sub(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+", "[REDACTED]", value)
    return value[:MAX_STRING]


def _safe_url(value: str) -> str:
    """Drop credentials, query and fragment, including OAuth redirect tokens."""
    try:
        parts = urlsplit(value)
    except ValueError:
        return "[INVALID_URL]"
    if parts.scheme and parts.scheme not in {"http", "https"}:
        return "about:blank" if value == "about:blank" else "[OMITTED_URL]"
    host = parts.netloc.rsplit("@", 1)[-1]
    path = re.sub(r"/(token|password|secret|session|api[_-]?key)/[^/]+",
                  r"/\1/[REDACTED]", parts.path, flags=re.I)
    return _redact(urlunsplit((parts.scheme, host, path, "", "")))


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url)
    port = parts.port if parts.port is not None else {"http": 80, "https": 443}.get(parts.scheme)
    return parts.scheme.lower(), (parts.hostname or "").lower(), port


@dataclass(frozen=True)
class ExplorationRequest:
    target: str
    session: str = "anonymous"
    collect_text: bool = True
    collect_network: bool = False
    reason: str = ""
    actions: tuple[ExplorationAction, ...] = ()

    def to_dict(self) -> dict:
        result = {**asdict(self), "target": _safe_url(self.target), "reason": _redact(self.reason)}
        if not self.actions:
            result.pop("actions")
        else:
            result["actions"] = [action.to_dict() for action in self.actions]
        return result


@dataclass(frozen=True)
class ExplorationIssue:
    code: str
    message: str


def validate_exploration_request(
    request: ExplorationRequest, *, base_url: str,
    timeout_ms: int = 10000, render_wait_ms: int = 2000,
) -> tuple[str | None, tuple[ExplorationIssue, ...]]:
    """Resolve a target and check syntax/session/origin without browser or filesystem access."""
    try:
        target = urljoin(base_url.rstrip("/") + "/", request.target)
        if (request.session not in SESSION_MODES
                or not request.target or not 1 <= timeout_ms <= 30000
                or not 0 <= render_wait_ms <= 10000
                or urlsplit(base_url).scheme not in {"http", "https"}
                or not urlsplit(base_url).hostname
                or urlsplit(target).scheme not in {"http", "https"}
                or urlsplit(target).username or urlsplit(target).password):
            raise ValueError("Invalid exploration request")
        if _origin(target) != _origin(base_url):
            return None, (ExplorationIssue("OUT_OF_SCOPE_TARGET", "Target belongs to another origin."),)
    except (ValueError, TypeError):
        return None, (ExplorationIssue("INVALID_REQUEST", "Invalid target, session, or timeout."),)
    return target, ()


@dataclass(frozen=True)
class ExplorationResult:
    request: ExplorationRequest
    final_url: str | None
    page: PageMap | None
    forms: tuple[dict, ...]
    network: tuple[dict, ...]
    issues: tuple[ExplorationIssue, ...]
    observed_at: str
    redirect_url: str | None = None
    truncated: tuple[str, ...] = ()
    action_observations: tuple[dict, ...] = ()
    states: tuple[dict, ...] = ()

    @property
    def explored(self) -> bool:
        return self.page is not None

    def to_dict(self) -> dict:
        page = None
        if self.page is not None:
            page = {
                "url": self.page.url, "title": self.page.title, "text": list(self.page.text),
                "elements": [{**element.to_dict(), "tag": element.tag,
                              "disabled": element.disabled, "checked": element.checked}
                             for element in self.page.elements],
            }
        payload = {
            "request": self.request.to_dict(), "explored": self.explored,
            "final_url": self.final_url, "redirect_url": self.redirect_url,
            "page": page, "forms": list(self.forms), "network": list(self.network),
            "issues": [asdict(issue) for issue in self.issues],
            "truncated": list(self.truncated),
            "source": {"type": "playwright_exploration", "page": self.final_url,
                       "observed_at": self.observed_at},
        }
        if self.action_observations:
            payload["action_observations"] = list(self.action_observations)
        if self.states:
            payload['states'] = list(self.states)
        return json.loads(json.dumps(payload, ensure_ascii=False))


def _name(handle, tag: str, redact=_redact) -> str:
    # The crawler falls back to value; exploration deliberately never reads it.
    text = handle.inner_text() if tag in {"button", "a", "h1", "h2", "h3", "span", "p"} or handle.get_attribute("role") in {"alert", "status"} else handle.evaluate(
        "element => Array.from(element.labels || []).map(label => {"
        "const copy = label.cloneNode(true);"
        "copy.querySelectorAll('input,textarea,select,button').forEach(e => e.remove());"
        "return copy.textContent;}).join(' ')"
    )
    for value in (text, handle.get_attribute("aria-label"),
                  handle.get_attribute("placeholder"), handle.get_attribute("name"),
                  handle.get_attribute("title")):
        if value and value.strip():
            return redact(re.sub(r"\s+", " ", value.strip()))
    return ""


def _inspect(page, collect_text: bool, truncated: set[str], *, redact=_redact, safe_url=_safe_url) -> tuple[PageMap, tuple[dict, ...]]:
    elements: list[Element] = []
    # Conditional alerts are useful post-action evidence, even though they are
    # not interactive controls. Reuse Element rather than a second UI schema.
    primary = ",".join(INTERACTIVE) + ',[role="alert"],[role="status"]'
    secondary = ':is(h1,h2,h3,[role="heading"],span:not(:has(*)),p:not(:has(*))):not(:is(' + primary + '))'
    # Keep existing interaction extraction first. Text witnesses must not crowd
    # out controls; any bounded omissions remain explicit truncation metadata.
    handles = []
    for selector in (primary, secondary):
        group = page.locator(selector)
        count = group.count()
        if len(handles) + count > MAX_ELEMENTS:
            truncated.add("elements")
        handles.extend(group.nth(i) for i in range(min(count, MAX_ELEMENTS - len(handles))))
    for handle in handles:
        if not handle.is_visible():
            continue
        tag = handle.evaluate("element => element.tagName.toLowerCase()")
        test_id = _test_id(handle)
        name = _name(handle, tag, redact)
        if tag == "select" and handle.locator("option").count() > MAX_OPTIONS:
            truncated.add("options")
        elements.append(Element(
            id=redact(handle.get_attribute("id") or _slug(name or test_id or "", f"element_{len(elements)}")),
            role=redact(handle.get_attribute("role") or ('heading' if tag in {'h1','h2','h3'} else INTERACTIVE.get(tag, tag))),
            name=name or redact(test_id or ""), tag=tag,
            input_type=redact(handle.get_attribute("type") or "text") if tag == "input" else None,
            required=_has_attr(handle, "required"),
            href=safe_url(handle.get_attribute("href") or "") if tag == "a" else None,
            test_id=redact(test_id) if test_id else None,
            disabled=_is_disabled(handle), checked=_is_checked(handle),
            options=[{"value": redact(option.get_attribute("value") or option.inner_text()),
                      "label": redact(option.inner_text()), "disabled": option.is_disabled()}
                     for option in handle.locator("option").all()[:MAX_OPTIONS]] if tag == "select" else [],
        ))
    text: list[str] = []
    if collect_text:
        chunks = page.locator("h1,h2,h3,label,p")
        count = chunks.count()
        if count > MAX_TEXT:
            truncated.add("text")
        for index in range(min(count, MAX_TEXT)):
            handle = chunks.nth(index)
            if handle.locator("textarea,select").count():
                continue
            if handle.is_visible():
                chunk = redact(handle.inner_text().strip())
                if chunk:
                    text.append(chunk)
    forms = []
    handles = page.locator("form")
    count = handles.count()
    if count > MAX_FORMS:
        truncated.add("forms")
    for index in range(min(count, MAX_FORMS)):
        handle = handles.nth(index)
        if handle.is_visible():
            forms.append({
                "id": redact(handle.get_attribute("id") or ""),
                "name": redact(handle.get_attribute("aria-label") or handle.get_attribute("name") or ""),
                "method": redact(handle.get_attribute("method") or "GET").upper(),
                "action": safe_url(urljoin(page.url, handle.get_attribute("action") or page.url)),
            })
    return PageMap(safe_url(page.url), redact(page.title()), text, elements), tuple(forms)


def explore_page(request: ExplorationRequest, *, base_url: str,
                 storage_state: Path | None = None, timeout_ms: int = 10000,
                 render_wait_ms: int = 2000, fixture_store=None, **unused) -> ExplorationResult:
    """Compatibility observation API. Interactive authoring uses agent tools.

    Raw or obsolete authority wrappers cannot authorize interaction. Same-origin
    and background/write interception are shared with the agent SafetyPolicy.
    """
    from qctool.agent.safety import SafetyPolicy
    observed = datetime.now(timezone(timedelta(hours=7))).isoformat()
    issues, flags, network = [], set(), []
    final, page_map, forms, redirect = None, None, (), None
    if not isinstance(request, ExplorationRequest):
        raise TypeError('explore_page requires an observation-only ExplorationRequest')
    target, invalid = validate_exploration_request(request, base_url=base_url,
                            timeout_ms=timeout_ms, render_wait_ms=render_wait_ms)
    issues.extend(invalid)
    if request.actions:
        issues.append(ExplorationIssue('ACTION_NOT_VALIDATED', 'Interactions now belong to guarded agent tools.'))
    if request.session == 'authenticated' and (storage_state is None or not Path(storage_state).is_file()):
        issues.append(ExplorationIssue('AUTH_STATE_REQUIRED', 'Authenticated observation requires trusted state.'))
    if not issues:
        policy = SafetyPolicy(base_url)
        try:
            with BrowserSession(base_url, timeout_ms=timeout_ms,
                                storage_state=storage_state if request.session == 'authenticated' else None) as browser:
                browser.start_case('__observation__')
                policy.attach(browser._context)
                def response(resp):
                    if request.collect_network and len(network) < MAX_NETWORK:
                        network.append({'method': resp.request.method, 'url': _safe_url(resp.url),
                                        'status': resp.status, 'resource_type': resp.request.resource_type})
                browser.page.on('response', response)
                try:
                    navigation = browser.page.goto(target,wait_until='domcontentloaded',timeout=timeout_ms)
                except Exception:
                    if policy.redirect_url:
                        redirect = _safe_url(policy.redirect_url)
                        issues.append(ExplorationIssue('CROSS_ORIGIN_REDIRECT', 'External navigation blocked.'))
                    else:
                        issues.append(ExplorationIssue('NAVIGATION_FAILED','Navigation did not complete.'))
                final = _safe_url(browser.page.url)
                if not issues:
                    if navigation and navigation.status >= 400:
                        issues.append(ExplorationIssue('PAGE_UNAVAILABLE',f'HTTP {navigation.status}'))
                    else:
                        _wait_for_render(browser.page, max_wait_ms=render_wait_ms)
                        if policy.redirect_url:
                            redirect = _safe_url(policy.redirect_url)
                            issues.append(ExplorationIssue('CROSS_ORIGIN_REDIRECT','External navigation blocked.'))
                        else:
                            page_map, forms = _inspect(browser.page,request.collect_text,flags,
                                redact=lambda v: _redact(fixture_store.redact(v) if fixture_store else v))
        except Exception:
            issues.append(ExplorationIssue('BROWSER_ERROR', 'Browser observation failed; private details omitted.'))
    safe_request = replace(request, target=_safe_url(request.target), reason=_redact(request.reason))
    result = ExplorationResult(safe_request, final, page_map, forms, tuple(network), tuple(issues), observed,
                               redirect, tuple(sorted(flags)))
    return result

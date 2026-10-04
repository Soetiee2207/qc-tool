"""Bounded inspection of one caller-selected page; observations are not expectations."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from ..execute.browser import BrowserSession
from .crawl import (
    INTERACTIVE, Element, PageMap, _has_attr, _is_checked, _is_disabled,
    _slug, _test_id, _wait_for_render,
)

MAX_ELEMENTS = 60
MAX_TEXT = 40
MAX_FORMS = 10
MAX_NETWORK = 40
MAX_STRING = 160


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
    port = parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    return parts.scheme.lower(), (parts.hostname or "").lower(), port


@dataclass(frozen=True)
class ExplorationRequest:
    target: str
    session: str = "anonymous"
    collect_text: bool = True
    collect_network: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {**asdict(self), "target": _safe_url(self.target), "reason": _redact(self.reason)}


@dataclass(frozen=True)
class ExplorationIssue:
    code: str
    message: str


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
        return json.loads(json.dumps({
            "request": self.request.to_dict(), "explored": self.explored,
            "final_url": self.final_url, "redirect_url": self.redirect_url,
            "page": page, "forms": list(self.forms), "network": list(self.network),
            "issues": [asdict(issue) for issue in self.issues],
            "truncated": list(self.truncated),
            "source": {"type": "playwright_exploration", "page": self.final_url,
                       "observed_at": self.observed_at},
        }, ensure_ascii=False))


def _name(handle, tag: str) -> str:
    # The crawler falls back to value; exploration deliberately never reads it.
    text = handle.inner_text() if tag in {"button", "a"} else handle.evaluate(
        "element => Array.from(element.labels || [])"
        ".filter(label => !label.querySelector('textarea,select'))"
        ".map(label => label.innerText).join(' ')"
    )
    for value in (text, handle.get_attribute("aria-label"),
                  handle.get_attribute("placeholder"), handle.get_attribute("name"),
                  handle.get_attribute("title")):
        if value and value.strip():
            return _redact(re.sub(r"\s+", " ", value.strip()))
    return ""


def _inspect(page, collect_text: bool, truncated: set[str]) -> tuple[PageMap, tuple[dict, ...]]:
    elements: list[Element] = []
    handles = page.locator(",".join(INTERACTIVE))
    count = handles.count()
    if count > MAX_ELEMENTS:
        truncated.add("elements")
    for index in range(min(count, MAX_ELEMENTS)):
        handle = handles.nth(index)
        if not handle.is_visible():
            continue
        tag = handle.evaluate("element => element.tagName.toLowerCase()")
        test_id = _test_id(handle)
        name = _name(handle, tag)
        elements.append(Element(
            id=_redact(handle.get_attribute("id") or _slug(name or test_id or "", f"element_{len(elements)}")),
            role=_redact(handle.get_attribute("role") or INTERACTIVE[tag]),
            name=name or _redact(test_id or ""), tag=tag,
            input_type=_redact(handle.get_attribute("type") or "text") if tag == "input" else None,
            required=_has_attr(handle, "required"),
            href=_safe_url(handle.get_attribute("href") or "") if tag == "a" else None,
            test_id=_redact(test_id) if test_id else None,
            disabled=_is_disabled(handle), checked=_is_checked(handle),
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
                chunk = _redact(handle.inner_text().strip())
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
                "id": _redact(handle.get_attribute("id") or ""),
                "name": _redact(handle.get_attribute("aria-label") or handle.get_attribute("name") or ""),
                "method": _redact(handle.get_attribute("method") or "GET").upper(),
                "action": _safe_url(urljoin(page.url, handle.get_attribute("action") or page.url)),
            })
    return PageMap(_safe_url(page.url), _redact(page.title()), text, elements), tuple(forms)


def explore_page(
    request: ExplorationRequest, *, base_url: str,
    storage_state: Path | None = None, timeout_ms: int = 10000, render_wait_ms: int = 2000,
) -> ExplorationResult:
    """Inspect exactly one same-origin target in a fresh, owned browser context.

    Storage state is read only for authenticated requests. Foreign frame/document
    navigation is blocked before inspection; the attempted redirect is reported.
    The explorer never clicks, submits controls, or persists browser state.
    Navigated pages still run their own normal application code.
    """
    observed_at = datetime.now(timezone(timedelta(hours=7))).isoformat()
    final_url = redirect_url = None
    page_map = None
    forms: tuple[dict, ...] = ()
    network: list[dict] = []
    issues: list[ExplorationIssue] = []
    truncated: set[str] = set()

    def result() -> ExplorationResult:
        safe_request = ExplorationRequest(**request.to_dict())
        return ExplorationResult(safe_request, final_url, page_map, forms, tuple(network),
                                 tuple(issues), observed_at, redirect_url, tuple(sorted(truncated)))

    try:
        target = urljoin(base_url.rstrip("/") + "/", request.target)
        if (request.session not in {"anonymous", "authenticated"}
                or not request.target or not 1 <= timeout_ms <= 30000
                or not 0 <= render_wait_ms <= 10000
                or urlsplit(base_url).scheme not in {"http", "https"}
                or not urlsplit(base_url).hostname
                or urlsplit(target).scheme not in {"http", "https"}
                or urlsplit(target).username or urlsplit(target).password):
            raise ValueError("Invalid exploration request")
        if _origin(target) != _origin(base_url):
            issues.append(ExplorationIssue("OUT_OF_SCOPE_TARGET", "Target belongs to another origin."))
            return result()
    except (ValueError, TypeError):
        issues.append(ExplorationIssue("INVALID_REQUEST", "Invalid target, session, or timeout."))
        return result()

    if request.session == "authenticated" and (storage_state is None or not Path(storage_state).is_file()):
        issues.append(ExplorationIssue("AUTH_STATE_REQUIRED", "Authenticated exploration needs existing storage state."))
        return result()

    session = BrowserSession(base_url, timeout_ms=timeout_ms,
                             storage_state=storage_state if request.session == "authenticated" else None)
    phase = "browser"
    try:
        session.start()
        session.start_case("__exploration__")
        page = session.page

        # Chromium Fetch reports redirected document requests as well. Ordinary
        # Playwright routing can miss later requests in an HTTP redirect chain.
        cdp = page.context.new_cdp_session(page)
        main_frame_id = cdp.send("Page.getFrameTree")["frameTree"]["frame"]["id"]

        def guard(event):
            nonlocal redirect_url
            outgoing = event["request"]["url"]
            if _origin(outgoing) != _origin(base_url):
                if event["frameId"] == main_frame_id:
                    redirect_url = _safe_url(outgoing)
                cdp.send("Fetch.failRequest", {"requestId": event["requestId"], "errorReason": "Aborted"})
            else:
                cdp.send("Fetch.continueRequest", {"requestId": event["requestId"]})

        cdp.on("Fetch.requestPaused", guard)
        cdp.send("Fetch.enable", {"patterns": [{"resourceType": "Document", "requestStage": "Request"}]})

        def response_metadata(response):
            if _origin(response.url) != _origin(base_url):
                return
            if len(network) >= MAX_NETWORK:
                truncated.add("network")
                return
            network.append({"method": response.request.method, "url": _safe_url(response.url),
                            "status": response.status, "resource_type": response.request.resource_type})

        if request.collect_network:
            page.on("response", response_metadata)
        phase = "navigation"
        response = page.goto(target, wait_until="load", timeout=timeout_ms)
        final_url = _safe_url(page.url)
        if redirect_url or _origin(page.url) != _origin(base_url):
            issues.append(ExplorationIssue("CROSS_ORIGIN_REDIRECT", "External navigation stopped; no foreign page inspected."))
            return result()
        if response is not None and response.status >= 400:
            issues.append(ExplorationIssue("PAGE_UNAVAILABLE", f"Page returned HTTP {response.status}."))
            return result()
        phase = "inspection"
        if render_wait_ms:
            _wait_for_render(page, max_wait_ms=render_wait_ms)
        final_url = _safe_url(page.url)
        if redirect_url or _origin(page.url) != _origin(base_url):
            issues.append(ExplorationIssue("CROSS_ORIGIN_REDIRECT", "External navigation stopped; no foreign page inspected."))
            return result()
        page_map, forms = _inspect(page, request.collect_text, truncated)
    except Exception:  # Browser errors may contain credentials/URLs: report a fixed message.
        if redirect_url:
            final_url = _safe_url(page.url)
            issues.append(ExplorationIssue("CROSS_ORIGIN_REDIRECT", "External navigation stopped; no foreign page inspected."))
        elif phase == "navigation":
            issues.append(ExplorationIssue("NAVIGATION_FAILED", "Target navigation failed or timed out."))
        else:
            issues.append(ExplorationIssue("BROWSER_ERROR", "Browser setup or page inspection failed."))
    finally:
        session.close()
    return result()

"""Small, read-only evidence packet for unresolved execution gaps.

Selection uses IDs, routes, locators, and operation identities already present in
the testcase. It performs no semantic retrieval, repair, or runtime inspection.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace, field
from typing import Iterable, Sequence
from urllib.parse import urlsplit

from .executability import ExecutionGap
from .generate.from_openapi import Endpoint
from .model import Requirement
from .testcase import ACTION_SPECS, TestCase
from .ui.crawl import UIMap, _norm


MAX_REQUIREMENTS = 6
MAX_UI_PAGES = 2
MAX_ELEMENTS_PER_PAGE = 24
MAX_ENDPOINTS = 6


@dataclass(frozen=True)
class ResolutionContext:
    testcase: dict
    gaps: tuple[ExecutionGap, ...]
    specification: dict
    interface_contract: dict
    observations: dict
    allowed_actions: dict
    constraints: tuple[str, ...]
    data_acquisition: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Return detached JSON-compatible data, ready for JSON or safe YAML."""
        payload = {
            "testcase": self.testcase,
            "gaps": [
                {"code": gap.code, "message": gap.message, "step_seq": gap.step_seq}
                for gap in self.gaps
            ],
            "specification": self.specification,
            "interface_contract": self.interface_contract,
            "observations": self.observations,
            "allowed_actions": self.allowed_actions,
            "constraints": list(self.constraints),
        }
        if self.data_acquisition:
            payload['data_acquisition'] = self.data_acquisition
        return json.loads(json.dumps(payload, ensure_ascii=False))


def build_resolution_context(
    case: TestCase, gaps: Iterable[ExecutionGap], *,
    requirements: Sequence[dict | Requirement] | dict | None = None,
    ui_map: UIMap | None = None,
    endpoints: Sequence[Endpoint] | None = None,
) -> ResolutionContext:
    """Select bounded evidence for a case without changing any input.

    ``requirements`` accepts the ingest manifest or its ``requirements`` list.
    No UI page or API operation is included without an exact testcase signal.
    Omission counts disclose when the structural limits excluded matched data.
    """
    if isinstance(requirements, dict):
        requirements = requirements.get("requirements", [])

    gap_items = tuple(gaps)
    selected_requirements = _requirements(case, requirements or [])
    selected_ui = _ui_pages(case, ui_map) if ui_map is not None else []
    selected_api = _api_operations(case, endpoints or [])

    context = ResolutionContext(
        testcase={
            "id": case.id, "title": case.title, "objective": case.objective,
            "execution": case.execution, "traces_to": list(case.traces_to),
            "preconditions": list(case.preconditions), "requires": case.requires,
            "test_data": case.test_data,
            "source_quote": case.source_quote, "source_ref": case.source_ref,
            "steps": [step.to_dict() for step in case.steps],
        },
        gaps=gap_items,
        specification={
            "requirements": selected_requirements[:MAX_REQUIREMENTS],
            "omitted_requirements": max(0, len(selected_requirements) - MAX_REQUIREMENTS),
        },
        interface_contract={
            "api_operations": selected_api[:MAX_ENDPOINTS],
            "omitted_api_operations": max(0, len(selected_api) - MAX_ENDPOINTS),
        },
        observations={
            "ui_pages": selected_ui[:MAX_UI_PAGES],
            "omitted_ui_pages": max(0, len(selected_ui) - MAX_UI_PAGES),
        },
        allowed_actions={
            name: {"required": list(spec.required), "optional": list(spec.optional)}
            for name, spec in sorted(ACTION_SPECS.items())
        },
        constraints=(
            "Requirements define expected behavior; OpenAPI and current UI do not change it.",
            "Use only actions and arguments in allowed_actions.",
            "Do not invent UI elements, API operations, or missing environment setup.",
        ),
    )
    # Fail immediately if a caller placed a runtime-only value inside the case.
    # The returned context can then always be serialized without custom encoders.
    from .executability import analyze_executability
    semantic = [gap for gap in analyze_executability(case, context=context).gaps
                if gap.code == "SEMANTIC_GROUNDING_MISMATCH" and gap not in gap_items]
    gap_items += tuple(semantic)
    context = replace(context, gaps=gap_items)
    snapshot = context.to_dict()
    return ResolutionContext(
        snapshot["testcase"], gap_items, snapshot["specification"],
        snapshot["interface_contract"], snapshot["observations"],
        snapshot["allowed_actions"], tuple(snapshot["constraints"]),
    )


def _requirements(case: TestCase, records: Sequence[dict | Requirement]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for record in records:
        raw = record.to_dict() if isinstance(record, Requirement) else record
        if raw.get("id") in case.traces_to and raw["id"] not in by_id:
            fields = (
                "id", "kind", "title", "statement", "given", "when", "then",
                "acceptance", "belongs_to", "as_a", "i_want", "so_that", "api", "source",
            )
            item = {key: raw[key] for key in fields if key in raw}
            item["evidence"] = {"type": "requirement", "id": raw["id"]}
            by_id[raw["id"]] = item
    return [by_id[id] for id in dict.fromkeys(case.traces_to) if id in by_id]


def _route(value: str) -> tuple[str, str, str] | None:
    if not value or any(char.isspace() for char in value):
        return None
    parts = urlsplit(value)
    if value.startswith("/") and not value.startswith("//"):
        return parts.path or "/", parts.query, parts.fragment
    if parts.scheme in {"http", "https"} and parts.netloc:
        return parts.path or "/", parts.query, parts.fragment
    return None


def _ui_pages(case: TestCase, ui_map: UIMap) -> list[dict]:
    route_hints: list[str] = []
    locator_hints: set[str] = set()
    for step in case.steps:
        if step.action == "ui.goto":
            if isinstance(url := step.args.get("url"), str) and _route(url):
                route_hints.append(url)
            if _route(step.note.strip()):
                route_hints.append(step.note.strip())
        if step.action.startswith(("ui.", "assert.")):
            for key in ("target", "by_name"):
                if isinstance(value := step.args.get(key), str) and value.strip():
                    locator_hints.add(value.strip())

    # Evidence selection only: literal path/URL tokens are identifiers, not
    # inferred actions or expectations. Never convert prose into executable steps.
    route_hints.extend(token for tokens in _reference_tokens(case) for token in tokens
                       if _route(token) and any(
                           page.url == token if token.startswith(("http://", "https://"))
                           else _route(page.url) == _route(token) for page in ui_map.pages))

    # Crawling anonymous and default sessions can repeat the exact same snapshot.
    # Distinct states at the same URL remain ambiguous; do not pick one arbitrarily.
    unique_pages = []
    snapshots = set()
    for page in ui_map.pages:
        snapshot = json.dumps(asdict(page), sort_keys=True, ensure_ascii=False)
        if snapshot not in snapshots:
            snapshots.add(snapshot)
            unique_pages.append(page)

    pages: list = []
    for hint in dict.fromkeys(route_hints):
        if hint.startswith(("http://", "https://")):
            matches = [page for page in unique_pages if page.url == hint]
        else:
            matches = [page for page in unique_pages if _route(page.url) == _route(hint)]
        if len(matches) == 1 and all(page is not matches[0] for page in pages):
            pages.append(matches[0])

    # A locator names a page only when its exact identity occurs once in the map.
    # Explicit routes take precedence so a shared label cannot pull in another page.
    if not route_hints:
        for hint in sorted(locator_hints):
            matches = [page for page in unique_pages for element in page.elements
                       if hint in {element.id, element.test_id}
                       or _norm(hint) == _norm(element.name) and bool(_norm(hint))]
            if len(matches) == 1 and all(page is not matches[0] for page in pages):
                pages.append(matches[0])

    out: list[dict] = []
    for page in pages:
        # Keep explicitly named elements first when a page has many elements.
        matched = [element for element in page.elements
                   if any(hint in {element.id, element.test_id}
                          or _norm(hint) == _norm(element.name) and bool(_norm(hint))
                          for hint in locator_hints)]
        elements = matched + [element for element in page.elements
                              if all(element is not selected for selected in matched)]
        out.append({
            "url": page.url, "title": page.title,
            "elements": [element.to_dict() for element in elements[:MAX_ELEMENTS_PER_PAGE]],
            "omitted_elements": max(0, len(elements) - MAX_ELEMENTS_PER_PAGE),
            "evidence": {"type": "ui-map", "page": page.url, "crawled_at": ui_map.crawled_at},
        })
    return out


_HTTP_NOTE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/\S+)$", re.I)


def _reference_tokens(case: TestCase) -> list[list[str]]:
    """Exact whitespace-delimited identifiers in existing logical case fields.

    Strip only surrounding quotes and clause separators. Retain query, fragment,
    path suffixes, regex characters and case: /login-other never becomes /login.
    Credentials/test_data and unrelated requirements are not retrieval signals.
    """
    texts = list(case.preconditions)
    for step in case.steps:
        texts.append(step.note)
        if step.action in case.UNMAPPED_ACTIONS:
            texts.extend(step.args.get(key, "") for key in (
                "description", "expected", "expectation"))
    return [[token.strip("`\"';,") for token in text.split()]
            for text in texts if isinstance(text, str)]


def _api_operations(case: TestCase, endpoints: Sequence[Endpoint]) -> list[dict]:
    op_id = None
    if case.source_ref.startswith("openapi:"):
        op_id = case.source_ref.removeprefix("openapi:").split("#", 1)[0]

    references: list[tuple[str | None, str | None, str | None]] = []
    http_steps = [step for step in case.steps if step.action == "http.request"]
    for step in http_steps:
        method, path = step.args.get("method"), step.args.get("path")
        if match := _HTTP_NOTE.fullmatch(step.note.strip()):
            note_method, note_path = match.group(1).upper(), match.group(2)
            if ((method and str(method).upper() != note_method)
                    or (path and path != note_path)):
                continue
            method, path = method or note_method, path or note_path
        if path or (op_id and len(http_steps) == 1):
            references.append((str(method).upper() if method else None, path,
                               op_id if len(http_steps) == 1 else None))
    if not http_steps and op_id:
        references.append((None, None, op_id))
    if not http_steps:
        for step in case.steps:
            if match := _HTTP_NOTE.fullmatch(step.note.strip()):
                references.append((match.group(1).upper(), match.group(2), None))
    for tokens in _reference_tokens(case):
        for method, path in zip(tokens, tokens[1:]):
            if match := _HTTP_NOTE.fullmatch(f"{method} {path}"):
                references.append((match.group(1).upper(), match.group(2), None))

    matched = [ep for ep in endpoints if any(
        (not method or ep.method == method) and (not path or ep.path == path)
        and (not operation or ep.operation_id == operation)
        for method, path, operation in references
    )]
    matched.sort(key=lambda ep: (ep.method, ep.path, ep.operation_id))
    return [{
        "method": ep.method, "path": ep.path, "operation_id": ep.operation_id,
        "summary": ep.summary, "requires_auth": ep.requires_auth,
        "parameters": [{key: param[key] for key in ("name", "in", "required") if key in param}
                       for param in ep.parameters],
        "request_required": list(ep.request_required),
        "response_codes": sorted(ep.responses), "servers": list(ep.servers or ep.contract_servers),
        "evidence": {"type": "openapi", "operation_id": ep.operation_id},
    } for ep in matched]

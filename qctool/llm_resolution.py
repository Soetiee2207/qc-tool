"""Provider-independent proposal boundary. No model calls or testcase edits live here.

The parser checks JSON structure only. A later validator must verify actions,
arguments, evidence references, and requirement semantics before any application.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from .resolution_context import ResolutionContext


class LLMResponseError(ValueError):
    """The adapter returned malformed or mismatched structured output."""

    def __init__(self, message: str, *, category: str = "SCHEMA_ERROR", path: str = "$", position: int | None = None):
        self.category = category
        self.path = path
        self.position = position
        super().__init__(message)

    @property
    def diagnostics(self) -> dict:
        return {"category": self.category, "path": self.path, "position": self.position}


class ResolutionLLM(Protocol):
    """An injectable completion source; no provider SDK is required."""

    def complete(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class EvidenceReference:
    source: str
    ref: dict[str, str | int]

    def to_dict(self) -> dict:
        return {"source": self.source, "ref": dict(self.ref)}


@dataclass(frozen=True)
class AtomicProposal:
    action: str
    args: dict
    evidence: tuple[EvidenceReference, ...]

    def to_dict(self) -> dict:
        return {"action": self.action, "args": dict(self.args),
                "evidence": [ref.to_dict() for ref in self.evidence]}


@dataclass(frozen=True)
class ProposedChange:
    step_seq: int
    from_action: str
    gap_codes: tuple[str, ...]
    action: str
    args: dict
    reason: str
    evidence: tuple[EvidenceReference, ...]
    expansion: tuple[AtomicProposal, ...] = ()

    def to_dict(self) -> dict:
        return {
            "step_seq": self.step_seq, "from_action": self.from_action,
            "gap_codes": list(self.gap_codes),
            "proposed": ({"steps": [atom.to_dict() for atom in self.expansion]}
                         if self.expansion else {"action": self.action, "args": dict(self.args)}),
            "reason": self.reason,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class UnresolvedGap:
    code: str
    step_seq: int | None
    reason: str

    def to_dict(self) -> dict:
        return {"code": self.code, "step_seq": self.step_seq, "reason": self.reason}


@dataclass(frozen=True)
class ResolutionProposal:
    testcase_id: str
    changes: tuple[ProposedChange, ...]
    unresolved: tuple[UnresolvedGap, ...]

    @property
    def status(self) -> str:
        if self.changes and self.unresolved:
            return "partial"
        return "proposed" if self.changes else "unresolved"

    def to_dict(self) -> dict:
        return {
            "testcase_id": self.testcase_id, "status": self.status,
            "changes": [change.to_dict() for change in self.changes],
            "unresolved": [gap.to_dict() for gap in self.unresolved],
        }


_OUTPUT_SHAPE = {
    "testcase_id": "<supplied testcase.id>",
    "changes": [{
        "step_seq": "<existing step sequence>",
        "from_action": "<existing step action>",
        "gap_codes": ["<listed gap code>"],
        "proposed": {"action": "<allowed action>", "args": {}},
        "reason": "<evidence-based reason>",
        "evidence": [],
    }],
    "unresolved": [{
        "code": "<listed gap code>", "step_seq": "<step sequence or null>",
        "reason": "<missing evidence>",
    }],
}


def _evidence_catalog(data: dict) -> list[dict]:
    """Expose identifiers from the selected packet only; no evidence retrieval."""
    references: list[dict] = []

    def add(source: str, ref: dict) -> None:
        item = {"source": source, "ref": ref}
        if item not in references:
            references.append(item)

    for item in data["specification"].get("requirements", []):
        if item.get("id"):
            add("requirement", {"id": item["id"]})
    for item in data["interface_contract"].get("api_operations", []):
        ref = {key: item[key] for key in ("operation_id", "method", "path")
               if item.get(key)}
        if "operation_id" in ref or {"method", "path"} <= ref.keys():
            add("openapi", ref)
    for page in data["observations"].get("ui_pages", []):
        if not page.get("url"):
            continue
        add("ui-map", {"page": page["url"]})
        for element in page.get("elements", []):
            locator = {key: element[key] for key in ("test_id", "role", "name")
                       if element.get(key)}
            if locator:
                add("ui-map", {"page": page["url"], **locator})
    for step in data["testcase"].get("steps", []):
        add("testcase-step", {"step_seq": step["seq"], "action": step["action"]})
    return references


_EVIDENCE_SCHEMA = {
    "requirement": {"required": ["id"], "optional": [], "types": {"id": "nonempty string"}},
    "openapi": {"required": "operation_id OR both method and path",
                "optional": ["operation_id", "method", "path"], "types": "nonempty strings"},
    "ui-map": {"required": ["page"], "optional": ["test_id", "role", "name"],
               "types": "nonempty strings; page is the exact context page URL"},
    "testcase-step": {"required": ["step_seq"], "optional": ["action"],
                      "types": {"step_seq": "positive integer", "action": "nonempty string"}},
}


def build_resolution_prompt(context: ResolutionContext) -> str:
    """Build stable model input from only the already selected context packet."""
    data = context.to_dict()
    catalog = _evidence_catalog(data)
    output_shape = json.loads(json.dumps(_OUTPUT_SHAPE))
    output_shape["changes"][0]["evidence"] = catalog[:1]

    def section(name: str, value: object) -> str:
        return f"{name}\n{json.dumps(value, ensure_ascii=False, sort_keys=True)}"

    return "\n\n".join([
        "You propose execution-gap repairs as JSON. You do not edit or execute a testcase.",
        "Rules: Resolve only the listed gaps. Use only actions and arguments in ALLOWED ACTIONS. "
        "Cite evidence already present in these sections. Do not invent UI elements, API "
        "operations, credentials, role setup, or expected results. When evidence is "
        "insufficient, add an unresolved entry with a reason. Requirements define WHAT "
        "SHOULD happen; OpenAPI declares the interface; UI observations describe the "
        "current product. Never rewrite a requirement expectation to match observed UI. "
        "If Delete must be hidden but the UI shows Delete, do not propose assert.visible.",
        section("SPECIFICATION — REQUIREMENTS", data["specification"]),
        section("INTERFACE CONTRACT — OPENAPI", data["interface_contract"]),
        section("CURRENT UI OBSERVATION — UI MAP", data["observations"]),
        section("TESTCASE", data["testcase"]),
        section("EXECUTION GAPS", data["gaps"]),
        section("ALLOWED ACTIONS — ACTION_SPECS", data["allowed_actions"]),
        section("CONSTRAINTS", data["constraints"]),
        "Trusted fixture data is represented by aliases in TESTCASE.test_data and "
        "_fixture_refs metadata. For fill values, copy the exact supplied alias string "
        "(for example a configured fixture.field), never its underlying secret. "
        "Only aliases whose metadata says available=true may be used. Do not invent "
        "fixture names, fields, values or account state; missing aliases stay unresolved. "
        "Alias names are references, not literal email/password values. Fixture availability "
        "does not prove role, active/locked account state or business expectations.",
        section("EVIDENCE REFERENCE SCHEMA — exact ref field names, no additional fields", _EVIDENCE_SCHEMA),
        section("EVIDENCE REFERENCES — identifiers present in this context only", catalog),
        "Each evidence entry is exactly {\"source\": <source>, \"ref\": <object>}. "
        "Copy references from EVIDENCE REFERENCES. Use page, never url, in UI refs; "
        "use step_seq, never seq, in step refs. UI element refs require page. "
        "Do not include session, text, quote, or other extra reference fields. "
        "At most one change per step_seq. A change replaces one step with one action, "
        "for a normal replacement. Do not split a step into duplicate changes. Preserve the entire "
        "original step meaning: if it needs multiple actions or assertions that cannot "
        "be expressed by a validated ordered expansion, leave it unresolved. Do not drop credential "
        "entry, API status, toast, or other required outcomes to make a repair appear complete. "
        "Copy unresolved (code, step_seq) pairs exactly from EXECUTION GAPS; use null "
        "for case-level gaps. Missing credentials/test data must remain unresolved. "
        "If no reference supports a repair, leave the gap unresolved; do not guess evidence.",
        "Return one JSON object only, without Markdown or prose outside JSON. "
        "Each change needs step_seq, from_action, gap_codes, proposed action/args, "
        "reason, and evidence references. Evidence source is requirement, openapi, "
        "ui-map, or testcase-step. Unresolved gaps need code, step_seq, and reason. "
        "step_seq is a positive integer, or null only for a case-level unresolved gap. "
        "Angle-bracket strings in the shape are placeholders, not evidence. "
        "Do not propose perform.unmapped or assert.unmapped as a repair. "
        "An empty changes list is valid when nothing can be grounded.",
        "For unmapped steps ONLY, one change may instead propose an ordered expansion: "
        '"proposed": {"steps": [{"action": "<allowed action>", "args": {}, '
        '"evidence": [<copy actual reference objects>]}, ...]}. '
        "Include 2–8 atoms. Never mix steps with action/args. Each atom needs its own evidence. "
        "One expansion still counts as one change per original step_seq. List changes in source-step order. "
        "Every source clause must be preserved in order; unknown clauses must remain unresolved. "
        "Supported narrow forms: semicolon-separated fill/click actions, 'Nhập email và mật khẩu "
        "đúng|sai|không trống; bấm <exact button name>', explicit URL outcomes, visible/not visible "
        "controls, and documented HTTP status outcomes. Fill values must exist in test_data or be "
        "explicit literals in source. For the Vietnamese email/password form use supplied email and "
        "correct_password/wrong_password/non_empty_password respectively. Do not invent these values. "
        "HTTP assertions require a preceding http.request OR ui.click with explicit capture_response. "
        "capture_response is {method, path, origin, save_as (optional, default res), timeout_ms "
        "(optional, 100–30000)}. Use exact documented method/path and origin from contract servers, "
        "cite that operation, and only capture an operation explicitly expected by a later source outcome. "
        "Capture observes the triggering click, never sends an extra request. Captured body exposes only "
        "boolean $.success; headers, tokens and raw payload are not retained. A captured login response "
        "permits the EXACT outcome 'Đăng nhập thành công; URL chuyển tới /; POST /api/auth/login trả 200 "
        "với success=true' to expand into assert.http_status(200), assert.json_field($.success, true), "
        "assert.url_matches(/$), with matching source names and API/UI evidence. Preserve every outcome. "
        "Do not add a request solely to manufacture a response. "
        "Runtime UI evidence never establishes the expected business outcome.",
        section("OUTPUT JSON SHAPE", output_shape),
    ])


def propose_resolution(context: ResolutionContext, adapter: ResolutionLLM) -> ResolutionProposal:
    """Ask an injected adapter for a proposal; never receive or mutate a TestCase."""
    proposal = parse_resolution_proposal(adapter.complete(build_resolution_prompt(context)))
    if proposal.testcase_id != context.testcase["id"]:
        raise LLMResponseError("testcase_id does not match the supplied context", category="TESTCASE_MISMATCH", path="testcase_id")
    return proposal


def parse_resolution_proposal(response: str) -> ResolutionProposal:
    """Parse exact JSON shape; never interpret free-form model prose."""
    if not isinstance(response, str):
        raise LLMResponseError("Model response must be a JSON string", category="STRING_REQUIRED")
    try:
        raw = json.loads(response, object_pairs_hook=_unique_keys,
                         parse_constant=lambda value: _reject_constant(value))
    except (json.JSONDecodeError, ValueError) as exc:
        raise LLMResponseError("Invalid JSON response; content omitted", category="JSON_SYNTAX" if isinstance(exc, json.JSONDecodeError) else "JSON_STRUCTURE", position=getattr(exc, "pos", None)) from None

    _fields(raw, {"testcase_id", "changes", "unresolved"}, "proposal")
    testcase_id = _nonempty(raw["testcase_id"], "testcase_id")
    changes_raw = _list(raw["changes"], "changes")
    unresolved_raw = _list(raw["unresolved"], "unresolved")
    if not changes_raw and not unresolved_raw:
        raise LLMResponseError("Proposal must contain a change or unresolved gap", category="EMPTY_PROPOSAL")

    changes: list[ProposedChange] = []
    seen_steps: set[int] = set()
    for index, item in enumerate(changes_raw):
        where = f"changes[{index}]"
        _fields(item, {"step_seq", "from_action", "gap_codes", "proposed", "reason", "evidence"},
                where)
        seq = _positive_int(item["step_seq"], f"{where}.step_seq")
        if seq in seen_steps:
            raise LLMResponseError(f"{where}.step_seq duplicates an earlier change", category="DUPLICATE_STEP", path=f"{where}.step_seq")
        seen_steps.add(seq)
        proposed = item["proposed"]
        expansion: tuple[AtomicProposal, ...] = ()
        if isinstance(proposed, dict) and "steps" in proposed:
            _fields(proposed, {"steps"}, f"{where}.proposed")
            atoms = _list(proposed["steps"], f"{where}.proposed.steps")
            if not 2 <= len(atoms) <= 8:
                raise LLMResponseError("Expansion must contain 2–8 atomic steps", category="ARRAY_LENGTH", path=f"{where}.proposed.steps")
            parsed_atoms = []
            for i, atom in enumerate(atoms):
                label = f"{where}.proposed.steps[{i}]"
                _fields(atom, {"action", "args", "evidence"}, label)
                _arguments(atom["args"], label)
                parsed_atoms.append(AtomicProposal(
                    _nonempty(atom["action"], f"{label}.action"), atom["args"],
                    _parse_references(atom["evidence"], label)))
            expansion = tuple(parsed_atoms)
        else:
            _fields(proposed, {"action", "args"}, f"{where}.proposed")
            _arguments(proposed["args"], f"{where}.proposed")
        codes = _list(item["gap_codes"], f"{where}.gap_codes")
        evidence_raw = _list(item["evidence"], f"{where}.evidence")
        if not codes or not evidence_raw:
            raise LLMResponseError(f"{where} needs gap_codes and evidence", category="EMPTY_ARRAY", path=where)
        evidence: list[EvidenceReference] = []
        for position, ref in enumerate(evidence_raw):
            label = f"{where}.evidence[{position}]"
            _fields(ref, {"source", "ref"}, label)
            source = _nonempty(ref["source"], f"{label}.source")
            if source not in {"requirement", "openapi", "ui-map", "testcase-step"}:
                raise LLMResponseError(f"{label}.source is unknown", category="EVIDENCE_SOURCE", path=f"{label}.source")
            fields = ref["ref"]
            _evidence_fields(source, fields, f"{label}.ref")
            evidence.append(EvidenceReference(source, fields))
        changes.append(ProposedChange(
            step_seq=_positive_int(item["step_seq"], f"{where}.step_seq"),
            from_action=_nonempty(item["from_action"], f"{where}.from_action"),
            gap_codes=tuple(_nonempty(code, f"{where}.gap_codes") for code in codes),
            action="" if expansion else _nonempty(proposed["action"], f"{where}.proposed.action"),
            args={} if expansion else proposed["args"], reason=_nonempty(item["reason"], f"{where}.reason"),
            evidence=tuple(evidence), expansion=expansion,
        ))

    unresolved: list[UnresolvedGap] = []
    for index, item in enumerate(unresolved_raw):
        where = f"unresolved[{index}]"
        _fields(item, {"code", "step_seq", "reason"}, where)
        seq = item["step_seq"]
        unresolved.append(UnresolvedGap(
            code=_nonempty(item["code"], f"{where}.code"),
            step_seq=None if seq is None else _positive_int(seq, f"{where}.step_seq"),
            reason=_nonempty(item["reason"], f"{where}.reason"),
        ))
    return ResolutionProposal(testcase_id, tuple(changes), tuple(unresolved))


def _arguments(args: object, where: str) -> None:
    if not isinstance(args, dict) or not all(isinstance(key, str) for key in args):
        raise LLMResponseError(f"{where}.args must be an object", category="OBJECT_REQUIRED", path=f"{where}.args")


def _parse_references(raw: object, where: str) -> tuple[EvidenceReference, ...]:
    items = _list(raw, f"{where}.evidence")
    if not items:
        raise LLMResponseError(f"{where} needs evidence", category="EMPTY_ARRAY", path=f"{where}.evidence")
    result = []
    for index, item in enumerate(items):
        label = f"{where}.evidence[{index}]"
        _fields(item, {"source", "ref"}, label)
        source = _nonempty(item["source"], f"{label}.source")
        if source not in {"requirement", "openapi", "ui-map", "testcase-step"}:
            raise LLMResponseError(f"{label}.source is unknown", category="EVIDENCE_SOURCE", path=f"{label}.source")
        _evidence_fields(source, item["ref"], f"{label}.ref")
        result.append(EvidenceReference(source, item["ref"]))
    return tuple(result)


def _evidence_fields(source: str, fields: object, where: str) -> None:
    """Check reference structure, never whether the referenced evidence is trusted."""
    if not isinstance(fields, dict) or not fields:
        raise LLMResponseError(f"{where} must be a nonempty object", category="OBJECT_REQUIRED", path=where)
    keys = set(fields)
    if source == "requirement":
        _fields(fields, {"id"}, where)
    elif source == "openapi":
        if not keys <= {"operation_id", "method", "path"} or not (
            "operation_id" in keys or {"method", "path"} <= keys
        ):
            raise LLMResponseError(f"{where} requires operation_id or method and path; no extra fields", category="EVIDENCE_SHAPE", path=where)
    elif source == "ui-map":
        if "page" not in keys or not keys <= {"page", "test_id", "role", "name"}:
            raise LLMResponseError(f"{where} requires page; optional test_id, role, name only", category="EVIDENCE_SHAPE", path=where)
    elif source == "testcase-step":
        if "step_seq" not in keys or not keys <= {"step_seq", "action"}:
            raise LLMResponseError(f"{where} requires step_seq; optional action only", category="EVIDENCE_SHAPE", path=where)
    for key, value in fields.items():
        if source == "testcase-step" and key == "step_seq":
            _positive_int(value, f"{where}.step_seq")
        else:
            _nonempty(value, f"{where}.{key}")


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("Duplicate JSON key; identifier omitted")
        out[key] = value
    return out


def _reject_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _fields(value: object, expected: set[str], where: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise LLMResponseError(f"{where} must have exactly {sorted(expected)}", category="FIELD_SET", path=where)


def _list(value: object, where: str) -> list:
    if not isinstance(value, list):
        raise LLMResponseError(f"{where} must be an array", category="ARRAY_REQUIRED", path=where)
    return value


def _nonempty(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LLMResponseError(f"{where} must be a nonempty string", category="NONEMPTY_STRING_REQUIRED", path=where)
    return value


def _positive_int(value: object, where: str) -> int:
    if type(value) is not int or value < 1:
        raise LLMResponseError(f"{where} must be a positive integer", category="POSITIVE_INTEGER_REQUIRED", path=where)
    return value

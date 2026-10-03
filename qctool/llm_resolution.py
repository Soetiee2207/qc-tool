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
class ProposedChange:
    step_seq: int
    from_action: str
    gap_codes: tuple[str, ...]
    action: str
    args: dict
    reason: str
    evidence: tuple[EvidenceReference, ...]

    def to_dict(self) -> dict:
        return {
            "step_seq": self.step_seq, "from_action": self.from_action,
            "gap_codes": list(self.gap_codes),
            "proposed": {"action": self.action, "args": dict(self.args)},
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
        "evidence": [{"source": "<requirement|openapi|ui-map|testcase-step>",
                      "ref": {"<identifier field>": "<identifier value>"}}],
    }],
    "unresolved": [{
        "code": "<listed gap code>", "step_seq": "<step sequence or null>",
        "reason": "<missing evidence>",
    }],
}


def build_resolution_prompt(context: ResolutionContext) -> str:
    """Build stable model input from only the already selected context packet."""
    data = context.to_dict()

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
        "Return one JSON object only, without Markdown or prose outside JSON. "
        "Each change needs step_seq, from_action, gap_codes, proposed action/args, "
        "reason, and evidence references. Evidence source is requirement, openapi, "
        "ui-map, or testcase-step. Unresolved gaps need code, step_seq, and reason. "
        "step_seq is a positive integer, or null only for a case-level unresolved gap. "
        "Angle-bracket strings in the shape are placeholders, not evidence. "
        "Do not propose perform.unmapped or assert.unmapped as a repair. "
        "An empty changes list is valid when nothing can be grounded.",
        section("OUTPUT JSON SHAPE", _OUTPUT_SHAPE),
    ])


def propose_resolution(context: ResolutionContext, adapter: ResolutionLLM) -> ResolutionProposal:
    """Ask an injected adapter for a proposal; never receive or mutate a TestCase."""
    proposal = parse_resolution_proposal(adapter.complete(build_resolution_prompt(context)))
    if proposal.testcase_id != context.testcase["id"]:
        raise LLMResponseError("testcase_id does not match the supplied context")
    return proposal


def parse_resolution_proposal(response: str) -> ResolutionProposal:
    """Parse exact JSON shape; never interpret free-form model prose."""
    if not isinstance(response, str):
        raise LLMResponseError("Model response must be a JSON string")
    try:
        raw = json.loads(response, object_pairs_hook=_unique_keys,
                         parse_constant=lambda value: _reject_constant(value))
    except (json.JSONDecodeError, ValueError) as exc:
        raise LLMResponseError(f"Invalid JSON response: {exc}") from exc

    _fields(raw, {"testcase_id", "changes", "unresolved"}, "proposal")
    testcase_id = _nonempty(raw["testcase_id"], "testcase_id")
    changes_raw = _list(raw["changes"], "changes")
    unresolved_raw = _list(raw["unresolved"], "unresolved")
    if not changes_raw and not unresolved_raw:
        raise LLMResponseError("Proposal must contain a change or unresolved gap")

    changes: list[ProposedChange] = []
    for index, item in enumerate(changes_raw):
        where = f"changes[{index}]"
        _fields(item, {"step_seq", "from_action", "gap_codes", "proposed", "reason", "evidence"},
                where)
        proposed = item["proposed"]
        _fields(proposed, {"action", "args"}, f"{where}.proposed")
        if not isinstance(proposed["args"], dict) or not all(
            isinstance(key, str) for key in proposed["args"]
        ):
            raise LLMResponseError(f"{where}.proposed.args must be an object")
        codes = _list(item["gap_codes"], f"{where}.gap_codes")
        evidence_raw = _list(item["evidence"], f"{where}.evidence")
        if not codes or not evidence_raw:
            raise LLMResponseError(f"{where} needs gap_codes and evidence")
        evidence: list[EvidenceReference] = []
        for position, ref in enumerate(evidence_raw):
            label = f"{where}.evidence[{position}]"
            _fields(ref, {"source", "ref"}, label)
            source = _nonempty(ref["source"], f"{label}.source")
            if source not in {"requirement", "openapi", "ui-map", "testcase-step"}:
                raise LLMResponseError(f"{label}.source is unknown")
            fields = ref["ref"]
            if (not isinstance(fields, dict) or not fields
                    or not all(isinstance(key, str) and key
                               and type(value) in (str, int) and value != ""
                               for key, value in fields.items())):
                raise LLMResponseError(f"{label}.ref must contain scalar identifiers")
            evidence.append(EvidenceReference(source, fields))
        changes.append(ProposedChange(
            step_seq=_positive_int(item["step_seq"], f"{where}.step_seq"),
            from_action=_nonempty(item["from_action"], f"{where}.from_action"),
            gap_codes=tuple(_nonempty(code, f"{where}.gap_codes") for code in codes),
            action=_nonempty(proposed["action"], f"{where}.proposed.action"),
            args=proposed["args"], reason=_nonempty(item["reason"], f"{where}.reason"),
            evidence=tuple(evidence),
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


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"Duplicate JSON key: {key}")
        out[key] = value
    return out


def _reject_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _fields(value: object, expected: set[str], where: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise LLMResponseError(f"{where} must have exactly {sorted(expected)}")


def _list(value: object, where: str) -> list:
    if not isinstance(value, list):
        raise LLMResponseError(f"{where} must be an array")
    return value


def _nonempty(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LLMResponseError(f"{where} must be a nonempty string")
    return value


def _positive_int(value: object, where: str) -> int:
    if type(value) is not int or value < 1:
        raise LLMResponseError(f"{where} must be a positive integer")
    return value

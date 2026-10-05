"""Offline evaluation of the real resolution loop using recorded completions/evidence.

No live adapters are accepted and missing recordings never fall back to a browser.
The explorer substitution is scoped to this serial evaluation runner; production
modules and stage behavior are unchanged. Labels describe exact permitted or
unsafe action/argument snapshots, not a semantic judge or product pass/fail result.

Replay a YAML/JSON suite: python -m qctool.resolution_evaluation suite.yaml --out report.json
"""

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

import yaml

from . import exploration_execution
from .executability import ExecutionGap, ExecutabilityReport, analyze_executability
from .exploration_plan import _normalized_target
from .generate.from_openapi import Endpoint
from .generate.loader import load_endpoints
from .llm_resolution import LLMResponseError
from .resolution_context import ResolutionContext, build_resolution_context
from .resolution_cycle import ResolutionCycleIssue
from .resolution_loop import ResolutionLoopResult, _canonical, run_resolution_loop
from .testcase import CaseType, Priority, Step, StepKind, Technique, TestCase
from .ui.crawl import Element, PageMap, UIMap
from .ui.explore import ExplorationIssue, ExplorationRequest, ExplorationResult


@dataclass(frozen=True)
class StepGroundTruth:
    step_seq: int
    # None means there is no complete list of acceptable outcomes for this step.
    allowed: tuple[dict, ...] | None = None
    unsafe: tuple[dict, ...] = ()


@dataclass(frozen=True)
class ExplorationReplay:
    # Keep the original request separately: result.request intentionally drops
    # sensitive query/fragment data and must not be used to match recordings.
    request: ExplorationRequest
    result: ExplorationResult


@dataclass(frozen=True)
class ResolutionEvaluationCase:
    case: TestCase
    context: ResolutionContext
    resolution_responses: tuple[str, ...] = ()
    exploration_responses: tuple[str, ...] = ()
    explorations: tuple[ExplorationReplay, ...] = ()
    ground_truth: tuple[StepGroundTruth, ...] = ()
    base_url: str | None = None
    ui_map: UIMap | None = None
    endpoints: list[Endpoint] | None = None


def _jsonable(value):
    """Use existing serializers (especially explorer redaction) before dataclasses."""
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict"):
        return _jsonable(value.to_dict())
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


class _ReplayLLM:
    def __init__(self, responses, stage):
        self.responses, self.stage = tuple(responses), stage
        self.position = 0
        self.calls, self.issues = [], []

    def complete(self, prompt):
        response = self.responses[self.position] if self.position < len(self.responses) else None
        self.calls.append({"prompt": prompt, "response": response})
        if response is None:
            self.issues.append(ResolutionCycleIssue(
                self.stage, "REPLAY_MISS", "No recorded model response remains."))
            raise LLMResponseError("Recorded responses exhausted")
        self.position += 1
        return response


class _ReplayExplorer:
    def __init__(self, recordings):
        self.remaining = list(deepcopy(recordings))
        self.calls, self.issues = [], []

    @staticmethod
    def key(request, base_url):
        return (_normalized_target(request.target, base_url), request.session,
                request.collect_text, request.collect_network)

    def __call__(self, request, *, base_url, **kwargs):
        self.calls.append(request.to_dict())
        for index, recording in enumerate(self.remaining):
            if self.key(recording.request, base_url) == self.key(request, base_url):
                self.remaining.pop(index)
                return replace(deepcopy(recording.result),
                               request=ExplorationRequest(**request.to_dict()))
        self.issues.append(ResolutionCycleIssue(
            "exploration_execution", "REPLAY_MISS", "No matching recorded exploration remains."))
        return ExplorationResult(
            ExplorationRequest(**request.to_dict()), None, None, (), (),
            (ExplorationIssue("REPLAY_MISS", "No recorded page inspection matches this request."),), "")


def _snapshot(step):
    return {"action": step.action, "args": deepcopy(step.args)}


def _assessment(snapshot, label):
    # JSON identity keeps bool/int distinct; Python dict equality does not.
    signature = _canonical(snapshot)
    matched = None if label is None or label.allowed is None else any(
        signature == _canonical(outcome) for outcome in label.allowed)
    unsafe = None if label is None or not label.unsafe else any(
        signature == _canonical(outcome) for outcome in label.unsafe)
    status = "incorrect" if unsafe or matched is False else "correct" if matched else "unknown"
    return {"status": status, "unsafe": unsafe}


def _labelled_steps(case, labels):
    return [{"step_seq": label.step_seq,
             **_assessment(next((_snapshot(step) for step in case.steps if step.seq == label.step_seq),
                                None), label)} for label in labels]


def _applied_repairs(result, labels):
    by_seq = {label.step_seq: label for label in labels}
    repairs = []
    for index, cycle in enumerate(result.cycles, 1):
        if cycle.deterministic:
            for change in cycle.deterministic.changes:
                after = {"action": change.action, "args": change.after}
                repairs.append({"cycle": index, "source": "deterministic", "step_seq": change.step_seq,
                                "before": {"action": change.from_action or change.action, "args": change.before},
                                "after": after, **_assessment(after, by_seq.get(change.step_seq))})
        if cycle.application:
            for applied in cycle.application.applied_changes:
                record = applied.to_dict()
                repairs.append({"cycle": index, "source": "validated_llm", "step_seq": record["step_seq"],
                                "before": record["before"], "after": record["after"],
                                **_assessment(record["after"], by_seq.get(record["step_seq"]))})
    return repairs


@dataclass(frozen=True)
class ResolutionCaseEvaluation:
    testcase_id: str
    before: ExecutabilityReport
    after: ExecutabilityReport
    loop: ResolutionLoopResult
    improved: bool
    regressed: bool
    labels_before: tuple[dict, ...]
    labels_after: tuple[dict, ...]
    ground_truth: tuple[StepGroundTruth, ...]
    repairs: tuple[dict, ...]
    replay: dict

    def to_dict(self):
        return _jsonable({
            "testcase_id": self.testcase_id, "before": self.before, "after": self.after,
            "improved": self.improved, "regressed": self.regressed,
            "labels_before": self.labels_before, "labels_after": self.labels_after,
            "ground_truth": self.ground_truth,
            "repairs": self.repairs, "replay": self.replay, "loop": self.loop,
            "cycle_count": self.loop.cycle_count, "audit": self.loop.audit,
        })


@dataclass(frozen=True)
class ResolutionEvaluationReport:
    cases: tuple[ResolutionCaseEvaluation, ...]

    @property
    def summary(self):
        repairs = [repair for case in self.cases for repair in case.repairs]
        return {
            "total_cases": len(self.cases),
            "executable_before": sum(case.before.executable for case in self.cases),
            "executable_after": sum(case.after.executable for case in self.cases),
            "cases_improved": sum(case.improved for case in self.cases),
            "cases_regressed": sum(case.regressed for case in self.cases),
            "improved_case_ids": [case.testcase_id for case in self.cases if case.improved],
            "regressed_case_ids": [case.testcase_id for case in self.cases if case.regressed],
            "stop_reasons": dict(sorted(Counter(case.loop.stop_reason.value for case in self.cases).items())),
            "cycle_counts": dict(sorted(Counter(str(case.loop.cycle_count) for case in self.cases).items())),
            "gaps_before": dict(sorted(Counter(gap.code for case in self.cases for gap in case.before.gaps).items())),
            "gaps_after": dict(sorted(Counter(gap.code for case in self.cases for gap in case.after.gaps).items())),
            "execution_gaps_before": sum(len(case.before.gaps) for case in self.cases),
            "execution_gaps_after": sum(len(case.after.gaps) for case in self.cases),
            "correct_labelled_steps_before": sum(label["status"] == "correct" for case in self.cases for label in case.labels_before),
            "correct_labelled_steps_after": sum(label["status"] == "correct" for case in self.cases for label in case.labels_after),
            "labelled_steps": sum(len(case.labels_before) for case in self.cases),
            "applied_repairs": len(repairs),
            "labelled_repairs": sum(repair["status"] != "unknown" for repair in repairs),
            "unlabelled_repairs": sum(repair["status"] == "unknown" for repair in repairs),
            "false_repairs": sum(repair["status"] == "incorrect" for repair in repairs),
            "unsafe_repairs": sum(repair["unsafe"] is True for repair in repairs),
            "unsafe_labelled_repairs": sum(repair["unsafe"] is not None for repair in repairs),
            "rejected_proposed_changes": sum(len(cycle.validation.rejected_changes) for case in self.cases
                                            for cycle in case.loop.cycles if cycle.validation),
            "replay_errors": sum(len(case.replay["issues"]) for case in self.cases),
        }

    def to_dict(self):
        return {"summary": self.summary, "cases": [case.to_dict() for case in self.cases]}


def _check_labels(item):
    seen = set()
    for label in item.ground_truth:
        if type(label.step_seq) is not int or label.step_seq in seen or sum(
            step.seq == label.step_seq for step in item.case.steps
        ) != 1:
            raise ValueError("Ground truth must identify unique existing testcase steps")
        seen.add(label.step_seq)
        for outcome in (*(label.allowed or ()), *label.unsafe):
            if (not isinstance(outcome, dict) or set(outcome) != {"action", "args"}
                    or not isinstance(outcome["action"], str) or not isinstance(outcome["args"], dict)):
                raise ValueError("Label outcomes need exactly action and args")
        if any(_canonical(outcome) in {_canonical(unsafe) for unsafe in label.unsafe}
               for outcome in (label.allowed or ())):
            raise ValueError("The same outcome cannot be both allowed and unsafe")


def evaluate_resolution_loop(
    cases: list[ResolutionEvaluationCase] | tuple[ResolutionEvaluationCase, ...], *, max_cycles: int = 3,
) -> ResolutionEvaluationReport:
    """Evaluate serially from recordings only, without modifying caller artifacts.

    Improvement requires executable/gap/label gains with no regression. New gaps,
    lost executability, newly invalid structure, lost correct labels, or a labelled
    false/unsafe applied repair count as regression. Semantic scores cover only
    supplied labels; absent ground truth is unknown, never assumed correct.
    """
    if type(max_cycles) is not int or max_cycles < 1:
        raise ValueError("max_cycles must be a positive integer")
    items = deepcopy(tuple(cases))
    if len({item.case.id for item in items}) != len(items):
        raise ValueError("Evaluation testcase IDs must be unique")
    for item in items:
        _check_labels(item)
    evaluated = []
    for item in items:
        before = analyze_executability(item.case)
        resolution = _ReplayLLM(item.resolution_responses, "resolution_llm")
        planning = _ReplayLLM(item.exploration_responses, "exploration_llm")
        explorer = _ReplayExplorer(item.explorations)
        with patch.object(exploration_execution, "explore_page", explorer):
            result = run_resolution_loop(
                item.case, item.context, max_cycles=max_cycles,
                resolution_llm=resolution, exploration_llm=planning,
                base_url=item.base_url, ui_map=item.ui_map, endpoints=item.endpoints)
        after = analyze_executability(result.case)
        before_labels = _labelled_steps(item.case, item.ground_truth)
        after_labels = _labelled_steps(result.case, item.ground_truth)
        repairs = _applied_repairs(result, item.ground_truth)
        before_gaps = Counter((gap.code, gap.step_seq) for gap in before.gaps)
        after_gaps = Counter((gap.code, gap.step_seq) for gap in after.gaps)
        regressed = bool(
            before.executable and not after.executable or after_gaps - before_gaps
            or before.validation_error is None and after.validation_error is not None
            or any(old["status"] == "correct" and new["status"] == "incorrect"
                   for old, new in zip(before_labels, after_labels))
            or any(repair["status"] == "incorrect" for repair in repairs))
        improved = not regressed and bool(
            not before.executable and after.executable or before_gaps - after_gaps
            or before.validation_error is not None and after.validation_error is None
            or sum(label["status"] == "correct" for label in after_labels)
               > sum(label["status"] == "correct" for label in before_labels))
        replay = {
            "resolution_calls": resolution.calls, "exploration_plan_calls": planning.calls,
            "exploration_calls": explorer.calls,
            "unused_resolution_responses": len(resolution.responses) - resolution.position,
            "unused_exploration_responses": len(planning.responses) - planning.position,
            "unused_explorations": len(explorer.remaining),
            "issues": _jsonable(resolution.issues + planning.issues + explorer.issues),
        }
        evaluated.append(ResolutionCaseEvaluation(
            item.case.id, before, after, result, improved, regressed,
            tuple(before_labels), tuple(after_labels), item.ground_truth, tuple(repairs), replay))
    return deepcopy(ResolutionEvaluationReport(tuple(evaluated)))


def _case_from_dict(raw):
    data = deepcopy(raw)
    data.pop("expected", None)
    data.pop("content_hash", None)
    provenance = data.pop("provenance", {})
    data.update(source_quote=provenance.get("source_quote", ""), source_ref=provenance.get("source_ref", ""))
    for key, cls in (("priority", Priority), ("type", CaseType), ("technique", Technique)):
        if key in data:
            data["case_type" if key == "type" else key] = cls(data.pop(key))
    data["steps"] = [Step(**{**step, "kind": StepKind(step["kind"])}) for step in data["steps"]]
    return TestCase(**data)


def _page_from_dict(raw):
    return PageMap(raw["url"], raw.get("title", ""), list(raw.get("text", [])), [
        Element(**{**element, "tag": element.get("tag", "")}) for element in raw.get("elements", [])])


def load_evaluation_suite(path: Path) -> list[ResolutionEvaluationCase]:
    """Read YAML/JSON replay packets; file references are relative to the suite."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("Evaluation suite requires a cases array")
    cases = []
    for raw in payload["cases"]:
        case = _case_from_dict(raw["case"])
        ui_map = UIMap.load(path.parent / raw["ui_map"]) if raw.get("ui_map") else None
        endpoints = load_endpoints(path.parent / raw["openapi"])[0] if raw.get("openapi") else None
        context = build_resolution_context(case, analyze_executability(case).gaps,
                                           requirements=raw.get("requirements"), ui_map=ui_map, endpoints=endpoints)
        if "context" in raw:
            packet = deepcopy(raw["context"])
            packet["gaps"] = tuple(ExecutionGap(**gap) for gap in packet["gaps"])
            packet["constraints"] = tuple(packet["constraints"])
            context = ResolutionContext(**packet)
        recordings = []
        for recorded in raw.get("explorations", []):
            request = ExplorationRequest(**recorded["request"])
            result = recorded["result"]
            recordings.append(ExplorationReplay(request, ExplorationResult(
                ExplorationRequest(**result["request"]), result.get("final_url"),
                _page_from_dict(result["page"]) if result.get("page") is not None else None,
                tuple(result.get("forms", [])), tuple(result.get("network", [])),
                tuple(ExplorationIssue(**issue) for issue in result.get("issues", [])),
                result["source"]["observed_at"], result.get("redirect_url"), tuple(result.get("truncated", [])),
            )))
        def responses(name):
            return tuple(item if isinstance(item, str) else json.dumps(item, ensure_ascii=False, sort_keys=True)
                         for item in raw.get(name, []))
        labels = tuple(StepGroundTruth(label["step_seq"],
                                      tuple(label["allowed"]) if label.get("allowed") is not None else None,
                                      tuple(label.get("unsafe", []))) for label in raw.get("ground_truth", []))
        cases.append(ResolutionEvaluationCase(
            case, context, responses("resolution_responses"), responses("exploration_responses"),
            tuple(recordings), labels, raw.get("base_url"), ui_map, endpoints))
    return cases


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline resolution-loop replay evaluation")
    parser.add_argument("suite", type=Path, help="YAML/JSON testcase and replay suite")
    parser.add_argument("--out", type=Path, help="Write JSON report; default is stdout")
    parser.add_argument("--max-cycles", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        report = evaluate_resolution_loop(load_evaluation_suite(args.suite), max_cycles=args.max_cycles)
        output = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(output, encoding="utf-8")
        else:
            print(output, end="")
    except Exception:
        print("Evaluation failed: invalid suite, replay data, or output path.", file=sys.stderr)
        return 2
    return 1 if report.summary["cases_regressed"] or report.summary["replay_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

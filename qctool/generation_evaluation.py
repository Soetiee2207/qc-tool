"""Benchmark generation offline, dùng lại adapter/nhãn replay resolution.

python -m qctool.generation_evaluation suite.yaml --out report.json
Không nhận provider thật; explorer luôn được thay bằng recording, kể cả khi
recording thiếu. Chỉ chạy serial vì substitution được giới hạn bằng mock patch.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, replace
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

import yaml

from . import exploration_execution
from .coverage import CoverageReport, CoverageStatus, analyze_coverage
from .coverage_plan import plan_coverage
from .executability import analyze_executability
from .generate.loader import load_endpoints
from .generation import GenerationResult, run_generation
from .resolution_context import build_resolution_context
from .resolution_evaluation import (
    ExplorationReplay, StepGroundTruth, _ReplayExplorer, _ReplayLLM,
    _applied_repairs, _canonical, _case_from_dict, _jsonable, _page_from_dict,
)
from .testcase import Step, StepKind
from .ui.crawl import UIMap
from .ui.explore import ExplorationIssue, ExplorationRequest, ExplorationResult


@dataclass(frozen=True)
class GenerationReplayScenario:
    id: str
    category: str
    inputs: dict
    resolution_responses: tuple[str, ...]
    exploration_responses: tuple[str, ...]
    explorations: tuple[ExplorationReplay, ...]
    ground_truth: dict


def load_generation_suite(path: Path) -> tuple[GenerationReplayScenario, ...]:
    """Load native requirements/cases/evidence; never synthesize completions.

    context_evidence contains explicit, reviewed selection references. It can
    select only exact pages/operations actually in the supplied fixture files.
    The normal testcase snapshot/vocabulary is built by the existing builder.
    """
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    scenarios = []
    for raw in payload["scenarios"]:
        requirements = deepcopy(raw.get("requirements", []))
        flows = deepcopy(raw.get("flows"))
        existing = tuple(_case_from_dict(case) for case in raw.get("existing_cases", []))
        ui_fixture = raw.get("ui_map") or raw.get("context_ui_map")
        ui_map = UIMap.load(path.parent / ui_fixture) if ui_fixture else None
        endpoints = load_endpoints(path.parent / raw["openapi"])[0] if raw.get("openapi") else None
        baseline = analyze_coverage(requirements, [c for c in existing if analyze_executability(c).executable], flows=flows)
        plan = plan_coverage(baseline, existing_cases=[c for c in existing if analyze_executability(c).executable],
                             reserved_case_ids=[c.id for c in existing])
        candidates = {case.id: case for case in plan.cases}
        contexts = {}
        for testcase_id, selection in raw.get("context_evidence", {}).items():
            if testcase_id not in candidates:
                raise ValueError("Context selection must identify an initial planned candidate")
            case = candidates[testcase_id]
            context = build_resolution_context(case, analyze_executability(case).gaps, requirements=requirements)
            pages, operations = [], []
            for url in selection.get("ui_pages", []):
                if ui_map is None or sum(page.url == url for page in ui_map.pages) != 1:
                    raise ValueError("Recorded page reference does not exist uniquely")
                probe = deepcopy(case)
                probe.steps = [Step(1, StepKind.WHEN, "ui.goto", {"url": url})]
                packet = build_resolution_context(probe, (), ui_map=ui_map)
                pages.extend(packet.observations["ui_pages"])
            for ref in selection.get("api_operations", []):
                if endpoints is None or sum(e.method == ref["method"] and e.path == ref["path"]
                                            for e in endpoints) != 1:
                    raise ValueError("Recorded operation reference does not exist uniquely")
                probe = deepcopy(case)
                probe.steps = [Step(1, StepKind.WHEN, "http.request", deepcopy(ref))]
                packet = build_resolution_context(probe, (), endpoints=endpoints)
                operations.extend(packet.interface_contract["api_operations"])
            contexts[testcase_id] = replace(
                context, observations={"ui_pages": pages, "omitted_ui_pages": 0},
                interface_contract={"api_operations": operations, "omitted_api_operations": 0})
        recordings = []
        for record in raw.get("explorations", []):
            result = record["result"]
            recordings.append(ExplorationReplay(
                ExplorationRequest(**record["request"]), ExplorationResult(
                    ExplorationRequest(**result["request"]), result.get("final_url"),
                    _page_from_dict(result["page"]) if result.get("page") else None,
                    tuple(result.get("forms", [])), tuple(result.get("network", [])),
                    tuple(ExplorationIssue(**issue) for issue in result.get("issues", [])),
                    result["source"]["observed_at"], result.get("redirect_url"),
                    tuple(result.get("truncated", [])))))
        def responses(name):
            return tuple(value if isinstance(value, str) else json.dumps(value, sort_keys=True)
                         for value in raw.get(name, []))
        inputs = dict(requirements=requirements, existing_cases=existing, flows=flows,
                      contexts=contexts, ui_map=ui_map if raw.get("ui_map") else None, endpoints=endpoints,
                      base_url=raw.get("base_url"), max_passes=raw.get("max_passes", 3),
                      max_cycles=raw.get("max_cycles", 3))
        scenarios.append(GenerationReplayScenario(raw["id"], raw["category"], inputs,
                                                 responses("resolution_responses"),
                                                 responses("exploration_responses"),
                                                 tuple(recordings), deepcopy(raw.get("ground_truth", {}))))
    if len({s.id for s in scenarios}) != len(scenarios):
        raise ValueError("Scenario IDs must be unique")
    return tuple(scenarios)


def _obligations(report):
    return {o.id: o for r in report.requirements for o in r.obligations}


def _steps(case):
    return [{"action": step.action, "args": deepcopy(step.args)} for step in case.steps]


def _semantic(result, truth):
    cases = {case.id: case for case in result.executable_cases}
    obligations = _obligations(result.coverage)
    assessments = []
    for label in truth.get("obligations", []):
        obligation = obligations.get(label["id"])
        covered = obligation is not None and obligation.status == CoverageStatus.COVERED
        if label.get("expect_abstention"):
            status = "correct" if not covered else "incorrect"
        elif label.get("allowed_steps") is None:
            status = "unknown"
        else:
            allowed = {_canonical(steps) for steps in label["allowed_steps"]}
            status = "correct" if covered and any(
                _canonical(_steps(cases[id])) in allowed for id in obligation.testcase_ids if id in cases
            ) else "incorrect"
        assessments.append({"obligation_id": label["id"], "status": status,
                            "expected_abstention": bool(label.get("expect_abstention"))})
    labelled = {a["obligation_id"] for a in assessments}
    assessments.extend({"obligation_id": id, "status": "unknown", "expected_abstention": False}
                       for id in obligations if id not in labelled)
    if truth.get("expect_abstention"):
        status = "correct" if not result.accepted_generated_cases and not result.success else "incorrect"
    elif not assessments:
        status = "unknown"
    elif any(a["status"] == "incorrect" for a in assessments):
        status = "incorrect"
    elif all(a["status"] == "correct" for a in assessments):
        status = "correct"
    else:
        status = "unknown"
    return status, assessments


def _repairs(loop, labels):
    by_seq = {}
    for label in labels:
        for alternative in label.get("allowed_steps", []) or []:
            for seq, snapshot in enumerate(alternative, 1):
                entry = by_seq.setdefault(seq, {"allowed": [], "unsafe": []})
                if snapshot not in entry["allowed"]:
                    entry["allowed"].append(snapshot)
        for unsafe in label.get("unsafe_steps", []):
            by_seq.setdefault(unsafe["step_seq"], {"allowed": [], "unsafe": []})["unsafe"].append(unsafe["snapshot"])
    ground = tuple(StepGroundTruth(seq, tuple(data["allowed"]) if data["allowed"] else None,
                                  tuple(data["unsafe"])) for seq, data in sorted(by_seq.items()))
    return _applied_repairs(loop, ground)


@dataclass(frozen=True)
class GenerationScenarioEvaluation:
    id: str
    category: str
    before: CoverageReport
    result: GenerationResult
    semantic: str
    semantic_obligations: tuple[dict, ...]
    repairs: tuple[dict, ...]
    replay: dict

    def to_dict(self):
        return _jsonable(self.__dict__)


@dataclass(frozen=True)
class GenerationEvaluationReport:
    scenarios: tuple[GenerationScenarioEvaluation, ...]

    @property
    def summary(self):
        items = self.scenarios
        passes = [entry for item in items for entry in item.result.history]
        loops = [record.resolution for entry in passes if entry.resolution
                 for record in entry.resolution.case_results if record.resolution]
        repairs = [repair for item in items for repair in item.repairs]
        flow_kinds = {"flow", "decision", "scenario", "transition", "error_surface"}
        coverage = lambda report: sum(r.status == CoverageStatus.COVERED for r in report.requirements)
        requirements = lambda report: [r for r in report.requirements if r.kind not in flow_kinds]
        covered = lambda report: sum(o.status == CoverageStatus.COVERED for o in _obligations(report).values())
        distribution = lambda values: dict(sorted(Counter(values).items()))
        semantic_counts = lambda values: {status: Counter(values).get(status, 0)
                                           for status in ("correct", "incorrect", "unknown")}
        pass_counts = [len(item.result.history) for item in items]
        cycle_counts = [loop.cycle_count for loop in loops]
        return {
            "scenarios": len(items),
            "requirements_total": sum(len(requirements(item.before)) for item in items),
            "coverage_sources_total": sum(len(item.before.requirements) for item in items),
            "flow_sources_total": sum(sum(r.kind in flow_kinds for r in item.before.requirements) for item in items),
            "obligations_total": sum(len(_obligations(item.before)) for item in items),
            "covered_requirements_before": sum(r.status == CoverageStatus.COVERED for item in items for r in requirements(item.before)),
            "covered_requirements_after": sum(r.status == CoverageStatus.COVERED for item in items for r in requirements(item.result.coverage)),
            "covered_sources_before": sum(coverage(item.before) for item in items),
            "covered_sources_after": sum(coverage(item.result.coverage) for item in items),
            "covered_obligations_before": sum(covered(item.before) for item in items),
            "covered_obligations_after": sum(covered(item.result.coverage) for item in items),
            "complete_executable_coverage_before": sum(bool(item.before.requirements) and
                all(r.status == CoverageStatus.COVERED for r in item.before.requirements) for item in items),
            "complete_executable_coverage_after": sum(item.result.success for item in items),
            "generated_logical_cases": sum(len(p.resolution.planned_cases) for p in passes if p.resolution),
            "accepted_executable_cases": sum(len(item.result.accepted_generated_cases) for item in items),
            "unresolved_generated_cases": sum(len(item.result.coverage_loop.unresolved_cases)
                                              for item in items if item.result.coverage_loop),
            "semantic_scenarios": semantic_counts([item.semantic for item in items]),
            "semantic_obligations": semantic_counts([a["status"] for item in items for a in item.semantic_obligations]),
            "correct_expected_abstentions": sum(a["status"] == "correct" and a["expected_abstention"]
                                                for item in items for a in item.semantic_obligations),
            "applied_repairs": len(repairs),
            "deterministic_repairs": sum(r["source"] == "deterministic" for r in repairs),
            "false_applied_repairs": sum(r["status"] == "incorrect" for r in repairs),
            "unsafe_applied_repairs": sum(r["unsafe"] is True for r in repairs),
            "unknown_applied_repairs": sum(r["status"] == "unknown" for r in repairs),
            "rejected_proposed_changes": sum(len(c.validation.rejected_changes) for l in loops for c in l.cycles if c.validation),
            "coverage_stop_reasons": distribution(item.result.coverage_loop.stop_reason.value
                                                   for item in items if item.result.coverage_loop),
            "resolution_stop_reasons": distribution(l.stop_reason.value for l in loops),
            "generation_statuses": distribution(item.result.status.value for item in items),
            "pass_counts": distribution(str(n) for n in pass_counts),
            "cycle_counts": distribution(str(n) for n in cycle_counts),
            "average_passes": sum(pass_counts) / len(pass_counts) if pass_counts else 0,
            "max_passes": max(pass_counts, default=0),
            "average_cycles": sum(cycle_counts) / len(cycle_counts) if cycle_counts else 0,
            "max_cycles": max(cycle_counts, default=0),
            "replay_errors": sum(len(item.replay["issues"]) for item in items),
        }

    def to_dict(self):
        categories = {}
        for item in self.scenarios:
            entry = categories.setdefault(item.category, {"scenarios": 0, "successes": 0,
                "semantic_correct": 0, "semantic_incorrect": 0, "semantic_unknown": 0,
                "quality_failure_ids": [], "unresolved_generated_cases": 0})
            entry["scenarios"] += 1
            entry["successes"] += item.result.success
            entry[f"semantic_{item.semantic}"] += 1
            if item.semantic == "incorrect":
                entry["quality_failure_ids"].append(item.id)
            if item.result.coverage_loop:
                entry["unresolved_generated_cases"] += len(item.result.coverage_loop.unresolved_cases)
        return {"summary": self.summary, "categories": categories,
                "scenarios": [item.to_dict() for item in self.scenarios]}


def evaluate_generation(scenarios) -> GenerationEvaluationReport:
    evaluated = []
    for item in deepcopy(tuple(scenarios)):
        inputs = item.inputs
        before = analyze_coverage(inputs["requirements"],
                                  [c for c in inputs["existing_cases"] if analyze_executability(c).executable],
                                  flows=inputs["flows"])
        seen = set()
        for label in item.ground_truth.get("obligations", []):
            if label["id"] not in _obligations(before) or label["id"] in seen:
                raise ValueError("Ground truth must identify unique real obligations")
            seen.add(label["id"])
        resolution = _ReplayLLM(item.resolution_responses, "resolution_llm")
        planning = _ReplayLLM(item.exploration_responses, "exploration_llm")
        explorer = _ReplayExplorer(item.explorations)
        with patch.object(exploration_execution, "explore_page", explorer):
            result = run_generation(**inputs,
                                    resolution_llm=resolution if resolution.responses else None,
                                    exploration_llm=planning if planning.responses else None)
        semantic, assessment = _semantic(result, item.ground_truth)
        repairs = []
        for entry in result.history:
            if entry.resolution is None:
                continue
            for record in entry.resolution.case_results:
                if record.resolution is None:
                    continue
                ids = {link.obligation.id for link in entry.resolution.audit if link.testcase_id == record.testcase_id}
                labels = [label for label in item.ground_truth.get("obligations", []) if label["id"] in ids]
                repairs.extend({"pass": entry.pass_number, "testcase_id": record.testcase_id, **r}
                               for r in _repairs(record.resolution, labels))
        replay = {"resolution_calls": resolution.calls, "exploration_plan_calls": planning.calls,
                  "exploration_calls": explorer.calls,
                  "issues": _jsonable(resolution.issues + planning.issues + explorer.issues),
                  "unused_resolution_responses": len(resolution.responses) - resolution.position,
                  "unused_exploration_responses": len(planning.responses) - planning.position,
                  "unused_explorations": len(explorer.remaining)}
        evaluated.append(GenerationScenarioEvaluation(item.id, item.category, before, result,
                                                      semantic, tuple(assessment), tuple(repairs), replay))
    return deepcopy(GenerationEvaluationReport(tuple(evaluated)))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline run_generation benchmark")
    parser.add_argument("suite", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        report = evaluate_generation(load_generation_suite(args.suite))
        output = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(output, encoding="utf-8")
        else:
            print(output, end="")
    except Exception:
        print("Generation evaluation failed: invalid suite/replay/output.", file=sys.stderr)
        return 2
    return 1 if (report.summary["replay_errors"] or report.summary["false_applied_repairs"]
                 or report.summary["unsafe_applied_repairs"]
                 or report.summary["semantic_scenarios"].get("incorrect", 0)) else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Standalone approved TC002 empty-form observation; no resolution or model call.

Run from the repo root with normal-pipeline artifacts:
uv run python scripts/explore_salonhub_002.py --artifacts <pipeline-output-dir>
"""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yaml

from qctool.executability import analyze_executability
from qctool.exploration_plan import validate_exploration_plan
from qctool.generate.loader import load_endpoints
from qctool.llm_exploration import parse_exploration_plan
from qctool.resolution_context import build_resolution_context
from qctool.resolution_evaluation import _case_from_dict
from qctool.ui.crawl import UIMap
from qctool.ui.explore import explore_page


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    source = args.artifacts
    payload = yaml.safe_load((source / "testcases.yaml").read_text())
    case = _case_from_dict(next(c for c in payload["testcases"] if c["id"] == "TC_SALON_AUTH_002"))
    requirements = yaml.safe_load((source / "requirements.yaml").read_text())["requirements"]
    ui = UIMap.load(source / "ui-map.yaml")
    endpoints, _, _ = load_endpoints(Path("samples/smoke/openapi.yaml"))
    context = build_resolution_context(case, analyze_executability(case).gaps,
                                       requirements=requirements, ui_map=ui, endpoints=endpoints)
    before = deepcopy((case, context, ui))
    step = next(s for s in case.steps if s.action == "assert.unmapped"
                and s.args.get("expected") == "không gửi POST /api/auth/login")
    raw_plan = {"testcase_id": case.id, "requests": [{
        "target": "/login", "session": "anonymous",
        "purposes": [{"gap_code": "UNMAPPED_ACTION", "step_seq": step.seq,
                      "reason": "Observe the source-required empty submit, validation and exact request count.",
                      "intent": "observe_network"}],
        "actions": [{"action": "ui.click", "target": "login-submit-btn", "step_seq": step.seq}],
    }]}
    plan = parse_exploration_plan(json.dumps(raw_plan))
    validated = validate_exploration_plan(plan, context, case, ui.base_url)
    out = args.out or Path("artifacts") / ("salonhub-002-exploration-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=True)
    audit = {"plan": plan.to_dict(), "validation": validated.to_dict(), "results": [], "llm_calls": 0}
    for approved in validated.valid_requests:
        audit["results"].append(explore_page(approved, base_url=ui.base_url).to_dict())
    assert (case, context, ui) == before
    audit["inputs_unchanged"] = True
    (out / "exploration.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    print("Validation:", validated.status, "approved requests:", len(validated.valid_requests))
    for result in audit["results"]:
        print("Explored:", result["explored"], "URL:", result["final_url"], "issues:", result["issues"])
        for action in result.get("action_observations", []):
            print("Action:", action["action"], action["target"], "request_count:", action["request_count"])
        if result["page"]:
            alerts = [e for e in result["page"]["elements"] if e["role"] == "alert"]
            print("Alerts:", json.dumps(alerts, ensure_ascii=False))
    print("Audit:", out / "exploration.json")
    return 0 if validated.valid_requests and all(r["explored"] and not r["issues"] for r in audit["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

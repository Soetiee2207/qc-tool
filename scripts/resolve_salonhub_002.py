"""Resolve normal-pipeline TC002 using one approved real empty-submit inspection.

No testcase reconstruction, source restoration, credentials or live model call.
The planner completion is a deterministic recorded-format fixture. All plans and
repairs still pass the production validators. This generates IR, not a Pass.
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
from qctool.exploration_plan import ExplorationPlan, ExplorationPurpose, PlannedExploration
from qctool.generate.loader import load_endpoints
from qctool.resolution_context import build_resolution_context
from qctool.resolution_evaluation import _case_from_dict, _jsonable
from qctool.resolution_loop import run_resolution_loop
from qctool.ui.crawl import UIMap
from qctool.ui.explore import ExplorationAction


class RecordedPlanner:
    def complete(self, prompt):
        supplied = json.loads(prompt.split('TESTCASE — EXPLICIT ROUTES AND SESSION REQUIREMENTS\n')[1].split('\n\n')[0])
        step = next(s for s in supplied['steps'] if s['action'] == 'assert.unmapped'
                    and s['args']['expected'] == 'Hiển thị Vui lòng điền đầy đủ thông tin')
        return json.dumps(ExplorationPlan(supplied['id'], (PlannedExploration('/login', (
            ExplorationPurpose('UNMAPPED_ACTION', step['seq'], 'Observe source-required empty-submit validation', 'observe_network'),),
            actions=(ExplorationAction('login-submit-btn', step['seq']),)),)).to_dict())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    payload = yaml.safe_load((args.artifacts / 'testcases.yaml').read_text())
    case = _case_from_dict(next(c for c in payload['testcases'] if c['id'] == 'TC_SALON_AUTH_002'))
    requirements = yaml.safe_load((args.artifacts / 'requirements.yaml').read_text())
    ui = UIMap.load(args.artifacts / 'ui-map.yaml')
    endpoints, _, _ = load_endpoints(Path('samples/smoke/openapi.yaml'))
    context = build_resolution_context(case, analyze_executability(case).gaps,
        requirements=requirements, ui_map=ui, endpoints=endpoints)
    before = deepcopy((case, context, ui))
    result = run_resolution_loop(case, context, ui_map=ui, endpoints=endpoints,
        exploration_llm=RecordedPlanner(), base_url=ui.base_url, max_cycles=3)
    assert (case, context, ui) == before
    out = args.out or Path('artifacts') / ('salonhub-002-resolution-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True, exist_ok=True)
    audit = {'input_artifacts': str(args.artifacts), 'before': case.to_dict(),
             'initial_context': context.to_dict(), 'result': _jsonable(result),
             'real_llm_calls': 0, 'planner': 'recorded-format fixture', 'inputs_unchanged': True}
    (out / 'resolution.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    (out / 'testcases.yaml').write_text(yaml.safe_dump({'testcases': [result.case.to_dict()]}, allow_unicode=True, sort_keys=False))
    print('Executable:', result.executable, 'cycles:', result.cycle_count, 'stop:', result.stop_reason.value)
    for index, cycle in enumerate(result.cycles, 1):
        print('Cycle', index, 'after gaps:', [(g.code, g.step_seq) for g in cycle.after.gaps])
        if cycle.exploration_execution:
            for observation in cycle.exploration_execution.exploration_results:
                for action in observation.action_observations:
                    print('Observed:', action['target'], 'POST count:', action['request_count'], 'URL:', action['final_url'])
        print('Issues:', [(issue.stage, issue.code) for issue in cycle.issues])
    for step in result.case.steps:
        print(step.seq, step.action, step.args)
    print('Audit:', out / 'resolution.json')
    return 0 if result.executable else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Evaluate existing artifacts offline. Does not rerun generation or a website.

uv run python scripts/run_agent_benchmark.py artifacts/agent-redesign-acceptance
"""
import argparse
import json
from pathlib import Path
import sys
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from qctool.generation_evaluation import evaluate_generation


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run_dir',type=Path)
    p.add_argument('--labels',type=Path,help='Reviewed JSON labels keyed by testcase/obligation ID')
    p.add_argument('--out',type=Path)
    args=p.parse_args(argv)
    generation=json.loads((args.run_dir/'generation.json').read_text())
    files=sorted((args.run_dir/'runs').glob('*/results.json'))
    execution=json.loads(files[-1].read_text()) if files else None
    labels=json.loads(args.labels.read_text()) if args.labels else None
    result=evaluate_generation(generation,execution=execution,ground_truth=labels).to_dict()
    result['baseline']={'source':'docs/findings/customer-workflow-evidence.md',
        'recorded_runnable':'3–4/7','recorded_total_tokens':330933,'fresh_baseline_run':False}
    # Include every recorded debug attempt, not just the last successful run.
    attempts=sorted(args.run_dir.glob('attempt-*-generation.json'))
    result['diagnostic_attempts']=[{'artifact':str(f),'summary':evaluate_generation(json.loads(f.read_text())).summary()} for f in attempts]
    target=args.out or args.run_dir/'agent-benchmark.json'
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result['summary'],ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())

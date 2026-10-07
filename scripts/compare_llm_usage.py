#!/usr/bin/env python3
"""Compare acceptance call usage without writing prompt/completion content.

Older baselines may contain prompts: read only to estimate component sizes.
Totals are actual provider usage; component counts are explicitly estimates.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qctool.llm_prompt import COMPONENTS, describe_prompt


def summarize_calls(packet):
    calls = []
    for index, call in enumerate(packet['calls'], 1):
        composition = call.get('prompt_composition')
        if not composition and isinstance(call.get('prompt'), str):
            composition = describe_prompt(call['prompt'])
        components = {}
        for group in COMPONENTS:
            record = (composition or {}).get('components', {}).get(group, {})
            components[group] = {k: record[k] for k in ('bytes', 'estimated_tokens')
                                 if type(record.get(k)) is int and record[k] >= 0}
        usage = {k: call['usage'][k] for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')
                 if type(call.get('usage', {}).get(k)) is int and call['usage'][k] >= 0}
        calls.append({'call': index, 'stage': call['stage'] if call.get('stage') in ('resolution', 'exploration') else 'unknown',
                      'usage': usage, 'components': components})
    return {'calls': calls, 'call_count': len(calls),
            'resolution_calls': sum(c['stage']=='resolution' for c in calls),
            'exploration_calls': sum(c['stage']=='exploration' for c in calls),
            'usage': {k: sum(c['usage'][k] for c in calls) if all(k in c['usage'] for c in calls) else None
                      for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')},
            'component_estimates': {k: sum(c['components'][k].get('estimated_tokens', 0) for c in calls) for k in COMPONENTS}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('current', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    try:
        result = {'component_measurement': 'section UTF-8 bytes / 4 estimate; not provider tokenizer counts',
                  'totals_measurement': 'actual provider usage',
                  'before': summarize_calls(json.loads(args.baseline.read_text())),
                  'after': summarize_calls(json.loads(args.current.read_text()))}
        text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
        if args.out:
            args.out.write_text(text)
        else:
            print(text, end='')
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        print('Unable to read valid call usage records; input content omitted.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

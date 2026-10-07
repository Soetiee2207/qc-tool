#!/usr/bin/env python3
"""Content-free cache telemetry from acceptance.json; actual provider counts only."""
import argparse
import json
from pathlib import Path


def summarize_cache(packet):
    calls = []
    for index, call in enumerate(packet.get('calls', []), 1):
        usage = call.get('usage', {})
        def count(key):
            value = usage.get(key)
            return value if type(value) is int and value >= 0 else None
        prompt, hit, miss = (count(k) for k in ('prompt_tokens', 'prompt_cache_hit_tokens', 'prompt_cache_miss_tokens'))
        valid = (prompt is not None and prompt > 0 and hit is not None and hit <= prompt
                 and (miss is None or hit + miss == prompt))
        capability = call.get('capability', call.get('stage'))
        capability = capability if capability in ('resolution','exploration') else 'unknown'
        family = call.get('cache_family')
        calls.append({'call':index, 'capability':capability,
            'cache_family':family if family in ('resolution','exploration') else None,
            'prompt_tokens':prompt, 'hit_tokens':hit, 'miss_tokens':miss,
            'hit_ratio': hit/prompt if valid else None, 'completion_tokens':count('completion_tokens')})
    def total(items):
        counts = {key:sum(c[key] for c in items) if items and all(c[key] is not None for c in items) else None
                  for key in ('prompt_tokens','hit_tokens','miss_tokens','completion_tokens')}
        counts['call_count'] = len(items)
        counts['hit_ratio'] = (counts['hit_tokens']/counts['prompt_tokens']
                              if counts['prompt_tokens'] and all(c['hit_ratio'] is not None for c in items) else None)
        return counts
    return {'calls':calls, 'overall':total(calls),
            'resolution':total([c for c in calls if c['capability']=='resolution']),
            'exploration':total([c for c in calls if c['capability']=='exploration'])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('acceptance',type=Path)
    parser.add_argument('--out',type=Path)
    args = parser.parse_args(argv)
    try:
        result = summarize_cache(json.loads(args.acceptance.read_text()))
        output = json.dumps(result,indent=2)+'\n'
        if args.out:args.out.write_text(output)
        else:print(output,end='')
        return 0
    except (OSError,ValueError,TypeError,AttributeError):
        parser.exit(2,'Unable to read cache telemetry; input content omitted.\n')


if __name__=='__main__':
    raise SystemExit(main())

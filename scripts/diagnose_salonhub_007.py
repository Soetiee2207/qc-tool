"""Chẩn đoán một resolution call thật cho SalonHub 007; không chạy browser/pipeline.

Chạy tường minh: uv run python scripts/diagnose_salonhub_007.py --enable-llm
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from qctool.executability import analyze_executability
from qctool.generate.loader import load_endpoints
from qctool.generation import _serializable
from qctool.llm_provider import load_llm_provider
from qctool.pipeline import PipelineConfig
from qctool.resolution_context import build_resolution_context
from qctool.resolution_cycle import run_resolution_cycle
from qctool.resolution_evaluation import _case_from_dict
from qctool.ui.crawl import UIMap


_CHANGE_FIELDS = {"step_seq", "from_action", "gap_codes", "proposed", "reason", "evidence"}
# Unknown field names themselves may contain secrets. Persist known schema/alias
# names only; arbitrary names and ALL values are omitted.
_DIAGNOSTIC_FIELDS = _CHANGE_FIELDS | {
    "action", "args", "steps", "expansion", "capture_response", "source", "kind",
    "seq", "status", "confidence", "metadata", "testcase_id", "unresolved",
    "proposed_steps", "replacement", "replace_with", "description", "note",
}


def completion_field_shape(response: str) -> list[dict]:
    """Return field-set diagnostics, never completion values or unknown key names."""
    try:
        raw = json.loads(response)
    except (ValueError, TypeError):
        return []
    if not isinstance(raw, dict) or not isinstance(raw.get("changes"), list):
        return []
    result = []
    for index, change in enumerate(raw["changes"][:100]):
        path = f"changes[{index}]"
        if not isinstance(change, dict):
            result.append({"path": path, "object": False})
            continue
        keys = set(change)
        extra = keys - _CHANGE_FIELDS
        result.append({"path": path, "object": True,
                       "fields": sorted(keys & _DIAGNOSTIC_FIELDS),
                       "missing_fields": sorted(_CHANGE_FIELDS - keys),
                       "extra_fields": sorted(extra & _DIAGNOSTIC_FIELDS),
                       "redacted_extra_field_count": len(extra - _DIAGNOSTIC_FIELDS)})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--enable-llm', action='store_true')
    source.add_argument('--replay-proposal', type=Path)
    parser.add_argument('--config', type=Path, default=Path('qctool.smoke.yaml'))
    parser.add_argument('--audit', type=Path, default=Path('artifacts/salonhub-smoke/generation.json'))
    parser.add_argument('--out', type=Path, default=Path('artifacts/salonhub-007-provider-diagnostic/audit.json'))
    args = parser.parse_args()
    cfg = PipelineConfig.from_file(args.config)
    if args.enable_llm and not cfg.llm_enabled:
        parser.error('LLM must also be explicitly enabled in configuration.')
    provider = load_llm_provider() if args.enable_llm else None
    class Replay:
        def complete(self, prompt):
            return args.replay_proposal.read_text()
    source_adapter = provider if provider is not None else Replay()
    field_shapes = []
    class DiagnosticAdapter:
        def complete(self, prompt):
            response = source_adapter.complete(prompt)
            field_shapes.extend(completion_field_shape(response))
            return response  # Pass through unchanged to the strict parser.
    adapter = DiagnosticAdapter()
    original = json.loads(args.audit.read_text())
    entries = original['coverage_loop']['history'][0]['resolution']['case_results']
    entry = next(e for e in entries if e['testcase_id'] == 'TC_SALON_AUTH_007')
    case = _case_from_dict(entry['case'])
    if cfg.fixture_store:
        case = cfg.fixture_store.bind(case)
    ui_map = UIMap.load(args.audit.parent / 'ui-map.yaml')
    endpoints, _, _ = load_endpoints(cfg.openapi)
    requirements = yaml.safe_load((args.audit.parent / 'requirements.yaml').read_text())
    context = build_resolution_context(case, analyze_executability(case).gaps,
                                       requirements=requirements, ui_map=ui_map, endpoints=endpoints)
    snapshot = deepcopy((case, context))
    result = run_resolution_cycle(case, context, resolution_llm=adapter,
                                  fixture_store=cfg.fixture_store, ui_map=ui_map, endpoints=endpoints)
    assert (case, context) == snapshot, 'Caller inputs changed'
    payload = {'testcase_id': case.id, 'observed_at': datetime.now(timezone.utc).isoformat(),
               'model': provider.model if provider else 'recorded-replay',
               'completion_field_shape': field_shapes, 'cycle': _serializable(result)}
    if cfg.fixture_store:
        payload = cfg.fixture_store.redact(payload)
    # Defense against API-key echo in public provider identifiers too.
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if provider:
        encoded = encoded.replace(provider.api_key, '[REDACTED]')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(encoded + '\n')
    attempts = [attempt for stage in result.audit for attempt in stage.provider_attempts]
    print(json.dumps({'audit': str(args.out), 'provider_attempts': attempts,
                      'completion_field_shape': field_shapes,
                      'proposal_parsed': result.proposal is not None,
                      'validation_status': getattr(result.validation, 'status', None),
                      'executable': result.after.executable,
                      'issues': _serializable(result.issues)}, ensure_ascii=False))
    return 1 if any(i.stage == 'resolution_llm' for i in result.issues) else 0


if __name__ == '__main__':
    raise SystemExit(main())

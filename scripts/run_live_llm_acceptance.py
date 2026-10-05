"""Acceptance model thật, bật tường minh; không được gọi trong offline CI."""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from qctool.config import load_dotenv
from qctool.executability import analyze_executability
from qctool.execute.browser import BrowserSession
from qctool.execute.runner import HttpSession, run_cases
from qctool.exploration_execution import execute_validated_exploration
from qctool.exploration_plan import (
    ExplorationPlan, ExplorationPurpose, PlannedExploration, validate_exploration_plan,
)
from qctool.generation import _serializable
from qctool.llm_provider import LLMConfigurationError, load_llm_provider
from qctool.resolution_context import build_resolution_context
from qctool.resolution_loop import run_resolution_loop
from qctool.resolve import resolve_deterministically
from qctool.testcase import Step, StepKind, TestCase
from tests.mock_server import create_server


def fixture():
    """Ý định viết tay cho app hư cấu: click link, không submit/update dữ liệu."""
    case = TestCase(
        id="TC_LIVE_001", module="LIVE", title="Mở Dự án bằng link điều hướng",
        objective="Click Dự án → URL /ui/du-an", traces_to=["AC-LIVE-001"],
        source_ref="scripts/run_live_llm_acceptance.py:fixture",
        source_quote="Given Open /; When Click Dự án; Then URL /ui/du-an",
        execution="manual", steps=[
            Step(1, StepKind.GIVEN, "ui.goto", {"url": "/"}),
            Step(2, StepKind.WHEN, "perform.unmapped", {"description": "Click Dự án"}),
            Step(3, StepKind.THEN, "assert.url_matches", {"pattern": "/ui/du-an$"}),
        ],
    )
    context = build_resolution_context(case, analyze_executability(case).gaps,
        requirements=[{"id": "AC-LIVE-001", "statement": case.source_quote,
                       "source": {"file": case.source_ref, "quote": case.source_quote}}])
    return case, context


def sanitize(value, key):
    """Lớp cuối trước khi ghi log: không ghi credential dù provider echo lại."""
    def redact(item):
        if isinstance(item, str):
            return item.replace(key, "[REDACTED]").replace(
                json.dumps(key, ensure_ascii=False)[1:-1], "[REDACTED]")
        if isinstance(item, dict):
            return {redact(k): redact(v) for k, v in item.items()}
        if isinstance(item, list):
            return [redact(v) for v in item]
        return item
    return redact(_serializable(value))


class RecordedLLM:
    def __init__(self, provider, stage, calls, persist):
        self.provider, self.stage, self.calls, self.persist = provider, stage, calls, persist

    def complete(self, prompt):
        record = {"stage": self.stage, "started_at": datetime.now(timezone.utc).isoformat(),
                  "prompt": prompt, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                  "model": self.provider.model, "status": "STARTED"}
        self.calls.append(record)
        started = time.monotonic()
        self.persist()
        client = replace(self.provider, on_response_metadata=lambda metadata: record.update(metadata))
        try:
            response = client.complete(prompt)
            record.update(status="COMPLETED", response=response)
            return response
        except Exception as exc:
            # Không ghi raw exception từ transport/provider khác.
            record.update(status="FAILED", error_code=getattr(exc, "code", type(exc).__name__))
            raise
        finally:
            record["duration_seconds"] = round(time.monotonic() - started, 3)
            self.persist()


def run_acceptance(provider, out, *, with_exploration=False):
    out.mkdir(parents=True, exist_ok=True)
    report = {"status": "RUNNING", "model": provider.model, "provider": provider.base_url,
              "calls": [], "with_exploration": with_exploration}

    def persist():
        (out / "live-acceptance.json").write_text(
            json.dumps(sanitize(report, provider.api_key), ensure_ascii=False, indent=2), encoding="utf-8")

    server = create_server(0, "/api/v1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        case, context = fixture()
        original = case.to_dict()
        report.update(base_url=base, original_case=original, before=analyze_executability(case))
        baseline = resolve_deterministically(case)
        assert not analyze_executability(baseline.case).executable
        assert not baseline.changes, "Fixture không được hoàn thành bằng resolver deterministic"
        if not with_exploration:
            # Target do script cố định vẫn qua safety validator trước khi mở browser.
            plan = ExplorationPlan(case.id, (PlannedExploration("/", (
                ExplorationPurpose("UNMAPPED_ACTION", 2, "Inspect known starting page"),)),))
            approved = validate_exploration_plan(plan, context, case, base_url=base)
            assert approved.valid_requests and not approved.issues
            initial = execute_validated_exploration(approved, context, base_url=base)
            report["initial_exploration"] = initial
            assert initial.successful_requests and not initial.issues, "Không đọc được UI fixture"
            context = initial.context
        report["input_context"] = context
        resolution = RecordedLLM(provider, "resolution", report["calls"], persist)
        exploration = RecordedLLM(provider, "exploration", report["calls"], persist)
        result = run_resolution_loop(case, context, resolution_llm=resolution,
            exploration_llm=exploration if with_exploration else None,
            base_url=base, max_cycles=3 if with_exploration else 1)
        report.update(resolution=result, audit=result.audit, final_case=result.case,
                      after=analyze_executability(result.case))
        assert case.to_dict() == original, "Input bị thay đổi"
        assert any(c["stage"] == "resolution" for c in report["calls"]), "Không gọi ResolutionLLM"
        rejected = [change for cycle in result.cycles if cycle.validation
                    for change in cycle.validation.rejected_changes]
        report["rejected_changes"] = rejected
        assert not rejected, "Model trả proposal bị validator từ chối; xem audit"
        assert result.executable, "Model chưa giải được testcase; xem gaps/issues trong audit"
        assert any(c.application and c.application.applied_changes for c in result.cycles), "Không có repair đã validate"
        # Ground truth của fixture; không sửa output model để đạt acceptance.
        assert result.case.steps[1].action == "ui.click"
        assert result.case.steps[1].args.get("target") == "nav-projects"
        assert result.case.steps[2] == case.steps[2], "Kỳ vọng gốc phải được giữ nguyên"
        with BrowserSession(base, timeout_ms=8000, evidence_dir=out / "evidence", trace=True) as browser:
            execution = run_cases([result.case], HttpSession(base + "/api/v1"), browser=browser)
        report["execution"] = execution
        assert execution.cases[0].status == "Pass", "Executable nhưng runner chưa Pass"
        assert len(execution.cases[0].steps) == 3 and all(s.ok for s in execution.cases[0].steps)
        report["status"] = "PASSED"
    except Exception as exc:
        report.update(status="FAILED", error_code=type(exc).__name__)
        # Assertion messages do script định nghĩa, không phải lỗi network thô.
        if isinstance(exc, AssertionError):
            report["failure"] = str(exc)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        report["llm_calls"] = len(report["calls"])
        persist()
    return sanitize(report, provider.api_key)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manual acceptance với model + Chromium thật")
    parser.add_argument("--llm", action="store_true", help="Cho phép gọi model thật")
    parser.add_argument("--with-exploration", action="store_true", help="Bắt đầu thiếu UI evidence; thử model planner")
    parser.add_argument("--out", type=Path, default=REPO / "artifacts/live-llm-acceptance")
    args = parser.parse_args(argv)
    load_dotenv()
    if not args.llm and os.getenv("QCTOOL_LLM_ENABLED", "").lower() != "true":
        print("SKIPPED: cần --llm hoặc QCTOOL_LLM_ENABLED=true; không gọi model/browser.")
        return 2
    try:
        provider = load_llm_provider()
    except LLMConfigurationError as exc:
        print(f"SKIPPED: {exc}; không gọi model/browser.")
        return 2
    result = run_acceptance(provider, args.out, with_exploration=args.with_exploration)
    print(json.dumps({key: result[key] for key in ("status", "model", "provider", "llm_calls")}, ensure_ascii=False))
    print(f"Audit: {args.out / 'live-acceptance.json'}")
    return 0 if result["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

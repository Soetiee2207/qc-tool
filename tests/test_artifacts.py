"""Bố cục artifacts theo bước + dấu vết đủ để biết tool đang làm gì và hỏng ở đâu."""
import json

from qctool.artifacts import RunTracker
from qctool.pipeline import PipelineConfig, run_pipeline


def test_failure_points_to_stage_error_log_with_traceback(tmp_path):
    out = tmp_path / "out"
    result = run_pipeline(PipelineConfig(docs_dir=tmp_path / "missing", feature="x", out_dir=out))
    assert not result.ok
    run = json.loads((out / "run.json").read_text())
    assert run["status"] == "failed" and run["error"]["stage"] == "ingest"
    assert run["stages"]["ingest"]["status"] == "failed"
    log = (out / run["error"]["log"]).read_text()
    assert "FileNotFoundError" in log and "Traceback" in log
    assert run["stages"]["generate"]["status"] == "pending"


def test_new_run_clears_outputs_but_keeps_knowledge_and_session(tmp_path):
    (tmp_path / "2-crawl").mkdir(parents=True)
    for name in ("app-model.yaml", ".auth-state.json", "old.png"):
        (tmp_path / "2-crawl" / name).write_text("x")
    (tmp_path / "5-execute").mkdir()
    (tmp_path / "5-execute" / "results.json").write_text("{}")
    RunTracker(tmp_path)
    assert (tmp_path / "2-crawl/app-model.yaml").is_file() and (tmp_path / "2-crawl/.auth-state.json").is_file()
    assert not (tmp_path / "2-crawl/old.png").exists() and not (tmp_path / "5-execute").exists()


def test_events_are_redacted_and_follow_stage_aliases(tmp_path):
    tracker = RunTracker(tmp_path, redact=lambda s: s.replace("hunter2", "[REDACTED]"))
    tracker.event("ingest", "đọc tài liệu")
    tracker.event("agent", "mật khẩu hunter2")
    tracker.event("ui", "vẫn ở bước generate")
    events = [json.loads(l) for l in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [e["stage"] for e in events] == ["ingest", "generate", "generate"]
    assert "hunter2" not in (tmp_path / "events.jsonl").read_text() + (tmp_path / "3-generate/stage.log").read_text()
    state = json.loads((tmp_path / "run.json").read_text())
    assert state["stages"]["ingest"]["status"] == "done" and state["current_stage"] == "generate"

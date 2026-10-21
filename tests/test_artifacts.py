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


def _feature(project, name, *, started, results):
    art = project / name / "artifacts"
    (art / "5-execute/evidence").mkdir(parents=True)
    (art / "6-report").mkdir()
    (art / "run.json").write_text(json.dumps({"started_at": started, "stages": {}, "error": None}))
    (art / "5-execute/results.json").write_text(json.dumps({"results": results}))
    (art / "5-execute/evidence/TC_A_001-fail.png").write_bytes(b"png")
    (art / "6-report/report.md").write_text("# report")
    return art


def test_project_summary_lists_every_case_and_skips_stale_feature(tmp_path):
    from datetime import timedelta
    from qctool import summary
    project = tmp_path / "shop"
    started = summary.now()
    fresh = _feature(project, "login", started=(started + timedelta(seconds=1)).isoformat(timespec="seconds"), results=[
        {"case_id": "TC_A_001", "module": "M", "title": "Sai mật khẩu", "status": "Fail",
         "actual": ["[OK] mở trang", "[X] không thấy thông báo"], "evidence": {"screenshots": ["TC_A_001-fail.png"]}},
        {"case_id": "TC_A_002", "title": "Đăng nhập", "status": "Pass", "actual": ["[OK]"], "flaky": True},
        {"case_id": "TC_A_003", "title": "403", "status": "Blocked", "blocked_reason": "Cần tài khoản không có quyền"}])
    stale = _feature(project, "cart", started=(started - timedelta(days=1)).isoformat(timespec="seconds"), results=[
        {"case_id": "TC_OLD_001", "title": "cũ", "status": "Pass"}])
    out = summary.write_project_summary(project, [("login", 1, fresh), ("cart", 2, stale)], started)

    assert out.parent == project / "summary" and out.name == started.strftime("%Y-%m-%d_%H-%M-%S")
    data = json.loads((out / "summary.json").read_text())
    assert [r["id"] for r in data["testcases"]] == ["TC_A_001", "TC_A_002", "TC_A_003"]   # TC_OLD_001 không lọt vào
    assert data["totals"] == {"Pass": 1, "Fail": 1, "Blocked": 1, "Not Executed": 0, "total": 3, "flaky": 1}
    assert data["exit_code"] == 2 and not data["features"][1]["ran"]
    md = (out / "summary.md").read_text()
    assert "[X] không thấy thông báo" in md and "Cần tài khoản không có quyền" in md and "chập chờn" in md
    assert "login/5-execute/evidence/TC_A_001-fail.png" in md and "`cart`: Không chạy tới pipeline" in md
    assert (out / "login/5-execute/evidence/TC_A_001-fail.png").is_file()      # bằng chứng được chép
    assert (out / "login/6-report/report.md").is_file() and not (out / "cart").exists()
    assert len((out / "testcases.csv").read_text(encoding="utf-8-sig").splitlines()) == 4
    assert out.name in (project / "summary/README.md").read_text()


def test_summary_falls_back_to_generated_cases_when_not_executed(tmp_path):
    from datetime import timedelta
    from qctool import summary
    project = tmp_path / "shop"
    started = summary.now()
    art = project / "login" / "artifacts"
    (art / "3-generate").mkdir(parents=True)
    (art / "run.json").write_text(json.dumps({"started_at": (started + timedelta(seconds=1)).isoformat(timespec="seconds")}))
    (art / "3-generate/testcases.yaml").write_text("testcases:\n  - {id: TC_X_001, title: a, module: M}\n")
    out = summary.write_project_summary(project, [("login", 4, art)], started)
    rows = json.loads((out / "summary.json").read_text())["testcases"]
    assert [(r["id"], r["status"]) for r in rows] == [("TC_X_001", "Not Executed")]

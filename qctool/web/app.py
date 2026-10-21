"""Web UI — `qctool ui`. Bấm là chạy.

Chỉ dùng thư viện chuẩn (`http.server`) để không thêm phụ thuộc: tool này phải
cài được ở nơi khác mà không phải kéo theo cả một web framework.

Hai nguyên tắc:

- **Chạy feature của project = chạy đúng như CLI.** Cấu hình đọc từ
  `projects/<p>/<feature>/qctool.yaml` qua `cli_run.preflight` (cùng hàm với `qctool run`),
  kết quả ghi vào `<feature>/artifacts/`. Web không tự dựng cấu hình riêng — trước đây
  nó bỏ mất `llm`, `account`, `exploration` nên agent không bao giờ chạy.
- **Mọi thứ hiển thị đọc từ đĩa** (`run.json`, `events.jsonl`, `generation.json`,
  `results.json`). Lượt chạy từ CLI, từ web, đang chạy hay đã xong đều xem được như nhau.

Chạy:  qctool ui --port 8080
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from qctool import config as cfg_mod
from qctool import pipeline
from qctool.web import chat, setup
from qctool.artifacts import GMT7
from qctool.pipeline import PipelineConfig, run_pipeline
from qctool.web.chat_page import CHAT_PAGE

MAX_BODY = 2 * 1024 * 1024
PROJECTS = Path("projects")
STALE_SECONDS = 15 * 60      # run.json "running" mà events.jsonl im lâu hơn → tiến trình đã chết
MAX_EVENTS = 5000            # mỗi lần trả tối đa; UI hỏi tiếp bằng `since`


# ── Lượt chạy trong tiến trình này ──────────────────────────────────────────
@dataclass
class Job:
    id: str
    started_at: str
    artifacts: str = ""                  # thư mục artifacts (tương đối với cwd)
    stage: str = "queued"
    messages: list[str] = field(default_factory=list)
    done: bool = False
    result: dict | None = None
    error: str | None = None
    exit_code: int | None = None         # như `qctool run`: 0 OK · 1 lỗi sản phẩm · 2 pipeline · 3 sinh thiếu · 4 bị chặn
    lock: threading.Lock = field(default_factory=threading.Lock)

    def log(self, stage: str, message: str) -> None:
        with self.lock:
            self.stage = stage
            self.messages.append(f"[{datetime.now().strftime('%H:%M:%S')}] [{stage}] {message}")

    def snapshot(self) -> dict:
        with self.lock:
            return {"id": self.id, "started_at": self.started_at, "artifacts": self.artifacts,
                    "stage": self.stage, "messages": list(self.messages), "done": self.done,
                    "result": self.result, "error": self.error}


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, artifacts: str = "") -> Job:
        job = Job(id=datetime.now().strftime("%Y%m%d-%H%M%S-%f"),
                  started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), artifacts=artifacts)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def live_for(self, artifacts: str) -> Job | None:
        with self._lock:
            return next((j for j in self._jobs.values() if j.artifacts == artifacts and not j.done), None)


STORE = JobStore()


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _inside_project(raw: str) -> Path | None:
    try:
        resolved = Path(raw).expanduser().resolve()
        resolved.relative_to(Path.cwd().resolve())
        return resolved
    except (ValueError, OSError):
        return None


def _execute(job: Job, cfg: PipelineConfig, adapter, out: Path) -> None:
    """Chạy pipeline đồng bộ cho `job`; luôn kết thúc job, kể cả khi tool lỗi."""
    from qctool.cli_run import build_summary, redact
    error = None
    result = None
    try:
        result = run_pipeline(cfg, on_progress=job.log, resolution_llm=adapter, exploration_llm=adapter)
        error = result.error
        folder = result.out_dir or out
        folder.mkdir(parents=True, exist_ok=True)
        summary = redact(build_summary(result), cfg)
        job.exit_code = summary.get("exit_code")
        (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / "pipeline.log").write_text(redact("\n".join(job.messages + result.log), cfg) + "\n",
                                             encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — job phải luôn kết thúc, kể cả khi tool lỗi
        error = error or f"{type(exc).__name__}: {exc}"
    with job.lock:
        job.done = True
        job.error = error
        job.stage = "error" if error else "done"
        if result is not None and not error:
            job.result = {
                "feature": result.feature,
                "artifacts": job.artifacts,
                "total_cases": result.total_cases,
                "counts": result.counts,
                "pass_rate": round(result.pass_rate, 1),
                "generation_status": result.generation_status,
            }


def _project_summary(runs: list[tuple[str, int | None, str]], started) -> str | None:
    """Báo cáo tổng hợp `projects/<p>/summary/<ngày_giờ>/` — như `qctool run <project>` (cli._each_feature).

    `runs` = [(đường dẫn qctool.yaml, exit_code, thư mục artifacts)]. Chỉ ghi cho feature thuộc project
    (`projects/<p>/<feature>/qctool.yaml` + `project.yaml`); lượt chạy ad-hoc không có project.
    """
    from qctool import summary
    paths = [Path(c) for c, _, _ in runs]
    if not paths or any(p.name != "qctool.yaml" for p in paths):
        return None
    project = paths[0].parent.parent
    if any(p.parent.parent != project for p in paths) or not (project / "project.yaml").is_file():
        return None
    out = summary.write_project_summary(
        project, [(p.parent.name, 2 if code is None else code, Path(art)) for p, (_, code, art) in zip(paths, runs)],
        started)
    return _rel(out)


def _start_job(cfg: PipelineConfig, adapter=None, config: str | None = None) -> Job:
    out = cfg.out_dir or pipeline.ARTIFACTS_ROOT / cfg.feature
    job = STORE.create(_rel(out))

    def worker() -> None:
        from qctool.summary import now
        started = now()
        _execute(job, cfg, adapter, out)
        if config:
            try:
                _project_summary([(config, job.exit_code, job.artifacts)], started)
            except Exception as exc:  # noqa: BLE001
                job.log("summary", f"Không ghi được báo cáo tổng hợp: {exc}")

    threading.Thread(target=worker, daemon=True).start()
    return job


def _run_feature(config: str, only: list[str], on_start, trace_sensitive: bool = False) -> dict:
    """Một mục của kế hoạch chat = `qctool run <project> --<feature> --only … [--trace-sensitive]`."""
    cfg, adapter = _project_config({"config": config, "only": " ".join(only), "trace_sensitive": trace_sensitive})
    out = cfg.out_dir or pipeline.ARTIFACTS_ROOT / cfg.feature
    if running := STORE.live_for(_rel(out)):
        raise ValueError(f"{_rel(out)} đang có lượt chạy {running.id}")
    job = STORE.create(_rel(out))
    on_start(job.artifacts)
    _execute(job, cfg, adapter, out)
    cases = [{"case_id": c.get("case_id"), "title": str(c.get("title") or "")[:160], "status": c.get("status"),
              "evidence": c.get("evidence", [])} for c in _results(Path(out))]
    return {"artifacts": job.artifacts, "job_id": job.id, "error": job.error, "result": job.result,
            "exit_code": job.exit_code, "cases": cases[:50]}


def _plan_summary(runs: list[tuple[str, dict]], started) -> str | None:
    return _project_summary([(config, run.get("exit_code"), run.get("artifacts") or "") for config, run in runs
                             if run.get("artifacts")], started)


def _open_trace(p: dict) -> dict:
    """Mở Playwright Trace Viewer trên máy đang chạy `qctool ui` (giống `qctool trace`)."""
    import subprocess
    import sys
    path = _inside_project(str(p.get("path") or ""))
    if path is None or not path.is_file() or not path.name.endswith(".trace.zip") or path.parent.name != "evidence":
        raise setup.SetupError("Chỉ mở được file *.trace.zip trong thư mục evidence/ của dự án.")
    subprocess.Popen([sys.executable, "-m", "playwright", "show-trace", str(path)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return {"ok": True, "path": _rel(path)}


def _feature_info(config_path: Path) -> dict:
    feature = config_path.parent
    info = {"name": feature.name, "path": _rel(feature), "config": _rel(config_path),
            "docs": sorted(p.name for p in feature.glob("*.md")),
            "openapi": (feature / "openapi.yaml").is_file(), "error": None}
    try:
        cfg = PipelineConfig.from_file(config_path)
    except Exception as exc:  # noqa: BLE001 — hiển thị cho người dùng sửa
        info["error"] = f"{type(exc).__name__}: {exc}"
        info["artifacts"] = _rel(feature / "artifacts")
        return info
    out = cfg.out_dir or pipeline.ARTIFACTS_ROOT / cfg.feature
    info.update(artifacts=_rel(out), web_url=cfg.web_url, base_url=cfg.base_url,
                llm=cfg.llm_enabled, auth_mode=cfg.auth_mode, write_mode=cfg.write_mode,
                headless=cfg.headless, ui_trace=cfg.ui_trace, skip_run=cfg.skip_run,
                fixtures=bool(cfg.fixture_store))
    return info


def _get_projects() -> list[dict]:
    from qctool.cli import features_of
    projects = []
    if not PROJECTS.is_dir():
        return projects
    for p in sorted(PROJECTS.iterdir()):
        features = features_of(p) if p.is_dir() and not p.name.startswith(".") else []
        if not features:
            continue
        meta = {}
        if (p / "project.yaml").is_file():
            try:
                meta = yaml.safe_load((p / "project.yaml").read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001
                meta = {}
        projects.append({"id": p.name, "path": _rel(p), "web_url": meta.get("web", "") if isinstance(meta, dict) else "",
                         "features": [_feature_info(f) for f in features]})
    return projects


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _parse_time(text: str | None) -> float | None:
    try:
        return datetime.fromisoformat(text).timestamp() if text else None
    except ValueError:
        return None


def _alive(pid) -> bool:
    """Không có pid (run.json cũ) → coi như còn sống, để luật STALE_SECONDS quyết định."""
    import os
    if type(pid) is not int:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _run_state(folder: Path) -> dict | None:
    """run.json + trạng thái thật: live / running (tiến trình khác) / interrupted."""
    run = _read_json(folder / "run.json")
    if not run:
        return None
    rel = _rel(folder)
    job = STORE.live_for(rel)
    status = run.get("status")
    if status == "running":
        events = folder / "events.jsonl"
        last = events.stat().st_mtime if events.is_file() else (folder / "run.json").stat().st_mtime
        if job is None and (not _alive(run.get("pid")) or time.time() - last > STALE_SECONDS):
            status = "interrupted"   # tiến trình chạy nó đã chết (Ctrl+C, tắt máy…) — không còn ai ghi
    now = time.time()
    for stage in (run.get("stages") or {}).values():
        start, end = _parse_time(stage.get("started_at")), _parse_time(stage.get("finished_at"))
        if start is not None:
            stage["seconds"] = round((end if end is not None else now) - start, 1) if (end or status == "running") else None
    start, end = _parse_time(run.get("started_at")), _parse_time(run.get("finished_at"))
    run["seconds"] = round((end or now) - start) if start else None
    run["status"] = status
    run["dir"] = rel
    run["job_id"] = job.id if job else None
    results = _read_json(folder / "5-execute" / "results.json") or {}
    run["counts"] = results.get("summary") or None
    summary = _read_json(folder / "summary.json") or {}
    run["qc_status"] = summary.get("status")
    run["generation_status"] = summary.get("generation_status")
    return run


def _get_runs() -> dict:
    latest, history = [], []
    if PROJECTS.is_dir():
        for run_json in PROJECTS.glob("**/artifacts/run.json"):
            if "summary" in run_json.parts:
                continue
            state = _run_state(run_json.parent)
            if state:
                state["project"] = run_json.parent.parent.parent.name
                state["feature_name"] = run_json.parent.parent.name
                latest.append(state)
        for summary_json in PROJECTS.glob("*/summary/*/summary.json"):
            data = _read_json(summary_json) or {}
            folder = summary_json.parent
            history.append({"dir": _rel(folder), "project": folder.parent.parent.name,
                            "started_at": data.get("started_at", folder.name),
                            "seconds": data.get("duration_seconds"), "totals": data.get("totals", {}),
                            "exit_code": data.get("exit_code"),
                            "summary_md": _rel(folder / "summary.md") if (folder / "summary.md").is_file() else None,
                            "features": [{"name": f.get("name"), "status": f.get("status"),
                                          "dir": _rel(folder / f["name"]) if (folder / f.get("name", "") / "run.json").is_file() else None}
                                         for f in data.get("features", []) if isinstance(f, dict)]})
    latest.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    history.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    return {"latest": latest, "history": history[:30]}


def _events(folder: Path, since: int) -> tuple[list[dict], int]:
    path = folder / "events.jsonl"
    if not path.is_file():
        return [], 0
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out = []
    for line in lines[since:since + MAX_EVENTS]:
        try:
            out.append(json.loads(line))
        except ValueError:
            out.append({"t": "", "stage": "", "level": "raw", "message": line})
    return out, len(lines)


def _agent(folder: Path) -> list[dict]:
    """Agent đã làm gì cho từng intent — lấy từ generation.json (đã redact khi ghi)."""
    data = _read_json(folder / "3-generate" / "generation.json") or {}
    rows = []
    for record in data.get("agent_history") or []:
        case, intent = record.get("case") or {}, record.get("intent") or {}
        attempts = record.get("provider_attempts") or []
        rows.append({
            "case_id": case.get("id"), "title": case.get("title"), "intent_id": intent.get("id"),
            "expected": intent.get("expected"), "given": intent.get("given"), "when": intent.get("when"),
            "stop_reason": record.get("stop_reason"), "dry_run_passed": record.get("dry_run_passed"),
            "issues": record.get("issues") or [], "generation_status": case.get("generation_status"),
            "review_reasons": case.get("review_reasons") or [],
            "llm_calls": len(attempts),
            "tokens": sum((a.get("usage") or {}).get("total_tokens", 0) for a in attempts),
            "history": record.get("history") or [],
            "steps": [{"seq": s.get("seq"), "kind": s.get("kind"), "action": s.get("action"), "args": s.get("args")}
                      for s in case.get("steps") or []],
        })
    issues = [i for i in data.get("issues") or [] if i.get("code") == "AUTHORING_UNAVAILABLE"]
    return rows if rows or not issues else [{"case_id": i.get("testcase_id"), "stop_reason": i.get("code"),
                                             "issues": [i.get("message")], "history": [], "steps": []} for i in issues]


def _results(folder: Path) -> list[dict]:
    data = _read_json(folder / "5-execute" / "results.json") or {}
    evidence_dir = folder / "5-execute" / "evidence"
    evidence = sorted(evidence_dir.iterdir()) if evidence_dir.is_dir() else []
    cases = []
    for case in data.get("results") or []:
        cid = case.get("case_id") or ""
        files = [_rel(p) for p in evidence if p.name.startswith(cid + "-") or p.name.startswith(cid + ".")]
        cases.append({**case, "evidence": files})
    return cases


def _files(folder: Path) -> list[dict]:
    out = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.name.startswith(".") or "evidence" in path.parts:
            continue   # .auth-state.json / .token là bí mật phiên đăng nhập
        out.append({"path": _rel(path), "name": path.relative_to(folder).as_posix(), "size": path.stat().st_size})
    return out


def _run_detail(raw: str, since: int, full: bool) -> tuple[int, dict]:
    folder = _inside_project(raw)
    if folder is None:
        return 403, {"error": "chỉ được đọc thư mục trong dự án"}
    if not (folder / "run.json").is_file():
        return 404, {"error": f"không có run.json trong {raw}"}
    state = _run_state(folder)
    events, total = _events(folder, since)
    body = {"run": state, "events": events, "events_total": total}
    if full:
        body.update(agent=_agent(folder), results=_results(folder), files=_files(folder),
                    summary=_read_json(folder / "summary.json"))
    return 200, body


# ── Dựng cấu hình ───────────────────────────────────────────────────────────
def _bool(p: dict, key: str) -> bool | None:
    value = p.get(key)
    return value if isinstance(value, bool) else None


def _project_config(p: dict):
    """Feature của project → đúng đường `qctool run <project> --<feature>` (cli_run.preflight)."""
    from qctool.cli_run import PreflightError, preflight
    path = _inside_project(p["config"])
    if path is None or not path.is_file() or path.name != "qctool.yaml":
        raise ValueError(f"Không tìm thấy qctool.yaml: {p['config']}")
    args = argparse.Namespace(config=str(path))
    for key in ("web_url", "base_url"):
        if value := (p.get(key) or "").strip().rstrip("/"):
            setattr(args, key, value)
    if (llm := _bool(p, "llm")) is not None:
        args.llm = llm
    if _bool(p, "skip_run"):
        args.skip_run = True
    if _bool(p, "headless") is False:
        args.headless = False
    if _bool(p, "trace_sensitive"):
        # Người bấm chọn tường minh: trace/ảnh cả case có mật khẩu (= --trace-sensitive của CLI).
        args.trace_sensitive = True
    if only := [x.strip() for x in str(p.get("only") or "").replace(",", " ").split() if x.strip()]:
        args.only = only
    try:
        checked = preflight(args)
    except PreflightError as exc:
        raise ValueError(f"Preflight: {exc}") from None
    cfg = checked.config
    if cfg.write_mode:
        # Chế độ ghi chỉ bật khi người dùng xác nhận (TTY/--yes). Web chưa có bước đó.
        raise ValueError("Feature này cấu hình `mode: write` (tạo/sửa/xoá dữ liệu thật). Web UI không có bước "
                         "xác nhận — chạy bằng CLI: qctool run <project> --<feature> --write")
    if (trace := _bool(p, "ui_trace")) is not None:
        cfg.ui_trace = trace
    return cfg, checked.adapter


def _adhoc_config(p: dict) -> tuple[PipelineConfig, object]:
    def path_of(key: str) -> Path | None:
        raw = (p.get(key) or "").strip()
        if not raw:
            return None
        path = Path(raw).expanduser()
        if not path.exists():
            raise ValueError(f"Không tìm thấy đường dẫn ở ô `{key}`: {raw}")
        return path

    docs_dir = path_of("docs_dir")
    openapi = path_of("openapi")
    base_url = (p.get("base_url") or "").strip().rstrip("/")
    web_url = (p.get("web_url") or "").strip().rstrip("/")
    if web_url and not web_url.startswith(("http://", "https://")):
        raise ValueError("Link webapp phải bắt đầu bằng http:// hoặc https://")
    if not docs_dir and not openapi:
        raise ValueError("Cần ít nhất một nguồn đầu vào: thư mục tài liệu hoặc file OpenAPI")
    auth_mode = p.get("auth_mode") or "manual"
    if auth_mode == "token" and not (p.get("bearer_token") or "").strip() and base_url:
        raise ValueError("Chọn xác thực bằng token nhưng chưa dán token")
    try:
        timeout = int(p.get("timeout_seconds") or 30)
    except (TypeError, ValueError):
        raise ValueError("Timeout phải là một số") from None
    feature = (p.get("feature") or "feature").strip()
    llm_enabled = bool(p.get("llm") or p.get("llm_enabled"))
    adapter = None
    if llm_enabled:
        try:
            adapter = pipeline.load_llm_provider()
        except Exception:  # noqa: BLE001
            raise ValueError("Bật LLM nhưng cấu hình chưa đúng: cần QCTOOL_LLM_MODEL và QCTOOL_LLM_API_KEY trong .env") from None
    return PipelineConfig(
        docs_dir=docs_dir, openapi=openapi, feature=feature,
        out_dir=pipeline.WEB_ROOT / Path(feature).name / "artifacts",
        module=(p.get("module") or "").strip() or None,
        base_url=base_url, web_url=web_url, auth_mode=auth_mode,
        username=(p.get("username") or "").strip() or None, password=p.get("password") or None,
        bearer_token=(p.get("bearer_token") or "").strip() or None,
        timeout_seconds=max(1, timeout), verify_ssl=bool(p.get("verify_ssl", True)),
        skip_run=bool(p.get("skip_run", False)), headless=bool(p.get("ui_headless", True)),
        ui_trace=bool(p.get("ui_trace", False)), llm_enabled=llm_enabled,
    ), adapter


def _llm_info() -> dict:
    import os
    cfg_mod.load_dotenv()
    return {"model": os.environ.get("QCTOOL_LLM_MODEL", ""),
            "base_url": os.environ.get("QCTOOL_LLM_BASE_URL", ""),
            "key_set": bool(os.environ.get("QCTOOL_LLM_API_KEY", "").strip()),
            "enabled_default": cfg_mod._flag("QCTOOL_LLM_ENABLED", False),
            "thinking": os.environ.get("QCTOOL_LLM_THINKING", ""),
            "timeout": os.environ.get("QCTOOL_LLM_TIMEOUT_SECONDS", "")}


PAGE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>qc-tool</title>
<style>
  :root {
    --bg: #f8fafc; --surface: #fff; --border: #e2e8f0; --border-light: #f1f5f9;
    --text: #0f172a; --text-2: #475569; --muted: #94a3b8;
    --primary: #2563eb; --primary-light: #eff6ff;
    --pass: #16a34a; --pass-bg: #dcfce7; --fail: #dc2626; --fail-bg: #fee2e2;
    --block: #b45309; --block-bg: #fef3c7; --none: #64748b; --none-bg: #f1f5f9;
    --mono: ui-monospace, 'JetBrains Mono', Menlo, monospace;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; background: var(--bg);
         color: var(--text); line-height: 1.5; display: flex; min-height: 100vh; font-size: 13.5px; }
  aside { width: 220px; background: var(--surface); border-right: 1px solid var(--border); flex-shrink: 0; }
  .brand { padding: 18px 20px; font-weight: 700; font-size: 16px; border-bottom: 1px solid var(--border-light); }
  nav { padding: 12px; display: flex; flex-direction: column; gap: 4px; }
  nav a { padding: 9px 12px; border-radius: 8px; color: var(--text-2); cursor: pointer; font-weight: 500; }
  nav a:hover { background: var(--border-light); }
  nav a.active { background: var(--primary-light); color: var(--primary); font-weight: 600; }
  main { flex: 1; padding: 28px 36px; min-width: 0; max-width: 1280px; }
  h1 { font-size: 20px; margin: 0 0 18px; }
  h2 { font-size: 15px; margin: 22px 0 10px; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 18px 20px; margin-bottom: 18px; }
  .row { display: flex; gap: 14px; flex-wrap: wrap; align-items: center; }
  .grow { flex: 1; min-width: 200px; }
  label.lbl { display: block; font-weight: 600; margin: 12px 0 5px; }
  .opt, .muted { color: var(--muted); font-weight: 400; font-size: 12px; }
  input[type=text], select { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; font: inherit; background: #fff; }
  .check { display: flex; align-items: center; gap: 8px; margin: 6px 0; cursor: pointer; }
  button, .btn { font: inherit; font-weight: 600; border-radius: 6px; padding: 7px 14px; cursor: pointer;
                 border: 1px solid var(--border); background: #fff; color: var(--text-2); text-decoration: none; display: inline-block; }
  button:hover, .btn:hover { background: var(--border-light); }
  button.primary { background: var(--primary); border-color: var(--primary); color: #fff; }
  button.primary:disabled { opacity: .6; cursor: wait; }
  .small { padding: 3px 9px; font-size: 12px; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 8px 10px; background: #f8fafc; border-bottom: 1px solid var(--border); color: var(--text-2); font-weight: 600; font-size: 12.5px; }
  td { padding: 8px 10px; border-bottom: 1px solid var(--border-light); vertical-align: top; }
  tr.click { cursor: pointer; } tr.click:hover td { background: #fbfcfe; }
  code, .mono { font-family: var(--mono); font-size: 12px; }
  .badge { display: inline-block; font-size: 11.5px; font-weight: 600; padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
  .b-pass { background: var(--pass-bg); color: var(--pass); } .b-fail { background: var(--fail-bg); color: var(--fail); }
  .b-block { background: var(--block-bg); color: var(--block); } .b-none { background: var(--none-bg); color: var(--none); }
  .b-live { background: #dbeafe; color: #1d4ed8; }
  .warn { background: var(--block-bg); border: 1px solid #fde68a; color: #78350f; border-radius: 6px; padding: 10px 12px; margin: 10px 0; }
  .err { background: var(--fail-bg); border: 1px solid #fecaca; color: #991b1b; border-radius: 6px; padding: 10px 12px; margin: 10px 0; white-space: pre-wrap; }
  .info { background: var(--primary-light); border: 1px solid #bfdbfe; color: #1e3a8a; border-radius: 6px; padding: 10px 12px; margin: 10px 0; }
  .tabs { display: flex; gap: 18px; border-bottom: 1px solid var(--border); margin: 14px 0 16px; }
  .tabs a { padding: 8px 2px; cursor: pointer; color: var(--text-2); border-bottom: 2px solid transparent; font-weight: 500; }
  .tabs a.active { color: var(--primary); border-color: var(--primary); font-weight: 600; }
  .stages { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin-bottom: 14px; }
  .stage { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; background: #fff; cursor: pointer; min-width: 0; }
  .stage.running { border-color: var(--primary); box-shadow: 0 0 0 1px var(--primary); }
  .stage.done { background: #f6fef9; } .stage.failed { border-color: var(--fail); background: #fff5f5; }
  .stage.skipped { opacity: .6; } .stage.sel { outline: 2px solid #93c5fd; }
  .stage .t { font-weight: 600; font-size: 12.5px; } .stage .s { font-size: 11.5px; color: var(--text-2); }
  .stage .m { font-size: 11px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 3px; }
  .log { background: #0f172a; color: #cbd5e1; font-family: var(--mono); font-size: 12px; border-radius: 8px;
         padding: 12px 14px; max-height: 62vh; overflow: auto; }
  .log div { white-space: pre-wrap; word-break: break-word; padding: 1px 0; }
  .log .ts { color: #64748b; } .log .st { color: #93c5fd; } .log .lv-detail { color: #94a3b8; }
  .log .lv-error { color: #fca5a5; } .log .agent { color: #c4b5fd; } .log .ok { color: #86efac; } .log .bad { color: #fdba74; }
  .filters { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-bottom: 10px; }
  .filters select, .filters input[type=text] { width: auto; }
  .kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px; }
  .kpi { border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; background: #fff; }
  .kpi b { font-size: 22px; display: block; }
  details { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; background: #fff; }
  details > summary { padding: 9px 12px; cursor: pointer; list-style: none; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  details > summary::-webkit-details-marker { display: none; }
  details[open] > summary { border-bottom: 1px solid var(--border-light); }
  details .body { padding: 10px 12px; }
  pre.view { background: #0f172a; color: #e2e8f0; padding: 12px; border-radius: 8px; max-height: 70vh; overflow: auto; font-size: 12px; white-space: pre-wrap; word-break: break-word; }
  .pulse { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--primary); animation: p 1.2s infinite; margin-right: 4px; }
  @keyframes p { 50% { opacity: .3; } }
  @media (max-width: 900px) { body { flex-direction: column; } aside { width: auto; } .stages { grid-template-columns: repeat(3, 1fr); } main { padding: 16px; } }
</style>
</head>
<body>
<aside>
  <div class="brand">qc-tool</div>
  <nav>
    <a id="nav-home" onclick="go('home')">Lượt chạy</a>
    <a id="nav-create" onclick="go('create')">Chạy QC</a>
    <a id="nav-settings" onclick="go('settings')">Cài đặt</a>
  </nav>
</aside>
<main>

<!-- ═══ Danh sách lượt chạy ═══ -->
<section id="view-home">
  <div class="row" style="justify-content:space-between"><h1>Lượt chạy</h1>
    <div><button onclick="loadRuns()">Làm mới</button> <button class="primary" onclick="go('create')">+ Chạy QC</button></div></div>
  <div class="muted" style="margin-bottom:8px">Kết quả mới nhất của từng feature (<code>&lt;feature&gt;/artifacts/</code> — lượt sau ghi đè lượt trước). Gồm cả lượt chạy bằng CLI.</div>
  <div class="card" style="padding:0; overflow:auto">
    <table><thead><tr><th>Bắt đầu</th><th>Feature</th><th>Trạng thái</th><th>Kết quả</th><th>Thời gian</th><th>Thư mục</th></tr></thead>
    <tbody id="runs-latest"></tbody></table>
  </div>
  <h2>Lịch sử chạy cả project <span class="opt">— <code>projects/&lt;p&gt;/summary/&lt;ngày_giờ&gt;/</code>, bản chép không bị ghi đè</span></h2>
  <div id="runs-history"></div>
</section>

<!-- ═══ Chạy QC ═══ -->
<section id="view-create" style="display:none">
  <h1>Chạy QC</h1>
  <div class="card">
    <div class="row">
      <div class="grow"><label class="lbl">Project</label><select id="sel-project" onchange="onProject()"></select></div>
      <div class="grow"><label class="lbl">Feature</label><select id="sel-feature" onchange="onFeature()"></select></div>
    </div>
    <div id="feature-info"></div>
  </div>
  <div class="card" id="overrides">
    <div style="font-weight:700">Tuỳ chỉnh cho lượt này <span class="opt">— để trống = theo qctool.yaml / project.yaml</span></div>
    <div class="row">
      <div class="grow"><label class="lbl">Website (web_url)</label><input type="text" id="o-web" placeholder="theo cấu hình"></div>
      <div class="grow"><label class="lbl">API (base_url)</label><input type="text" id="o-api" placeholder="theo cấu hình"></div>
    </div>
    <label class="lbl">Chỉ chạy AC <span class="opt">— vd: 001-1 002-3 (để trống = mọi AC)</span></label>
    <input type="text" id="o-only" placeholder="001-1 001-4">
    <div style="margin-top:12px">
      <label class="check"><input type="checkbox" id="o-llm"> Sinh testcase bằng authoring agent (LLM) <span class="opt" id="llm-note"></span></label>
      <label class="check"><input type="checkbox" id="o-run"> Thực thi testcase sau khi sinh</label>
      <label class="check"><input type="checkbox" id="o-headless"> Chạy trình duyệt ẩn (headless)</label>
      <label class="check"><input type="checkbox" id="o-trace"> Lưu trace Playwright <span class="opt">(case điền mật khẩu: chỉ có ảnh đã che ô mật khẩu)</span></label>
      <label class="check"><input type="checkbox" id="o-trace-sens"> Trace cả case nhập tài khoản/mật khẩu <span class="opt">(file trace chứa mật khẩu thật — chỉ xem trên máy này)</span></label>
    </div>
    <div id="run-error"></div>
    <div class="row" style="justify-content:space-between; margin-top:14px">
      <div class="muted">Kết quả ghi vào: <code id="out-path">—</code></div>
      <button class="primary" id="go" onclick="startRun()">▶ Chạy QC</button>
    </div>
  </div>
</section>

<!-- ═══ Chi tiết lượt chạy ═══ -->
<section id="view-run" style="display:none">
  <div class="row" style="justify-content:space-between">
    <div><button class="small" onclick="go('home')">← Lượt chạy</button> <b id="run-title" style="margin-left:8px"></b></div>
    <div id="run-badge"></div>
  </div>
  <div class="muted" id="run-meta" style="margin-top:6px"></div>
  <div id="run-error-box"></div>
  <div class="stages" id="stages" style="margin-top:14px"></div>
  <div id="agent-progress"></div>
  <div class="tabs">
    <a id="tab-log" onclick="tab('log')">Log chi tiết</a>
    <a id="tab-agent" onclick="tab('agent')">Agent</a>
    <a id="tab-results" onclick="tab('results')">Kết quả</a>
    <a id="tab-files" onclick="tab('files')">File</a>
  </div>
  <div id="pane-log">
    <div class="filters">
      <select id="f-stage" onchange="renderLog()"><option value="">Mọi bước</option></select>
      <label class="check"><input type="checkbox" id="f-detail" checked onchange="renderLog()"> Hiện chi tiết (detail)</label>
      <input type="text" id="f-text" placeholder="Lọc theo chữ / mã case…" oninput="renderLog()">
      <label class="check"><input type="checkbox" id="f-follow" checked> Tự cuộn</label>
      <span class="muted" id="log-count"></span>
      <button class="small" onclick="copyLog()">Copy</button>
    </div>
    <div class="log" id="log"></div>
  </div>
  <div id="pane-agent" style="display:none"></div>
  <div id="pane-results" style="display:none"></div>
  <div id="pane-files" style="display:none"></div>
</section>

<!-- ═══ Xem file ═══ -->
<section id="view-file" style="display:none">
  <div class="row"><button class="small" onclick="backFromFile()">← Quay lại</button> <code id="file-title"></code>
    <a class="btn small" id="file-dl">Tải về</a></div>
  <pre class="view" id="file-body" style="margin-top:12px"></pre>
</section>

<!-- ═══ Cài đặt ═══ -->
<section id="view-settings" style="display:none">
  <h1>Cài đặt</h1>
  <div class="card"><table><tbody id="settings"></tbody></table>
  <div class="muted" style="margin-top:10px">Sửa trong <code>.env</code> (không commit). Cấu hình từng feature nằm ở <code>projects/&lt;p&gt;/project.yaml</code> và <code>&lt;feature&gt;/qctool.yaml</code>.</div></div>
</section>

</main>
<script>
const STAGES = [['ingest','Đọc tài liệu'],['crawl','Mở web / đăng nhập'],['generate','Agent sinh testcase'],['render','Xuất Excel'],['execute','Chạy testcase'],['report','Báo cáo']];
const STATUS_TEXT = {running:'Đang chạy', done:'Xong', failed:'Lỗi pipeline', interrupted:'Bị dừng giữa chừng', pending:'Chờ', skipped:'Bỏ qua'};
const QC_TEXT = {SUCCESS:'Đạt hết', EXECUTION_FAILED:'Có lỗi sản phẩm', GENERATION_INCOMPLETE:'Sinh case chưa đủ', EXECUTION_INCOMPLETE:'Còn case bị chặn / chưa chạy', PIPELINE_ERROR:'Lỗi cấu hình/pipeline'};
let projects = [], llmInfo = {}, runs = {latest: [], history: []};
let cur = null;   // {dir, events:[], total, run, full, timer}
let lastView = 'home';

function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }
function fmtSec(s) { if (s == null) return '—'; s = Number(s); if (s < 60) return s.toFixed(s < 10 ? 1 : 0) + 's'; const m = Math.floor(s / 60); return m + 'm' + String(Math.round(s % 60)).padStart(2, '0') + 's'; }
function fmtTime(t) { return t ? String(t).replace('T', ' ').slice(0, 19) : '—'; }
function statusBadge(st) { const c = st === 'running' ? 'b-live' : st === 'done' ? 'b-pass' : st === 'failed' ? 'b-fail' : 'b-block';
  return '<span class="badge ' + c + '">' + (st === 'running' ? '<span class="pulse"></span>' : '') + esc(STATUS_TEXT[st] || st) + '</span>'; }
function caseBadge(st) { const c = {Pass:'b-pass', Fail:'b-fail', Blocked:'b-block'}[st] || 'b-none'; return '<span class="badge ' + c + '">' + esc(st) + '</span>'; }
function counts(c) { if (!c) return '<span class="muted">—</span>';
  return '<span class="mono">' + [['Pass','b-pass'],['Fail','b-fail'],['Blocked','b-block'],['Not Executed','b-none']]
    .map(([k, cl]) => '<span class="badge ' + cl + '" title="' + k + '">' + (c[k] || 0) + '</span>').join(' ') + '</span>'; }
async function getJSON(url) { const r = await fetch(url); const d = await r.json(); if (!r.ok) throw new Error(d.error || r.status); return d; }

function go(view) {
  ['home','create','run','file','settings'].forEach(v => document.getElementById('view-' + v).style.display = v === view ? '' : 'none');
  ['home','create','settings'].forEach(v => document.getElementById('nav-' + v).className = v === view ? 'active' : '');
  if (view !== 'run' && view !== 'file' && cur && cur.timer) { clearTimeout(cur.timer); cur.timer = null; }
  if (view === 'home') { loadRuns(); history.replaceState(null, '', '#'); }
  if (view !== 'file') lastView = view;
}

// ── Danh sách ──
async function loadRuns() {
  try { runs = await getJSON('/api/runs'); } catch (e) { return; }
  const tb = document.getElementById('runs-latest');
  tb.innerHTML = runs.latest.map(r => '<tr class="click" data-dir="' + esc(r.dir) + '" onclick="openRun(this.dataset.dir)">'
    + '<td class="mono">' + esc(fmtTime(r.started_at)) + '</td>'
    + '<td><b>' + esc(r.project) + '</b> / ' + esc(r.feature_name) + '</td>'
    + '<td>' + statusBadge(r.status) + (r.qc_status ? ' <span class="muted">' + esc(QC_TEXT[r.qc_status] || r.qc_status) + '</span>' : '') + '</td>'
    + '<td>' + counts(r.counts) + '</td><td class="mono">' + fmtSec(r.seconds) + '</td>'
    + '<td class="mono muted">' + esc(r.dir) + '</td></tr>').join('')
    || '<tr><td colspan="6" class="muted">Chưa có lượt chạy nào.</td></tr>';
  document.getElementById('runs-history').innerHTML = runs.history.map(h => '<details><summary><b>' + esc(h.project) + '</b> <span class="mono">' + esc(fmtTime(h.started_at)) + '</span> '
    + counts(h.totals) + ' <span class="muted">' + fmtSec(h.seconds) + '</span>'
    + (h.summary_md ? ' <a class="btn small" data-p="' + esc(h.summary_md) + '" onclick="event.preventDefault(); viewFile(this.dataset.p)">summary.md</a>' : '') + '</summary><div class="body"><table>'
    + h.features.map(f => '<tr' + (f.dir ? ' class="click" data-dir="' + esc(f.dir) + '" onclick="openRun(this.dataset.dir)"' : '') + '><td>' + esc(f.name) + '</td><td>' + esc(f.status) + '</td><td class="muted">' + (f.dir ? 'xem log/kết quả →' : 'không có bản chép') + '</td></tr>').join('')
    + '</table></div></details>').join('') || '<div class="muted">Chưa có.</div>';
}

// ── Chạy QC ──
async function loadProjects() {
  try { projects = await getJSON('/api/projects'); } catch (e) { projects = []; }
  const sel = document.getElementById('sel-project');
  sel.innerHTML = projects.map(p => '<option value="' + esc(p.id) + '">' + esc(p.id) + ' (' + p.features.length + ' feature)</option>').join('') || '<option value="">Chưa có project — qctool init &lt;project&gt;/&lt;feature&gt;</option>';
  onProject();
}
function curProject() { return projects.find(p => p.id === document.getElementById('sel-project').value); }
function curFeature() { const p = curProject(); return p && p.features.find(f => f.name === document.getElementById('sel-feature').value); }
function onProject() {
  const p = curProject();
  document.getElementById('sel-feature').innerHTML = p ? p.features.map(f => '<option value="' + esc(f.name) + '">' + esc(f.name) + '</option>').join('') : '';
  onFeature();
}
function onFeature() {
  const f = curFeature(), box = document.getElementById('feature-info');
  document.getElementById('run-error').innerHTML = '';
  if (!f) { box.innerHTML = ''; return; }
  let h = '<table style="margin-top:12px"><tbody>'
    + '<tr><td style="width:170px">Cấu hình</td><td><code>' + esc(f.config) + '</code> <span class="muted">+ project.yaml</span></td></tr>'
    + '<tr><td>Tài liệu</td><td>' + (f.docs.map(d => '<code>' + esc(d) + '</code>').join(' ') || '<span class="muted">không có .md</span>') + (f.openapi ? ' · <code>openapi.yaml</code>' : '') + '</td></tr>';
  if (f.error) { box.innerHTML = h + '</tbody></table><div class="err">Cấu hình lỗi: ' + esc(f.error) + '</div>'; return; }
  h += '<tr><td>Website / API</td><td><code>' + esc(f.web_url || '—') + '</code> · <code>' + esc(f.base_url || '—') + '</code></td></tr>'
    + '<tr><td>Xác thực</td><td><code>' + esc(f.auth_mode) + '</code>' + (f.fixtures ? ' · có test fixture (account)' : '') + '</td></tr>'
    + '<tr><td>LLM</td><td>' + (f.llm ? 'bật' : '<b>tắt</b>') + ' · model <code>' + esc(llmInfo.model || '—') + '</code>' + (llmInfo.key_set ? '' : ' · <b style="color:var(--fail)">chưa có QCTOOL_LLM_API_KEY</b>') + '</td></tr>'
    + '<tr><td>Chế độ</td><td>' + (f.write_mode ? '<b style="color:var(--fail)">write</b> — web không chạy được, dùng CLI --write' : 'safe (chỉ đọc)') + '</td></tr>'
    + '</tbody></table>';
  box.innerHTML = h;
  document.getElementById('o-llm').checked = !!f.llm;
  document.getElementById('o-run').checked = !f.skip_run;
  document.getElementById('o-headless').checked = f.headless !== false;
  document.getElementById('o-trace').checked = !!f.ui_trace;
  document.getElementById('o-trace-sens').checked = false;
  document.getElementById('o-web').value = ''; document.getElementById('o-api').value = ''; document.getElementById('o-only').value = '';
  document.getElementById('llm-note').textContent = llmInfo.key_set ? '' : '(chưa có API key trong .env — preflight sẽ báo lỗi)';
  document.getElementById('out-path').textContent = f.artifacts;
}
async function startRun() {
  const f = curFeature(), btn = document.getElementById('go'), errBox = document.getElementById('run-error');
  errBox.innerHTML = '';
  if (!f) { errBox.innerHTML = '<div class="err">Chọn project và feature.</div>'; return; }
  const payload = { config: f.config, llm: document.getElementById('o-llm').checked,
    skip_run: !document.getElementById('o-run').checked, headless: document.getElementById('o-headless').checked,
    ui_trace: document.getElementById('o-trace').checked || document.getElementById('o-trace-sens').checked,
    trace_sensitive: document.getElementById('o-trace-sens').checked, web_url: document.getElementById('o-web').value,
    base_url: document.getElementById('o-api').value, only: document.getElementById('o-only').value };
  btn.disabled = true; btn.textContent = 'Đang kiểm tra cấu hình…';
  try {
    const r = await fetch('/api/run', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    const d = await r.json();
    if (!r.ok) { errBox.innerHTML = '<div class="err">' + esc(d.error) + '</div>'; return; }
    openRun(d.artifacts, d.after);
  } catch (e) { errBox.innerHTML = '<div class="err">Không kết nối được máy chủ: ' + esc(e.message) + '</div>'; }
  finally { btn.disabled = false; btn.textContent = '▶ Chạy QC'; }
}

// ── Chi tiết lượt chạy ──
function openRun(dir, after) {
  if (cur && cur.timer) clearTimeout(cur.timer);
  cur = {dir: dir, after: after || '', events: [], total: 0, run: null, full: null, stage: '', timer: null, fails: 0};
  history.replaceState(null, '', '#run=' + encodeURIComponent(dir));
  go('run');
  document.getElementById('run-title').textContent = dir;
  document.getElementById('log').innerHTML = '';
  ['agent','results','files'].forEach(t => document.getElementById('pane-' + t).innerHTML = '<div class="muted">Đang tải…</div>');
  tab('log');
  poll();
}
// Không bao giờ ngừng theo dõi vì một lần đọc hỏng: lúc pipeline dọn thư mục, run.json có thể
// vắng mặt hoặc còn là của lượt trước. Thử lại, chỉ dừng khi lượt chạy thật sự kết thúc.
async function poll() {
  if (!cur) return;
  const me = cur;
  try { await pollOnce(me); me.fails = 0; }
  catch (e) {
    if (cur !== me) return;
    me.fails += 1;
    document.getElementById('run-error-box').innerHTML = me.fails > 3 ? '<div class="warn">Chưa đọc được trạng thái (' + esc(e.message) + ') — đang thử lại…</div>' : '';
    me.timer = setTimeout(poll, Math.min(5000, 500 * me.fails));
  }
}
async function pollOnce(me) {
  const wantFull = !me.full || (me.run && me.run.status === 'running' && Date.now() - (me.fullAt || 0) > 5000);
  const d = await getJSON('/api/run?dir=' + encodeURIComponent(me.dir) + '&since=' + me.total + (wantFull ? '&full=1' : ''));
  if (cur !== me) return;
  if (!d.run || (me.after && (d.run.started_at || '') < me.after)) {   // lượt mới chưa ghi run.json
    document.getElementById('agent-progress').innerHTML = '<div class="info"><span class="pulse"></span>Đang khởi động lượt chạy…</div>';
    me.timer = setTimeout(poll, 500); return;
  }
  if (d.events_total < me.total) { me.events = []; me.total = 0; me.full = null; me.timer = setTimeout(poll, 50); return; }   // thư mục bị ghi đè
  me.events = me.events.concat(d.events); me.total = me.events.length;
  const wasRunning = me.run && me.run.status === 'running';
  me.run = d.run;
  if (d.agent) { me.full = d; me.fullAt = Date.now(); }
  renderRun(); renderLog(true);
  if (d.agent) { renderAgent(); renderResults(); renderFiles(); }
  const running = d.run.status === 'running';
  if (running || me.events.length < d.events_total) me.timer = setTimeout(poll, running ? 1000 : 50);
  else if (wasRunning) { me.full = null; me.timer = setTimeout(poll, 50); }   // lần cuối: lấy kết quả hoàn chỉnh
}
function renderRun() {
  const r = cur.run;
  document.getElementById('run-badge').innerHTML = statusBadge(r.status) + (r.qc_status ? ' <span class="badge b-none">' + esc(QC_TEXT[r.qc_status] || r.qc_status) + '</span>' : '');
  document.getElementById('run-meta').innerHTML = 'Bắt đầu ' + esc(fmtTime(r.started_at)) + ' · ' + (r.finished_at ? 'kết thúc ' + esc(fmtTime(r.finished_at)) + ' · ' : '')
    + 'tổng ' + fmtSec(r.seconds) + (r.mode ? ' · chế độ <code>' + esc(r.mode) + '</code>' : '') + (r.generation_status ? ' · generation <code>' + esc(r.generation_status) + '</code>' : '')
    + (r.job_id ? ' · chạy từ web UI này' : r.status === 'running' ? ' · đang chạy ở tiến trình khác (CLI)' : '');
  let err = '';
  if (r.error) err += '<div class="err"><b>Lỗi ở bước ' + esc(r.error.stage) + ':</b> ' + esc(r.error.message) + (r.error.log ? ' — <a href="#" data-p="' + esc(cur.dir + '/' + r.error.log) + '" onclick="event.preventDefault(); viewFile(this.dataset.p)">' + esc(r.error.log) + '</a>' : '') + '</div>';
  if (r.status === 'interrupted') err += '<div class="warn">run.json vẫn ghi "đang chạy" nhưng tiến trình chạy nó không còn (đã tắt <code>qctool ui</code>/CLI, Ctrl+C, tắt máy…) hoặc im lặng hơn 15 phút. Kết quả các bước sau là của lượt trước hoặc không có.</div>';
  const unavailable = cur.events.find(e => /Không chạy authoring agent/.test(e.message));
  if (unavailable) err += '<div class="warn">' + esc(unavailable.message) + '</div>';
  document.getElementById('run-error-box').innerHTML = err;
  document.getElementById('stages').innerHTML = STAGES.map(([k, name]) => {
    const s = (r.stages || {})[k] || {}, st = s.status || 'pending';
    return '<div class="stage ' + st + (cur.stage === k ? ' sel' : '') + '" onclick="pickStage(\'' + k + '\')" title="Bấm để lọc log theo bước này">'
      + '<div class="t">' + name + '</div><div class="s">' + esc(STATUS_TEXT[st] || st) + ' · ' + fmtSec(s.seconds) + '</div>'
      + '<div class="m" title="' + esc(s.reason || s.last_message || '') + '">' + esc(s.reason || s.last_message || '') + '</div></div>';
  }).join('');
  // Tiến độ agent: đọc từ dòng "▶ Intent i/N"
  let done = 0, total = 0, now = '';
  cur.events.forEach(e => { const m = /([▶■]) Intent (\d+)\/(\d+) · (\S+)/.exec(e.message || ''); if (m) { total = +m[3]; if (m[1] === '■') done = +m[2]; else now = m[4]; } });
  document.getElementById('agent-progress').innerHTML = total ? '<div class="info">Agent: xong ' + done + '/' + total + ' intent'
    + (r.status === 'running' && done < total ? ' · đang viết <b>' + esc(now) + '</b>' : '') + '</div>' : '';
  const sel = document.getElementById('f-stage'), v = sel.value;
  sel.innerHTML = '<option value="">Mọi bước</option>' + STAGES.map(([k, n]) => '<option value="' + k + '">' + n + '</option>').join('');
  sel.value = v;
}
function pickStage(k) { cur.stage = cur.stage === k ? '' : k; document.getElementById('f-stage').value = cur.stage; tab('log'); renderRun(); renderLog(); }
function lineClass(e) {
  const m = e.message || '';
  if (e.level === 'error' || /⚠|LỖI|Error/.test(m)) return 'lv-error';
  if (/→ cần sửa|cần sửa/.test(m)) return 'bad';
  if (/→ OK|READY|✓/.test(m)) return 'ok';
  if (/ · lượt \d+:| · LLM nói:|Intent \d+\//.test(m)) return 'agent';
  return e.level === 'detail' ? 'lv-detail' : '';
}
function renderLog(incremental) {
  if (!cur) return;
  const stage = document.getElementById('f-stage').value, detail = document.getElementById('f-detail').checked,
        text = document.getElementById('f-text').value.toLowerCase(), box = document.getElementById('log');
  cur.stage = stage;
  // pipeline ghi nhiều tin hai lần (info + detail) — bỏ bản detail trùng ngay sau bản info
  const rows = cur.events.filter((e, i) => !(e.level === 'detail' && i && cur.events[i - 1].message === e.message)).filter(e => (!stage || e.stage === stage) && (detail || e.level !== 'detail') && (!text || (e.message || '').toLowerCase().includes(text)));
  document.getElementById('log-count').textContent = rows.length + '/' + cur.events.length + ' dòng';
  box.innerHTML = rows.map(e => '<div class="' + lineClass(e) + '"><span class="ts">' + esc(String(e.t || '').slice(11, 19)) + '</span> <span class="st">' + esc((e.stage || '').padEnd(8)) + '</span> ' + esc(e.message) + '</div>').join('')
    || '<div class="muted">Chưa có log.</div>';
  if (document.getElementById('f-follow').checked) box.scrollTop = box.scrollHeight;
}
function copyLog() { navigator.clipboard.writeText(cur.events.map(e => e.t + ' [' + e.stage + '] [' + e.level + '] ' + e.message).join('\n')); }
function tab(t) { ['log','agent','results','files'].forEach(x => { document.getElementById('pane-' + x).style.display = x === t ? '' : 'none'; document.getElementById('tab-' + x).className = x === t ? 'active' : ''; }); }

function renderAgent() {
  const rows = cur.full.agent || [], pane = document.getElementById('pane-agent');
  if (!rows.length) { pane.innerHTML = '<div class="muted">Không có dữ liệu agent (chưa tới bước sinh testcase, hoặc nguồn chỉ có OpenAPI — sinh tất định, không qua agent).</div>'; return; }
  const totalTok = rows.reduce((a, r) => a + (r.tokens || 0), 0);
  pane.innerHTML = '<div class="muted" style="margin-bottom:8px">' + rows.length + ' intent · ' + totalTok + ' token · nguồn: <code>3-generate/generation.json</code>. Thời gian từng lượt LLM/tool xem ở tab Log (lọc theo mã case).</div>'
    + rows.map(r => {
      const ok = r.stop_reason === 'READY';
      return '<details><summary><span class="badge ' + (ok ? 'b-pass' : 'b-block') + '">' + esc(r.stop_reason || '—') + '</span><b class="mono">' + esc(r.case_id) + '</b>'
        + '<span class="mono muted">' + esc(r.intent_id || '') + '</span><span>' + esc(r.title || r.expected || '') + '</span>'
        + '<span class="muted">' + (r.llm_calls || 0) + ' lượt LLM · ' + (r.history || []).length + ' tool · ' + (r.tokens || 0) + ' token</span></summary><div class="body">'
        + (r.expected ? '<div><b>Given</b> ' + esc(r.given) + '<br><b>When</b> ' + esc(r.when) + '<br><b>Then</b> ' + esc(r.expected) + '</div>' : '')
        + (r.issues && r.issues.length ? '<div class="warn">' + r.issues.map(esc).join('<br>') + '</div>' : '')
        + (r.review_reasons && r.review_reasons.length && !ok ? '<div class="muted">Lý do: ' + r.review_reasons.map(esc).join('; ') + '</div>' : '')
        + ((r.history || []).length ? '<h2>Các lần gọi tool</h2><table><thead><tr><th>Lượt</th><th>Tool</th><th>KQ</th><th>Tham số</th><th>Lỗi / phản hồi gate</th></tr></thead><tbody>'
          + r.history.map(h => '<tr><td>' + esc(h.turn == null ? '' : h.turn) + '</td><td class="mono">' + esc(h.tool) + '</td><td>' + (h.ok ? '<span style="color:var(--pass)">OK</span>' : '<span style="color:var(--fail)">cần sửa</span>') + '</td>'
            + '<td class="mono">' + esc(h.arguments ? JSON.stringify(h.arguments) : '') + '</td><td>' + esc([h.error, (h.errors || []).join('; '), h.failed_step != null ? 'bước ' + h.failed_step : '', (h.concerns || []).join('; ')].filter(Boolean).join(' · ')) + '</td></tr>').join('')
          + '</tbody></table>' : '')
        + (r.steps && r.steps.length ? '<h2>Testcase cuối cùng</h2><table><tbody>' + r.steps.map(s => '<tr><td>' + esc(s.seq) + '</td><td>' + esc(s.kind) + '</td><td class="mono">' + esc(s.action) + '</td><td class="mono">' + esc(JSON.stringify(s.args || {})) + '</td></tr>').join('') + '</tbody></table>' : '')
        + '</div></details>';
    }).join('');
}
function renderResults() {
  const cases = cur.full.results || [], pane = document.getElementById('pane-results');
  if (!cases.length) { pane.innerHTML = '<div class="muted">Chưa có <code>5-execute/results.json</code>.</div>'; return; }
  const c = {}; cases.forEach(x => c[x.status] = (c[x.status] || 0) + 1);
  const proj = /\/artifacts$/.test(cur.dir) ? cur.dir.split('/').slice(-3, -1).join('/') : '';
  pane.innerHTML = '<div class="kpis">' + [['Pass','b-pass'],['Fail','b-fail'],['Blocked','b-block'],['Not Executed','b-none']].map(([k, cl]) => '<div class="kpi"><b>' + (c[k] || 0) + '</b><span class="badge ' + cl + '">' + k + '</span></div>').join('') + '</div>'
    + cases.map(x => '<details><summary>' + caseBadge(x.status) + (x.flaky ? '<span class="badge b-block">flaky</span>' : '') + '<b class="mono">' + esc(x.case_id) + '</b><span>' + esc(x.title) + '</span><span class="muted">' + fmtSec((x.duration_ms || 0) / 1000) + '</span></summary><div class="body">'
      + (x.blocked_reason ? '<div class="warn">Bị chặn: ' + esc(x.blocked_reason) + '</div>' : '')
      + (x.status === 'Not Executed' && x.review_reasons && x.review_reasons.length ? '<div class="muted">Chưa chạy vì: ' + x.review_reasons.map(esc).join('; ') + ' (generation: ' + esc(x.generation_status) + ')</div>' : '')
      + ((x.steps || []).length ? '<table><thead><tr><th>#</th><th>Action</th><th>KQ</th><th>Thời gian</th><th>Chi tiết</th></tr></thead><tbody>' + x.steps.map(s => '<tr><td>' + esc(s.seq) + '</td><td class="mono">' + esc(s.action) + '</td><td>' + (s.ok ? '<span style="color:var(--pass)">✓</span>' : '<span style="color:var(--fail)">✗</span>') + '</td><td class="mono">' + fmtSec((s.duration_ms || 0) / 1000) + '</td><td>' + esc(s.detail) + '</td></tr>').join('') + '</tbody></table>' : '')
      + '<div class="row" style="margin-top:8px;flex-wrap:wrap">' + (x.evidence || []).filter(p => p.endsWith('.png')).map(p => '<a target="_blank" href="/api/download?inline=1&path=' + encodeURIComponent(p) + '" title="' + esc(p.split('/').pop()) + '"><img src="/api/download?inline=1&path=' + encodeURIComponent(p) + '" style="height:140px;border:1px solid var(--line);border-radius:6px" loading="lazy"></a>').join(' ') + '</div>'
      + '<div class="row" style="margin-top:8px">' + (x.evidence || []).filter(p => p.endsWith('.trace.zip')).map(p => '<button class="small" data-trace="' + esc(p) + '" onclick="openTrace(this)">▶ Mở trace Playwright</button> <a class="btn small" href="/api/download?path=' + encodeURIComponent(p) + '">📦 tải ' + esc(p.split('/').pop()) + '</a>').join(' ')
      + (proj && (x.evidence || []).some(p => p.endsWith('.trace.zip')) ? ' <span class="muted">hoặc terminal: <code>qctool trace ' + esc(proj) + ' ' + esc(x.case_id) + '</code></span>' : '')
      + ((x.evidence || []).length ? '' : '<span class="muted">Không có ảnh/trace cho case này.</span>') + '</div>'
      + '</div></details>').join('');
}
async function openTrace(btn) {
  btn.disabled = true;
  try {
    const r = await fetch('/api/trace/open', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path: btn.dataset.trace})});
    const d = await r.json(); if (!r.ok) throw new Error(d.error);
    btn.textContent = 'Đã mở cửa sổ Trace Viewer';
  } catch (e) { alert(e.message); }
  setTimeout(() => { btn.disabled = false; btn.textContent = '▶ Mở trace Playwright'; }, 4000);
}
function renderFiles() {
  const files = cur.full.files || [], pane = document.getElementById('pane-files');
  pane.innerHTML = '<div class="card" style="padding:0"><table><thead><tr><th>File</th><th>Kích thước</th><th></th></tr></thead><tbody>'
    + files.map(f => '<tr><td class="mono">' + esc(f.name) + '</td><td class="mono muted">' + (f.size > 1024 ? (f.size / 1024).toFixed(1) + ' KB' : f.size + ' B') + '</td><td style="white-space:nowrap">'
      + (/\.(md|log|json|jsonl|yaml|yml|csv|xml|txt)$/.test(f.name) ? '<button class="small" data-p="' + esc(f.path) + '" onclick="viewFile(this.dataset.p)">Xem</button> ' : '')
      + '<a class="btn small" href="/api/download?path=' + encodeURIComponent(f.path) + '">Tải</a></td></tr>').join('')
    + '</tbody></table></div><div class="muted">Thư mục: <code>' + esc(cur.dir) + '</code> · ảnh/trace ở tab Kết quả.</div>';
}
async function viewFile(path) {
  go('file');
  document.getElementById('file-title').textContent = path;
  document.getElementById('file-dl').href = '/api/download?path=' + encodeURIComponent(path);
  const body = document.getElementById('file-body'); body.textContent = 'Đang tải…';
  try { const r = await fetch('/api/download?inline=1&path=' + encodeURIComponent(path)); body.textContent = r.ok ? await r.text() : (await r.json()).error; }
  catch (e) { body.textContent = e.message; }
}
function backFromFile() { if (lastView === 'run' && cur) { go('run'); if (cur.run && cur.run.status === 'running') poll(); } else go(lastView); }

async function loadSettings() {
  try {
    const c = await getJSON('/api/config'); llmInfo = c.llm || {};
    document.getElementById('settings').innerHTML = [['LLM model', llmInfo.model], ['LLM base URL', llmInfo.base_url], ['LLM API key', llmInfo.key_set ? 'đã đặt' : 'CHƯA ĐẶT'],
      ['QCTOOL_LLM_ENABLED (mặc định khi YAML không ghi)', String(llmInfo.enabled_default)], ['LLM thinking', llmInfo.thinking], ['LLM timeout (s)', llmInfo.timeout],
      ['Tài khoản (.env)', c.username], ['Chế độ xác thực mặc định (.env)', c.auth_mode], ['API base URL (.env)', c.base_url]]
      .map(([k, v]) => '<tr><td style="width:300px"><b>' + esc(k) + '</b></td><td><code>' + esc(v || '—') + '</code></td></tr>').join('');
  } catch (e) {}
}

document.addEventListener('DOMContentLoaded', async function () {
  await loadSettings();
  loadProjects();
  const m = /#run=(.+)/.exec(location.hash);
  if (m) openRun(decodeURIComponent(m[1])); else go('home');
});
</script>
</body>
</html>
"""


def _q(query: dict, key: str) -> str:
    return (query.get(key) or [""])[0]


# Cấu hình qua giao diện — logic ở `web/setup.py`, đây chỉ là bảng định tuyến.
SETUP_GET = {
    "/api/setup/projects": lambda q: setup.list_projects(),
    "/api/setup/project": lambda q: setup.get_project(_q(q, "project")),
    "/api/setup/feature": lambda q: setup.get_feature(_q(q, "project"), _q(q, "feature")),
    "/api/setup/doc": lambda q: setup.read_doc(_q(q, "project"), _q(q, "feature"), _q(q, "name")),
    "/api/setup/check": lambda q: setup.check_feature(_q(q, "project"), _q(q, "feature")),
    "/api/setup/env": lambda q: setup.get_env(),
}
SETUP_POST = {
    "/api/setup/projects": lambda p: setup.create_project(p.get("name", ""), p.get("form") or {}),
    "/api/setup/project/form": lambda p: setup.save_project_form(p.get("project", ""), p.get("form") or {}),
    "/api/setup/project/yaml": lambda p: setup.save_project_yaml(p.get("project", ""), str(p.get("yaml") or "")),
    "/api/setup/features": lambda p: setup.create_feature(p.get("project", ""), p.get("name", "")),
    "/api/setup/feature/account": lambda p: setup.save_feature_account(
        p.get("project", ""), p.get("feature", ""), p.get("login_for") or [], p.get("test_values") or {}),
    "/api/setup/feature/yaml": lambda p: setup.save_feature_yaml(p.get("project", ""), p.get("feature", ""),
                                                                 str(p.get("yaml") or "")),
    "/api/setup/doc": lambda p: setup.save_doc(p.get("project", ""), p.get("feature", ""), p.get("name", ""),
                                               p.get("content")),
    "/api/setup/doc/delete": lambda p: setup.delete_doc(p.get("project", ""), p.get("feature", ""), p.get("name", "")),
    "/api/setup/env": lambda p: setup.save_env(p.get("updates") or {}, p.get("clear") or []),
    "/api/setup/llm-test": lambda p: setup.test_llm(),
}


def _llm():
    from qctool.agent.llm_provider import load_llm_provider
    return load_llm_provider()


def _chat_upload(p: dict) -> dict:
    files = p.get("files") or []
    if not isinstance(files, list) or not all(isinstance(f, dict) for f in files):
        raise chat.ChatError("files phải là danh sách {name, content}.")
    target = {k: str(p[k]) for k in ("web", "api") if p.get(k) is not None}
    out = chat.upload(p.get("project", ""), p.get("feature") or "main", files, target)
    if p.get("session") and (out["saved"] or target):
        f = out["feature"]
        parts = []
        if out["saved"]:
            parts.append(f"Người dùng đã tải {', '.join(out['saved'])} vào feature {p.get('feature') or 'main'}"
                         + (f" ({f['acs']} AC đọc được)" if f else ""))
        if target:
            parts.append("Cập nhật URL: " + ", ".join(f"{k}={v or '(trống)'}" for k, v in target.items()))
        chat.note(p["project"], p["session"], ". ".join(parts) + ".")
    return out


def _chat_account(p: dict) -> dict:
    updates = {"QCTOOL_USERNAME": str(p.get("username") or "").strip()}
    if p.get("password"):
        updates["QCTOOL_PASSWORD"] = str(p["password"])
    if not updates["QCTOOL_USERNAME"]:
        raise chat.ChatError("Nhập tài khoản (email/username).")
    setup.save_env(updates)
    if p.get("project") and p.get("session"):
        # Chỉ báo "đã có tài khoản" — không đưa username/mật khẩu vào transcript gửi LLM.
        chat.note(p["project"], p["session"], "Người dùng đã lưu tài khoản test vào .env.")
    return {"ok": True}


# Chế độ chat — logic ở `web/chat.py`.
CHAT_GET = {
    "/api/chat/sessions": lambda q: chat.list_sessions(_q(q, "project")),
    "/api/chat/session": lambda q: chat.view(chat.load(_q(q, "project"), _q(q, "id"))),
    "/api/chat/catalog": lambda q: chat._overview(chat.catalog(_q(q, "project"))),
    "/api/chat/status": lambda q: {"llm_ready": chat.llm_ready(), "projects": setup.list_projects(),
                                   "account_set": all(e["set"] for e in setup.get_env()
                                                      if e["key"] in ("QCTOOL_USERNAME", "QCTOOL_PASSWORD"))},
}
CHAT_POST = {
    "/api/chat/new": lambda p: chat.view(chat.create(p.get("project", ""))),
    "/api/chat/message": lambda p: chat.send(p.get("project", ""), p.get("id", ""), p.get("text", ""), _llm),
    "/api/chat/run": lambda p: chat.start_plan(p.get("project", ""), p.get("id", ""), p.get("plan", ""), _run_feature,
                                               options={"trace_sensitive": p.get("trace_sensitive") is True},
                                               summarize=_plan_summary),
    "/api/trace/open": lambda p: _open_trace(p),
    "/api/chat/cancel": lambda p: chat.cancel_plan(p.get("project", ""), p.get("id", ""), p.get("plan", "")),
    "/api/chat/upload": _chat_upload,
    "/api/chat/account": _chat_account,
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "qc-tool"

    def log_message(self, fmt, *args) -> None:
        pass   # UI hỏi /api/run mỗi giây — in ra thì terminal chỉ còn rác

    # ── Định tuyến ──────────────────────────────────────────────────────────
    def do_GET(self) -> None:                       # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            return self._html(CHAT_PAGE)
        if path == "/console":
            return self._html(PAGE)
        if path == "/api/projects":
            return self._json(200, _get_projects())
        if path == "/api/runs":
            return self._json(200, _get_runs())
        if path == "/api/run":
            try:
                since = max(0, int((query.get("since") or ["0"])[0]))
            except ValueError:
                since = 0
            code, body = _run_detail((query.get("dir") or [""])[0], since,
                                     (query.get("full") or ["0"])[0] in ("1", "true"))
            return self._json(code, body)
        if path.startswith("/api/jobs/"):
            job = STORE.get(path.rsplit("/", 1)[-1])
            if not job:
                return self._json(404, {"error": "không tìm thấy lượt chạy"})
            return self._json(200, job.snapshot())
        if path == "/api/config":
            env = cfg_mod.load_config()
            return self._json(200, {"base_url": env.base_url, "auth_mode": env.auth_mode,
                                    "username": env.username, "oidc_issuer": env.oidc_issuer,
                                    "llm": _llm_info()})
        if path == "/api/download":
            return self._download()
        if path in SETUP_GET:
            return self._setup(SETUP_GET[path], query)
        if path in CHAT_GET:
            return self._setup(CHAT_GET[path], query)
        return self._json(404, {"error": f"không có đường dẫn {path}"})

    def _setup(self, handler, arg) -> None:
        try:
            return self._json(200, handler(arg))
        except (setup.SetupError, chat.ChatError) as exc:
            return self._json(400, {"error": str(exc)})

    def do_POST(self) -> None:                      # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        # Chặn trang web lạ gửi POST ngầm tới 127.0.0.1 (CSRF): form/no-cors fetch không đặt được
        # Content-Type JSON mà không qua CORS preflight — server này không trả lời preflight.
        origin = self.headers.get("Origin")
        if not (self.headers.get("Content-Type") or "").startswith("application/json") or (
                origin and urllib.parse.urlparse(origin).netloc != self.headers.get("Host")):
            return self._json(403, {"error": "Chỉ nhận JSON từ chính giao diện qc-tool"})
        if path in SETUP_POST or path in CHAT_POST:
            try:
                payload = self._read_json()
            except ValueError as exc:
                return self._json(400, {"error": str(exc)})
            return self._setup(SETUP_POST.get(path) or CHAT_POST[path], payload)
        if path != "/api/run":
            return self._json(404, {"error": f"không có đường dẫn {path}"})
        try:
            payload = self._read_json()
            cfg, adapter = _project_config(payload) if payload.get("config") else _adhoc_config(payload)
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        out = _rel(cfg.out_dir or pipeline.ARTIFACTS_ROOT / cfg.feature)
        if running := STORE.live_for(out):
            return self._json(409, {"error": f"{out} đang có lượt chạy {running.id} — chờ nó xong",
                                    "artifacts": out})
        after = datetime.now(GMT7).isoformat(timespec="seconds")
        job = _start_job(cfg, adapter, payload.get("config") or None)
        return self._json(202, {"job_id": job.id, "artifacts": job.artifacts, "after": after})

    # ── Tiện ích ────────────────────────────────────────────────────────────
    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        if length > MAX_BODY:
            raise ValueError("Dữ liệu gửi lên quá lớn")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON không hợp lệ: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Dữ liệu gửi lên phải là JSON object")
        return data

    def _download(self) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        raw = (query.get("path") or [""])[0]
        inline = (query.get("inline") or ["0"])[0] in ("1", "true")
        if not raw:
            return self._json(400, {"error": "thiếu tham số `path`"})
        resolved = _inside_project(raw)
        if resolved is None:
            return self._json(403, {"error": "chỉ được tải file trong thư mục dự án"})
        if resolved.name.startswith(".") or resolved.name == ".env":
            return self._json(403, {"error": "file ẩn (phiên đăng nhập, token, .env) không được tải qua web"})
        if not resolved.is_file():
            return self._json(404, {"error": f"không tìm thấy file: {raw}"})
        ctype = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        if inline and resolved.suffix in (".md", ".log", ".jsonl", ".yaml", ".yml", ".csv", ".txt"):
            ctype = "text/plain; charset=utf-8"
        data = resolved.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        disposition = "inline" if inline else "attachment"
        self.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{urllib.parse.quote(resolved.name)}")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _html(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code: int, data) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(port: int = 8080, host: str = "127.0.0.1", open_browser: bool = True) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}"
    print()
    print(f"  qc-tool đang chạy tại {url}")
    print("  Ctrl+C để dừng.")
    print()
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng.")
    finally:
        server.server_close()

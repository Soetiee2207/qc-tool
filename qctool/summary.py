"""Báo cáo tổng hợp một lượt `qctool run <project>` → `projects/<project>/summary/<ngày_giờ>/`.

Artifacts của feature bị ghi đè mỗi lượt chạy, nên summary CHÉP lại những gì cần xem
lại sau này (report, results, xlsx, log, evidence). Feature không chạy tới pipeline (lỗi
cấu hình) vẫn còn artifacts của lượt TRƯỚC — nhận ra qua `run.json.started_at` và không
chép, để báo cáo không trộn kết quả cũ vào lượt mới.
"""
from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from qctool.artifacts import GMT7

STATUSES = ("Pass", "Fail", "Blocked", "Not Executed")
EXIT_LABEL = {0: "OK", 1: "Có lỗi sản phẩm", 2: "Lỗi cấu hình/pipeline", 3: "Sinh case chưa đủ",
              4: "Có case bị chặn/chưa chạy"}
COPY = ["run.json", "events.jsonl", "summary.json", "pipeline.log", "3-generate/testcases.yaml",
        "3-generate/generation.json", "4-render/testcases.xlsx", "5-execute/results.json",
        "5-execute/results.csv", "5-execute/junit.xml", "5-execute/evidence", "6-report/report.md"]


@dataclass
class FeatureRun:
    name: str
    exit_code: int
    artifacts: Path
    fresh: bool = False
    counts: dict = field(default_factory=lambda: dict.fromkeys(STATUSES, 0))
    flaky: int = 0
    error: str = ""
    mode: str = "safe"
    rows: list = field(default_factory=list)


def now() -> datetime:
    return datetime.now(GMT7)


def write_project_summary(project: Path, runs: list[tuple[str, int, Path]], started: datetime) -> Path:
    """`runs` = [(feature, exit_code, artifacts_dir)] theo thứ tự đã chạy."""
    finished = now()
    out = project / "summary" / started.strftime("%Y-%m-%d_%H-%M-%S")
    out.mkdir(parents=True, exist_ok=True)
    features = [_collect(name, code, art, started, out / name) for name, code, art in runs]
    rows = [r for f in features for r in f.rows]
    totals = {s: sum(f.counts[s] for f in features) for s in STATUSES}
    meta = {"project": project.name, "started_at": started.isoformat(timespec="seconds"),
            "finished_at": finished.isoformat(timespec="seconds"),
            "duration_seconds": round((finished - started).total_seconds()),
            "exit_code": max((f.exit_code for f in features), default=0),
            "write_features": [f.name for f in features if f.fresh and f.mode == "write"],
            "totals": {**totals, "total": len(rows), "flaky": sum(f.flaky for f in features)},
            "features": [{"name": f.name, "exit_code": f.exit_code, "status": EXIT_LABEL.get(f.exit_code, str(f.exit_code)),
                          "ran": f.fresh, "counts": f.counts, "flaky": f.flaky, "error": f.error} for f in features]}
    (out / "summary.json").write_text(json.dumps({**meta, "testcases": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out / "testcases.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Feature", "Mã testcase", "Module", "Tiêu đề", "Kết quả", "Chập chờn", "Chi tiết", "Bằng chứng"])
        for r in rows:
            writer.writerow([r["feature"], r["id"], r["module"], r["title"], r["status"],
                             "có" if r["flaky"] else "", r["detail"], " ".join(r["evidence"])])
    (out / "summary.md").write_text(_markdown(meta, features, rows), encoding="utf-8")
    _write_index(project / "summary")
    return out


def _collect(name: str, code: int, art: Path, started: datetime, dest: Path) -> FeatureRun:
    run = FeatureRun(name, code, art)
    state = _json(art / "run.json")
    try:
        run.fresh = datetime.fromisoformat(state["started_at"]) >= started.replace(microsecond=0)
    except (KeyError, TypeError, ValueError):
        run.fresh = False
    if not run.fresh:
        run.error = "Không chạy tới pipeline (lỗi cấu hình/preflight) — xem output terminal"
        return run
    run.mode = state.get("mode", "safe")
    if err := state.get("error"):
        run.error = f"Bước {err.get('stage')}: {err.get('message')} → {name}/{err.get('log')}"
    for rel in COPY + [s["error_log"] for s in state.get("stages", {}).values() if s.get("error_log")]:
        src = art / rel
        if src.is_dir():
            shutil.copytree(src, dest / rel, dirs_exist_ok=True)
        elif src.is_file():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)
    results = _json(art / "5-execute/results.json").get("results")
    if results is None:   # sinh case mà không chạy (skip_run / thiếu URL / pipeline dừng sớm)
        cases = (_yaml(art / "3-generate/testcases.yaml").get("testcases") or [])
        results = [{"case_id": c.get("id"), "module": c.get("module"), "title": c.get("title"),
                    "status": "Not Executed", "actual": ["Lượt này không thực thi testcase"]} for c in cases]
    for r in results:
        status = r.get("status") if r.get("status") in STATUSES else "Not Executed"
        run.counts[status] += 1
        run.flaky += bool(r.get("flaky"))
        run.rows.append({"feature": name, "id": r.get("case_id") or "", "module": r.get("module") or "",
                         "title": r.get("title") or "", "status": status, "flaky": bool(r.get("flaky")),
                         "detail": _detail(r), "evidence": [f"{name}/5-execute/evidence/{p}" for p in _evidence(r)]})
    return run


def _detail(r: dict) -> str:
    if r.get("blocked_reason"):
        return r["blocked_reason"]
    actual = [str(a) for a in r.get("actual") or []]
    failed = [a for a in actual if a.startswith("[X]")]
    return " · ".join(failed or actual[-1:])


def _evidence(r: dict) -> list[str]:
    ev = r.get("evidence") or {}
    paths = list(ev.get("screenshots") or []) + ([ev["trace"]] if ev.get("trace") else [])
    return [Path(p).name for p in paths]


def _markdown(meta: dict, features: list[FeatureRun], rows: list[dict]) -> str:
    t = meta["totals"]
    executed = t["Pass"] + t["Fail"]
    rate = f"{t['Pass'] / executed * 100:.0f}% ({t['Pass']}/{executed} test tự động chạy được)" if executed else "—"
    md = [f"# Báo cáo tổng hợp — {meta['project']}", "",
          f"- Bắt đầu: {meta['started_at']} · Kết thúc: {meta['finished_at']} · {meta['duration_seconds']} giây",
          f"- Kết quả chung: **{EXIT_LABEL.get(meta['exit_code'], meta['exit_code'])}** (mã thoát {meta['exit_code']})",
          f"- Tỉ lệ đạt: {rate}",
          *([f"- ⚠ **Chế độ GHI** ở: {', '.join(meta['write_features'])} — lượt này đã tạo/sửa/xoá dữ liệu thật"]
            if meta["write_features"] else ["- Chế độ: chỉ đọc (safe)"]), "",
          "## 1. Số liệu", "",
          "| Tổng | Đạt | Lỗi | Bị chặn | Chưa chạy | Chập chờn |", "|---|---|---|---|---|---|",
          f"| {t['total']} | {t['Pass']} | {t['Fail']} | {t['Blocked']} | {t['Not Executed']} | {t['flaky']} |", "",
          "**Lỗi** = sản phẩm trả sai. **Bị chặn** = chưa chạy được vì thiếu điều kiện môi trường — không phải bug. "
          "**Chưa chạy** = case thủ công/chưa map, gồm các AC ghi dữ liệu thật.", "",
          "## 2. Theo feature", "",
          "| Feature | Chế độ | Trạng thái | Đạt | Lỗi | Bị chặn | Chưa chạy | Báo cáo |", "|---|---|---|---|---|---|---|---|"]
    for f in features:
        link = f"[report]({f.name}/6-report/report.md)" if (f.fresh and f.counts["Pass"] + f.counts["Fail"] + f.counts["Blocked"]) else "—"
        c = f.counts
        md.append(f"| {f.name} | {'⚠ ghi' if f.mode == 'write' else 'đọc'} | {EXIT_LABEL.get(f.exit_code, f.exit_code)} | {c['Pass']} | {c['Fail']} | {c['Blocked']} "
                  f"| {c['Not Executed']} | {link} |")
    if problems := [f for f in features if f.error]:
        md += ["", "**Feature không hoàn tất:**", ""] + [f"- `{f.name}`: {f.error}" for f in problems]
    for title, status in (("3. Lỗi sản phẩm (Fail)", "Fail"), ("4. Bị chặn (Blocked)", "Blocked")):
        md += ["", f"## {title}", ""]
        picked = [r for r in rows if r["status"] == status]
        md += [f"- `{r['feature']}` **{r['id']}** — {r['title']}  \n  {r['detail']}"
               + (f"  \n  Bằng chứng: " + ", ".join(f"[{Path(e).name}]({e})" for e in r["evidence"]) if r["evidence"] else "")
               for r in picked] or ["Không có."]
    if flaky := [r for r in rows if r["flaky"]]:
        md += ["", "## Chập chờn (chỉ đạt sau khi chạy lại)", ""] + [f"- `{r['feature']}` **{r['id']}** — {r['title']}" for r in flaky]
    md += ["", f"## 5. Toàn bộ testcase ({len(rows)})", "",
           "| Feature | Mã | Tiêu đề | Kết quả | Chi tiết |", "|---|---|---|---|---|"]
    md += [f"| {r['feature']} | {r['id']} | {_cell(r['title'])} | {r['status']}{' ⚠ chập chờn' if r['flaky'] else ''} "
           f"| {_cell(r['detail'])} |" for r in rows]
    md += ["", "Bản sao đầy đủ của từng feature (report, results, testcases.xlsx, log, evidence) nằm trong thư mục "
           "con cùng tên. File máy đọc: `summary.json`, `testcases.csv`.", ""]
    return "\n".join(md)


def _write_index(root: Path) -> None:
    runs = []
    for d in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
        meta = _json(d / "summary.json")
        if meta:
            runs.append((d.name, meta))
    md = [f"# Lịch sử chạy — {root.parent.name}", "", "Mới nhất lên đầu. Mỗi dòng là một lượt `qctool run`.", "",
          "| Lượt chạy | Feature | Tổng | Đạt | Lỗi | Bị chặn | Chưa chạy | Kết quả |", "|---|---|---|---|---|---|---|---|"]
    for name, m in runs:
        t = m.get("totals", {})
        md.append(f"| [{name}]({name}/summary.md) | {len(m.get('features', []))} | {t.get('total', 0)} | {t.get('Pass', 0)} "
                  f"| {t.get('Fail', 0)} | {t.get('Blocked', 0)} | {t.get('Not Executed', 0)} "
                  f"| {EXIT_LABEL.get(m.get('exit_code'), m.get('exit_code'))} |")
    (root / "README.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}

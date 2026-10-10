"""Bố cục artifacts của một lượt chạy + dấu vết từng bước.

    <feature>/artifacts/
      run.json        trạng thái: bước nào đã chạy, đang chạy, lỗi ở đâu, file nào sinh ra
      events.jsonl    mỗi dòng một sự kiện {t, stage, level, message} — UI đọc trực tiếp
      1-ingest/ … 6-report/   output của đúng bước đó + stage.log (+ error.log khi lỗi)

Mỗi lượt chạy ghi đè lượt trước, trừ tri thức/phiên đăng nhập trong `2-crawl/` (KEEP):
xoá chúng là bắt agent dò lại từ đầu và đăng nhập lại mỗi lần.

Mọi message đi qua `redact` trước khi chạm đĩa — log là thứ người ta hay gửi cho nhau.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

STAGES = {
    "ingest": "1-ingest",
    "crawl": "2-crawl",
    "generate": "3-generate",
    "render": "4-render",
    "execute": "5-execute",
    "report": "6-report",
}
# Tên chặng mà code phát ra → bước trong bố cục.
ALIASES = {"agent": "generate", "run": "execute", "done": "report"}  # "ui"/"error": giữ bước hiện tại
KEEP = {"2-crawl/app-model.yaml", "2-crawl/.auth-state.json", "2-crawl/.token",
        "pipeline.log"}   # CLI mở log trực tiếp trước khi pipeline dọn thư mục
GMT7 = timezone(timedelta(hours=7))


def _now() -> str:
    return datetime.now(GMT7).isoformat(timespec="seconds")


def stage_dir(root: Path, stage: str) -> Path:
    path = root / STAGES[stage]
    path.mkdir(parents=True, exist_ok=True)
    return path


class RunTracker:
    def __init__(self, root: Path, *, redact=lambda text: text, feature: str = ""):
        self.root = root
        self.redact = redact
        self.current: str | None = None
        _clean(root)
        root.mkdir(parents=True, exist_ok=True)
        self.state = {"feature": feature, "status": "running", "started_at": _now(),
                      "finished_at": None, "current_stage": None, "error": None,
                      "stages": {name: {"dir": folder, "status": "pending"} for name, folder in STAGES.items()}}
        self._save()

    def dir(self, stage: str) -> Path:
        return stage_dir(self.root, stage)

    def event(self, stage: str, message: str, level: str = "info") -> None:
        stage = ALIASES.get(stage, stage)
        if stage in STAGES and stage != self.current:
            self._start(stage)
        stage = self.current or stage
        message = self.redact(message)
        line = {"t": _now(), "stage": stage, "level": level, "message": message}
        with (self.root / "events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        if stage in STAGES:
            with (self.dir(stage) / "stage.log").open("a", encoding="utf-8") as fh:
                fh.write(f"{line['t']} [{level}] {message}\n")
            self.state["stages"][stage]["last_message"] = message
        self._save()

    def output(self, stage: str, path: Path | None) -> None:
        if path is None:
            return
        info = self.state["stages"][stage]
        try:
            rel = path.relative_to(self.root).as_posix()
        except ValueError:
            rel = str(path)
        if rel not in info.setdefault("outputs", []):
            info["outputs"].append(rel)
        self._save()

    def skip(self, stage: str, reason: str) -> None:
        if stage == self.current:
            self.current = None
        self.state["stages"][stage].update(status="skipped", reason=self.redact(reason))
        self._save()

    def fail(self, error: str, detail: str = "") -> None:
        stage = self.current or "ingest"
        error = self.redact(error)
        log = self.dir(stage) / "error.log"
        log.write_text(error + "\n\n" + self.redact(detail), encoding="utf-8")
        self.state["stages"][stage].update(status="failed", finished_at=_now(), error=error,
                                           error_log=log.relative_to(self.root).as_posix())
        self.state.update(status="failed", error={"stage": stage, "message": error,
                                                   "log": log.relative_to(self.root).as_posix()})
        self.current = None
        self._finish()

    def finish(self) -> None:
        self._close("done")
        self.state["status"] = "done"
        self._finish()

    def _start(self, stage: str) -> None:
        self._close("done")
        self.current = stage
        self.state["current_stage"] = stage
        self.state["stages"][stage].update(status="running", started_at=_now())

    def _close(self, status: str) -> None:
        if self.current:
            self.state["stages"][self.current].update(status=status, finished_at=_now())
        self.current = None

    def _finish(self) -> None:
        self.state.update(finished_at=_now(), current_stage=None)
        self._save()

    def _save(self) -> None:
        tmp = self.root / ".run.json.tmp"
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.root / "run.json")   # UI đọc giữa chừng không thấy file dở


def _clean(root: Path) -> None:
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        rel = path.relative_to(root).as_posix()
        if rel in KEEP or any(k.startswith(rel + "/") for k in KEEP):
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)

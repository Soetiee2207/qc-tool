"""Web UI — `qctool ui`. Bấm là chạy.

Chỉ dùng thư viện chuẩn (`http.server`) để không thêm phụ thuộc: tool này phải
cài được ở nơi khác mà không phải kéo theo cả một web framework.

Chạy:  qctool ui --port 8080
"""

from __future__ import annotations

import json
import mimetypes
import threading
import urllib.parse
import uuid
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from qctool import config as cfg_mod
from qctool import pipeline
from qctool.pipeline import PipelineConfig, run_pipeline

MAX_BODY = 2 * 1024 * 1024


@dataclass
class Job:
    """Một lượt chạy, có tiến trình để UI theo dõi."""

    id: str
    started_at: str
    stage: str = "queued"
    messages: list[str] = field(default_factory=list)
    done: bool = False
    result: dict | None = None
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def log(self, stage: str, message: str) -> None:
        with self.lock:
            self.stage = stage
            self.messages.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "id": self.id,
                "started_at": self.started_at,
                "stage": self.stage,
                "messages": list(self.messages),
                "done": self.done,
                "result": self.result,
                "error": self.error,
            }


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self) -> Job:
        job = Job(id=uuid.uuid4().hex[:12],
                  started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def latest(self) -> Job | None:
        with self._lock:
            if not self._jobs:
                return None
            return max(self._jobs.values(), key=lambda j: j.started_at)


STORE = JobStore()


def _start_job(cfg: PipelineConfig) -> Job:
    job = STORE.create()

    def worker() -> None:
        result = run_pipeline(cfg, on_progress=job.log)
        with job.lock:
            job.done = True
            if result.error:
                job.error = result.error
                job.stage = "error"
            else:
                job.stage = "done"
                job.result = {
                    "feature": result.feature,
                    "total_cases": result.total_cases,
                    "counts": result.counts,
                    "pass_rate": round(result.pass_rate, 1),
                    "report_path": str(result.report_path) if result.report_path else None,
                    "run_dir": str(result.run_dir) if result.run_dir else None,
                    "xlsx_path": str(result.xlsx_path) if result.xlsx_path else None,
                    "testcases_path": str(result.testcases_path) if result.testcases_path else None,
                    "requirements_path": str(result.requirements_path) if result.requirements_path else None,
                    "gaps": (result.generated_report.gaps if result.generated_report else {}),
                    "needs_mapping": len(result.generated_report.needs_mapping)
                    if result.generated_report else 0,
                    "skipped": [],
                }

    threading.Thread(target=worker, daemon=True).start()
    return job


# ── Trang HTML ───────────────────────────────────────────────────────────────
PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>qc-tool — Tự động hoá QC</title>
<style>
  :root { --blue:#1f4e79; --orange:#9c5700; --green:#1a7f37; --red:#b91c1c;
          --grey:#6b7280; --line:#e5e7eb; --bg:#f9fafb; }
  * { box-sizing:border-box; }
  body { font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
         margin:0; background:var(--bg); color:#111827; line-height:1.5; }
  header { background:var(--blue); color:#fff; padding:18px 28px; }
  header h1 { margin:0; font-size:19px; font-weight:600; }
  header p { margin:4px 0 0; font-size:13px; opacity:.85; }
  main { max-width:900px; margin:0 auto; padding:24px 20px 60px; }
  .card { background:#fff; border:1px solid var(--line); border-radius:10px;
          padding:20px 22px; margin-bottom:18px; }
  .card h2 { margin:0 0 4px; font-size:15px; color:var(--blue); }
  .card .hint { font-size:12.5px; color:var(--grey); margin:0 0 16px; }
  label { display:block; font-size:13px; font-weight:600; margin:12px 0 5px; }
  label .opt { font-weight:400; color:var(--grey); font-size:12px; }
  input, select { width:100%; padding:9px 11px; border:1px solid #d1d5db;
         border-radius:7px; font-size:13.5px; font-family:inherit; background:#fff; }
  input:focus, select:focus { outline:2px solid var(--blue); outline-offset:-1px; }
  .row { display:flex; gap:14px; }
  .row > div { flex:1; }
  button { background:var(--blue); color:#fff; border:0; border-radius:7px;
           padding:11px 22px; font-size:14px; font-weight:600; cursor:pointer;
           font-family:inherit; }
  button:hover { background:#16395a; }
  button:disabled { background:#9ca3af; cursor:not-allowed; }
  button.ghost { background:#fff; color:var(--blue); border:1px solid var(--blue);
                 padding:8px 16px; font-size:13px; }
  button.ghost:hover { background:#eff6ff; }
  #log { background:#0f172a; color:#cbd5e1; font-family:ui-monospace,Menlo,monospace;
         font-size:12.5px; padding:14px 16px; border-radius:8px; max-height:340px;
         overflow-y:auto; white-space:pre-wrap; display:none; line-height:1.65; }
  #log.on { display:block; }
  .stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(110px,1fr));
           gap:12px; margin:16px 0 4px; }
  .stat { background:var(--bg); border:1px solid var(--line); border-radius:8px;
          padding:12px 14px; }
  .stat .n { font-size:23px; font-weight:700; line-height:1.2; }
  .stat .k { font-size:11.5px; color:var(--grey); text-transform:uppercase;
             letter-spacing:.03em; margin-top:2px; }
  .n.pass { color:var(--green); } .n.fail { color:var(--red); }
  .n.block { color:var(--orange); }
  .banner { border-radius:8px; padding:12px 15px; font-size:13.5px; margin:14px 0; }
  .banner.err { background:#fef2f2; border:1px solid #fecaca; color:#991b1b; }
  .banner.ok { background:#f0fdf4; border:1px solid #bbf7d0; color:#166534; }
  .links a { display:inline-block; margin:6px 10px 0 0; font-size:13px;
             color:var(--blue); text-decoration:none; font-weight:600; }
  .links a:hover { text-decoration:underline; }
  .dot { display:inline-block; width:8px; height:8px; border-radius:50%;
         background:var(--orange); margin-right:7px; animation:pulse 1.1s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.25} }
  code { background:#f3f4f6; padding:1px 5px; border-radius:4px; font-size:12.5px; }
</style>
</head>
<body>
<header>
  <h1>qc-tool — Tự động hoá QC</h1>
  <p>Tài liệu + OpenAPI + môi trường &rarr; testcase &rarr; chạy &rarr; báo cáo</p>
</header>
<main>
  <form id="form">
    <div class="card">
      <h2>1. Đầu vào</h2>
      <p class="hint">Đưa ít nhất một nguồn. Tài liệu sinh case từ requirement,
         OpenAPI sinh case kỹ thuật (đầy đủ hơn).</p>
      <label>Thư mục tài liệu <span class="opt">— chứa urd.md và srs.md</span></label>
      <input name="docs_dir" placeholder="/đường/dẫn/tới/docs/login-sso">
      <label>File OpenAPI <span class="opt">— .yaml hoặc .json</span></label>
      <input name="openapi" placeholder="/đường/dẫn/tới/openapi.yaml">
      <div class="row">
        <div>
          <label>Tên feature</label>
          <input name="feature" value="login-sso" required>
        </div>
        <div>
          <label>Module <span class="opt">(tuỳ chọn)</span></label>
          <input name="module" placeholder="AUTH">
        </div>
      </div>
    </div>

    <div class="card">
      <h2>2. Môi trường cần test</h2>
      <p class="hint">Để trống thì chỉ sinh testcase, không chạy.</p>
      <label>Địa chỉ API</label>
      <input name="base_url" placeholder="https://dev-qc-portal.datafactory.fit">
      <label>Link webapp <span class="opt">— bật test UI/UX bằng trình duyệt thật</span></label>
      <input name="web_url" placeholder="https://dev-qc-portal.datafactory.fit">
      <div class="row">
        <div>
          <label>Cách xác thực</label>
          <select name="auth_mode">
            <option value="token">Dán sẵn token</option>
            <option value="browser">Đăng nhập qua trình duyệt</option>
            <option value="password">Tên đăng nhập + mật khẩu (OIDC)</option>
            <option value="manual" selected>Không xác thực</option>
          </select>
        </div>
        <div>
          <label>Timeout (giây)</label>
          <input name="timeout_seconds" type="number" value="30" min="1">
        </div>
      </div>
      <label>Bearer token</label>
      <input name="bearer_token" placeholder="eyJhbGciOi…" autocomplete="off">
      <div class="row">
        <div>
          <label>Tên đăng nhập</label>
          <input name="username" autocomplete="off">
        </div>
        <div>
          <label>Mật khẩu</label>
          <input name="password" type="password" autocomplete="off">
        </div>
      </div>
      <label style="display:flex;align-items:center;gap:8px;font-weight:400;margin-top:14px">
        <input type="checkbox" name="verify_ssl" checked style="width:auto">
        Kiểm tra chứng chỉ SSL
      </label>
      <label style="display:flex;align-items:center;gap:8px;font-weight:400">
        <input type="checkbox" name="skip_run" style="width:auto">
        Chỉ sinh testcase, không chạy
      </label>
    </div>

    <div class="card">
      <h2>3. Test UI/UX</h2>
      <p class="hint">Chỉ dùng khi đã điền «Link webapp». Bỏ trống = chạy như cũ.</p>
      <div class="row">
        <div>
          <label>Chạy lại khi hỏng</label>
          <select name="ui_retry">
            <option value="0" selected>Không chạy lại</option>
            <option value="1">1 lần</option>
            <option value="2">2 lần</option>
          </select>
        </div>
        <div>
          <label>Bằng chứng</label>
          <select name="ui_evidence">
            <option value="on-fail" selected>Khi test hỏng</option>
            <option value="always">Mọi test</option>
            <option value="off">Không lưu</option>
          </select>
        </div>
      </div>
      <label style="display:flex;align-items:center;gap:8px;font-weight:400;margin-top:14px">
        <input type="checkbox" name="ui_trace" style="width:auto">
        Lưu trace Playwright <span class="opt">— xem lại từng bước bằng trace viewer</span>
      </label>
      <label style="display:flex;align-items:center;gap:8px;font-weight:400">
        <input type="checkbox" name="ui_axe" style="width:auto">
        Quét accessibility (axe-core)
      </label>
      <label style="display:flex;align-items:center;gap:8px;font-weight:400">
        <input type="checkbox" name="ui_headless" checked style="width:auto">
        Chạy trình duyệt ẩn <span class="opt">— bỏ tick để xem tận mắt</span>
      </label>
      <label style="display:flex;align-items:center;gap:8px;font-weight:400">
        <input type="checkbox" name="soft_assert" style="width:auto">
        Kiểm tra mềm <span class="opt">— sai không dừng case, chạy hết để thấy mọi lỗi</span>
      </label>
    </div>

    <button type="submit" id="go">Chạy QC</button>
  </form>

  <div class="card" id="progress" style="display:none">
    <h2 id="ptitle">Đang chạy…</h2>
    <p class="hint" id="pstage"></p>
    <div id="log"></div>
    <div id="out"></div>
  </div>
</main>
<script>
const form = document.getElementById('form');
const go = document.getElementById('go');
const progress = document.getElementById('progress');
const logBox = document.getElementById('log');
const out = document.getElementById('out');
const ptitle = document.getElementById('ptitle');
const pstage = document.getElementById('pstage');
let timer = null;

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  go.disabled = true; go.textContent = 'Đang chạy…';
  out.innerHTML = ''; logBox.textContent = ''; logBox.classList.add('on');
  progress.style.display = 'block';
  ptitle.innerHTML = '<span class="dot"></span>Đang chạy…';
  pstage.textContent = '';
  progress.scrollIntoView({behavior:'smooth', block:'nearest'});

  const fd = new FormData(form);
  const payload = {};
  for (const [k, v] of fd.entries()) payload[k] = v;
  payload.verify_ssl = fd.has('verify_ssl');
  payload.skip_run = fd.has('skip_run');

  let res;
  try {
    res = await fetch('/api/run', {method:'POST', headers:{'Content-Type':'application/json'},
                                   body: JSON.stringify(payload)});
  } catch (err) {
    fail('Không gọi được server: ' + err.message); return;
  }
  if (!res.ok) { const t = await res.text(); fail(t); return; }
  const {job_id} = await res.json();
  timer = setInterval(() => poll(job_id), 900);
});

async function poll(id) {
  let s;
  try { s = await (await fetch('/api/jobs/' + id)).json(); }
  catch (e) { return; }
  logBox.textContent = s.messages.join('\\n');
  logBox.scrollTop = logBox.scrollHeight;
  pstage.textContent = s.stage;
  if (s.done) { clearInterval(timer); finish(s); }
}

function fail(msg) {
  clearInterval(timer); go.disabled = false; go.textContent = 'Chạy QC';
  ptitle.textContent = 'Lỗi';
  out.innerHTML = '<div class="banner err">' + escapeHtml(msg) + '</div>';
}

function finish(s) {
  go.disabled = false; go.textContent = 'Chạy lại';
  if (s.error) { fail(s.error); return; }
  const r = s.result;
  ptitle.textContent = 'Kết quả';
  let html = '';
  if (r.counts) {
    const c = r.counts;
    html += '<div class="stats">'
      + stat(r.total_cases, 'Tổng test', '')
      + stat(c.Pass, 'Đạt', 'pass')
      + stat(c.Fail, 'Lỗi', 'fail')
      + stat(c.Blocked, 'Bị chặn', 'block')
      + stat((r.pass_rate ?? 0) + '%', 'Tỉ lệ đạt', '')
      + '</div>';
  } else {
    html += '<div class="stats">' + stat(r.total_cases, 'Testcase đã sinh', '') + '</div>';
  }
  const gapTotal = Object.values(r.gaps || {}).reduce((a, b) => a + b.length, 0);
  if (gapTotal || r.needs_mapping) {
    html += '<div class="banner ok">' + gapTotal + ' requirement chưa có testcase'
         + (r.needs_mapping ? ' · ' + r.needs_mapping + ' case cần map trước khi chạy' : '')
         + '</div>';
  }
  html += '<div class="links">';
  if (r.report_path) html += link('/api/download?path=' + encodeURIComponent(r.report_path), 'Báo cáo (.md)');
  if (r.xlsx_path)   html += link('/api/download?path=' + encodeURIComponent(r.xlsx_path), 'Testcase (.xlsx)');
  if (r.testcases_path) html += link('/api/download?path=' + encodeURIComponent(r.testcases_path), 'Testcase (.yaml)');
  if (r.run_dir)     html += link('/api/download?path=' + encodeURIComponent(r.run_dir + '/results.csv'), 'Kết quả (.csv)');
  if (r.run_dir)     html += link('/api/download?path=' + encodeURIComponent(r.run_dir + '/junit.xml'), 'JUnit XML');
  html += '</div>';
  out.innerHTML = html;
}

function stat(n, k, cls) {
  return '<div class="stat"><div class="n ' + cls + '">' + (n ?? 0) + '</div>'
       + '<div class="k">' + k + '</div></div>';
}
function link(href, text) { return '<a href="' + href + '">' + text + ' ↓</a>'; }
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, m =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "qc-tool"

    def log_message(self, fmt, *args) -> None:
        if self.path.startswith("/api/"):
            print(f"  {self.command} {self.path}")

    # ── Định tuyến ──────────────────────────────────────────────────────────
    def do_GET(self) -> None:                       # noqa: N802
        path = urllib.parse.urlparse(self.path).path

        if path in ("/", "/index.html"):
            return self._html(PAGE)

        if path.startswith("/api/jobs/"):
            job = STORE.get(path.rsplit("/", 1)[-1])
            if not job:
                return self._json(404, {"error": "không tìm thấy lượt chạy"})
            return self._json(200, job.snapshot())

        if path == "/api/config":
            env = cfg_mod.load_config()
            return self._json(200, {
                "base_url": env.base_url,
                "auth_mode": env.auth_mode,
                "username": env.username,
                "oidc_issuer": env.oidc_issuer,
            })

        if path == "/api/download":
            return self._download()

        return self._json(404, {"error": f"không có đường dẫn {path}"})

    def do_POST(self) -> None:                      # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path != "/api/run":
            return self._json(404, {"error": f"không có đường dẫn {path}"})

        try:
            payload = self._read_json()
            cfg = self._to_config(payload)
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})

        job = _start_job(cfg)
        return self._json(202, {"job_id": job.id})

    # ── Tiện ích ────────────────────────────────────────────────────────────
    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        if length > MAX_BODY:
            raise ValueError("Dữ liệu gửi lên quá lớn")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON không hợp lệ: {exc}") from exc

    def _to_config(self, p: dict) -> PipelineConfig:
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

        try:
            retry = max(0, min(int(p.get("ui_retry") or 0), 3))
        except (TypeError, ValueError):
            retry = 0

        feature = (p.get("feature") or "feature").strip()
        return PipelineConfig(
            docs_dir=docs_dir,
            openapi=openapi,
            feature=feature,
            # Lượt chạy từ web chưa gắn project: gom vào projects/web/<feature>/ để
            # cùng bố cục artifacts theo bước như CLI, không rải ra thư mục gốc.
            out_dir=pipeline.WEB_ROOT / Path(feature).name / "artifacts",
            module=(p.get("module") or "").strip() or None,
            base_url=base_url,
            web_url=web_url,
            auth_mode=auth_mode,
            username=(p.get("username") or "").strip() or None,
            password=p.get("password") or None,
            bearer_token=(p.get("bearer_token") or "").strip() or None,
            timeout_seconds=max(1, timeout),
            verify_ssl=bool(p.get("verify_ssl", True)),
            skip_run=bool(p.get("skip_run", False)),
            created_by=(p.get("created_by") or "qc-tool").strip(),
            headless=bool(p.get("ui_headless", True)),
            ui_retry=retry,
            ui_evidence=str(p.get("ui_evidence") or "on-fail"),
            ui_trace=bool(p.get("ui_trace", False)),
            ui_axe=bool(p.get("ui_axe", False)),
            soft_assert=bool(p.get("soft_assert", False)),
        )

    def _download(self) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        raw = (query.get("path") or [""])[0]
        if not raw:
            return self._json(400, {"error": "thiếu tham số `path`"})

        target = Path(raw).expanduser()
        # Chỉ cho tải file trong thư mục làm việc — không để lộ file hệ thống.
        try:
            root = Path.cwd().resolve()
            resolved = target.resolve()
            resolved.relative_to(root)
        except (ValueError, OSError):
            return self._json(403, {"error": "chỉ được tải file trong thư mục dự án"})

        if not resolved.is_file():
            return self._json(404, {"error": f"không tìm thấy file: {raw}"})

        ctype = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        data = resolved.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", f'attachment; filename="{resolved.name}"')
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
    print("  Mở trình duyệt, điền đường dẫn tài liệu và OpenAPI, bấm Chạy QC.")
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

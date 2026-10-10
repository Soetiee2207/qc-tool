"""API giả để chạy thử executor — chỉ dùng thư viện chuẩn.

Mục đích: chứng minh runner thật sự chạy được testcase, không cần chờ spec thật.
Server này cài đặt ĐÚNG contract trong `projects/demo/task-manager/openapi.yaml`
— nhưng **cố ý có bug**, để báo cáo có cả Pass lẫn Fail. Một mock hoàn hảo thì
không chứng minh được gì: không biết runner có phát hiện lỗi hay không.

    uv run python -m tests.mock_server --port 8099

Bug cài sẵn:
  1. `POST /projects` trả 200 thay vì 201.
  2. `DELETE /projects/{id}` trả 204 kể cả khi dự án còn việc chưa xong (đúng ra 409).
  3. `/health` chậm 120ms, vượt ngưỡng p95 = 50ms khai trong spec.
  4. `GET /projects` bỏ sót field `page_size` trong response.

Trang HTML (`/` và `/ui/...`) phục vụ cho test UI/UX bằng Playwright. Trang này
cũng có bug cài sẵn — nhưng theo kiểu bug **giao diện**, thứ mà test API không
thể thấy:
  5. Nút «Lưu» không bao giờ bị vô hiệu hoá dù ô tên trống (đúng ra phải khoá).
  6. Đổi trạng thái dự án xong **không** cập nhật nhãn trên màn hình — bảng vẫn
     hiện trạng thái cũ cho tới khi tải lại (bug state của SPA).
  7. Ô «Tên dự án» trong dialog không được focus khi mở (lỗi accessibility).
  8. `/ui/loi-js` cố ý ném lỗi JavaScript để thử `assert.console_clean`.

Ghi chú kỹ thuật: `Handler` tắt thuật toán Nagle. Không tắt thì mỗi request thứ
hai trở đi trên một kết nối keep-alive chậm thêm ~40ms (Nagle + delayed-ACK của
`http.server` khi trả lời theo nhiều lần ghi). Con số đó đủ để làm hỏng mọi
ngưỡng hiệu năng trong test, và nó là **độ trễ của server giả**, không phải của
sản phẩm.
"""

from __future__ import annotations

import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PROJECT = {
    "id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
    "name": "Dự án mẫu",
    "description": "Mô tả",
    "status": "active",
    "priority": 2,
    "tags": ["a"],
    "owner": {
        "id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
        "name": "Nguyễn Văn A",
        "email": "a@example.com",
    },
    "created_at": "2026-01-01T00:00:00Z",
}

TASK = {
    "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "title": "Việc mẫu",
    "status": "todo",
    "estimate_hours": 4,
    "assignee_id": None,
    "tags": [],
    "created_at": "2026-01-01T00:00:00Z",
}

KNOWN_PREFIX = "/api/v1"

# ── Trang HTML để test UI/UX ────────────────────────────────────────────────
# Dựng bằng HTML thuần, không phụ thuộc framework: test phải chạy được offline.
# Mọi element đều có `data-testid` — đây cũng là ví dụ để thấy vì sao tool ưu
# tiên test id hơn nhãn hiển thị.
PAGE_INDEX = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><title>Trang chủ — mock</title></head>
<body>
  <header>
    <h1>Bảng điều khiển</h1>
    <nav>
      <a href="/ui/du-an" data-testid="nav-projects">Dự án</a>
      <a href="/ui/loi-js" data-testid="nav-broken">Trang lỗi JS</a>
    </nav>
  </header>
  <main>
    <p data-testid="welcome">Xin chào</p>
    <button data-testid="btn-add" type="button" onclick="moDialog()">Thêm dự án</button>
    <button data-testid="btn-disabled-demo" type="button" disabled>Không bấm được</button>
  </main>
  <div id="dialog" data-testid="dialog-add" style="display:none">
    <h2>Thêm dự án mới</h2>
    <label for="ten">Tên dự án</label>
    <input id="ten" name="ten" data-testid="input-name">
    <!-- BUG 5: nút Lưu đáng ra phải bị khoá khi ô tên trống -->
    <button data-testid="btn-save" type="button" onclick="luu()">Lưu</button>
  </div>
  <script>
    function moDialog() {
      document.getElementById('dialog').style.display = 'block';
      // BUG 7: đúng ra phải focus ô nhập đầu tiên khi mở dialog
    }
    function luu() {
      var ten = document.getElementById('ten').value;
      document.getElementById('welcome').textContent = 'Đã lưu: ' + ten;
    }
  </script>
</body></html>
"""

PAGE_PROJECTS = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><title>Dự án — mock</title></head>
<body>
  <h1>Danh sách dự án</h1>
  <table>
    <thead><tr><th>Mã</th><th>Tên</th><th>Trạng thái</th></tr></thead>
    <tbody>
      <tr data-testid="row-1"><td>D-01</td><td>Dự án mẫu</td>
        <td data-testid="status-1">active</td></tr>
      <tr data-testid="row-2"><td>D-02</td><td>Việc mẫu</td>
        <td data-testid="status-2">todo</td></tr>
    </tbody>
  </table>
  <button data-testid="btn-toggle" type="button" onclick="doiTrangThai()">Đổi trạng thái</button>
  <p data-testid="empty-hint" style="display:none">Không có dự án nào</p>
  <script>
    function doiTrangThai() {
      // BUG 6: đổi dữ liệu trong bộ nhớ nhưng KHÔNG cập nhật DOM — bảng vẫn
      // hiện trạng thái cũ. Đây là bug chỉ test UI mới thấy.
      window.__state = 'done';
    }
  </script>
</body></html>
"""

PAGE_JS_ERROR = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><title>Trang lỗi — mock</title></head>
<body>
  <h1>Trang có lỗi JavaScript</h1>
  <p data-testid="note">Trang này cố ý ném lỗi.</p>
  <script>
    // BUG 8: lỗi JS thật, để thử assert.console_clean
    window.setTimeout(function () {
      throw new Error('Lỗi cố ý trong mock server');
    }, 50);
  </script>
</body></html>
"""

PAGES = {
    "/": PAGE_INDEX,
    "/ui/du-an": PAGE_PROJECTS,
    "/ui/loi-js": PAGE_JS_ERROR,
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # Xem ghi chú ở docstring: không tắt Nagle thì kết nối keep-alive cộng thêm
    # ~40ms mỗi request — đủ để mọi ngưỡng hiệu năng trong test báo sai.
    disable_nagle_algorithm = True

    def log_message(self, *_args) -> None:
        pass                                    # im lặng khi chạy test

    # ── Định tuyến ──────────────────────────────────────────────────────────
    def _route(self, method: str):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # Trang HTML phục vụ test UI — chỉ thư viện chuẩn, không phụ thuộc gì.
        if method == "GET" and path in PAGES:
            return self._html(PAGES[path])

        if path.startswith(KNOWN_PREFIX):
            path = path[len(KNOWN_PREFIX):]

        if path == "/health" and method == "GET":
            time.sleep(0.12)                    # BUG 3: chậm hơn ngưỡng 50ms
            return self._json(200, {"status": "ok", "version": "2.3.0"})

        if path == "/projects" and method == "GET":
            if not self._authed():
                return self._unauthorized()
            # BUG 4: thiếu `page_size`
            return self._json(200, {"items": [PROJECT], "total": 1, "page": 1})

        if path == "/projects" and method == "POST":
            if not self._authed():
                return self._unauthorized()
            parsed, body = self._body()
            if not parsed:
                return self._json(400, {"code": "BAD_REQUEST", "message": "Body không đọc được"})
            for field in ("name", "owner_id"):
                if field not in body:
                    return self._json(422, {
                        "code": "VALIDATION_ERROR",
                        "message": f"Thiếu field bắt buộc: {field}",
                        "details": [{"field": field, "reason": "required"}],
                    })
            name = body.get("name", "")
            if not (3 <= len(name) <= 80):
                return self._json(422, {"code": "VALIDATION_ERROR",
                                        "message": "`name` phải dài 3–80 ký tự"})
            return self._json(200,                          # BUG 1: phải là 201
                              {**PROJECT, "name": name})

        m = re.fullmatch(r"/projects/([^/]+)", path)
        if m and method == "GET":
            if not self._authed():
                return self._unauthorized()
            if m.group(1) != PROJECT["id"]:
                return self._json(404, {"code": "NOT_FOUND", "message": "Không tìm thấy dự án"})
            return self._json(200, PROJECT)

        if m and method == "DELETE":
            if not self._authed():
                return self._unauthorized()
            if m.group(1) != PROJECT["id"]:
                return self._json(404, {"code": "NOT_FOUND", "message": "Không tìm thấy dự án"})
            return self._no_content()                       # BUG 2: phải là 409 nếu còn việc

        m = re.fullmatch(r"/projects/([^/]+)/tasks", path)
        if m and method == "POST":
            if not self._authed():
                return self._unauthorized()
            if m.group(1) != PROJECT["id"]:
                return self._json(404, {"code": "NOT_FOUND", "message": "Không tìm thấy dự án"})
            parsed, body = self._body()
            if not parsed:
                return self._json(400, {"code": "BAD_REQUEST", "message": "Body không đọc được"})
            if "title" not in body:
                return self._json(422, {"code": "VALIDATION_ERROR", "message": "Thiếu `title`"})
            title = body["title"]
            if not (1 <= len(title) <= 200):
                return self._json(422, {"code": "VALIDATION_ERROR",
                                        "message": "`title` phải dài 1–200 ký tự"})
            hours = body.get("estimate_hours")
            if hours is not None and not (0 <= hours <= 1000):
                return self._json(422, {"code": "VALIDATION_ERROR",
                                        "message": "`estimate_hours` phải trong 0–1000"})
            return self._json(201, {**TASK, "title": title,
                                    "estimate_hours": hours if hours is not None else 0})

        if m and method == "GET":
            if not self._authed():
                return self._unauthorized()
            if m.group(1) != PROJECT["id"]:
                return self._json(404, {"code": "NOT_FOUND", "message": "Không tìm thấy dự án"})
            return self._json(200, [TASK])

        return self._json(404, {"code": "NOT_FOUND", "message": f"Không có route {method} {path}"})

    # ── Tiện ích ────────────────────────────────────────────────────────────
    def _authed(self) -> bool:
        header = self.headers.get("Authorization", "")
        return header.startswith("Bearer ") and len(header) > len("Bearer ")

    def _body(self):
        """Đọc body. Trả `(parse_ok, data)`.

        Phân biệt **không parse được** (→ 400) với **parse được nhưng thiếu field**
        (→ 422). Gộp hai thứ này làm một là sai với contract khai trong spec, và
        khiến case kiểm tra 400 không bao giờ chạm được nhánh đúng.
        """
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return False, None
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            return True, json.loads(raw)
        except json.JSONDecodeError:
            return False, None

    def _send(self, code: int, payload: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def _json(self, code: int, data) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json")

    def _html(self, body: str) -> None:
        self._send(200, body.encode("utf-8"), "text/html; charset=utf-8")

    def _no_content(self) -> None:
        self._send(204, b"", "application/json")

    def _unauthorized(self) -> None:
        self._json(401, {"code": "UNAUTHORIZED",
                         "message": "Invalid or missing bearer token"})

    def _head(self) -> None:
        self._send(200, b"", "application/json")

    do_GET = lambda self: self._route("GET")          # noqa: E731
    do_POST = lambda self: self._route("POST")        # noqa: E731
    do_PATCH = lambda self: self._route("PATCH")      # noqa: E731
    do_DELETE = lambda self: self._route("DELETE")    # noqa: E731
    do_HEAD = lambda self: self._head()               # noqa: E731


def create_server(port: int = 0, prefix: str = KNOWN_PREFIX) -> ThreadingHTTPServer:
    """Dựng server. `port=0` → hệ điều hành chọn cổng trống."""
    global KNOWN_PREFIX
    KNOWN_PREFIX = prefix
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="API giả để chạy thử qc-tool")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--prefix", default="/api/v1",
                        help="Tiền tố đường dẫn (mặc định /api/v1)")
    args = parser.parse_args()

    server = create_server(args.port, args.prefix)
    host, port = server.server_address[:2]
    print(f"API giả đang chạy tại http://{host}:{port}{args.prefix}")
    print(f"Trang web giả (test UI/UX): http://{host}:{port}/")
    print("  Có 4 bug API + 4 bug giao diện cài sẵn — xem docstring đầu file")
    print("  Ctrl+C để dừng")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

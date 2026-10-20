"""Chế độ chat: agent điều phối chỉ lập kế hoạch từ AC có thật; chạy chỉ khi người dùng bấm."""
import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from qctool.web import chat

URD = """# URD — Demo · Giỏ hàng

### US-001 — Khách mở giỏ hàng

**As a** khách hàng
**I want** xem giỏ hàng
**So that** thanh toán

**Acceptance Criteria**

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-001-1 | Phiên anonymous chưa đăng nhập | Mở /cart | URL chuyển tới /login |
| AC-001-2 | Tài khoản customer đang hoạt động từ fixture active_user | Mở /cart | Hiển thị Giỏ hàng |
| AC-001-3 | ⚠ GHI DỮ LIỆU THẬT. Phiên đã đăng nhập | Bấm Đặt hàng | Hiển thị Đặt hàng thành công |
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in ("QCTOOL_USERNAME", "QCTOOL_PASSWORD", "QCTOOL_LLM_MODEL", "QCTOOL_LLM_API_KEY"):
        monkeypatch.setenv(key, "")
    root = tmp_path / "projects" / "shop"
    (root / "cart").mkdir(parents=True)
    (root / "project.yaml").write_text("web: https://shop.test\n", encoding="utf-8")
    (root / "cart" / "qctool.yaml").write_text("llm: true\n", encoding="utf-8")
    (root / "cart" / "urd.md").write_text(URD, encoding="utf-8")
    chat._CACHE.clear()
    return "shop"


class FakeLLM:
    """Trả lần lượt các response dựng sẵn; ghi lại messages model nhận được."""
    def __init__(self, responses):
        self.responses, self.seen = list(responses), []

    def chat(self, messages, tools, **kw):
        self.seen.append(json.loads(json.dumps(messages)))
        return self.responses.pop(0)


def _call(name, args, cid="c1", **extra):
    return {"role": "assistant", "content": None, **extra,
            "tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def _wait(project, sid, cond=lambda s: not s["busy"]):
    for _ in range(100):
        session = chat.load(project, sid)
        if cond(session):
            return session
        time.sleep(0.05)
    raise AssertionError("timeout")


PLAN = {"scope": "requirement", "title": "Giỏ hàng", "understanding": "Kiểm chặn anonymous",
        "items": [{"feature": "cart", "acs": ["AC-cart-001-1", "001-2"], "why": "chặn truy cập"}]}


def test_plan_accepts_only_real_acs(project):
    session = chat.create(project)
    with pytest.raises(chat.ChatError, match="không có AC 009-9"):
        chat.call_tool(session, "propose_test_plan", {**PLAN, "items": [{"feature": "cart", "acs": ["009-9"], "why": ""}]})
    with pytest.raises(chat.ChatError, match="Không có feature"):
        chat.call_tool(session, "propose_test_plan", {**PLAN, "items": [{"feature": "nope", "acs": [], "why": ""}]})
    result, _ = chat.call_tool(session, "propose_test_plan", PLAN)
    plan = session["messages"][-1]["plan"]
    assert result["ok"] and plan["items"][0]["acs"] == ["001-1", "001-2"]
    # 001-2 cần đăng nhập mà .env chưa có tài khoản → báo trước, không để người dùng tưởng Fail
    assert any("đăng nhập" in w for w in plan["warnings"])


def test_whole_feature_plan_warns_about_writes(project):
    session = chat.create(project)
    chat.call_tool(session, "propose_test_plan", {**PLAN, "scope": "flow",
                                                  "items": [{"feature": "cart", "acs": [], "why": ""}]})
    plan = session["messages"][-1]["plan"]
    assert plan["items"][0]["ac_count"] == 3 and plan["items"][0]["acs"] == []
    assert any("001-3" in w and "thủ công" in w for w in plan["warnings"])
    assert "độc lập" in plan["warnings"][0]       # flow không giả vờ là case E2E


def test_search_folds_vietnamese(project):
    hits, _ = chat.call_tool(chat.create(project), "search_requirements", {"query": "gio hang"})
    assert {h["id"] for h in hits["hits"]} >= {"001-2"}


def test_send_runs_tools_and_never_stores_reasoning(project):
    session = chat.create(project)
    llm = FakeLLM([_call("propose_test_plan", PLAN, reasoning_content="BÍ-MẬT-SUY-NGHĨ"),
                   {"role": "assistant", "content": "Đã lập P1 — bấm Chạy."}])
    chat.send(project, session["id"], "test chặn anonymous ở giỏ hàng", lambda: llm)
    done = _wait(project, session["id"])
    roles = [m["role"] for m in done["messages"]]
    assert roles == ["user", "tool", "plan", "assistant"]
    assert done["messages"][2]["plan"]["status"] == "proposed"      # chưa chạy gì
    raw = chat._path(project, session["id"]).read_text(encoding="utf-8")
    assert "BÍ-MẬT-SUY-NGHĨ" not in raw
    assert "llm" not in chat.view(done)


def test_llm_error_is_shown_not_hung(project):
    session = chat.create(project)

    def broken():
        raise RuntimeError("không có key")
    chat.send(project, session["id"], "xin chào", broken)
    done = _wait(project, session["id"])
    assert done["messages"][-1]["level"] == "error" and not done["busy"]


def test_plan_runs_only_on_start_and_reports_back(project):
    session = chat.create(project)
    chat.call_tool(session, "propose_test_plan", PLAN)
    chat._save(session)
    calls = []

    def run_feature(config, only, on_start):
        calls.append((config, only))
        on_start("projects/shop/cart/artifacts")
        return {"artifacts": "projects/shop/cart/artifacts", "error": None,
                "result": {"counts": {"Pass": 1, "Fail": 1}}}
    chat.start_plan(project, session["id"], "P1", run_feature)
    done = _wait(project, session["id"], lambda s: s["messages"][-1]["role"] == "note")
    plan = next(m["plan"] for m in done["messages"] if m["role"] == "plan")
    assert calls == [("projects/shop/cart/qctool.yaml", ["001-1", "001-2"])]
    assert plan["status"] == "done" and plan["totals"] == {"Pass": 1, "Fail": 1}
    with pytest.raises(chat.ChatError):
        chat.cancel_plan(project, session["id"], "P1")
    # Tin nhắn kế tiếp: model được báo kế hoạch đã chạy, đánh dấu là hệ thống viết
    llm = FakeLLM([{"role": "assistant", "content": "ok"}])
    chat.send(project, session["id"], "kết quả sao?", lambda: llm)
    _wait(project, session["id"])
    sent = [m["content"] for m in llm.seen[0] if m["role"] == "user"]
    assert any(c.startswith("[Thông báo hệ thống") and "Pass 1" in c for c in sent)


def test_upload_maps_names_and_creates_feature(project):
    out = chat.upload(project, "login", [{"name": "URD_Login v2.md", "content": URD}])
    assert out["saved"] == ["urd.md"] and out["feature"]["acs"] == 3
    assert chat.doc_name("Swagger-API.json") == "openapi.yaml"     # upload() đổi JSON → YAML
    with pytest.raises(Exception):
        chat.upload(project, "../etc", [{"name": "urd.md", "content": "x"}])


def test_feature_account_form_needs_role_then_writes_login_for(project):
    from qctool.web import setup
    # Project tạo từ web không có account.role → báo đúng chỗ, không phải lỗi fixture khó hiểu.
    with pytest.raises(setup.SetupError, match="vai trò tài khoản"):
        setup.save_feature_account(project, "cart", ["001-2"], {})
    form = setup.get_project(project)["form"]
    setup.save_project_form(project, {**form, "role": "customer"})
    out = setup.save_feature_account(project, "cart", ["001-2"], {"001-1": {"password": "SaiMatKhau123"}})
    acs = {a["short"]: a for a in out["acs"]}
    assert acs["001-2"]["login"] and not acs["001-1"]["login"]
    assert acs["001-1"]["test_values"] == {"password": "SaiMatKhau123"}


@pytest.fixture
def ui(project):
    from qctool.web.app import Handler
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://%s:%d" % server.server_address[:2]
    server.shutdown()
    server.server_close()


def _req(url, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                 method="GET" if data is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def test_http_chat_flow(ui, project, tmp_path):
    code, body = _req(ui + "/")
    assert code == 200 and "Trợ lý QC" in body
    assert "Chạy QC" in _req(ui + "/console")[1]
    code, body = _req(ui + "/api/chat/new", {"project": project})
    sid = json.loads(body)["id"]
    code, body = _req(ui + "/api/chat/account", {"username": "qa@shop.test", "password": "pw-123",
                                                 "project": project, "session": sid})
    assert code == 200
    saved = (tmp_path / "projects" / "shop" / "chat" / f"{sid}.json").read_text(encoding="utf-8")
    assert "pw-123" not in saved and "qa@shop.test" not in saved
    assert "QCTOOL_PASSWORD=pw-123" in (tmp_path / ".env").read_text(encoding="utf-8")
    code, body = _req(ui + "/api/chat/run", {"project": project, "id": sid, "plan": "P9"})
    assert code == 400 and "P9" in json.loads(body)["error"]
    code, _ = _req(ui + "/api/chat/session?project=shop&id=../../x")
    assert code == 400


def test_plan_passes_trace_opt_in_and_writes_summary(project):
    session = chat.create(project)
    chat.call_tool(session, "propose_test_plan", PLAN)
    chat._save(session)
    seen, summarized = [], []

    def run_feature(config, only, on_start, **options):
        seen.append(options)
        on_start("a")
        return {"artifacts": "a", "error": None, "exit_code": 0, "result": {"counts": {"Pass": 2}}}

    def summarize(runs, started):
        summarized.append([(c, r["exit_code"]) for c, r in runs])
        return "projects/shop/summary/x"
    chat.start_plan(project, session["id"], "P1", run_feature,
                    options={"trace_sensitive": True, "evil": 1}, summarize=summarize)
    done = _wait(project, session["id"], lambda s: s["messages"][-1]["role"] == "note")
    plan = next(m["plan"] for m in done["messages"] if m["role"] == "plan")
    assert seen == [{"trace_sensitive": True}]          # chỉ nhận đúng lựa chọn đã biết
    assert summarized == [[("projects/shop/cart/qctool.yaml", 0)]]
    assert plan["summary"] == "projects/shop/summary/x" and plan["options"] == {"trace_sensitive": True}


def test_project_summary_and_trace_open_guard(project, tmp_path):
    from qctool.web.app import _open_trace, _project_summary
    from qctool.summary import now
    art = tmp_path / "projects/shop/cart/artifacts"
    (art / "5-execute").mkdir(parents=True)
    started = now()
    (art / "run.json").write_text(json.dumps({"status": "done", "started_at": started.isoformat(timespec="seconds")}))
    (art / "5-execute/results.json").write_text(json.dumps({"results": [{"case_id": "TC_1", "status": "Pass"}]}))
    out = _project_summary([("projects/shop/cart/qctool.yaml", 0, str(art))], started)
    assert out and "summary.md" in {p.name for p in (tmp_path / out).iterdir()}
    assert _project_summary([("x/y.yaml", 0, str(art))], started) is None     # ad-hoc: không có project
    from qctool.web.setup import SetupError
    for bad in ("/etc/passwd", "projects/shop/cart/urd.md"):
        with pytest.raises(SetupError):
            _open_trace({"path": bad})

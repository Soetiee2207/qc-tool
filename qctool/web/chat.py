"""Chế độ chat: người dùng nói bằng ngôn ngữ tự nhiên, agent điều phối hiểu cần test phần nào.

Agent điều phối (orchestrator) KHÔNG viết testcase và KHÔNG tự chạy test. Nó chỉ:

1. đọc danh mục yêu cầu của project (feature → user story → AC) qua tool chỉ-đọc,
2. ánh xạ yêu cầu của người dùng ("test cả hệ thống", "test đăng nhập", "test luồng mua
   hàng") thành **kế hoạch** gồm các feature + mã AC có thật (`propose_test_plan` kiểm từng mã),
3. đọc kết quả lượt chạy từ đĩa khi được hỏi.

Kế hoạch chỉ chạy khi **người dùng bấm "Chạy"** trên giao diện (`start_plan`). Mỗi mục của kế
hoạch là đúng một lượt `qctool run <project> --<feature> --only …` (qua `run_feature` do
`web/app.py` truyền vào) — không có đường chạy nào chỉ tồn tại trong chat. Authoring agent,
gate, dry-run, safe mode giữ nguyên.

Luồng nghiệp vụ xuyên feature được chạy theo thứ tự các mục, nhưng **mỗi AC vẫn là một
testcase độc lập** (context trình duyệt riêng) — chưa có case E2E nối trạng thái giữa các AC.
Agent phải nói rõ điều đó, không được hứa hơn.

Phiên chat lưu ở `projects/<project>/chat/<id>.json` (projects/ gitignored). Không bao giờ chứa
mật khẩu/API key: tài khoản đi thẳng vào `.env` qua `setup.save_env`, tool chỉ thấy "đã đặt";
`reasoning_content` của model không được lưu (chỉ sống trong một lượt trả lời).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from qctool.web import setup

MAX_TURNS = 8            # số lần gọi LLM tối đa cho một tin nhắn người dùng
MAX_HISTORY = 60         # số message LLM giữ lại (cắt ở ranh giới tin nhắn người dùng)
WRITE_MARK = "GHI DỮ LIỆU THẬT"
LOGIN_HINTS = ("fixture active_user", "đăng nhập", "tài khoản customer")


class ChatError(ValueError):
    pass


# ── Danh mục yêu cầu ────────────────────────────────────────────────────────
_CACHE: dict[str, tuple[float, dict]] = {}


def _fold(text: str) -> str:
    """Bỏ dấu tiếng Việt để tìm "dang nhap" vẫn ra "Đăng nhập"."""
    text = unicodedata.normalize("NFD", str(text or "").lower()).replace("đ", "d")
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _title_of(folder: Path) -> str:
    urd = folder / "urd.md"
    if urd.is_file():
        for line in urd.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("# "):
                head = line[2:].strip()
                return re.split(r"\s+[·—]\s+", head)[-1].strip()
    return folder.name


def _feature_entry(project: str, feature: str) -> dict:
    folder = setup._feature_dir(project, feature)
    stamp = max((p.stat().st_mtime for p in folder.iterdir() if p.is_file()), default=0)
    key = folder.as_posix()
    if key in _CACHE and _CACHE[key][0] == stamp:
        return _CACHE[key][1]
    info = setup.get_feature(project, feature)
    stories: dict[str, dict] = {}
    try:
        from qctool import ingest
        doc = ingest.ingest_feature(folder, feature)
        for req in doc.get("requirements", []):
            if req.get("kind") == "user_story":
                stories[req["id"]] = {"id": req["source_ids"][0] if req.get("source_ids") else req["id"],
                                      "title": req.get("title", ""), "acs": []}
    except Exception:  # noqa: BLE001 — get_feature đã ghi cảnh báo đọc tài liệu
        pass
    acs = []
    for ac in info["acs"]:
        text = " ".join(str(ac.get(k) or "") for k in ("given", "when", "then"))
        entry = {"id": ac["short"], "story": (stories.get(ac.get("story") or "") or {}).get("id"),
                 "given": ac.get("given"), "when": ac.get("when"), "then": ac.get("then"),
                 "writes_data": WRITE_MARK in text,
                 "needs_login": ac["login"] or any(h in _fold(text) for h in map(_fold, LOGIN_HINTS))}
        acs.append(entry)
        if ac.get("story") in stories:
            stories[ac["story"]]["acs"].append(ac["short"])
    cfg = {}
    try:
        cfg = setup._load(folder / "qctool.yaml")
    except Exception:  # noqa: BLE001
        pass
    entry = {"feature": feature, "title": _title_of(folder), "docs": info["docs"],
             "openapi": (folder / "openapi.yaml").is_file(), "stories": list(stories.values()),
             "acs": acs, "write_mode": cfg.get("mode") == "write",
             "warnings": info["ingest_warnings"][:5], "config": (folder / "qctool.yaml").as_posix()}
    _CACHE[key] = (stamp, entry)
    return entry


def catalog(project: str) -> dict:
    folder = setup._project_dir(project)
    if not folder.is_dir():
        raise ChatError(f"Không có project {project}")
    proj = setup.get_project(project)
    form = proj.get("form") or {}
    features = [_feature_entry(project, f.parent.name) for f in sorted(folder.glob("*/qctool.yaml"))]
    env = {e["key"]: e for e in setup.get_env()}
    return {"project": project, "web": form.get("web"), "api": form.get("api"), "llm": form.get("llm"),
            "mode": form.get("mode", "safe"),
            "account_set": env["QCTOOL_USERNAME"]["set"] and env["QCTOOL_PASSWORD"]["set"],
            "features": features}


def _overview(cat: dict) -> dict:
    """Bản gọn đưa vào system prompt: đủ để chọn feature, không đủ để bịa AC."""
    return {"project": cat["project"], "web": cat["web"], "api": cat["api"], "mode": cat["mode"],
            "account_set": cat["account_set"],
            "features": [{"feature": f["feature"], "title": f["title"], "ac_count": len(f["acs"]),
                          "stories": [f"{s['id']} {s['title']}" for s in f["stories"]]}
                         for f in cat["features"]]}


# ── Tool của agent điều phối ────────────────────────────────────────────────
def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required, "additionalProperties": False}}}


TOOLS = [
    _fn("list_features", "Danh sách feature của project: tiêu đề, user story, số AC, tài liệu có sẵn.", {}, []),
    _fn("get_requirements", "Toàn bộ AC (Given/When/Then) của một feature. Gọi trước khi chọn AC cụ thể.",
        {"feature": {"type": "string"}}, ["feature"]),
    _fn("search_requirements", "Tìm AC theo từ khoá trên mọi feature (không phân biệt dấu). Dùng cho yêu cầu "
        "theo chức năng/luồng nằm rải nhiều feature.", {"query": {"type": "string"}}, ["query"]),
    _fn("propose_test_plan", "Đề xuất kế hoạch test để NGƯỜI DÙNG duyệt và bấm chạy. Không tự chạy. "
        "Mã AC phải lấy từ get_requirements/search_requirements; acs rỗng = toàn bộ AC của feature.",
        {"scope": {"type": "string", "enum": ["system", "feature", "requirement", "flow"],
                   "description": "system = cả hệ thống; feature = một/vài chức năng trọn vẹn; "
                                  "requirement = vài AC cụ thể; flow = luồng nghiệp vụ theo thứ tự"},
         "title": {"type": "string", "description": "Tên ngắn của kế hoạch, tiếng Việt"},
         "understanding": {"type": "string", "description": "Agent hiểu người dùng muốn kiểm gì, 1–3 câu"},
         "items": {"type": "array", "minItems": 1, "items": {"type": "object", "additionalProperties": False,
                   "properties": {"feature": {"type": "string"},
                                  "acs": {"type": "array", "items": {"type": "string"}},
                                  "why": {"type": "string", "description": "Vì sao chọn mục này / vai trò trong luồng"}},
                   "required": ["feature", "acs", "why"]}},
         "out_of_scope": {"type": "array", "items": {"type": "string"},
                          "description": "Phần người dùng yêu cầu nhưng tài liệu không có AC tương ứng"}},
        ["scope", "title", "understanding", "items"]),
    _fn("get_last_results", "Kết quả lượt chạy gần nhất của một feature (đọc từ đĩa): số Pass/Fail/Blocked/"
        "Not Executed và lý do của case không Pass.", {"feature": {"type": "string"}}, ["feature"]),
]

SYSTEM = """Bạn là trợ lý QC của qc-tool, nói tiếng Việt, ngắn gọn, thẳng thắn.

Nhiệm vụ: hiểu người dùng muốn test phần nào rồi lập KẾ HOẠCH TEST từ yêu cầu có trong tài liệu.
Phạm vi có thể là:
- system: cả hệ thống (mọi feature, mọi AC);
- feature: một hoặc vài chức năng trọn vẹn;
- requirement: vài AC cụ thể (vd "chỉ case sai mật khẩu");
- flow: luồng nghiệp vụ đi qua nhiều chức năng (vd đăng nhập → thêm giỏ → thanh toán) — xếp items theo đúng thứ tự các bước của luồng.

Quy tắc:
1. Chỉ dùng feature/mã AC có thật lấy từ tool. Không bịa AC, URL, dữ liệu. Phần người dùng muốn mà tài liệu không có → ghi vào out_of_scope và nói rõ.
2. Trước propose_test_plan với AC cụ thể, phải gọi get_requirements hoặc search_requirements. Yêu cầu cả hệ thống/cả feature thì dùng acs rỗng.
3. Yêu cầu mơ hồ đến mức có nhiều cách hiểu khác hẳn nhau → hỏi lại MỘT câu ngắn, kèm 2–3 lựa chọn cụ thể. Nếu chỉ hơi mơ hồ → chọn cách hiểu hợp lý nhất và nói rõ giả định trong understanding.
4. Bạn KHÔNG tự chạy test. Sau propose_test_plan, nói ngắn gọn kế hoạch gồm gì và nhắc người dùng bấm "▶ Chạy" trên thẻ kế hoạch. Không hứa kết quả.
5. Luồng nghiệp vụ: mỗi AC vẫn là một testcase độc lập (phiên trình duyệt riêng) chạy theo thứ tự, không phải một case E2E nối trạng thái — nói rõ khi lập plan flow.
6. AC có writes_data=true sẽ thành case thủ công ở chế độ safe (không ghi dữ liệu thật). AC needs_login cần tài khoản test; nếu account_set=false thì nhắc người dùng nhập tài khoản ở "Dữ liệu đầu vào".
7. Hỏi về kết quả → gọi get_last_results, chỉ nói số liệu có trong đó. Fail = sản phẩm sai so với tài liệu; Blocked = thiếu môi trường/dữ liệu, không phải lỗi sản phẩm; Not Executed = chưa chạy/thủ công.
8. Không bao giờ hỏi hay nhắc lại mật khẩu, API key trong chat.

Tổng quan project (mã AC chi tiết lấy qua tool):
"""


def _feature(cat: dict, name: str) -> dict:
    for f in cat["features"]:
        if f["feature"] == name:
            return f
    raise ChatError(f"Không có feature {name!r}. Có: {', '.join(f['feature'] for f in cat['features'])}")


def _short(raw: str, feature: str) -> str:
    return str(raw).strip().removeprefix("AC-").removeprefix(f"{feature}-")


def _search(cat: dict, query: str) -> list[dict]:
    words = [w for w in re.split(r"[^\w/]+", _fold(query)) if len(w) >= 2]
    if not words:
        raise ChatError("Từ khoá rỗng.")
    hits = []
    for f in cat["features"]:
        head = _fold(f"{f['feature']} {f['title']}")
        titles = {s["id"]: _fold(s["title"]) for s in f["stories"]}
        for ac in f["acs"]:
            body = _fold(" ".join(str(ac.get(k) or "") for k in ("given", "when", "then")))
            text = f"{head} {titles.get(ac['story'], '')} {body}"
            score = sum(1 for w in words if w in text)
            for a, b in zip(words, words[1:]):       # cụm "gio hang" nặng hơn "hang" lẻ (khách hàng)
                score += 2 * (f"{a} {b}" in text)
            if score:
                hits.append((score, {"feature": f["feature"], **ac}))
    hits.sort(key=lambda h: -h[0])
    best = hits[0][0] if hits else 0
    return [h for score, h in hits if score * 2 >= best][:25]


def _results(cat: dict, name: str) -> dict:
    f = _feature(cat, name)
    folder = Path(f["config"]).parent / "artifacts"
    run = _read_json(folder / "run.json")
    data = _read_json(folder / "5-execute" / "results.json")
    if not run:
        return {"feature": name, "ran": False, "note": "Feature này chưa chạy lần nào."}
    traces = {}
    cases_yaml = folder / "3-generate" / "testcases.yaml"
    if cases_yaml.is_file():
        import yaml
        try:
            for tc in (yaml.safe_load(cases_yaml.read_text(encoding="utf-8")) or {}).get("testcases") or []:
                traces[tc.get("id")] = [_short(t, name) for t in tc.get("traces_to") or []]
        except Exception:  # noqa: BLE001
            pass
    issues = []
    for r in (data or {}).get("results") or []:
        if r.get("status") != "Pass" or str(r.get("flaky")) == "True":
            issues.append({"case": r.get("case_id"), "acs": traces.get(r.get("case_id"), []),
                           "status": r.get("status"), "title": str(r.get("title") or "")[:160],
                           "actual": str(r.get("actual") or "")[:300]})
    return {"feature": name, "ran": True, "status": run.get("status"), "started_at": run.get("started_at"),
            "intent_ids": run.get("intent_ids"), "summary": (data or {}).get("summary"),
            "not_pass": issues[:30], "artifacts": folder.as_posix()}


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _plan(session: dict, cat: dict, args: dict) -> dict:
    scope = args.get("scope")
    if scope not in ("system", "feature", "requirement", "flow"):
        raise ChatError("scope phải là system | feature | requirement | flow.")
    items, errors, warnings = [], [], []
    for raw in args.get("items") or []:
        try:
            f = _feature(cat, str(raw.get("feature") or ""))
        except ChatError as exc:
            errors.append(str(exc))
            continue
        known = {a["id"]: a for a in f["acs"]}
        wanted = [_short(a, f["feature"]) for a in raw.get("acs") or []]
        unknown = [a for a in wanted if a not in known]
        if unknown:
            errors.append(f"{f['feature']}: không có AC {', '.join(unknown)}. Có: {', '.join(known)}")
            continue
        chosen = [known[a] for a in (wanted or known)]
        if not chosen:
            errors.append(f"{f['feature']}: tài liệu không có AC nào — không lập kế hoạch được.")
            continue
        items.append({"feature": f["feature"], "title": f["title"], "acs": list(dict.fromkeys(wanted)),
                      "ac_count": len(chosen), "why": str(raw.get("why") or "")[:300],
                      "ac_text": {a["id"]: a["then"] for a in chosen}})
        writes = [a["id"] for a in chosen if a["writes_data"]]
        if writes and not f["write_mode"]:
            warnings.append(f"{f['feature']}: {', '.join(writes)} ghi dữ liệu thật → chế độ safe sẽ để thủ công "
                            "(Not Executed).")
        if f["write_mode"]:
            warnings.append(f"{f['feature']}: cấu hình mode: write — giao diện không chạy được, dùng CLI --write.")
        if any(a["needs_login"] for a in chosen) and not cat["account_set"]:
            warnings.append(f"{f['feature']}: có AC cần đăng nhập nhưng chưa nhập tài khoản test → Blocked.")
    if errors:
        raise ChatError("Kế hoạch có lỗi, sửa rồi gọi lại: " + " | ".join(errors))
    if not items:
        raise ChatError("Kế hoạch không có mục nào.")
    if len({i["feature"] for i in items}) != len(items):
        raise ChatError("Mỗi feature chỉ xuất hiện một lần; gộp AC của cùng feature vào một mục.")
    if not cat["web"] and not cat["api"]:
        warnings.append("Project chưa có URL web/API → chỉ sinh testcase, không chạy được.")
    plan = {"id": f"P{sum(1 for m in session['messages'] if m['role'] == 'plan') + 1}", "scope": scope,
            "title": str(args.get("title") or "Kế hoạch test")[:120],
            "understanding": str(args.get("understanding") or "")[:600], "items": items,
            "out_of_scope": [str(x)[:200] for x in args.get("out_of_scope") or []][:10],
            "warnings": warnings, "status": "proposed", "runs": [],
            "created_at": datetime.now().isoformat(timespec="seconds")}
    if scope == "flow":
        plan["warnings"].insert(0, "Luồng chạy theo thứ tự các mục; mỗi AC là một testcase độc lập "
                                   "(phiên riêng), chưa nối trạng thái giữa các bước.")
    return plan


def call_tool(session: dict, name: str, args: dict) -> tuple[dict, str]:
    """→ (kết quả cho LLM, tóm tắt một dòng cho người dùng)."""
    cat = catalog(session["project"])
    if name == "list_features":
        return _overview(cat), f"{len(cat['features'])} feature"
    if name == "get_requirements":
        f = _feature(cat, str(args.get("feature") or ""))
        return ({"feature": f["feature"], "title": f["title"], "stories": f["stories"], "acs": f["acs"],
                 "doc_warnings": f["warnings"]}, f"{f['feature']}: {len(f['acs'])} AC")
    if name == "search_requirements":
        hits = _search(cat, str(args.get("query") or ""))
        return {"hits": hits}, f"“{args.get('query')}” → {len(hits)} AC"
    if name == "get_last_results":
        res = _results(cat, str(args.get("feature") or ""))
        s = res.get("summary") or {}
        return res, (f"{res['feature']}: " + (", ".join(f"{k} {v}" for k, v in s.items() if k != "pass_rate")
                                                if s else "chưa chạy"))
    if name == "propose_test_plan":
        plan = _plan(session, cat, args)
        session["messages"].append({"role": "plan", "plan": plan, "at": _now()})
        return ({"ok": True, "plan_id": plan["id"], "ac_total": sum(i["ac_count"] for i in plan["items"]),
                 "warnings": plan["warnings"], "note": "Đã hiện thẻ kế hoạch; chờ người dùng bấm Chạy."},
                f"{plan['id']}: {len(plan['items'])} feature, {sum(i['ac_count'] for i in plan['items'])} AC")
    raise ChatError(f"Không có tool {name}")


# ── Phiên chat ──────────────────────────────────────────────────────────────
_LOCKS: dict[str, threading.Lock] = {}
_ANSWERING: set[str] = set()     # phiên đang có thread trả lời trong tiến trình này
_LOCKS_GUARD = threading.Lock()


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _path(project: str, sid: str) -> Path:
    if not re.match(r"^[a-f0-9]{12}$", sid or ""):
        raise ChatError("Mã phiên chat không hợp lệ.")
    return setup._project_dir(project) / "chat" / f"{sid}.json"


def _lock(project: str, sid: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(f"{project}/{sid}", threading.Lock())


def _save(session: dict) -> None:
    path = _path(session["project"], session["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    session["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(session, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def load(project: str, sid: str) -> dict:
    path = _path(project, sid)
    if not path.is_file():
        raise ChatError("Không tìm thấy phiên chat.")
    session = json.loads(path.read_text(encoding="utf-8"))
    if session.get("busy") and f"{project}/{sid}" not in _ANSWERING:
        session["busy"] = False      # tiến trình trả lời đã chết (tắt `qctool ui` giữa chừng)
    for msg in session["messages"]:
        plan = msg.get("plan")
        if plan and plan["status"] == "running" and f"{project}/{sid}/{plan['id']}" not in _PLAN_THREADS:
            plan["status"] = "interrupted"
    return session


def create(project: str) -> dict:
    setup._project_dir(project)
    if not setup._project_dir(project).is_dir():
        raise ChatError(f"Không có project {project}")
    session = {"id": uuid.uuid4().hex[:12], "project": project, "title": "Cuộc trò chuyện mới",
               "created_at": datetime.now().isoformat(timespec="seconds"), "messages": [], "llm": [],
               "busy": False}
    _save(session)
    return session


def list_sessions(project: str) -> list[dict]:
    folder = setup._project_dir(project) / "chat"
    out = []
    for path in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.is_dir() else []:
        data = _read_json(path) or {}
        out.append({"id": data.get("id", path.stem), "title": data.get("title", ""), "updated_at": data.get("updated_at")})
    return out[:50]


def view(session: dict) -> dict:
    """Bản gửi giao diện: không có transcript LLM thô."""
    return {k: v for k, v in session.items() if k != "llm"}


def _trim(history: list[dict]) -> list[dict]:
    if len(history) <= MAX_HISTORY:
        return history
    cut = len(history) - MAX_HISTORY
    while cut < len(history) and history[cut].get("role") != "user":
        cut += 1          # không cắt giữa assistant(tool_calls) và tool trả lời
    return history[cut:]


def send(project: str, sid: str, text: str, llm_factory) -> dict:
    """Nhận tin nhắn, trả lời trong thread nền. UI hỏi lại `load` để thấy từng bước."""
    text = str(text or "").strip()
    if not text:
        raise ChatError("Tin nhắn rỗng.")
    if len(text) > 4000:
        raise ChatError("Tin nhắn tối đa 4000 ký tự.")
    lock = _lock(project, sid)
    with lock:
        session = load(project, sid)
        if session.get("busy"):
            raise ChatError("Trợ lý đang trả lời tin trước — chờ một chút.")
        session["messages"].append({"role": "user", "text": text, "at": _now()})
        session["llm"] += [{"role": "user", "content": f"[Thông báo hệ thống, không phải người dùng viết] {n}"}
                           for n in session.pop("pending_notes", [])]
        session["llm"].append({"role": "user", "content": text})
        if session["title"] == "Cuộc trò chuyện mới":
            session["title"] = text[:60]
        session["busy"] = True
        _ANSWERING.add(f"{project}/{sid}")
        _save(session)
    threading.Thread(target=_answer, args=(project, sid, llm_factory), daemon=True).start()
    return view(session)


def _answer(project: str, sid: str, llm_factory) -> None:
    lock = _lock(project, sid)

    def update(fn) -> dict:
        with lock:
            session = load(project, sid)
            fn(session)
            _save(session)
            return session

    try:
        llm = llm_factory()
        with lock:
            session = load(project, sid)
        cat = catalog(project)
        system = SYSTEM + json.dumps(_overview(cat), ensure_ascii=False, indent=1)
        turn_msgs: list[dict] = []          # message của lượt này, giữ reasoning_content trong RAM
        base = _trim(session["llm"])
        for _ in range(MAX_TURNS):
            update(lambda s: s.update(activity="Đang suy nghĩ…"))
            started = time.monotonic()
            response = llm.chat([{"role": "system", "content": system}, *base, *turn_msgs], TOOLS, max_tokens=1500)
            took = time.monotonic() - started
            turn_msgs.append(response)
            calls = response.get("tool_calls") or []
            content = (response.get("content") or "").strip()

            def record(s, response=response, calls=calls, content=content, took=took):
                s["llm"].append({k: v for k, v in response.items() if k != "reasoning_content"})
                if content:
                    s["messages"].append({"role": "assistant", "text": content, "at": _now(),
                                          "seconds": round(took, 1)})
            update(record)
            if not calls:
                break
            for call in calls:
                name = call["function"]["name"]
                tool_started = time.monotonic()
                try:
                    args = json.loads(call["function"]["arguments"] or "{}")
                    if not isinstance(args, dict):
                        raise ChatError("Tham số tool phải là JSON object.")
                    update(lambda s, name=name: s.update(activity=f"Đang chạy {name}…"))
                    with lock:
                        session = load(project, sid)
                        result, summary = call_tool(session, name, args)
                        _save(session)       # propose_test_plan thêm thẻ kế hoạch
                    ok = True
                except (ChatError, setup.SetupError, ValueError) as exc:
                    result, summary, ok = {"ok": False, "error": str(exc)}, str(exc)[:200], False
                tool_msg = {"role": "tool", "tool_call_id": call["id"],
                            "content": json.dumps(result, ensure_ascii=False)}
                turn_msgs.append(tool_msg)
                shown = {k: v for k, v in args.items() if k != "items"} if ok and isinstance(args, dict) else {}

                def add(s, tool_msg=tool_msg, name=name, summary=summary, ok=ok, shown=shown,
                        took=time.monotonic() - tool_started):
                    s["llm"].append(tool_msg)
                    at = len(s["messages"]) - (1 if ok and name == "propose_test_plan" else 0)
                    s["messages"].insert(at, {"role": "tool", "name": name, "args": shown, "summary": summary,
                                          "ok": ok, "seconds": round(took, 2), "at": _now()})
                update(add)
        else:
            update(lambda s: s["messages"].append({"role": "note", "at": _now(),
                   "text": f"Trợ lý dừng sau {MAX_TURNS} lượt gọi model mà chưa trả lời xong — hỏi lại cụ thể hơn."}))
    except Exception as exc:  # noqa: BLE001 — lỗi phải hiện cho người dùng, không treo "đang suy nghĩ"
        message = getattr(exc, "safe_message", None) or f"{type(exc).__name__}: {exc}"
        update(lambda s: s["messages"].append({"role": "note", "level": "error", "at": _now(),
                                               "text": f"Không gọi được LLM: {message}"}))
    finally:
        _ANSWERING.discard(f"{project}/{sid}")
        update(lambda s: s.update(busy=False, activity=""))


# ── Chạy kế hoạch (chỉ khi người dùng bấm) ──────────────────────────────────
_PLAN_THREADS: dict[str, threading.Thread] = {}


def _find_plan(session: dict, plan_id: str) -> dict:
    for msg in session["messages"]:
        if msg.get("plan", {}).get("id") == plan_id:
            return msg["plan"]
    raise ChatError(f"Không có kế hoạch {plan_id}")


def start_plan(project: str, sid: str, plan_id: str, run_feature, *, options: dict | None = None,
               summarize=None) -> dict:
    """`run_feature(config, only, on_start, **options) -> dict` chạy đồng bộ một feature (web/app.py).

    `options` là lựa chọn của người bấm (vd `trace_sensitive`); `summarize(runs, started)` ghi báo cáo
    tổng hợp `projects/<p>/summary/<ngày_giờ>/` như `qctool run <project>`.
    """
    options = {k: v for k, v in (options or {}).items() if k == "trace_sensitive" and v is True}
    lock = _lock(project, sid)
    with lock:
        session = load(project, sid)
        plan = _find_plan(session, plan_id)
        if plan["status"] == "running":
            raise ChatError("Kế hoạch này đang chạy.")
        if any(m.get("plan", {}).get("status") == "running" for m in session["messages"]):
            raise ChatError("Đang có kế hoạch khác chạy trong cuộc trò chuyện này.")
        cat = catalog(project)
        configs = {i["feature"]: _feature(cat, i["feature"])["config"] for i in plan["items"]}
        key = f"{project}/{sid}/{plan_id}"
        _PLAN_THREADS[key] = None       # đăng ký trước khi lưu "running" — load() coi thiếu là đã chết
        plan["status"] = "running"
        plan["started_at"] = datetime.now().isoformat(timespec="seconds")
        plan["options"] = options
        plan["runs"] = [{"feature": i["feature"], "status": "queued"} for i in plan["items"]]
        _save(session)

    def update(fn) -> None:
        with lock:
            s = load(project, sid)
            fn(_find_plan(s, plan_id), s)
            _save(s)

    def worker() -> None:
        from qctool.summary import now as summary_now
        began = summary_now()
        for index, item in enumerate(plan["items"]):
            def started(artifacts, index=index):
                update(lambda p, s: p["runs"][index].update(status="running", artifacts=artifacts,
                                                            started_at=_now()))
            try:
                outcome = run_feature(configs[item["feature"]], item["acs"], started, **options)
                entry = {"status": "error" if outcome.get("error") else "done", **outcome}
            except Exception as exc:  # noqa: BLE001 — một feature lỗi không chặn feature sau
                entry = {"status": "error", "error": str(exc)}
            update(lambda p, s, index=index, entry=entry: p["runs"][index].update(finished_at=_now(), **entry))
        totals: dict[str, int] = {}
        summary_dir = None
        if summarize is not None:
            with lock:
                runs = deepcopy(_find_plan(load(project, sid), plan_id)["runs"])
            try:
                summary_dir = summarize([(configs[r["feature"]], r) for r in runs], began)
            except Exception:  # noqa: BLE001 — thiếu báo cáo tổng hợp không làm hỏng kết quả đã chạy
                summary_dir = None

        def finish(p, s):
            for run in p["runs"]:
                for k, v in ((run.get("result") or {}).get("counts") or {}).items():
                    totals[k] = totals.get(k, 0) + int(v)
            p["status"], p["totals"] = "done", totals
            if summary_dir:
                p["summary"] = summary_dir
            errors = [r["feature"] for r in p["runs"] if r["status"] == "error"]
            text = (f"Kế hoạch {p['id']} chạy xong: "
                    + (", ".join(f"{k} {v}" for k, v in totals.items()) or "không có kết quả")
                    + (f". Lỗi ở: {', '.join(errors)}" if errors else ""))
            s["messages"].append({"role": "note", "text": text, "at": _now(), "plan_id": p["id"]})
            # Model biết kế hoạch đã chạy khi người dùng hỏi tiếp. Không chèn thẳng vào transcript:
            # có thể đang giữa assistant(tool_calls) và tool trả lời.
            s.setdefault("pending_notes", []).append(text)
        try:
            update(finish)
        finally:
            _PLAN_THREADS.pop(key, None)

    thread = threading.Thread(target=worker, daemon=True)
    _PLAN_THREADS[key] = thread
    thread.start()
    return view(load(project, sid))


def cancel_plan(project: str, sid: str, plan_id: str) -> dict:
    with _lock(project, sid):
        session = load(project, sid)
        plan = _find_plan(session, plan_id)
        if plan["status"] != "proposed":
            raise ChatError("Chỉ bỏ được kế hoạch chưa chạy.")
        plan["status"] = "cancelled"
        _save(session)
        return view(session)


# ── Dữ liệu đầu vào ─────────────────────────────────────────────────────────
DOC_ALIASES = [(re.compile(r"urd", re.I), "urd.md"), (re.compile(r"srs", re.I), "srs.md"),
               (re.compile(r"(openapi|swagger)", re.I), "openapi.yaml")]


def doc_name(filename: str) -> str:
    """Tên file người dùng thả vào → tên pipeline đọc (urd.md, srs.md, openapi.yaml) nếu nhận ra."""
    stem = Path(filename or "").name
    for pattern, target in DOC_ALIASES:
        if pattern.search(stem) and stem.lower().endswith((".md", ".yaml", ".yml", ".json")):
            return target
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip("-.") or "tai-lieu.md"
    return clean


def upload(project: str, feature: str, files: list[dict], target: dict | None = None) -> dict:
    """Tạo project/feature nếu chưa có, lưu tài liệu, cập nhật URL. Trả danh mục mới."""
    target = target or {}
    folder = setup._project_dir(project)
    if not (folder / "project.yaml").is_file():
        setup.create_project(project, {"web": target.get("web") or "", "api": target.get("api") or "", "llm": True})
    elif "web" in target or "api" in target:
        form = setup.get_project(project).get("form") or {}
        setup.save_project_form(project, {**form, **{k: target[k] for k in ("web", "api") if k in target}})
    saved = []
    if files:
        if not (setup._feature_dir(project, feature) / "qctool.yaml").is_file():
            setup.create_feature(project, feature)
        for f in files:
            name = doc_name(str(f.get("name") or ""))
            content = f.get("content")
            if name.endswith(".json"):
                import yaml
                try:
                    content = yaml.safe_dump(json.loads(content), allow_unicode=True, sort_keys=False)
                except (ValueError, TypeError):
                    raise setup.SetupError(f"{f.get('name')}: JSON không hợp lệ.") from None
                name = name[:-5] + ".yaml"
            setup.save_doc(project, feature, name, content)
            saved.append(name)
    _CACHE.clear()
    cat = catalog(project)
    info = next((x for x in cat["features"] if x["feature"] == feature), None)
    return {"saved": saved, "feature": info and {"feature": info["feature"], "title": info["title"],
                                                  "acs": len(info["acs"]), "docs": info["docs"],
                                                  "warnings": info["warnings"]},
            "overview": _overview(cat)}


def note(project: str, sid: str, text: str) -> None:
    """Ghi sự kiện (đã tải tài liệu, đã lưu tài khoản) vào cuộc trò chuyện để model biết."""
    with _lock(project, sid):
        session = load(project, sid)
        session["messages"].append({"role": "note", "text": text, "at": _now()})
        session.setdefault("pending_notes", []).append(text)
        _save(session)


def llm_ready() -> bool:
    from qctool import config
    config.load_dotenv()
    return bool(os.environ.get("QCTOOL_LLM_MODEL", "").strip() and os.environ.get("QCTOOL_LLM_API_KEY", "").strip())

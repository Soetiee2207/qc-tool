"""Cấu hình qua giao diện: project, feature, tài liệu, tài khoản test, `.env`.

Hàm thuần, không phụ thuộc HTTP — `web/app.py` chỉ định tuyến. Mọi đường dẫn đi qua
`_feature_dir`/`_project_dir` (tên kiểm bằng regex, nằm trong `projects/`), nên không ghi
được ra ngoài cây project dù payload gửi gì.

Ghi YAML luôn theo thứ tự: ghi → nạp lại bằng đúng loader của pipeline → lỗi thì trả
file cũ. Không bao giờ để lại một cấu hình mà `qctool run` không đọc được.

Bí mật chỉ ở `.env` (gitignored). API không bao giờ trả giá trị bí mật, chỉ "đã đặt/chưa".
"""
from __future__ import annotations

import argparse
import os
import re
import time
from pathlib import Path

import yaml

PROJECTS = Path("projects")
ENV_PATH = Path(".env")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,48}$")
DOC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}\.(md|yaml|yml)$")
MAX_DOC = 1024 * 1024
RESERVED = {"summary", "artifacts", "web", "chat"}

# Biến .env người dùng tự đặt được. `secret` → không bao giờ trả giá trị ra UI.
ENV_FIELDS = [
    {"key": "QCTOOL_USERNAME", "label": "Tài khoản test (email/username)", "secret": False,
     "group": "Tài khoản test", "help": "Tài khoản thật trên môi trường test; dùng cho AC tick 'dùng tài khoản thật'."},
    {"key": "QCTOOL_PASSWORD", "label": "Mật khẩu tài khoản test", "secret": True, "group": "Tài khoản test",
     "help": "Không ghi vào YAML, không hiện lại trên giao diện."},
    {"key": "QCTOOL_BEARER_TOKEN", "label": "Bearer token (auth.mode: token)", "secret": True, "group": "Tài khoản test",
     "help": "Chỉ cần khi API dùng token dán sẵn."},
    {"key": "QCTOOL_LLM_BASE_URL", "label": "LLM base URL", "secret": False, "group": "LLM",
     "help": "Provider OpenAI-compatible có tool calling, vd https://api.deepseek.com/v1"},
    {"key": "QCTOOL_LLM_MODEL", "label": "Model", "secret": False, "group": "LLM", "help": "vd deepseek-chat"},
    {"key": "QCTOOL_LLM_API_KEY", "label": "API key", "secret": True, "group": "LLM", "help": ""},
    {"key": "QCTOOL_LLM_TIMEOUT_SECONDS", "label": "Timeout mỗi lời gọi (giây)", "secret": False, "group": "LLM", "help": "90–120 là hợp lý"},
    {"key": "QCTOOL_LLM_THINKING", "label": "Thinking", "secret": False, "group": "LLM",
     "help": "DeepSeek: disabled = nhanh, rẻ hơn. Để trống = mặc định provider."},
]
ENV_KEYS = {f["key"]: f for f in ENV_FIELDS}

PROJECT_HEADER = ("# {name} — cấu hình chung cho mọi feature; feature ghi đè trong <feature>/qctool.yaml.\n"
                  "# Sửa qua `qctool ui` → Cấu hình. Tài khoản/khoá API chỉ ở .env.\n")
FEATURE_HEADER = ("# Feature {name}. Tài liệu (urd.md, srs.md, openapi.yaml) nằm cạnh file này.\n"
                  "# Chỉ AC trong account.login_for được dùng tài khoản thật.\n")


class SetupError(ValueError):
    pass


# ── Đường dẫn ───────────────────────────────────────────────────────────────
def _name(value: str, what: str) -> str:
    value = (value or "").strip()
    if not NAME_RE.match(value) or value in RESERVED:
        raise SetupError(f"Tên {what} chỉ gồm chữ thường, số, '-' hoặc '_' (tối đa 49 ký tự), "
                         f"không trùng {', '.join(sorted(RESERVED))}: {value!r}")
    return value


def _project_dir(project: str) -> Path:
    return PROJECTS / _name(project, "project")


def _feature_dir(project: str, feature: str) -> Path:
    return _project_dir(project) / _name(feature, "feature")


def _doc_path(project: str, feature: str, name: str) -> Path:
    if not DOC_RE.match(name or "") or name == "qctool.yaml":
        raise SetupError(f"Tên file tài liệu không hợp lệ: {name!r} (chỉ .md/.yaml ở thư mục feature; "
                         "qctool.yaml sửa ở mục Cấu hình)")
    return _feature_dir(project, feature) / name


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SetupError(f"{path} phải là YAML mapping.")
    return data


def _dump(header: str, data: dict) -> str:
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False) if data else ""
    return header + body


def _has_comments(text: str, header: str) -> bool:
    """Comment do người dùng viết (ngoài header tool tự sinh) sẽ mất khi lưu bằng form."""
    own = set(header.splitlines())
    return any(line.strip().startswith("#") or " #" in line for line in text.splitlines() if line not in own)


def _write_checked(path: Path, text: str) -> None:
    """Ghi rồi nạp lại bằng loader thật; lỗi → khôi phục bản cũ."""
    try:
        data = yaml.safe_load(text) if text.strip() else {}
    except yaml.YAMLError as exc:
        raise SetupError(f"YAML sai cú pháp: {exc}") from None
    if data is not None and not isinstance(data, dict):
        raise SetupError("File cấu hình phải là YAML mapping (key: value).")
    old = path.read_text(encoding="utf-8") if path.is_file() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    from qctool.pipeline import PipelineConfig
    targets = [path] if path.name == "qctool.yaml" else sorted(path.parent.glob("*/qctool.yaml"))
    try:
        for target in targets:
            PipelineConfig.from_file(target)
    except Exception as exc:  # noqa: BLE001 — trả lỗi cho người dùng sửa
        if old is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(old, encoding="utf-8")
        where = f" (khi nạp {target.parent.name}/qctool.yaml)" if target != path else ""
        raise SetupError(f"Cấu hình không hợp lệ{where}: {exc}") from None


# ── Project ─────────────────────────────────────────────────────────────────
PROJECT_FIELDS = ("web", "api", "llm", "role", "timeout_seconds", "evidence", "trace", "mode")


def _project_form(data: dict) -> dict:
    run, ui, account = data.get("run") or {}, data.get("ui") or {}, data.get("account") or {}
    llm = data.get("llm")
    evidence = ui.get("evidence", "on-fail")
    return {"web": data.get("web") or data.get("web_url") or "", "api": data.get("api") or run.get("base_url") or "",
            "llm": llm if isinstance(llm, bool) else bool((llm or {}).get("enabled", False)),
            "role": account.get("role", "") if isinstance(account, dict) else "",
            "timeout_seconds": run.get("timeout_seconds", 30),
            "evidence": "off" if evidence is False else str(evidence), "trace": bool(ui.get("trace", False)),
            "mode": data.get("mode", "safe")}


def _apply_project_form(data: dict, form: dict) -> dict:
    data = dict(data)
    url_re = re.compile(r"^https?://[^\s/?#]+[^\s?#]*$")
    for key in ("web", "api"):
        value = str(form.get(key) or "").strip().rstrip("/")
        if value and not url_re.match(value):
            raise SetupError(f"{key}: URL phải bắt đầu bằng http(s)://, không có khoảng trắng/query: {value!r}")
        if key == "web":
            data.pop("web_url", None)
        else:
            data["run"] = {k: v for k, v in (data.get("run") or {}).items() if k != "base_url"}
        if value:
            data[key] = value
        else:
            data.pop(key, None)
    data["llm"] = bool(form.get("llm"))
    role = str(form.get("role") or "").strip()
    account = dict(data.get("account") or {})
    if role:
        account["role"] = role
    else:
        account.pop("role", None)
    if account:
        data["account"] = account
    else:
        data.pop("account", None)
    try:
        timeout = int(form.get("timeout_seconds") or 30)
    except (TypeError, ValueError):
        raise SetupError("Timeout phải là số nguyên (giây).") from None
    if not 1 <= timeout <= 600:
        raise SetupError("Timeout trong khoảng 1–600 giây.")
    data["run"] = {**(data.get("run") or {}), "timeout_seconds": timeout}
    evidence = form.get("evidence") or "on-fail"
    if evidence not in ("off", "on-fail", "always"):
        raise SetupError("Bằng chứng: off | on-fail | always.")
    data["ui"] = {**(data.get("ui") or {}), "evidence": evidence, "trace": bool(form.get("trace"))}
    mode = form.get("mode") or "safe"
    if mode not in ("safe", "write"):
        raise SetupError("Chế độ: safe | write.")
    data["mode"] = mode
    return {k: v for k, v in data.items() if v not in ({}, None)}


def list_projects() -> list[dict]:
    out = []
    if not PROJECTS.is_dir():
        return out
    for p in sorted(PROJECTS.iterdir()):
        if not p.is_dir() or not NAME_RE.match(p.name) or p.name in RESERVED:
            continue
        if not (p / "project.yaml").is_file() and not any(p.glob("*/qctool.yaml")):
            continue
        out.append({"name": p.name, "features": sorted(f.parent.name for f in p.glob("*/qctool.yaml"))})
    return out


def get_project(project: str) -> dict:
    folder = _project_dir(project)
    path = folder / "project.yaml"
    if not folder.is_dir():
        raise SetupError(f"Không có project {project}")
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    try:
        form = _project_form(_load(path))
        error = None
    except Exception as exc:  # noqa: BLE001
        form, error = None, str(exc)
    return {"name": project, "path": path.as_posix(), "yaml": text, "form": form, "error": error,
            "has_comments": _has_comments(text, PROJECT_HEADER.format(name=project)),
            "features": [get_feature_summary(project, f.parent.name) for f in sorted(folder.glob("*/qctool.yaml"))]}


def create_project(project: str, form: dict) -> dict:
    folder = _project_dir(project)
    if (folder / "project.yaml").exists():
        raise SetupError(f"Project {project} đã có.")
    data = _apply_project_form({}, {"llm": True, **form})
    _write_checked(folder / "project.yaml", _dump(PROJECT_HEADER.format(name=project), data))
    return get_project(project)


def save_project_form(project: str, form: dict) -> dict:
    path = _project_dir(project) / "project.yaml"
    data = _apply_project_form(_load(path), form)
    _write_checked(path, _dump(PROJECT_HEADER.format(name=project), data))
    return get_project(project)


def save_project_yaml(project: str, text: str) -> dict:
    folder = _project_dir(project)
    if not folder.is_dir():
        raise SetupError(f"Không có project {project}")
    _write_checked(folder / "project.yaml", text)
    return get_project(project)


# ── Feature ─────────────────────────────────────────────────────────────────
def get_feature_summary(project: str, feature: str) -> dict:
    folder = _feature_dir(project, feature)
    docs = sorted(p.name for p in folder.iterdir() if p.is_file() and DOC_RE.match(p.name) and p.name != "qctool.yaml")
    return {"name": feature, "docs": docs}


def create_feature(project: str, feature: str) -> dict:
    folder = _feature_dir(project, feature)
    if (folder / "qctool.yaml").exists():
        raise SetupError(f"Feature {project}/{feature} đã có.")
    if not _project_dir(project).is_dir():
        raise SetupError(f"Không có project {project}")
    _write_checked(folder / "qctool.yaml", FEATURE_HEADER.format(name=feature))
    return get_feature(project, feature)


def _short(ac_id: str, feature: str) -> str:
    return ac_id.removeprefix("AC-").removeprefix(f"{feature}-")


def get_feature(project: str, feature: str) -> dict:
    folder = _feature_dir(project, feature)
    path = folder / "qctool.yaml"
    if not path.is_file():
        raise SetupError(f"Không có feature {project}/{feature}")
    text = path.read_text(encoding="utf-8")
    data, error = {}, None
    try:
        data = _load(path)
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    account = data.get("account") or {}
    name = data.get("feature") or feature
    login_for = {str(a).removeprefix("AC-").removeprefix(f"{name}-") for a in account.get("login_for") or []}
    test_values = {str(k): v for k, v in (account.get("test_values") or {}).items()}
    acs, ingest_warnings = [], []
    if any((folder / n).is_file() for n in ("urd.md", "srs.md")):
        try:
            from qctool import ingest
            doc = ingest.ingest_feature(folder, name)
            ingest_warnings = doc.get("warnings", [])
            for req in doc.get("requirements", []):
                if req.get("kind") != "acceptance_criterion":
                    continue
                short = _short(req["id"], name)
                acs.append({"id": req["id"], "short": short, "story": req.get("belongs_to"),
                            "given": req.get("given"), "when": req.get("when"), "then": req.get("then"),
                            "login": short in login_for, "test_values": test_values.get(short) or {}})
        except Exception as exc:  # noqa: BLE001
            ingest_warnings = [f"Không đọc được tài liệu: {exc}"]
    return {"project": project, "name": feature, "path": path.as_posix(), "yaml": text, "error": error,
            "has_comments": _has_comments(text, FEATURE_HEADER.format(name=feature)),
            "docs": get_feature_summary(project, feature)["docs"], "acs": acs, "ingest_warnings": ingest_warnings,
            "unknown_login": sorted(login_for - {a["short"] for a in acs}) if acs else []}


def save_feature_account(project: str, feature: str, login_for: list, test_values: dict) -> dict:
    path = _feature_dir(project, feature) / "qctool.yaml"
    data = _load(path)
    if not isinstance(login_for, list) or not all(isinstance(a, str) and a.strip() for a in login_for):
        raise SetupError("login_for phải là danh sách mã AC.")
    if not isinstance(test_values, dict):
        raise SetupError("test_values phải là {AC: {field: giá trị}}.")
    clean = {}
    for ac, values in test_values.items():
        values = {str(k).strip(): str(v) for k, v in (values or {}).items() if str(k).strip() and str(v) != ""}
        bad = [k for k in values if not re.match(r"^[a-z][a-z0-9_]*$", k)]
        if bad:
            raise SetupError(f"Tên field không hợp lệ ở {ac}: {', '.join(bad)} (chữ thường, số, _)")
        if values:
            clean[str(ac)] = values
    account = {k: v for k, v in (data.get("account") or {}).items() if k not in ("login_for", "test_values")}
    if login_for:
        # Loader chỉ nhận role trong danh sách đóng; không có thì báo đúng chỗ cần điền thay vì lỗi fixture khó hiểu.
        from qctool.data.fixtures import PUBLIC_FACT_VALUES
        roles = PUBLIC_FACT_VALUES["role"]
        role = account.get("role") or (_load(path.parent.parent / "project.yaml").get("account") or {}).get("role")
        if role not in roles:
            raise SetupError(f"AC dùng tài khoản thật cần chọn vai trò tài khoản ở mục 3 (hiện: {role or 'chưa chọn'}; "
                             f"hợp lệ: {', '.join(sorted(roles))}).")
        account["login_for"] = sorted(dict.fromkeys(a.strip() for a in login_for))
    if clean:
        account["test_values"] = clean
    if account:
        data["account"] = account
    else:
        data.pop("account", None)
    _write_checked(path, _dump(FEATURE_HEADER.format(name=feature), data))
    return get_feature(project, feature)


def save_feature_yaml(project: str, feature: str, text: str) -> dict:
    path = _feature_dir(project, feature) / "qctool.yaml"
    if not path.is_file():
        raise SetupError(f"Không có feature {project}/{feature}")
    _write_checked(path, text)
    return get_feature(project, feature)


def read_doc(project: str, feature: str, name: str) -> dict:
    path = _doc_path(project, feature, name)
    if not path.is_file():
        raise SetupError(f"Không có file {name}")
    return {"name": name, "content": path.read_text(encoding="utf-8", errors="replace")}


def save_doc(project: str, feature: str, name: str, content: str) -> dict:
    path = _doc_path(project, feature, name)
    if not (path.parent / "qctool.yaml").is_file():
        raise SetupError(f"Không có feature {project}/{feature}")
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_DOC:
        raise SetupError("Nội dung phải là văn bản, tối đa 1 MB.")
    if name.endswith((".yaml", ".yml")):
        try:
            spec = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            raise SetupError(f"{name}: YAML sai cú pháp: {exc}") from None
        if name.startswith("openapi") and not (isinstance(spec, dict) and "paths" in spec):
            raise SetupError(f"{name}: không giống OpenAPI (thiếu `paths`).")
    path.write_text(content, encoding="utf-8")
    return get_feature(project, feature)


def delete_doc(project: str, feature: str, name: str) -> dict:
    _doc_path(project, feature, name).unlink(missing_ok=True)
    return get_feature(project, feature)


def check_feature(project: str, feature: str) -> dict:
    """`qctool check` cho một feature: đọc cấu hình/tài liệu/OpenAPI, không gọi browser/model."""
    from qctool.cli_run import PreflightError, preflight
    path = _feature_dir(project, feature) / "qctool.yaml"
    started = time.monotonic()
    try:
        checked = preflight(argparse.Namespace(config=str(path)), require_target=False)
    except PreflightError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    cfg = checked.config
    notes = []
    if not cfg.web_url and not cfg.base_url:
        notes.append("Chưa có web/api — chỉ sinh được testcase, không chạy được.")
    if cfg.llm_enabled and not cfg.web_url:
        notes.append("LLM bật nhưng thiếu web — agent cần URL ứng dụng để viết case UI.")
    if not cfg.llm_enabled and cfg.docs_dir:
        notes.append("LLM tắt — case từ tài liệu sẽ ở dạng thủ công (Not Executed).")
    if cfg.auth_mode == "browser" and not (cfg.username and cfg.password):
        notes.append("Có AC dùng tài khoản thật nhưng .env chưa có QCTOOL_USERNAME/QCTOOL_PASSWORD.")
    if cfg.write_mode:
        notes.append("mode: write — web UI không chạy được, dùng CLI --write.")
    return {"ok": True, "requirements": checked.requirements, "operations": checked.operations,
            "warnings": checked.warnings, "notes": notes, "llm": cfg.llm_enabled, "web": cfg.web_url,
            "api": cfg.base_url, "auth_mode": cfg.auth_mode, "seconds": round(time.monotonic() - started, 2)}


# ── .env ────────────────────────────────────────────────────────────────────
def _env_lines() -> list[str]:
    return ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.is_file() else []


def _env_values() -> dict:
    values = {}
    for line in _env_lines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _, value = stripped.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_env() -> list[dict]:
    values = _env_values()
    out = []
    for field in ENV_FIELDS:
        value = values.get(field["key"], "")
        out.append({**field, "set": bool(value), "value": "" if field["secret"] else value})
    return out


def save_env(updates: dict, clear: list | None = None) -> list[dict]:
    """Chỉ ghi khoá trong ENV_FIELDS. Ô bí mật để trống = giữ nguyên; muốn xoá thì đưa vào `clear`."""
    clear = set(clear or [])
    changes = {}
    for key, value in (updates or {}).items():
        if key not in ENV_KEYS:
            raise SetupError(f"Không cho sửa biến {key} qua giao diện.")
        value = str(value or "").strip()
        if "\n" in value or "\r" in value:
            raise SetupError(f"{key}: không được có xuống dòng.")
        if ENV_KEYS[key]["secret"] and not value:
            continue
        changes[key] = value
    for key in clear:
        if key not in ENV_KEYS:
            raise SetupError(f"Không cho xoá biến {key} qua giao diện.")
        changes[key] = ""
    lines, seen = _env_lines(), set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip() if "=" in line and not line.strip().startswith("#") else None
        if key in changes:
            lines[i] = f"{key}={changes[key]}"
            seen.add(key)
    lines += [f"{k}={v}" for k, v in changes.items() if k not in seen]
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        ENV_PATH.chmod(0o600)
    except OSError:
        pass
    for key, value in changes.items():
        os.environ[key] = value   # load_dotenv không ghi đè biến đã có → cập nhật trực tiếp cho tiến trình này
    return get_env()


def test_llm() -> dict:
    """Một lời gọi tool-calling rất nhỏ: xác nhận key/model/base URL dùng được."""
    from qctool.agent.llm_provider import load_llm_provider
    started = time.monotonic()
    try:
        llm = load_llm_provider()
        tool = {"type": "function", "function": {"name": "ping", "description": "Reply ping.",
                                                  "parameters": {"type": "object", "properties": {}}}}
        response = llm.chat([{"role": "system", "content": "Call the ping tool."},
                             {"role": "user", "content": "ping"}], [tool], max_tokens=30)
    except Exception as exc:  # noqa: BLE001
        message = getattr(exc, "safe_message", None) or f"{type(exc).__name__}: {exc}"
        return {"ok": False, "error": message, "seconds": round(time.monotonic() - started, 1)}
    called = [c["function"]["name"] for c in response.get("tool_calls") or []]
    return {"ok": True, "tool_calling": "ping" in called, "seconds": round(time.monotonic() - started, 1),
            "model": os.environ.get("QCTOOL_LLM_MODEL", "")}


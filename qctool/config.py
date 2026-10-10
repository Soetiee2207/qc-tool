"""Đọc cấu hình và bí mật từ biến môi trường.

Quy tắc bất di bất dịch của repo này: **không hard-code credential**.
Bí mật đi qua `.env` (đã gitignore) hoặc biến môi trường thật.

Vì sao khắt khe kể cả khi hệ thống do chính mình làm: mục tiêu là tool dùng được
cho nhiều hệ thống. Hard-code bây giờ thì lúc chạy CI cho hệ thống của người khác
sẽ phải viết lại — và tệ hơn, credential sẽ nằm vĩnh viễn trong lịch sử git.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

AUTH_MODES = {"password", "token", "manual", "browser"}


class ConfigError(Exception):
    """Cấu hình thiếu hoặc sai."""


def load_dotenv(path: Path | None = None) -> None:
    """Nạp `.env` vào os.environ. Biến đã có sẵn trong môi trường thì không ghi đè.

    Tự viết thay vì thêm `python-dotenv`: định dạng `.env` đơn giản, và bớt một
    phụ thuộc thì tool dễ cài ở nơi khác hơn.
    """
    env_path = path or Path.cwd() / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    base_url: str
    auth_mode: str
    username: str | None = None
    password: str | None = None
    bearer_token: str | None = None
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    timeout_seconds: int = 30
    verify_ssl: bool = True

    def validate(self) -> None:
        """Kiểm tra cấu hình đủ dùng. Báo rõ thiếu gì, đừng để lỗi mơ hồ lúc chạy."""
        if self.auth_mode not in AUTH_MODES:
            raise ConfigError(
                f"QCTOOL_AUTH_MODE phải là một trong {sorted(AUTH_MODES)}, "
                f"đang là {self.auth_mode!r}"
            )
        if self.auth_mode == "password":
            missing = [
                name for name, value in
                (("QCTOOL_USERNAME", self.username), ("QCTOOL_PASSWORD", self.password))
                if not value
            ]
            if missing:
                raise ConfigError(
                    f"QCTOOL_AUTH_MODE=password cần {', '.join(missing)}. "
                    "Copy .env.example thành .env rồi điền."
                )
        if self.auth_mode == "token" and not self.bearer_token:
            raise ConfigError("QCTOOL_AUTH_MODE=token cần QCTOOL_BEARER_TOKEN.")
        if self.auth_mode == "browser":
            # `browser` là chế độ **duy nhất** được phép tự đăng nhập, nên thiếu
            # tài khoản phải báo ngay — không để tới lúc chạy mới phát hiện.
            missing = [
                name for name, value in
                (("QCTOOL_USERNAME", self.username), ("QCTOOL_PASSWORD", self.password))
                if not value
            ]
            if missing:
                raise ConfigError(
                    f"QCTOOL_AUTH_MODE=browser cần {', '.join(missing)}. "
                    "Copy .env.example thành .env rồi điền."
                )

    def redacted(self) -> str:
        """Bản in ra được — không lộ bí mật. Dùng khi log."""
        def mask(value: str | None) -> str:
            if not value:
                return "(chưa đặt)"
            return value[:2] + "…" + value[-1:] if len(value) > 3 else "…"

        return "\n".join([
            f"  base_url     : {self.base_url}",
            f"  auth_mode    : {self.auth_mode}",
            f"  username     : {self.username or '(chưa đặt)'}",
            f"  password     : {mask(self.password)}",
            f"  bearer_token : {mask(self.bearer_token)}",
            f"  timeout      : {self.timeout_seconds}s",
            f"  verify_ssl   : {self.verify_ssl}",
        ])


def load_config() -> Config:
    load_dotenv()
    return Config(
        base_url=os.environ.get("QCTOOL_BASE_URL", "").rstrip("/"),
        auth_mode=os.environ.get("QCTOOL_AUTH_MODE", "manual"),
        username=os.environ.get("QCTOOL_USERNAME") or None,
        password=os.environ.get("QCTOOL_PASSWORD") or None,
        bearer_token=os.environ.get("QCTOOL_BEARER_TOKEN") or None,
        oidc_issuer=os.environ.get("QCTOOL_OIDC_ISSUER") or None,
        oidc_client_id=os.environ.get("QCTOOL_OIDC_CLIENT_ID") or None,
        timeout_seconds=int(os.environ.get("QCTOOL_TIMEOUT_SECONDS", "30")),
        verify_ssl=_flag("QCTOOL_VERIFY_SSL", True),
    )


# ── File project (`projects/<tên>/qctool.yaml`) ─────────────────────────────
# Dạng gọn được mở rộng thành đúng dạng đầy đủ mà PipelineConfig.from_file đọc,
# nên logic chạy không đổi. Dạng đầy đủ vẫn dùng được và luôn thắng dạng gọn.

AGENT_BUDGET = {"max_turns": 14, "max_tokens": 90000, "max_seconds": 480, "completion_tokens": 2200}


def feature_name(path: Path) -> str:
    """`projects/customer/qctool.yaml` → `customer`; `x/foo.yaml` → `foo`."""
    return path.parent.name if path.name == "qctool.yaml" else path.stem


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for key, value in over.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def project_file(feature_config: Path) -> Path | None:
    """`projects/<p>/<f>/qctool.yaml` → `projects/<p>/project.yaml` nếu có."""
    candidate = feature_config.parent.parent / "project.yaml"
    return candidate if feature_config.name == "qctool.yaml" and candidate.is_file() else None


def expand_project(data: dict, path: Path, repo: Path | None = None) -> dict:
    """Dạng gọn → dạng đầy đủ. Feature thắng project; khoá tường minh thắng mặc định.

    Mặc định theo thư mục feature: tài liệu là chính thư mục (nếu có urd.md/srs.md),
    `openapi.yaml` nếu có, output vào `<feature>/artifacts/`.
    """
    import yaml
    if shared := project_file(path):
        base = yaml.safe_load(shared.read_text(encoding="utf-8")) or {}
        if not isinstance(base, dict):
            raise ConfigError(f"{shared} phải là YAML mapping.")
        data = _merge(base, data)
    data = dict(data)
    here = path.parent
    if path.name == "qctool.yaml":
        if "docs" not in data and "docs_dir" not in data and any((here / n).is_file() for n in ("urd.md", "srs.md")):
            data["docs_dir"] = "."
        if "openapi" not in data and (here / "openapi.yaml").is_file():
            data["openapi"] = "openapi.yaml"
        if "dir" not in (data.get("out") or {}):
            data["out"] = {**(data.get("out") or {}), "dir": "artifacts"}
    for short, long in (("docs", "docs_dir"), ("web", "web_url")):
        if short in data:
            data.setdefault(long, data.pop(short))
    if "api" in data:
        data["run"] = {"base_url": data.pop("api"), **(data.get("run") or {})}
    if isinstance(data.get("llm"), bool):
        data["llm"] = {"enabled": data["llm"]}
    data.setdefault("feature", feature_name(path))
    data.setdefault("module", data["feature"].upper().replace("-", "_"))
    gen = dict(data.get("generation") or {})
    gen.setdefault("budget", dict(AGENT_BUDGET))
    data["generation"] = gen
    if "account" in data:
        data = _expand_account(data, path, repo or Path.cwd())
    return data


def _expand_account(data: dict, path: Path, repo: Path) -> dict:
    """`account:` → test_fixtures (bindings + acquisition) cho đúng các AC liệt kê.

    Chỉ AC nằm trong `login_for` nhận tài khoản — AC kiểu "sai mật khẩu" không được
    bind ngầm. Credential luôn lấy từ env, không bao giờ từ YAML.
    """
    account = data.pop("account")
    if not isinstance(account, dict) or not isinstance(account.get("login_for"), list):
        raise ConfigError("account cần `login_for: [<AC>, …]`, ví dụ `login_for: [001-1, 001-3]`.")
    name = account.get("name", "active_user")
    facts = {"role": account.get("role", "user"), "account_state": account.get("state", "active")}
    aliases = [f"{name}.email", f"{name}.password"]
    proven = {"account_exists": True, "password_valid": True, "account_state": facts["account_state"]}
    docs = Path(data.get("docs_dir") or ".")
    docs = (docs if docs.is_absolute() else path.parent / docs).resolve()
    try:
        urd = docs.relative_to(repo.resolve()) / "urd.md"
    except ValueError:
        urd = docs / "urd.md"
    feature = data["feature"]
    bindings, requirements = {}, {}
    for raw in account["login_for"]:
        short = str(raw).removeprefix("AC-").removeprefix(f"{feature}-")
        ac = f"AC-{feature}-{short}"
        bindings[ac] = {"email": aliases[0], "password": aliases[1], "correct_password": aliases[1]}
        requirements[ac] = [{"fixture": name, "aliases": list(aliases), "facts": dict(proven),
                             "require_verified": False, "source_ref": f"{urd.as_posix()}:AC-{short}"}]
    data.setdefault("auth", {}).setdefault("mode", "browser")
    data["test_fixtures"] = {
        "fixtures": {name: {"email": {"env": "QCTOOL_USERNAME"}, "password": {"env": "QCTOOL_PASSWORD"},
                            "facts": facts}},
        "bindings": bindings,
        "acquisition": {"requirements": requirements, "evidence": [{
            "fixture": name, "facts": {**proven, "role": facts["role"]}, "assurance": "DECLARED",
            "source_ref": f"operator:confirmed-existing-{facts['role']}-account"}]},
        **(data.get("test_fixtures") or {}),
    }
    return data

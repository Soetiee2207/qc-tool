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

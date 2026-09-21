"""Chuẩn hoá ID tài liệu → ID canonical.

Tài liệu login-sso dùng `F-01`, `NFR-SEC-01`. Quy ước của repo portal
(`.kimi-code/rules/brainstorm/naming-conventions.md`) lại yêu cầu
`FR-{feature}-{NNN}` / `NFR-{feature}-{NNN}`, với lý do nêu rõ:

    "Feature prefix bắt buộc cho BO/CAP/FR/NFR/BR/E. Mục đích: tránh collision
     khi /gap cross-feature aggregate (vd FR-001 ambiguous khi 2 features)."

`F-01` đúng là dạng ambiguous đó. Nên tool map sang canonical, nhưng **giữ ID gốc**
trong `source_ids[]` để truy vết ngược về tài liệu vẫn được.
"""

from __future__ import annotations

import re

US_RE = re.compile(r"^US-(\d{3})$")
# Bắt cả phần đuôi số (nhóm 1) và phần feature (nhóm 2) — để `base_us_id` dựng
# lại được ID gốc `US-001` từ `US-login-sso-001`.
US_CANON_RE = re.compile(r"^(US)-([\w\-]+)-(\d{3})$")
AC_RE = re.compile(r"^AC-(\d{3})-(\d+)$")
FR_RE = re.compile(r"^F-(\d{2})$")
# `[A-Z0-9]+` chứ không phải `[A-Z]+`: nhóm i18n viết là `I18N`, có chữ số ở giữa.
NFR_RE = re.compile(r"^NFR-([A-Z0-9]+)-(\d{2})$")


def canonical(requirement_id: str, feature: str) -> str:
    """Map ID trong tài liệu sang ID canonical, có tiền tố feature.

    **Mọi loại ID đều được scope theo feature**, kể cả `US`/`AC`. Trước đây US/AC
    giữ nguyên với lý do "quy ước đã scope chúng qua đường dẫn feature" — đúng khi
    mỗi lần ingest chỉ đọc **một** feature. Sai ngay khi đọc cả cây tài liệu: repo
    portal có 15 feature cùng đánh số `US-001`, nên chúng đè lên nhau và `_dedupe`
    âm thầm bỏ mất requirement.

    Quy ước của chính repo portal cũng yêu cầu tiền tố feature cho mọi loại ID
    (xem docstring đầu file). Đổi ở đây cho khớp, và để ID **ổn định**: thêm một
    feature mới vào cây không được làm ID của feature cũ đổi theo.

    >>> canonical("F-01", "login-sso")
    'FR-login-sso-001'
    >>> canonical("NFR-SEC-01", "login-sso")
    'NFR-login-sso-001'
    >>> canonical("US-001", "login-sso")
    'US-login-sso-001'
    >>> canonical("AC-001-2", "login-sso")
    'AC-login-sso-001-2'
    """
    if m := US_RE.match(requirement_id):
        return f"US-{feature}-{m.group(1)}"

    if m := AC_RE.match(requirement_id):
        return f"AC-{feature}-{m.group(1)}-{m.group(2)}"

    if m := FR_RE.match(requirement_id):
        return f"FR-{feature}-{int(m.group(1)):03d}"

    if m := NFR_RE.match(requirement_id):
        # Số thứ tự cấp ở chỗ khác (xem allocate_nfr_numbers) — ở đây chỉ giữ đuôi
        return f"NFR-{feature}-{m.group(2)}"

    return requirement_id


def is_us(requirement_id: str) -> bool:
    """ID này có phải user story, ở dạng gốc (`US-001`) hay canonical?"""
    return bool(US_RE.match(requirement_id) or US_CANON_RE.match(requirement_id))


def base_us_id(requirement_id: str) -> str:
    """Bỏ tiền tố feature khỏi ID user story, nếu có.

    >>> base_us_id("US-login-sso-001")
    'US-001'
    >>> base_us_id("US-001")
    'US-001'
    """
    m = US_CANON_RE.match(requirement_id)
    if m:
        return f"{m.group(1)}-{m.group(3)}"
    return requirement_id


def nfr_category(requirement_id: str) -> str | None:
    """Nhóm của một NFR: SEC / PERF / AVAIL / I18N / OBS."""
    m = NFR_RE.match(requirement_id)
    return m.group(1) if m else None


def nfr_group_order(requirement_id: str) -> str:
    """Khoá sắp xếp để NFR cùng nhóm đứng cạnh nhau, đúng thứ tự tài liệu."""
    m = NFR_RE.match(requirement_id)
    if not m:
        return requirement_id
    return f"{m.group(1)}-{m.group(2)}"


def allocate_nfr_numbers(source_ids: list[str], feature: str) -> dict[str, str]:
    """Cấp số tuần tự cho NFR theo thứ tự xuất hiện trong tài liệu.

    Vì sao cần: tài liệu đánh số theo nhóm (`NFR-SEC-01`), nên `NFR-PERF-01` và
    `NFR-SEC-01` cùng là `-01`. Canonical `NFR-{feature}-{NNN}` cần số **duy nhất**,
    nếu không hai NFR khác nhau sẽ đụng ID.

    Nhóm (`SEC`, `PERF`, …) không mất — nó được giữ ở field `category`.
    """
    mapping: dict[str, str] = {}
    for index, source_id in enumerate(source_ids, start=1):
        mapping[source_id] = f"NFR-{feature}-{index:03d}"
    return mapping

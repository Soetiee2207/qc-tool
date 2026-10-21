"""Test cho chặng ingest.

Chạy: uv run python -m pytest tests/ -v

Mỗi test ở đây ứng với một bug **đã gặp thật** khi parse tài liệu login-sso,
hoặc một tính chất phải giữ. Không viết test cho thứ chưa từng hỏng.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qctool.ingest import ids  # noqa: E402
from qctool.ingest.markdown import _cells, _tables, parse_srs_nfr, parse_urd  # noqa: E402
from qctool.core.model import Requirement  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


# ── Hồi quy: 3 bug parser đã gặp thật ────────────────────────────────────────
def test_cells_respect_escaped_pipe():
    """Bug: ô chứa `\\|` bị cắt làm đôi, mọi cột sau lệch một ô.

    Tài liệu viết `string\\|null` cho kiểu union. Cắt thẳng theo `|` thì
    'string|null' thành 2 ô riêng.
    """
    row = "| 2 | `keycloak_issuer` | string\\|null | OIDC issuer URL |"
    cells = _cells(row)
    assert cells == ["2", "`keycloak_issuer`", "string|null", "OIDC issuer URL"], cells
    assert len(cells) == 4


def test_tables_skip_blank_line_before_table():
    """Bug: dòng trống giữa tiêu đề và bảng làm bảng đọc ra rỗng.

    Tài liệu thật có dạng `**Acceptance Criteria**` rồi dòng trống rồi mới
    tới bảng — không nhảy qua dòng trống thì mất sạch acceptance criteria.
    """
    lines = [
        "**Acceptance Criteria**",
        "",
        "| ID | Given | When | Then |",
        "| --- | --- | --- | --- |",
        "| AC-001-1 | a | b | c |",
    ]
    rows, _ = _tables(lines, 1)
    assert rows == [["AC-001-1", "a", "b", "c"]], rows


def test_tables_drop_header_row_by_position():
    """Hàng tiêu đề nhận diện bằng vị trí (ngay trước dòng `---`), không bằng tên cột."""
    lines = [
        "| HTTP | Condition | detail / code |",
        "| --- | --- | --- |",
        "| 401 | Missing Bearer | UNAUTHORIZED |",
    ]
    rows, _ = _tables(lines, 0)
    assert len(rows) == 1
    assert rows[0][0] == "401"


def test_nfr_group_with_digits_in_name():
    """Bug: `[A-Z]+` không khớp `I18N` vì tên nhóm có chữ số.

    Mất cả nhóm I18N (2 requirement) mà không báo lỗi.
    """
    assert ids.nfr_category("NFR-I18N-01") == "I18N"
    assert ids.nfr_category("NFR-SEC-01") == "SEC"


# ── Canonical ID ─────────────────────────────────────────────────────────────
def test_canonical_fr_gets_feature_prefix():
    assert ids.canonical("F-01", "login-sso") == "FR-login-sso-001"
    assert ids.canonical("F-10", "login-sso") == "FR-login-sso-010"


def test_canonical_nfr_gets_feature_prefix():
    assert ids.canonical("NFR-SEC-01", "payment") == "NFR-payment-01"


def test_canonical_us_and_ac_get_feature_prefix():
    """US/AC **cũng** phải có tiền tố feature.

    Trước đây chúng giữ nguyên ID gốc với lý do "quy ước đã scope qua đường dẫn
    feature" — chỉ đúng khi mỗi lần đọc một feature. Repo portal có 15 feature
    cùng đánh số `US-001`; đọc cả cây mà không prefix thì chúng đè lên nhau và
    `_dedupe` âm thầm bỏ mất requirement.
    """
    assert ids.canonical("US-001", "login-sso") == "US-login-sso-001"
    assert ids.canonical("AC-001-1", "login-sso") == "AC-login-sso-001-1"
    # ID gốc vẫn giữ được trong `source_ids` để truy vết ngược về tài liệu
    assert ids.base_us_id("US-login-sso-001") == "US-001"
    assert ids.is_us("US-001") and ids.is_us("US-login-sso-001")


def test_nfr_numbers_unique_across_groups():
    """Bug tiềm ẩn: tài liệu đánh số theo nhóm nên `NFR-SEC-01` và `NFR-PERF-01`
    cùng đuôi `-01`. Canonical phải cấp số duy nhất, nếu không hai NFR khác nhau
    đụng ID và requirement sau ghi đè requirement trước.
    """
    source = ["NFR-SEC-01", "NFR-SEC-02", "NFR-PERF-01", "NFR-I18N-01"]
    mapping = ids.allocate_nfr_numbers(source, "login-sso")
    assert len(set(mapping.values())) == 4, mapping
    assert mapping == {
        "NFR-SEC-01": "NFR-login-sso-001",
        "NFR-SEC-02": "NFR-login-sso-002",
        "NFR-PERF-01": "NFR-login-sso-003",
        "NFR-I18N-01": "NFR-login-sso-004",
    }


# ── Content hash ─────────────────────────────────────────────────────────────
def _req(**kw) -> Requirement:
    base = {"id": "FR-x-001", "kind": "functional", "title": "t"}
    return Requirement(**{**base, **kw})


def test_hash_stable_for_same_content():
    assert _req(statement="abc").content_hash == _req(statement="abc").content_hash


def test_hash_changes_when_statement_changes():
    assert _req(statement="abc").content_hash != _req(statement="xyz").content_hash


def test_hash_ignores_source_line_number():
    """Chèn một dòng ở đầu file không được làm mọi requirement đổi hash —
    nếu không, sửa một chỗ sẽ vô hiệu hoá toàn bộ testcase đã review.
    """
    from qctool.core.model import SourceRef

    a = _req(statement="abc", source=SourceRef(file="srs.md", line=10, quote="q"))
    b = _req(statement="abc", source=SourceRef(file="srs.md", line=999, quote="q"))
    assert a.content_hash == b.content_hash


def test_hash_covers_api_spec():
    """Đổi đặc tả API là đổi ngữ nghĩa — hash phải đổi, để testcase sinh lại."""
    from qctool.core.model import ApiSpec

    plain = _req()
    with_api = _req(api=ApiSpec(endpoint="GET /x", method="GET"))
    assert plain.content_hash != with_api.content_hash


# ── Parser trên fixture ──────────────────────────────────────────────────────
def test_parse_fixture_urd():
    reqs, warns = parse_urd(FIXTURES / "urd.md", "demo")
    kinds = [r.kind for r in reqs]
    assert kinds.count("user_story") == 2
    assert kinds.count("acceptance_criterion") == 3
    assert not warns

    us = next(r for r in reqs if r.id == "US-demo-001")
    assert us.as_a == "nhân viên"
    assert us.i_want == "đăng nhập một lần"
    assert us.source_ids == ["US-001"], "giữ ID gốc để truy vết về tài liệu"

    ac = next(r for r in reqs if r.id == "AC-demo-001-1")
    assert ac.belongs_to == "US-demo-001", "trỏ tới US canonical, không phải ID gốc"
    assert ac.source_ids == ["AC-001-1"]
    assert ac.given and ac.when and ac.then


def test_parse_fixture_nfr_all_five_groups():
    reqs, warns = parse_srs_nfr(FIXTURES / "srs.md", "demo")
    assert not warns
    assert len(reqs) == 5, [r.id for r in reqs]
    categories = {r.category for r in reqs}
    assert categories == {"SEC", "PERF", "AVAIL", "I18N", "OBS"}
    assert len({r.id for r in reqs}) == 5, "canonical ID phải duy nhất"


# ── Hồi quy: đọc cả cây tài liệu, và luồng nghiệp vụ ────────────────────────
def test_discover_features_finds_nested(tmp_path):
    """Thư mục cha chứa nhiều feature con — phải quét đệ quy tìm ra hết."""
    from qctool.ingest import discover_features

    (tmp_path / "a" / "feat-one").mkdir(parents=True)
    (tmp_path / "a" / "feat-one" / "urd.md").write_text("x", encoding="utf-8")
    (tmp_path / "b" / "feat-two").mkdir(parents=True)
    (tmp_path / "b" / "feat-two" / "srs.md").write_text("x", encoding="utf-8")
    # Thư mục không liên quan — không được nhặt
    (tmp_path / "OAS").mkdir()
    (tmp_path / "OAS" / "urd.md").write_text("x", encoding="utf-8")

    found = [p.name for p in discover_features(tmp_path)]
    assert sorted(found) == ["feat-one", "feat-two"]


def test_ingest_parent_dir_reads_all_features(tmp_path):
    """Trỏ vào thư mục CHA không được báo '0 requirement'.

    Đây là lỗi người dùng gặp thật: trỏ vào `docs/` của repo (29 feature con nằm
    trong thư mục riêng), tool tìm `urd.md` ở cấp gốc, không thấy, rồi kết luận
    không đọc được requirement nào.
    """
    from qctool.ingest import ingest_feature

    for name, us in (("alpha", "US-001"), ("beta", "US-001")):
        d = tmp_path / "group" / name
        d.mkdir(parents=True)
        (d / "urd.md").write_text(
            f"### {us} — Chức năng {name}\n\n**As a** user\n**I want** x\n"
            f"**So that** y\n\n**Acceptance Criteria**\n\n"
            f"| ID | Given | When | Then |\n|---|---|---|---|\n"
            f"| AC-001-1 | a | b | c |\n",
            encoding="utf-8",
        )

    data = ingest_feature(tmp_path, None)
    ids = [r["id"] for r in data["requirements"]]
    assert len(data["features"]) == 2
    # Cùng `US-001` nhưng khác feature ⇒ ID phải khác nhau, không đè lên nhau
    assert "US-alpha-001" in ids and "US-beta-001" in ids
    assert len(ids) == len(set(ids)), "ID trùng giữa các feature"


def test_extract_flows_from_sequence_and_state(tmp_path):
    """Đọc được sequence diagram, state machine, và bảng quyết định."""
    from qctool.ingest import flows as flows_mod

    srs = tmp_path / "srs"
    srs.mkdir()
    (srs / "x-flows.md").write_text(
        "## 1. Luồng đăng nhập\n\n```mermaid\nsequenceDiagram\n"
        "    User->>FE: Open /projects\n"
        "    FE->>User: Redirect /login\n"
        "    User->>FE: Click Sign in\n```\n",
        encoding="utf-8",
    )
    (srs / "x-states.md").write_text(
        "```mermaid\nstateDiagram-v2\n"
        "    Loading --> Authenticated: check-sso OK\n"
        "    Authenticated --> Unauthenticated: logout\n```\n",
        encoding="utf-8",
    )
    brain = tmp_path / "brainstorms"
    brain.mkdir()
    (brain / "b.md").write_text(
        "## 6. Behavior\n\n### 6.1 Decision Points\n\n"
        "| ID | Flow | Khi nào | YES | NO |\n|---|---|---|---|---|\n"
        "| D1 | Login | keycloak enabled? | Init PKCE | authError |\n",
        encoding="utf-8",
    )

    warnings: list[str] = []
    data = flows_mod.extract(tmp_path, "demo", warnings)

    assert data["counts"]["flow"] == 1
    assert data["counts"]["transition"] == 2
    assert data["counts"]["decision"] == 1
    flow = data["flow"][0]
    assert len(flow["steps"]) == 3
    assert flow["steps"][0]["action"] == "Open /projects"

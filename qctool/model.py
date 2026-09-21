"""Mô hình dữ liệu cho requirement — trung tâm của chặng ingest.

Nguyên tắc thiết kế:

1. **Dùng dataclass stdlib**, không thêm pydantic. Model này chỉ để mang dữ liệu,
   không cần validate phức tạp. Ít phụ thuộc = dễ cài ở nơi khác.

2. **`content_hash` chỉ tính trên nội dung ngữ nghĩa**, KHÔNG tính số dòng hay vị trí.
   Nhờ vậy: sửa lỗi chính tả ở chỗ khác trong file → requirement không đổi hash
   → testcase cũ giữ nguyên. Chỉ khi câu chữ của chính requirement đổi thì hash mới đổi.

3. **`source_ids` giữ ID gốc trong tài liệu** (`F-01`), song song với `id` canonical
   (`FR-login-sso-001`). Người đọc SRS thấy `F-01`, người đọc testcase thấy
   `FR-login-sso-001`, và hai bên vẫn nối được với nhau.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SourceRef:
    """Requirement này nằm ở đâu trong tài liệu gốc."""

    file: str          # đường dẫn tương đối tới gốc feature
    line: int          # số dòng bắt đầu
    quote: str         # trích nguyên văn — để người đọc đối chiếu được

    def to_dict(self) -> dict:
        return {"file": self.file, "line": self.line, "quote": self.quote}


@dataclass
class ApiSpec:
    """Đặc tả API gắn với một functional requirement (nếu tài liệu có)."""

    endpoint: str | None = None
    method: str | None = None
    auth: str | None = None
    request: list[dict] = field(default_factory=list)
    response: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    flow: list[str] = field(default_factory=list)
    error_handling: list[dict] = field(default_factory=list)
    implementation: str | None = None

    def is_empty(self) -> bool:
        return not any([
            self.endpoint, self.method, self.auth,
            self.request, self.response, self.errors,
            self.flow, self.error_handling, self.implementation,
        ])

    def to_dict(self) -> dict:
        out: dict = {}
        if self.endpoint:
            out["endpoint"] = self.endpoint
        if self.method:
            out["method"] = self.method
        if self.auth:
            out["auth"] = self.auth
        if self.flow:
            out["flow"] = self.flow
        if self.implementation:
            out["implementation"] = self.implementation
        if self.request:
            out["request"] = self.request
        if self.response:
            out["response"] = self.response
        if self.errors:
            out["errors"] = self.errors
        if self.error_handling:
            out["error_handling"] = self.error_handling
        return out


@dataclass
class Requirement:
    """Một yêu cầu — dù là user story, functional hay non-functional."""

    id: str                          # canonical: FR-login-sso-001
    kind: str                        # user_story | acceptance_criterion | functional | non_functional
    title: str
    # Feature mà requirement này thuộc về. Cần khi ingest cả cây tài liệu: nhiều
    # feature cùng đánh số `US-001`, nên chỉ nhìn ID không biết nó của feature nào.
    feature: str = ""
    source_ids: list[str] = field(default_factory=list)
    statement: str = ""
    category: str | None = None      # với NFR: SEC / PERF / AVAIL / I18N / OBS
    traces_to: list[str] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)
    # user story
    as_a: str | None = None
    i_want: str | None = None
    so_that: str | None = None
    belongs_to: str | None = None    # với AC: US chứa nó
    # acceptance criterion (Given/When/Then)
    given: str | None = None
    when: str | None = None
    then: str | None = None
    # functional
    api: ApiSpec | None = None
    source: SourceRef | None = None

    # ── hash ────────────────────────────────────────────────────────────────
    def _semantic_payload(self) -> dict:
        """Phần nội dung quyết định danh tính của requirement.

        Cố ý KHÔNG đưa `source.line` vào: chèn một dòng ở đầu file không được
        làm mọi requirement đổi hash.
        """
        payload: dict = {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "statement": self.statement,
        }
        for key in ("category", "as_a", "i_want", "so_that", "given", "when", "then"):
            value = getattr(self, key)
            if value:
                payload[key] = value
        if self.traces_to:
            payload["traces_to"] = self.traces_to
        if self.acceptance:
            payload["acceptance"] = self.acceptance
        if self.api is not None and not self.api.is_empty():
            payload["api"] = self.api.to_dict()
        return payload

    @property
    def content_hash(self) -> str:
        blob = json.dumps(self._semantic_payload(), sort_keys=True, ensure_ascii=False)
        return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        out: dict = {"id": self.id}
        if self.feature:
            out["feature"] = self.feature
        if self.source_ids and self.source_ids != [self.id]:
            out["source_ids"] = self.source_ids
        out["kind"] = self.kind
        if self.category:
            out["category"] = self.category
        if self.belongs_to:
            out["belongs_to"] = self.belongs_to
        out["title"] = self.title
        for key in ("as_a", "i_want", "so_that", "given", "when", "then", "statement"):
            value = getattr(self, key)
            if value:
                out[key] = value
        if self.traces_to:
            out["traces_to"] = self.traces_to
        if self.acceptance:
            out["acceptance"] = self.acceptance
        if self.api is not None and not self.api.is_empty():
            out["api"] = self.api.to_dict()
        out["content_hash"] = self.content_hash
        if self.source is not None:
            out["source"] = self.source.to_dict()
        return out


@dataclass
class Attachment:
    """Tài liệu phụ (flows, states, wireframe) — ghi hash để biết khi nào đổi,
    nhưng chưa parse sâu ở M01."""

    path: str
    doc_type: str
    sha256: str

    def to_dict(self) -> dict:
        return {"path": self.path, "type": self.doc_type, "sha256": self.sha256}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

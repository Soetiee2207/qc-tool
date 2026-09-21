---
type: finding
status: open
created: 2026-09-18
updated: 2026-09-18
lang: vi
owner: "@binhhm"
source: docs/authentication/login-sso/srs.md, docs/authentication/login-sso/urd.md
source_hash: "sha256:54b4c13e4685c50cd2118c36a5153992ec344ceeb94afecbf866b88542ed763d"
links: [docs/brainstorms/2026-09-18-qc-automation-tool.md]
tags: [login-sso, doc-quality, testability]
changelog:
  - 2026-09-18 | manual | rà SRS/URD login-sso; 10 phát hiện (P1–P10) + 1 xác nhận khớp hệ thống thật
---

# Review tài liệu login-sso — 2026-09-18

> Phát hiện khi rà `srs.md` / `urd.md` để chuẩn bị làm ground cho tool QC.
> Đây là **phát hiện về tài liệu**, chưa sửa gì. Chưa đẩy sang repo portal — xem Mục cuối.

Nguồn rà:

| File | SHA-256 |
|---|---|
| `srs.md` | `54b4c13e…763d` |
| `urd.md` | `952f94ce…1bd` |

Repo portal tại thời điểm rà: commit `1104150`.

## Tổng hợp

| # | Phát hiện | Mức | Ảnh hưởng tới tool |
|---|---|---|---|
| P1 | NFR-AVAIL-02 trỏ tới mục "Unresolved" không tồn tại | Trung bình | Traceability đứt |
| P2 | 7/10 function không có API spec, chỉ có Implementation | **Cao** | Không sinh được case cho 7 function |
| P3 | Khối "Error handling" + "Location" + "Auth" lặp y hệt ở 7 function | **Cao** | Error behaviour thật không được đặc tả |
| P4 | "Auth: … (except F-01, F-03 pre-login)" mâu thuẫn với F-02 check-sso | Trung bình | Sai precondition |
| P5 | 13 NFR không trace về US/AC nào | Trung bình | Orphan khi build traceability |
| P6 | AC-002-1/2 tham chiếu module Users + `user:view` — SRS ghi OUT of scope | Trung bình | Scope conflict |
| P7 | F-01 Flow bước 1 câu bị cụt, thiếu hệ quả | Thấp | Precondition mơ hồ |
| P8 | Error envelope 401 thực tế lồng `detail.error.code`, SRS không đặc tả | Thấp | Assert shape sai nếu tin doc |
| P9 | **Xác nhận**: `/auth/config` khớp chính xác SRS | — | Tài liệu đáng tin làm ground |
| P10 | Hệ ID trong tài liệu không khớp quy ước ID của chính repo | Trung bình | Phải có bảng map ID trước khi build traceability |

## Chi tiết

### P1 — Tham chiếu treo tới "Unresolved"

`srs.md:528` — NFR-AVAIL-02 kết thúc bằng `(xem Unresolved)`. **Không có mục Unresolved nào** trong
`srs.md` (heading cuối là `### 4.5. Observability (NFR-OBS)` tại dòng 537).

→ Traceability đứt. Sinh testcase cho NFR-AVAIL-02 sẽ không biết kỳ vọng gì.

### P2 — 7/10 function không có API specification

| Function | Có API spec? |
|---|---|
| F-01 Get auth config | ✅ §3.2.1 |
| F-04 Load session profile | ✅ §3.2.4 |
| F-05 Patch preferred locale | ✅ §3.2.5 |
| F-02, F-03, F-06, F-07, F-08, F-09, F-10 | ❌ chỉ có "B. Implementation" |

→ 70% function không sinh được **technical testcase** (chỉ sinh được acceptance case từ `urd.md`).
Đây là lý do trực tiếp khiến D2 (nguồn ground cho API) phải chốt sớm.

### P3 — Boilerplate lặp y hệt ở 7 function

Bảy function F-02, F-03, F-06, F-07, F-08, F-09, F-10 dùng **cùng một** khối:

```markdown
**Location:** `frontend/src/shared/auth/AuthProvider.tsx`, `RequirePermission.tsx`, `LoginScreen.tsx`

**Auth:** Session must be authenticated (except F-01, F-03 pre-login)

**Error handling**

| Condition | Behavior |
| --- | --- |
| Init timeout | Show login, optional authError |
| Refresh fail | clearSession → /login |
| Unsafe callback | defaultHomePath(permissions) |
```

Vấn đề: F-07 (token refresh) và F-10 (upload reauth) rõ ràng có error behaviour **khác** —
`login-sso-states.md` mô tả `SoftExpired` + `UploadSessionBanner` amber, `urd.md` AC-006-1 mô tả
banner reauth. Nhưng bảng error handling của F-07/F-10 lại y hệt F-02.

→ **Error behaviour thật của 7 function không được đặc tả.** Sinh negative case từ đây sẽ ra case sai.

### P4 — Mâu thuẫn về auth precondition

F-02 là "Init Keycloak check-sso" — chạy **trước** khi đăng nhập, theo đúng
`login-sso-flows.md` §3 ("FE->>KC: init onLoad check-sso … No session → Show LoginScreen").
Nhưng dòng `Auth:` của F-02 lại ghi "Session must be authenticated (except F-01, **F-03** pre-login)".
F-02 không nằm trong danh sách exception.

→ Precondition sinh ra cho F-02 sẽ sai (yêu cầu session đã auth trong khi mục đích hàm là kiểm tra
lúc chưa auth).

### P5 — NFR không trace

13 NFR (`NFR-SEC-01..04`, `NFR-PERF-01..03`, `NFR-AVAIL-01..02`, `NFR-I18N-01..02`, `NFR-OBS-01..02`)
không có cột traceability về US/AC. 10 FR thì có (`**Traceability:** US-00x` ở mỗi §3.2).

Thêm: một số NFR không nêu cách đo — `NFR-OBS-01` "401/403 rates **monitorable**" — monitorable
bằng gì, ngưỡng nào? Không kiểm chứng được thì không test được.

→ Validator sẽ báo 11 orphan. Đây là gap thật, không phải lỗi tool.

### P6 — Scope conflict giữa URD và SRS

`urd.md` AC-002-1: *"User có `project:view` only → Nav Projects visible; **Users hidden**"*
`urd.md` AC-002-2: *"User thiếu `user:view` → Navigate `/users` → Redirect `/forbidden`"*

`srs.md` §1.2 Scope ghi rõ **OUT: "Admin user CRUD"**, và §2.2 chỉ định nghĩa
`DEFAULT_PERMISSIONS = project:view + settings:view` — **không có `user:view`**.

→ AC-002-1/2 test một thứ nằm ngoài scope SRS. Cần chốt: bỏ AC, hay bổ sung Users module vào scope.

### P7 — Câu bị cụt ở F-01

`srs.md` §3.2.1 Flow bước 1: *"`resolveKeycloakInit()` — nếu thiếu VITE_KEYCLOAK_*"* — câu không có
vế hệ quả (thiếu thì sao? fallback về đâu?).

→ Precondition / expected result của F-01 mơ hồ ở nhánh lỗi cấu hình.

### P8 — Error envelope thực tế lồng, SRS không đặc tả

SRS bảng error của F-04 ghi:

| HTTP | Condition | detail / code |
|---|---|---|
| 401 | Missing/invalid Bearer | `UNAUTHORIZED` |

Thực tế trên dev:

```json
{"detail":{"error":{"code":"UNAUTHORIZED","message":"Invalid or missing bearer token","details":[]}}}
```

→ Code `UNAUTHORIZED` **đúng** (khớp doc), nhưng shape là `detail.error.code` **lồng 3 tầng**,
không phải `detail` phẳng. Nếu assert theo doc sẽ fail.

### P9 — Xác nhận khớp (điểm cộng)

`GET /api/v1/auth/config` trên `https://dev-qc-portal.datafactory.fit/` trả **200**:

```json
{"keycloak_enabled":true,"keycloak_issuer":"https://auth.datafactory.fit/realms/vd-dev","keycloak_client_id":"vd-portal","keycloak_realm":"vd-dev"}
```

Khớp **chính xác** 4 field trong bảng Response 200 của SRS §3.2.1.
IdP `https://auth.datafactory.fit/realms/vd-dev/.well-known/openid-configuration` → 200.

→ Kết luận: `srs.md` cho phần đã đặc tả là **đáng tin**. Vấn đề nằm ở phần *chưa* đặc tả (P2, P3),
không phải ở phần đã viết.

### Bổ sung — không có OpenAPI

| Endpoint | Kết quả |
|---|---|
| `GET /openapi.json` | 200 nhưng trả `index.html` (SPA fallback) |
| `GET /api/v1/openapi.json` | 404 |

→ Portal không expose spec. Ảnh hưởng trực tiếp tới D2.

### P10 — Hệ ID tài liệu không khớp quy ước ID của chính repo

`srs.md` dùng `F-01`…`F-10` cho functional requirement và `NFR-SEC-01`, `NFR-PERF-01`… cho NFR.

Nhưng quy ước của repo (`.kimi-code/rules/brainstorm/naming-conventions.md`, mục "ID conventions")
lại quy định:

| Loại | Format | Ví dụ |
|---|---|---|
| Functional Requirement | `FR-{feature}-{NNN}` | `FR-payment-001` |
| Non-Functional Requirement | `NFR-{feature}-{NNN}` | `NFR-payment-001` |

Và nêu rõ lý do: *"Feature prefix bắt buộc cho BO/CAP/FR/NFR/BR/E. Mục đích: tránh collision khi `/gap`
cross-feature aggregate (vd `FR-001` ambiguous khi 2 features)."*

→ `F-01` **chính là** dạng ambiguous mà quy ước sinh ra để chống: module Authentication cũng có `F-01`,
module Payment cũng có `F-01`. NFR thì đã có prefix nhóm (`SEC`/`PERF`) nhưng vẫn thiếu feature.

**Ảnh hưởng tới tool:** trước khi build traceability matrix, phải có **bảng map ID**:

| ID trong tài liệu | ID canonical | Giữ nguyên trong |
|---|---|---|
| `F-01` | `FR-login-sso-001` | `source_ids: ["F-01"]` |
| `NFR-SEC-01` | `NFR-login-sso-001` | `source_ids: ["NFR-SEC-01"]` |

Giữ ID gốc trong `source_ids[]` để truy vết **ngược về tài liệu** vẫn được — người đọc SRS thấy `F-01`,
người đọc testcase thấy `FR-login-sso-001`, và hai bên nối được với nhau.

Việc này thuộc M01, không phải M05 — hash và ID phải chốt ngay từ chặng ingest, không phải vá ở chặng report.

## Đề xuất xử lý

| # | Đề xuất | Ai |
|---|---|---|
| P1 | Thêm mục "Unresolved / Open questions" vào `srs.md`, hoặc bỏ tham chiếu | @binhhm |
| P2, P3 | Bổ sung API spec + error handling riêng cho F-02/F-03/F-06..F-10 | @binhhm + dev |
| P4 | Sửa dòng `Auth:` của F-02 — thêm F-02 vào exception pre-login | @binhhm |
| P5 | Thêm cột traceability cho NFR; nêu cách đo cho NFR-OBS-01 | @binhhm |
| P6 | Chốt: bỏ AC-002-1/2 hoặc đưa Users module vào scope SRS | PO |
| P7 | Viết nốt vế hệ quả của F-01 bước 1 | @binhhm |
| P8 | Ghi rõ error envelope shape vào SRS (dùng chung cho mọi endpoint) | @binhhm + dev |
| P10 | Thống nhất hệ ID: đổi `F-01` → `FR-login-sso-001` trong tài liệu, hoặc chấp nhận map ở tầng tool | @binhhm |

## Ghi chú về vị trí lưu

File này nằm trong repo `qc-tool`, **không** nằm trong repo portal. Lý do: quy ước tracking của portal
(`docs/reports/README.md`) giới hạn ở công việc sản phẩm *trong repo đó*, và mọi claim phải trace được
về commit / CR / doc path của repo đó.

Các phát hiện P1–P8, P10 **là việc của portal** (sửa tài liệu sản phẩm). Khi anh muốn, có thể chuyển thành:
- một **CR** (`docs/cr/CR-<yyyymmdd>-<nn>.md`) nếu cần đổi `srs.md`/`urd.md`, hoặc
- dòng **todo** trong `docs/reports/todo.md` §2 nếu chỉ là việc đồng bộ tài liệu.

Riêng **P10 khác bản chất** — nó là *quyết định thiết kế ID*, ảnh hưởng cả tool lẫn tài liệu.
Nên chốt trước khi làm M01.


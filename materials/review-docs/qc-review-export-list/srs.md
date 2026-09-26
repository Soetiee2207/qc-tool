<!-- doc-meta: type=srs | feature=review/qc-review-export-list | status=draft | updated=2026-09-25 -->
# **SOFTWARE REQUIREMENTS SPECIFICATION**

Export — QC Review List (Excel/CSV)

Version 1.4 | 2026-09-25

|  |  |  |  |
| --- | --- | --- | --- |
| **Version** | **Date** | **Author** | **Changes** |
| 1.4 | 2026-09-25 | @kimi-code | Selection giữ khi sang trang, chỉ reset khi đổi filter/project (DP-394) |
| 1.3 | 2026-09-22 | @binhhm | "Xuất tất cả" chạy nền; bỏ nút Xuất header, dùng `QCQueueSelectionBar` |
| 1.2 | 2026-09-11 | @binhhm | Đối chiếu code: luồng vào chế độ xuất = nút **Xuất** header → export mode bar 2 hành động (không còn 1 nút Export gọi thẳng preview); CSV build **đồng bộ in-process** (không stream); selected scope khớp cả `id` và `external_id`; bổ sung sanitize formula-injection; sửa mô tả body 403 |
| 1.1 | 2026-09-10 | @binhhm | F-02: Export/Assign giờ là 2 chế độ chọn loại trừ nhau (trước đây 1 tick cập nhật đồng thời cả 2 set); sửa Scope §1.2 khớp behavior mới |
| 1.0 | 2026-09-03 | @cursor-agent | Initial draft — kế thừa `urd.md`, brainstorm `qc-review-export-list`, wireframe `ascii-screen/` |

**Table of Contents**

1. **INTRODUCTION**

**1.1. Purpose**

- Đặc tả kỹ thuật function **Export** trên màn QC Review Listing (`QCQueue`) — Excel/CSV download.
- Đối tượng: dev frontend/backend, QA, ops.
- Kế thừa `docs/review/qc-review-export-list/urd.md`.

**1.2. Scope**

- **IN SCOPE:**
  - UI: điểm vào DUY NHẤT của Export là thanh chọn `QCQueueSelectionBar`, render khi có ≥1 dòng được tick; trong thanh có **"Xuất theo lựa chọn"** / **"Xuất tất cả {N} mục khớp lọc"** (cả hai gate `qc:result:export`) và link **"Hủy"**; dialog `QCQueueExportDialog`. Không còn nút Xuất trên header và không còn bước "bật chế độ chọn-để-xuất".
  - Modes queue: `final_qc` (route `/qc/review`, `product_line=all`), `annotation` (route `/qc/annotation`, `manual_annotation_only=true`). Nhánh `tapdata_qc` (`product_line=tapdata`) còn trong code `QCQueue` nhưng **chưa có route nào mount** — `/tapdata/qc/queue` hiện redirect về `/qc/review` (mode `final_qc`).
  - API: `POST /api/v1/qc/queue/export/preview`, `POST /api/v1/qc/queue/export` (scope `selected`), và bộ job nền `POST /api/v1/qc/queue/export/jobs` + `GET …/export/jobs/{job_id}` + `GET …/export/jobs/{job_id}/download` (scope `filtered`).
  - Format: **xlsx** (default, openpyxl write-only worksheet) hoặc **csv** (UTF-8 BOM) — build **in-process, một lần** trong request handler (scope `selected`) hoặc trong worker nền (scope `filtered`), qua `_build_csv_bytes_from_stmt` / `_build_xlsx_bytes_from_stmt`; không dùng `StreamingResponse`.
  - Scope export: `selected` (khi `item_ids` non-empty) hoặc `filtered` (all pages matching filters).
  - Selection: **một tập chọn duy nhất** (`assignSelected`) dùng chung cho cả Gán lẫn Xuất; tập này **chỉ reset khi đổi filter hoặc đổi project** (DP-394) — sang trang vẫn giữ selection.
  - 17 cột export (`EXPORT_HEADERS` trong `queue_export.py`).
  - Auth: permission `qc:result:export` + Keycloak group ∈ `QC_QUEUE_EXPORT_GROUPS`.
  - Audit log P1: `emit_event` `qc.queue.export` sau build thành công — áp dụng cho cả đường đồng bộ lẫn job nền (worker dựng file qua cùng `build_queue_export`).
  - Large export warning: `count > 10_000` → `large_export_warning=true`.
  - Chống formula injection: mọi cell bắt đầu bằng `=`, `+`, `-`, `@`, tab, CR đều được prefix `'` trước khi ghi file (`_sanitize_spreadsheet_cell`).
- **OUT OF SCOPE:**
  - Export từ QC Review detail.
  - Gửi file qua email / S3 link / Slack — kết quả vẫn chỉ là download trình duyệt (job nền nội bộ portal không tính là kênh phân phối ngoài).
  - Thông báo "export ready sau" khi user rời màn — user vẫn chờ trong dialog.
  - Column picker (P2).
  - Hard cap row count.
  - Rate limit v1.
- **Integration boundary:** PostgreSQL `qc_queue_items` + `qc_reviews` + `projects` + `qc_export_jobs` — không external API.

**1.3. Definitions and Acronyms**

|  |  |
| --- | --- |
| **SRS / FR / NFR** | Software / Functional / Non-Functional Requirements |
| **Export scope `selected`** | `item_ids.length > 0` — export theo ID, bỏ qua filter hiện tại |
| **Export scope `filtered`** | `item_ids` rỗng — export mọi item khớp filter + `visible_queue_stmt` |
| **Export job** | Bản ghi `qc_export_jobs` (model `QcExportJob`) mang cả trạng thái lẫn nội dung file; job thuộc riêng người tạo (`requested_by`) |
| **QC_QUEUE_EXPORT_GROUPS** | `vd-admins`, `vd-platform-engineers`, `vd-qc-leads`, `vd-project-managers` |
| **LARGE_EXPORT_WARNING_THRESHOLD** | `10_000` rows |

## 2. System Overview

**2.1. High-Level Architecture**

```
QCQueue.tsx
├── usePermission(PERMISSIONS.QC_EXPORT)  → qc:result:export
├── assignSelected: Set<itemId> + assignSelectedMeta: Map<id, row>   — tập chọn DUY NHẤT
├── selectionResetKey = JSON.stringify({ filters (bỏ page), projectId }) → clearSelection()  (DP-394)
├── QCQueueSelectionBar   (chỉ khi assignSelected.size > 0)
│   ├── "Xuất theo lựa chọn"  → openExportFlow("selected")   (disabled khi 0 mục / đang load preview)
│   └── "Xuất tất cả {N} mục khớp lọc" → openExportFlow("filtered")
├── openExportFlow(scope) → previewQcQueueExport(filters, itemIds)
├── QCQueueExportDialog → handleConfirmExport()
│   ├── scope selected → exportQcQueueDownload()  → apiDownload POST /qc/queue/export (đồng bộ)
│   └── scope filtered → createQcQueueExportJob() → waitForQcQueueExportJob()
│                        → downloadQcQueueExportJob()   (bất đồng bộ, DP-382)
│       └── triggerBrowserDownload(blob, filename) → clearSelection()

FastAPI router.py
├── POST /queue/export/preview → preview_queue_export()
├── POST /queue/export → build_queue_export()          (đồng bộ, scope selected)
├── POST /queue/export/jobs → enqueue_export_job()      (trả ngay, DP-382)
├── GET  /queue/export/jobs/{id}          → poll trạng thái
└── GET  /queue/export/jobs/{id}/download → file; 409 nếu chưa xong / failed
    └── queue_export.py
        ├── visible_queue_stmt(user)  — project scope enforce
        ├── _apply_queue_filters()    — when filtered
        ├── _export_stmt order_by(created_at DESC, id DESC) — khớp keyset của batch reader
        ├── load_only(...) + defer(metadata/timeline/face_bboxes/playback_url) — không nạp blob không dùng
        ├── openpyxl write-only (xlsx) | csv.writer → bytes (BOM \ufeff)
        └── _log_export_audit()       — ClickHouse audit event

qc_export_jobs (Postgres)
└── export_loop.py → qc_export_loop()  — worker nền riêng, poll ~5s, MAX_JOBS_PER_CYCLE=2
    └── export_jobs.py: claim_next_export_job() → process_one_export_job()
        ├── snapshot requester (groups + permissions lúc enqueue)
        ├── LOCK_STALE_AFTER=30 phút, MAX_ATTEMPTS=3
        └── file lưu inline (cột content) → status done
```

**Wireframes:**

- [[docs/review/qc-review-export-list/ascii-screen/qc-review-list-export-default.md|List mặc định (không còn nút Export ở header)]]
- [[docs/review/qc-review-export-list/ascii-screen/qc-review-list-export-selection.md|Thanh chọn hợp nhất + 2 hành động Export]]
- [[docs/review/qc-review-export-list/ascii-screen/qc-review-export-dialog-confirm.md|Confirm dialog]]
- [[docs/review/qc-review-export-list/ascii-screen/qc-review-export-dialog-large-warning.md|Large export warning]]

**2.2. System User Profile**

|  |  |  |  |
| --- | --- | --- | --- |
| **User Role** | **Description** | **Permission Level** | **Key Actions** |
| QC Lead (`vd-qc-leads`) | Trưởng nhóm QC | `qc:result:export` + group | Export mọi project visible |
| Platform Administrator (`vd-admins`, `vd-platform-engineers`) | Quản trị nền tảng | Same | Export mọi project |
| Project Administrator (`vd-project-managers`) | PM project | Same | Export chỉ item trong `visible_queue_stmt` scope |
| QC Reviewer | Reviewer thường | **Không** có `qc:result:export` hoặc group | Không thấy nút Export |

## 3. Functional Requirements

### 3.1 Function List

|  |  |  |
| --- | --- | --- |
| **ID** | **Function Name** | **Description (technical)** |
| F-01 | Authorize export access | FE `canExport`; BE `require_qc_queue_export()` — permission + SSO group intersection. |
| F-02 | Selection cho export | Dùng chung tập `assignSelected` với luồng Gán; toggle per row / toggleAll page; **reset** khi filter/project đổi — **không** reset khi chỉ đổi trang (DP-394). |
| F-03 | Preview export scope & count | `POST /export/preview` → `{ count, scope, large_export_warning }`. |
| F-04 | Generate export file | Scope `selected`: `POST /export` trả xlsx/csv bytes. Scope `filtered`: `POST /export/jobs` + poll + download. Filename `qc-review-export-YYYY-MM-DD.{ext}`. |
| F-05 | Export dialog & error UX | Confirm message, format radio, preparing state, toast errors, browser download. |
| F-06 | Async export job lifecycle | Job nền trong `qc_export_jobs`: enqueue → worker dựng file → poll → download; per-owner, có timeout/khoá. |

**Traceability:**

| URD | Functions |
| --- | --- |
| US-001 Export filtered | F-03, F-04 (scope=filtered), F-06 |
| US-002 Export selected | F-02, F-03, F-04 (scope=selected) |
| US-003 Phân quyền | F-01 |
| US-004 Dialog & errors | F-03, F-05 |

### 3.2 Function Detail

**3.2.1. F-01 Authorize export access**

#### A. Flow

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | User | Mở `QCQueue` (any mode). |
| 2 | System (Frontend) | `usePermission(PERMISSIONS.QC_EXPORT)` → `user.permissions` contains `qc:result:export`. |
| 3 | System (Frontend) | Nếu false → **không render** 2 nút Export trên thanh chọn `QCQueueSelectionBar` — user vẫn tick và gán được nếu có `qc:assign`. |
| 4 | User | Gọi API export (bypass UI). |
| 5 | System (Backend) | `require_qc_queue_export()`: check permission `qc:result:export`; check `{g.lstrip("/") for g in user.groups} ∩ QC_QUEUE_EXPORT_GROUPS ≠ ∅`. |
| 6 | System (Backend) | Fail → HTTP 403 body `{"error": {"code": "FORBIDDEN", "message": "Insufficient permissions", "details": ["qc:result:export"]}}` (thiếu permission) hoặc `details: ["qc:queue:export:role"]` (đủ permission nhưng ngoài SSO group allowlist). |

#### B. API Specification

**Không có API riêng** — enforced trên F-03/F-04 endpoints via dependency `require_qc_queue_export()`.

**Authorized groups:** `vd-admins`, `vd-platform-engineers`, `vd-qc-leads`, `vd-project-managers`.

**Project scope:** `visible_queue_stmt(user, db)` — Project Admin chỉ thấy/export item project được phép (server-side, không tin `project_id` filter từ client alone).

---

**3.2.2. F-02 Selection cho export (dùng chung tập với luồng Gán)**

> **Cập nhật 2026-09-22 (sửa 2026-09-25):** Không còn "chế độ chọn-để-xuất" và không còn tập chọn riêng cho Export. Checkbox cột tác động lên **một** tập `assignSelected`; thanh chọn `QCQueueSelectionBar` mang cả hành động Gán lẫn Xuất. Tập này **chỉ reset khi đổi filter/project** (`selectionResetKey` bỏ `page` → `clearSelection()`); sang trang vẫn giữ selection.

#### A. Flow

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | QC Lead | Tick ≥1 dòng trên trang hiện tại → `toggleSelect(id)` thêm id vào `assignSelected` và lưu `{id, filename}` vào `assignSelectedMeta`. |
| 2 | System (Frontend) | `QCQueueSelectionBar` render (chỉ khi `assignSelected.size > 0`) với badge "Đã chọn {N} mục", **Phân công**, **Xuất theo lựa chọn** (`selectedCount === 0`? disabled), **Xuất tất cả {M} mục khớp lọc** (`filteredTotal === 0`? disabled — `{M}` = `pagination.total`) và **Hủy**. |
| 3 | QC Lead | Bấm **Xuất theo lựa chọn** → `openExportFlow("selected")` với `itemIds = Array.from(assignSelected)`. |
| 4 | QC Lead | Hoặc bấm **Xuất tất cả {M} mục khớp lọc** → `openExportFlow("filtered")` với `itemIds = []` (scope theo filter). |
| 5 | QC Lead | Bấm **Hủy** → `clearSelection()`: `assignSelected` rỗng, `assignSelectedMeta` rỗng, `assignOpen=false`, `dismissSelectAllBanner=false`. |
| 6 | System (Frontend) | Đổi filter/project → `selectionResetKey` đổi → effect gọi `clearSelection()`; **đổi trang thì không reset** — tick giữ nguyên khi sang trang. |

#### B. API Specification

**Không có API — xử lý nội bộ** React state trong `QCQueue.tsx`.

---

**3.2.3. F-03 Preview export scope & count**

#### A. Flow

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | User | Bấm **"Xuất theo lựa chọn"** (`openExportFlow("selected")`) hoặc **"Xuất tất cả {M} mục khớp lọc"** (`openExportFlow("filtered")`). |
| 2 | System (Frontend) | Guard client: scope `selected` mà `itemIds=[]` → toast `qc_export_no_items`, stop. Scope `filtered` mà `pagination.total=0` và không loading → toast `qc_export_no_items`, stop. |
| 3 | System (Frontend) | `POST /export/preview` với `item_ids` + mirror of list filters (project/status/priority/q/date/manual_annotation_only/product_line). |
| 4 | System (Backend) | `item_ids` non-empty → `scope="selected"`, count = items in scope user can access. |
| 5 | System (Backend) | `item_ids` empty → `scope="filtered"`, count = all matching filters (all pages). |
| 6 | System (Backend) | `large_export_warning = count > 10000`. |
| 7 | System (Frontend) | `count=0` → toast no items; else open dialog với count/scope/warning. |

#### B. API Specification

**Endpoint**: `POST /api/v1/qc/queue/export/preview`
**Method**: POST
**Description**: Đếm rows sẽ export + xác định scope trước dialog confirm.

**Request**

| **No** | **Field** | **Data type** | **Mandatory** | **Description** |
| --- | --- | --- | --- | --- |
| **Header** | | | | |
| 1 | `Authorization` | string | Yes | Bearer JWT. |
| **Body** | | | | |
| 2 | `item_ids` | string[] | No | Selected IDs; non-empty → scope selected. |
| 3 | `project_id` | string | No | Filter — UUID project. |
| 4 | `status` | string | No | Filter status. |
| 5 | `priority` | string | No | Filter priority. |
| 6 | `assignee_id` | string | No | Filter assignee; `"unassigned"` special. FE hiện **không gửi** field này (xem ghi chú dưới bảng). |
| 7 | `q` | string | No | Search (max 200 chars FE). |
| 8 | `created_from` | string | No | ISO date filter start. |
| 9 | `created_to` | string | No | ISO date filter end. |
| 10 | `manual_annotation_only` | boolean | No | `true` for annotation queue mode. |
| 11 | `product_line` | string | No | `tapdata` \| `default` \| `all`. |

**Ghi chú payload FE:** `buildQcQueueExportPayload()` (`frontend/src/shared/api/qc.ts`) luôn gửi `item_ids` + `manual_annotation_only`, và chỉ thêm `project_id` / `status`(≠`all`) / `priority`(≠`all`) / `q`(trim, cắt 200 ký tự) / `created_from` / `created_to` / `product_line` khi có giá trị. `assignee_id` **chưa được FE gửi** — list toolbar hiện không expose filter assignee (API backend vẫn nhận field này nếu gọi trực tiếp).

**Response** (`QcQueueExportPreviewOut`)

| **No** | **Field** | **Data type** | **Description** |
| --- | --- | --- | --- |
| 1 | `count` | integer | Số dòng sẽ export. |
| 2 | `scope` | string | `"selected"` \| `"filtered"`. |
| 3 | `large_export_warning` | boolean | `true` if `count > 10000`. |
| 4 | `error.detail` | string | 403 forbidden; 400 invalid. |

---

**3.2.4. F-04 Generate export file**

#### A. Flow

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | User | Dialog **Tiếp tục** → `handleConfirmExport()`. |
| 2 | System (Frontend) | Rẽ nhánh theo scope: `selected` → `POST /export` (đồng bộ); `filtered` → `POST /export/jobs` (bất đồng bộ). |
| 3 | System (Backend) | Re-run `preview_queue_export`; `count=0` → 400 `"No items to export"`. |
| 4 | System (Backend) | Build rows theo batch `EXPORT_BATCH_SIZE=2000` (`_iter_export_item_batches` keyset theo `created_at` + `id` — `_export_stmt` có `order_by(created_at.desc(), id.desc())` khớp đúng keyset này; mỗi batch qua `_rows_for_items` để gom project name / review / reviewer name / duration mirror theo batch — không N+1 per row). |
| 5 | System (Backend) | Build **toàn bộ file trong một lần gọi**: **xlsx** = openpyxl `Workbook(write_only=True)` → `SpooledTemporaryFile(max_size=16MB)` → bytes; **csv** = `csv.writer` vào `io.StringIO` → prefix `\ufeff` → encode UTF-8 → bytes. Đường `filtered` chạy trong worker nền, `selected` vẫn chạy ngay trong request. |
| 6 | System (Backend) | `row_count=0` sau khi build → 400 `"No items to export"`; ngược lại `_log_export_audit(user, count=row_count, scope, format)` rồi trả `Response` (hoặc lưu vào job rồi `status="done"`). |
| 7 | System (Frontend) | `triggerBrowserDownload(blob, filename)`; `setExportOpen(false)` + `clearSelection()` (xoá tập chọn). |

**Export columns (17):**

`QC Item ID`, `Upload ID`, `Filename`, `Project`, `Duration`, `Status`, `Reject reason`, `Priority`, `Assignee`, `Created at`, `Project ID`, `Batch ID`, `Reject comment`, `Last reviewed at`, `Last reviewed by`, `QC type`, `Tags`.

`QC type` values: `final_qc` | `annotation` | `tapdata` (from `_qc_type_label`).

#### B. API Specification

**Endpoint**: `POST /api/v1/qc/queue/export` (chỉ scope `selected`)
**Method**: POST
**Description**: Build file và trả binary download (`Content-Disposition: attachment`).

**Request** — same as F-03 preview body, plus:

| **No** | **Field** | **Data type** | **Default** | **Mandatory** | **Description** |
| --- | --- | --- | --- | --- | --- |
| 12 | `format` | string | `xlsx` | Yes | `xlsx` \| `csv` (regex validated). |

**Response**

| **No** | **Field** | **Data type** | **Description** |
| --- | --- | --- | --- |
| 1 | Body | binary | File build đầy đủ (xlsx workbook hoặc CSV bytes có BOM). |
| 2 | `Content-Disposition` | header | `attachment; filename="qc-review-export-YYYY-MM-DD.xlsx"` (ngày UTC tại thời điểm build) |
| 3 | `Content-Type` | header | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` (xlsx) hoặc `text/csv; charset=utf-8` (csv) |
| 4 | `error.detail` | string | `"No items to export"` (400); `"Excel export unavailable (openpyxl not installed)"` (500); body 403 như F-01 |

**Selected scope rule:** Khi `item_ids` provided, `_export_stmt` lọc `QcQueueItem.id IN item_ids` **HOẶC** `QcQueueItem.external_id IN item_ids` (FE gửi ID nội bộ của row) **within** `visible_queue_stmt` — IDs ngoài quyền bị loại silently; count có thể < len(item_ids); `count=0` sau khi lọc → 400.

**Ghi chú hiệu năng `_export_stmt`:** câu query export chỉ `load_only(...)` các cột thực sự ghi ra file và `defer(metadata_json, timeline_json, face_bboxes_json, playback_url)` trên item (cùng `load_only(...)` trên `QcReview`) — trước đây nó nạp cả blob không dùng. `LARGE_EXPORT_WARNING_THRESHOLD` vẫn là `10_000`.

---

**3.2.5. F-05 Export dialog & error UX**

#### A. Flow

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | System (Frontend) | Dialog title `qc_export_list_title` = "Xuất danh sách QC Review"; confirm `qc_export_confirm_selected` = "Xuất {count} mục đã chọn. Tiếp tục?" hoặc `qc_export_confirm_filtered` = "Xuất {count} mục khớp bộ lọc hiện tại. Tiếp tục?". |
| 2 | System (Frontend) | `large_export_warning=true` → hiện `qc_export_large_warning` = "Việc này có thể mất một lúc" (màu amber). |
| 3 | System (Frontend) | Format radio `qc_export_format`: `qc_export_format_xlsx` = "Excel (.xlsx)" (default) / `qc_export_format_csv` = "CSV"; disable khi `isExporting`. |
| 4 | System (Frontend) | Continue (`qc_continue`) → khi đang tải, nút đổi thành `qc_export_preparing` = "Đang chuẩn bị xuất…"; dialog **không đóng** khi `isExporting` (Cancel cũng disabled). |
| 5 | System (Frontend) | Success: browser download only — **no success toast**; dialog đóng + `clearSelection()`. |
| 6 | System (Frontend) | Error: toast `qc_export_failed` = "Xuất thất bại. Vui lòng thử lại hoặc thu hẹp bộ lọc." / `qc_export_no_items` = "Không có mục để xuất"; job `failed` → hiện `job.error` nếu có, không thì dùng `qc_export_failed`. |
| 7 | User | Đóng tab khi preparing → request/job bị bỏ; không resume, không có thông báo "export ready sau". |

#### B. API Specification

**Không có API — UI-only** (`QCQueueExportDialog.tsx`, i18n keys `qc_export_*`).

---

**3.2.6. F-06 Async export job lifecycle (scope `filtered`, DP-382)**

"Xuất tất cả" có thể là cả hàng đợi, vượt `proxy_read_timeout 120s` (nginx) — nên nó được worker nền dựng file, FE poll tới khi tải được.

| Endpoint | Method | Mô tả |
| --- | --- | --- |
| `/api/v1/qc/queue/export/jobs` | POST | Tạo job, trả ngay `{ id, status, ready }` |
| `/api/v1/qc/queue/export/jobs/{job_id}` | GET | Poll trạng thái |
| `/api/v1/qc/queue/export/jobs/{job_id}/download` | GET | Trả file; **409** nếu chưa xong hoặc job `failed`; **404** nếu job không thuộc caller |

**Response** (`200`, `QcQueueExportJobOut`)

| **Field** | **Data type** | **Description** |
| --- | --- | --- |
| `id` | string | Job handle. |
| `status` | string | `pending` \| `running` \| `done` \| `failed`. |
| `format` | string | `xlsx` \| `csv`. |
| `row_count` | int\|null | Số row đã ghi. |
| `filename` | string\|null | Tên file khi xong. |
| `error` | string\|null | Thông báo lỗi khi `failed`. |
| `ready` | bool | `true` chỉ khi `status == done` **và** đã có nội dung file. |

**Quy tắc vận hành:**

| Quy tắc | Chi tiết |
| --- | --- |
| Trạng thái nằm ở Postgres | Bảng `qc_export_jobs` (model `QcExportJob`), **không** nằm trong RAM worker — portal chạy 8 uvicorn worker nên request poll rất dễ rơi vào worker chưa từng dựng file |
| Snapshot quyền lúc enqueue | `requester` lưu `groups` + `permissions` tại thời điểm tạo job; queue scope suy ra từ đó. Đổi quyền sau đó **không** mở rộng một export đã xếp hàng |
| Job thuộc riêng người tạo | Lọc theo `requested_by`; người khác poll/download → **404** |
| Khoá có hết hạn | `LOCK_STALE_AFTER = 30 phút`, `MAX_ATTEMPTS = 3` — worker chết giữa chừng thì job được nhặt lại, không kẹt vĩnh viễn |
| Worker riêng | `qc_export_loop` (task riêng, không nằm dưới `QC_SYNC_ENABLED`), poll ~5 s, `MAX_JOBS_PER_CYCLE = 2` |
| File lưu inline | Cột `content` trong `qc_export_jobs`; export vài MB, chưa cần object storage |
| Chỉ "Xuất tất cả" đi async | "Xuất theo lựa chọn" vẫn đồng bộ — tập ID tick tay đủ nhỏ, và tránh làm chậm thao tác phổ biến |
| Poll phía FE | `waitForQcQueueExportJob(jobId)`: interval **2000 ms**, timeout **10 phút**; hết hạn thì **throw** `export_job_timeout` thay vì treo dialog vô hạn |
| Không có UI danh sách job | Job không được lưu lại để xem sau — user vẫn chờ trong dialog như trước |

## 4. Non-Functional Requirements

**4.1. Performance**

- Preview endpoint p95 < 2s cho count ≤ 50k rows (COUNT query).
- Export scope `selected` p95 < 30s cho ≤ 1,000 rows (URD target UX).
- Export 10k+ rows (scope `filtered`): warning shown; job **trả về ngay**, file do worker nền dựng nên request không còn phải nằm trong `proxy_read_timeout 120s` — đây chính là lý do tách async (DP-382).
- **Cả CSV và XLSX đều build fully in-process** trong một lần gọi — đổi lại không còn rủi ro "stream trả file rỗng" như bản `StreamingResponse` cũ. XLSX ghi qua `SpooledTemporaryFile(max_size=SPOOL_MAX_BYTES=16MB)` (memory → disk khi vượt ngưỡng); CSV dựng trong `io.StringIO`.
- Batch fetch `EXPORT_BATCH_SIZE=2000` (keyset `created_at` + `id`) — no N+1 per row for reviews/projects.
- Hệ quả cần theo dõi: export rất lớn giữ nguyên toàn bộ file trong RAM tiến trình dựng file (CSV) — chưa có hard cap, xem §4.4.

**4.2. Availability & Reliability**

- Kế thừa portal SLA ≥ 99.5%/month.
- Scope `selected`: build trong request handler với session DB của request. Scope `filtered`: build trong worker nền (`qc_export_loop`) với session riêng của worker; file ghi vào job row khi xong.
- Lỗi giữa chừng → request trả lỗi (selected) hoặc job chuyển `failed` với `error` (filtered); không có partial file phía server. Job `failed` vẫn bị xoá/thử lại theo `MAX_ATTEMPTS=3` trước khi chốt `failed`.

**4.3. Security**

- Dual gate: RBAC permission `qc:result:export` + SSO group allowlist (`vd-admins`, `vd-platform-engineers`, `vd-qc-leads`, `vd-project-managers`) — group check chặn cả grant cũ còn sót (vd `vd-ml-engineers`).
- `visible_queue_stmt` enforces project membership — Project Admin cannot export other projects' items even with guessed IDs.
- Export job **per-owner**: lọc theo `requested_by`; người khác poll/download → 404. Nhờ vậy một handle job không trở thành kênh đọc chéo dữ liệu queue.
- Job row **snapshot** groups + permissions của requester lúc enqueue — export đã xếp hàng không tự mở rộng khi quyền thay đổi sau đó.
- Audit event `qc.queue.export` logs `user_id`, `username`, `row_count`, `scope`, `format` (ClickHouse) — dùng chung cho cả đường đồng bộ lẫn job nền.
- Formula injection: cell bắt đầu bằng `=`/`+`/`-`/`@`/tab/CR được prefix `'` (`_sanitize_spreadsheet_cell`) — chống CSV/XLSX injection khi mở bằng Excel.
- No PII beyond existing queue list fields in export file.

**4.4. Scalability**

- No hard row cap v1; CSV/XLSX build in-process (không stream).
- Nhiều export có thể xếp hàng cùng lúc; worker xử lý `MAX_JOBS_PER_CYCLE = 2` mỗi vòng poll rồi nhặt tiếp job kế. Khoá job (`locked_at`/`locked_by` + `LOCK_STALE_AFTER = 30 phút`) chỉ để một worker không nhặt trùng job — **không** phải distributed lock cho toàn bộ export.
- `EXPORT_BATCH_SIZE` tunable for memory.

**4.5. Maintainability**

- Tests: `backend/tests/features/qc/test_queue_export.py` — preview count, large warning, xlsx/csv build; `test_export_jobs.py`, `test_export_job_routes.py`, `test_export_job_http.py` — enqueue/claim/fail/retry, per-owner 404, 409 khi chưa xong.
- Column list single source `EXPORT_HEADERS` tuple.
- FE: `QCQueueExportDialog.test.tsx` cover dialog; `qc-queue-selection.test.ts` cover `waitForQcQueueExportJob` (poll, timeout). Không còn component mode bar nào để test.

**4.6. Usability**

- Excel default format; CSV UTF-8 BOM for Vietnamese in Excel Windows.
- Nhãn hành động export nằm trong thanh chọn hợp nhất (`qc_export_selected_action`, `qc_export_filtered_action`) — không còn nhãn riêng cho "chế độ xuất". Badge dùng chung `bulk_assign_selected` = "Đã chọn {N} mục" cho cả Gán lẫn Xuất.
- Dialog blocks close while `isExporting` (Cancel + overlay dismiss đều chặn); hết timeout poll → lỗi rõ ràng thay vì treo.

**4.7. Compliance**

- Audit log P1 shipped — supports traceability who exported how many rows.
- Không áp dụng GDPR export-specific beyond portal baseline.

**NFR Summary Table**

|  |  |  |  |
| --- | --- | --- | --- |
| **ID** | **Requirement** | **Metric / Target** | **Priority** |
| NFR-P-01 | Export ≤1k rows (selected) | p95 < 30s end-to-end | High |
| NFR-P-02 | Preview count | p95 < 2s | Medium |
| NFR-P-03 | Large export warning | Trigger at count > 10,000 | High |
| NFR-P-04 | Export "tất cả" xếp hàng | Endpoint tạo job trả về trong ~2s; không phụ thuộc số row | Medium |
| NFR-P-05 | Poll phía FE | Interval 2s, timeout 10 phút → lỗi `export_job_timeout` | Medium |
| NFR-SEC-01 | Export authorization | 100% requests pass permission + group check | High |
| NFR-SEC-02 | Project scope leak | 0 rows outside `visible_queue_stmt` in output | High |
| NFR-SEC-03 | Export job ownership | 100% job truy cập bởi người khác trả 404 | High |
| NFR-SEC-04 | Audit log | 100% successful exports emit `qc.queue.export` event | Medium |
| NFR-M-01 | Backend tests | `test_queue_export.py` + `test_export_job*.py` pass on CI | High |
| NFR-U-01 | CSV Vietnamese | UTF-8 BOM prefix on every CSV export | High |

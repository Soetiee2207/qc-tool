<!-- doc-meta: type=srs | feature=docs/review/qc-audit | status=draft | updated=2026-09-25 -->
# **SOFTWARE REQUIREMENTS SPECIFICATION**

Audit — vòng QC thứ 2 (module Review)

Version 1.2  |  2026-09-25

| **Version** | **Date** | **Author** | **Changes** |
| --- | --- | --- | --- |
| 1.2 | 2026-09-25 | @kimi-code | Đối chiếu code: mã lý do OTS đa chọn, kho thật, needs_revision |
| 1.0 | 2026-09-08 | @binhhm | Initial draft từ urd.md, 7 functions, 4 diagram |
| 1.1 | 2026-09-11 | @binhhm | Đối chiếu code đã triển khai (c8122ad, c862f90): sửa hợp đồng API theo schema thật, thêm endpoint `/history`, cập nhật bảng/trạng thái/UI, ghi rõ phần chưa cưỡng chế ở backend |

## 1. INTRODUCTION

**1.1. Purpose**

Đặc tả kỹ thuật cho sub-module **Audit** — vòng kiểm tra chất lượng thứ hai trong module Review.

- **Viết cho:** đội phát triển backend/frontend (baseline triển khai) và QA (căn cứ viết test case).
- **Mục tiêu:** hợp đồng kỹ thuật giữa nghiệp vụ đã chốt ở [[docs/review/qc-audit/urd.md|URD]] và phần triển khai — định nghĩa kiến trúc, danh sách chức năng, hợp đồng API và các chỉ tiêu phi chức năng.
- **Phạm vi hợp lệ:** phase 1 của sub-module Audit.

**1.2. Scope**

**IN SCOPE**

- Namespace API mới `/api/v1/qc/audit` cho hàng đợi Audit, màn chấm và ghi nhận quyết định.
- Bảng dữ liệu mới lưu kết quả vòng 2, tách khỏi bảng `qc_reviews` của vòng 1.
- Ba trạng thái mới của item: `pending_audit`, `audit_passed`, `audit_rejected`.
- Quyền mới `qc:audit:perform` và nhóm SSO mới `vd-qc-auditors` cho auditor.
- Thay đổi hành vi `submit_review` hiện có: vòng 1 Pass chuyển item sang `pending_audit`; vòng 1 Reject đặt `needs_revision` (item quay lại bước annotation, không vào hàng đợi Audit) — thay vì kết thúc ở `passed`/`rejected`.
- Dời thời điểm chuẩn bị bàn giao từ vòng 1 sang vòng Audit.
- Màn hình frontend mới: hàng đợi Audit và màn chấm Audit.

**OUT OF SCOPE**

- Cơ chế lấy mẫu theo lô và ngưỡng phần trăm fail — hoãn sang phase sau.
- Màn thống kê chất lượng reviewer — hoãn sang phase sau; phase này chỉ tích lũy dữ liệu.
- Chỉnh sửa dữ liệu ở vòng Audit (vùng làm mờ, metadata) — auditor chỉ đọc.
- Thông báo tự động (email, in-app) khi Audit lật quyết định.
- Giới hạn số vòng lặp reject.
- Khóa item khi đang chấm và cơ chế giao việc cho auditor.
- Nghiệp vụ bên trong Warehousing — Audit chỉ chuẩn bị bàn giao tới ranh giới đó.
- Hồi tố item đã bàn giao trước khi có Audit.
- Hiển thị kết quả Audit trong lịch sử review sẵn có của reviewer vòng 1 — xem F-07: code triển khai bằng endpoint lịch sử Audit riêng, bọc quyền auditor.

**Integration boundary**

| Hệ thống / thành phần | Giao thức | Mục đích |
| --- | --- | --- |
| QC Review vòng 1 (`backend/app/features/qc`) | Gọi hàm nội bộ cùng service | Nguồn cấp item; nơi item quay về sau khi Audit reject |
| Pipeline xử lý dữ liệu | Outbox + Kafka `qc.audit.reprocess_requested` (khi `pipeline_kafka_active`) | Phát yêu cầu chạy lại khâu xử lý khi Audit reject |
| Warehousing (`/api/v1/warehousing/items`) | HTTP — danh sách kho thật đọc từ bảng `portal_warehouse_items` (`backend/app/features/portal_flow/warehouse_router.py`, đăng ký ở `backend/app/main.py`). `GET /api/v1/delivery/warehousing/mock-items` cũ chỉ còn phục vụ bộ chọn item của đơn giao hàng | Điểm ra của nhánh Audit Pass — dòng kho được tạo từ lần Audit Pass (`materialize_from_audit_pass`) |
| Iceberg outbox (`lakehouse/outbox.py`) | Ghi bản ghi outbox trong cùng transaction | Phát sự kiện `audit_decision` và `audit_reprocess_requested` cho lakehouse |
| Kafka pipeline (tùy chọn, theo `pipeline_kafka_active`) | Topic `pipeline_kafka_qc_review_topic` | Phát `qc.audit.passed`, `qc.audit.rejected`, `qc.audit.reprocess_requested` cho Dagster |
| Keycloak / SSO dùng chung | OIDC group claim | Cấp nhóm quyền `vd-qc-auditors` |
| QC Checklists | Truy vấn nội bộ | Bộ tiêu chí chấm, dùng chung với vòng 1; màn Audit hiện chưa render checklist |

**1.3. Definitions and Acronyms**

| **Term / Acronym** | **Definition** |
| --- | --- |
| **SRS** | Software Requirements Specification |
| **FR** | Functional Requirement — yêu cầu chức năng |
| **NFR** | Non-Functional Requirement — yêu cầu phi chức năng |
| **UC** | Use Case |
| **API** | Application Programming Interface |
| **Audit** | Vòng kiểm tra chất lượng thứ hai, chạy sau QC Review |
| **Vòng 1** | QC Review hiện có, ghi kết quả vào bảng `qc_reviews` |
| **Vòng 2** | Audit, ghi kết quả vào bảng mới `qc_audit_reviews` |
| **Luật tách vai** | Ràng buộc chặn auditor chấm item mà chính họ đã review ở vòng 1 |
| **Warehousing** | Sub-module thuộc module Delivery, tiếp nhận dữ liệu sau khi Audit Pass |
| **uuidv7** | Định danh phiên dữ liệu dùng xuyên suốt QC, khóa liên kết giữa item và bản ghi review |

## 2. SYSTEM OVERVIEW

**2.1. High-Level Architecture**

Audit là sub-module nằm trong feature `qc` sẵn có của backend, không tách service riêng.

**Backend** — FastAPI + SQLAlchemy + PostgreSQL, đặt trong `backend/app/features/qc/`:

- `audit_router.py` — router prefix `/qc/audit` (đăng ký ở `backend/app/main.py` với prefix `/api/v1`), 4 endpoint, tất cả bọc `require_permission("qc:audit:perform")`.
- `audit_service.py` — tầng service: kiểm quyền, dựng response chi tiết/lịch sử.
- `audit_store.py` — tầng ghi trạng thái vòng 2, gọi `_autofill_delivery_on_pass` khi pass.
- `audit_queries.py` — truy vấn hàng đợi Audit, lọc luật tách vai ở tầng SQL.
- `audit_reprocessing.py` — phát yêu cầu chạy lại khi reject; `complete_audit_reprocess()` đưa item về `pending` (**hiện chưa có caller**).
- `audit_schemas.py` — khuôn request/response.
- `models.py` — bổ sung bảng `qc_audit_reviews` và hai cột `qc_queue_items.audit_entered_at`, `qc_queue_items.reprocess_status`.
- Migration: `backend/alembic/versions/20260909_0050_qc_audit_round2.py`.

**Điểm cần chú ý về mô hình dữ liệu.** Bảng `qc_reviews` hiện có ràng buộc `UniqueConstraint("uuidv7")` — mỗi phiên dữ liệu chỉ có đúng một bản ghi review. Vòng 2 vì vậy **không dùng lại được bảng này**; bảng riêng `qc_audit_reviews` đã được tạo với `UniqueConstraint("uuidv7", "round_no")`, giữ được lịch sử khi item quay vòng nhiều lần, kèm các cột `round1_revision` và `round1_reviewer_id` để neo kết quả vòng 1 tại thời điểm audit.

**Thay đổi lên luồng đang chạy.** `submit_review` trong `review_store.py` nay đặt `item.status = "pending_audit"` và `item.audit_entered_at = now` cho **nhánh Pass**; **nhánh Reject đặt `item.status = "needs_revision"`** nên item không vào hàng đợi Audit (hàng đợi chỉ lọc `status='pending_audit'`). Không còn gọi `_autofill_delivery_on_pass()`; việc chuẩn bị bàn giao dời sang thời điểm Audit Pass (`audit_store.submit_audit_decision`).

**Frontend** — React + TypeScript + TanStack Query, trong `frontend/src/features/qc/audit/`:

- `AuditQueue.tsx` — hàng đợi Audit, dùng chung khung `ListFiltersBar`/`ListPagination`/`PageShell`, không có chọn hàng loạt và giao việc.
- `AuditQueueTable.tsx` — bảng kết quả.
- `AuditReviewDetail.tsx` — màn chấm: sidebar trái + video phải, toolbar Pass/Reject ở góc phải.
- `ReviewSidebarTabs.tsx` (trong `frontend/src/features/qc/review/`) — component sidebar dùng chung cho cả màn review lẫn màn Audit (`MetadataQcAuditLayout.tsx` truyền vào): 2 tab "Audit bàn giao" (metadata chỉ đọc) và "Lịch sử review"; khối kết quả vòng 1 nằm cố định phía trên hai tab. `AuditSidebarTabs.tsx` cũ đã bị gỡ.
- `AuditRound1Result.tsx` — khối kết quả vòng 1 (chỉ đọc).
- Route `/qc/audit` và `/qc/audit/:id` trong `frontend/src/app/App.tsx`, bọc `RequirePermission` với `PERMISSIONS.QC_AUDIT` (`qc:audit:perform`); mục menu "Audit QC" trong nhóm "Đánh giá" (`frontend/src/shared/config/nav.ts`).
- API client `frontend/src/shared/api/audit.ts`.

**Lưu đồ nghiệp vụ tổng quan:** [[docs/review/qc-audit/srs/qc-audit-flows.md|Audit — Flows]] · [[docs/review/qc-audit/srs/qc-audit-states.md|Audit — States]]

**2.2. System User Profile**

| **User Role** | **Description** | **Permission Level** | **Key Actions** |
| --- | --- | --- | --- |
| Auditor | Người thực hiện vòng kiểm tra thứ hai; nhóm SSO `vd-qc-auditors`, tách khỏi reviewer vòng 1 | `qc:audit:perform`; chỉ đọc với dữ liệu nội dung | Xem hàng đợi Audit, xem kết quả vòng 1, chấm Pass, chấm Reject kèm mã lý do |
| QC Reviewer (vòng 1) | Người chấm ở QC Review vòng 1 | `qc:queue:view`, `qc:review:perform` — **không** có `qc:audit:perform` | Chấm vòng 1; **chưa có đường xem kết quả Audit** (F-07 chưa nối vào màn lịch sử) |
| QC Lead | Cấp quản lý đội QC | `qc:queue:view`, `qc:review:perform`, `qc:assign`… — **không** có `qc:audit:perform` | Theo dõi dashboard QC sẵn có; chưa xem được kết quả Audit |
| System (Scheduler / Pipeline) | Tác nhân tự động | Không qua tầng quyền HTTP | Chuyển item sang `pending_audit` khi vòng 1 Pass, sang `needs_revision` khi vòng 1 Reject; phát yêu cầu chạy lại xử lý khi Audit reject; đưa item về `pending` khi xử lý lại xong |

## 3. FUNCTIONAL REQUIREMENTS

### 3.1 Function List

| **ID** | **Function Name** | **Description (technical)** | **Nguồn US** |
| --- | --- | --- | --- |
| F-01 | List Audit Queue | Truy vấn item `status='pending_audit'`, join `qc_reviews` lấy kết quả vòng 1, lọc bỏ item do chính người gọi review ở vòng 1, phân trang. | US-001 |
| F-02 | Get Audit Review Detail | Trả về chi tiết item cho màn chấm: kết quả vòng 1, khối review đầy đủ (kèm `criteria`), lịch sử các vòng audit. | US-002 |
| F-03 | Submit Audit Decision | Ghi bản ghi `qc_audit_reviews`, cập nhật trạng thái item, phát sự kiện outbox. Xử lý cả hai nhánh pass và reject trong một endpoint. | US-003, US-004 |
| F-04 | Enqueue Item To Audit | Sửa `submit_review` của vòng 1: nhánh Pass chuyển item sang `pending_audit` (kèm `audit_entered_at`); nhánh Reject đặt `needs_revision` để quay lại bước annotation, không vào hàng đợi Audit. Không có API riêng. | US-001 |
| F-05 | Handoff To Warehousing On Audit Pass | Dời `_autofill_delivery_on_pass` từ vòng 1 sang vòng Audit; mở cổng `_audit_gate_open` cho deliverable sync và Phase 2. Không có API riêng. | US-003 |
| F-06 | Requeue For Reprocessing On Audit Reject | Phát yêu cầu chạy lại các bước xử lý dữ liệu (outbox + Kafka). Không có API riêng. | US-004 |
| F-07 | Expose Audit Result In Review History | Endpoint lịch sử Audit riêng `/api/v1/qc/audit/queue/{item_id}/history`, bọc quyền auditor; chưa nối vào màn lịch sử của reviewer vòng 1. | US-005 |

### 3.2 Function Detail

**3.2.1. F-01 List Audit Queue**

#### A. **Flow**

**Diagram**

Xem sequence diagram: [[docs/review/qc-audit/srs/qc-audit-flows.md|F-01 Load Audit Queue (Sequence)]]

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | Auditor | Mở route `/qc/audit` |
| 2 | Frontend | Gọi `GET /api/v1/qc/audit/queue` kèm tham số phân trang và bộ lọc |
| 3 | API | Kiểm tra quyền `qc:audit:perform`; thiếu quyền trả 403 |
| 4 | API | Truy vấn `qc_queue_items` với `status = 'pending_audit'`, loại bản ghi đã xoá và các project không hiển thị; auditor dùng pool chung toàn bộ project (không giới hạn theo người được giao như hàng đợi vòng 1) |
| 5 | API | Join `qc_reviews` theo `uuidv7` lấy `decision`, `reason_code`, `reviewer_id`, `reviewed_at` của vòng 1; item chưa có reviewer vòng 1 không vào danh sách |
| 6 | API | Loại bỏ dòng có `qc_reviews.reviewer_id = current_user.id` — luật tách vai áp ở tầng SQL, không ở frontend |
| 7 | API | Áp bộ lọc `round1_decision`, `project_id`, `q`, khoảng ngày (so trên `audit_entered_at`, fallback `updated_at`); phân trang |
| 8 | API | Trả `data` + `pagination` |
| 9 | Frontend | `total = 0` thì render trạng thái rỗng; ngược lại render bảng kèm cột "QC1" (Pass/Reject), "Reviewer" và "Vào audit" |

### B. API Specification

**Endpoint**: `/api/v1/qc/audit/queue`
**Method**: GET
**Description**: Danh sách item đang chờ audit, kèm kết quả QC Review vòng 1, đã áp luật tách vai.

**Request**

| **No** | **Field** | **Data type** | **Default value** | **Mandatory** | **Description** |
| --- | --- | --- | --- | --- | --- |
| **Header** | | | | | |
| 1 | `Authorization` | string | | Yes | Bearer token của phiên đăng nhập. |
| **Query** | | | | | |
| 2 | `page` | integer | 1 | No | Trang hiện tại, tối thiểu 1. |
| 3 | `limit` | integer | 50 | No | Số dòng mỗi trang, khoảng hợp lệ 1–500 (bằng với `/qc/queue` hiện có). |
| 4 | `round1_decision` | string | | No | Lọc theo kết quả vòng 1: `approved` hoặc `rejected`. Bỏ trống là lấy cả hai. |
| 5 | `project_id` | uuid | | No | Lọc theo project. |
| 6 | `q` | string | | No | Tìm theo filename, external_id hoặc tên project. |
| 7 | `created_from` | string | | No | Ngày bắt đầu theo ISO, biên ngày tính theo GMT+7. |
| 8 | `created_to` | string | | No | Ngày kết thúc theo ISO. |

**Response**

| **No** | **Field** | **Data type** | **Description** |
| --- | --- | --- | --- |
| 1 | `data[].id` | uuid | ID item trong hàng đợi. |
| 2 | `data[].external_id` | string | Mã đối chiếu với khâu thu thập. |
| 3 | `data[].filename` | string | Tên file nội dung. |
| 4 | `data[].project_id` | uuid | ID project. |
| 5 | `data[].project_name` | string | Tên project. |
| 6 | `data[].duration` | string | Thời lượng đã định dạng. |
| 7 | `data[].thumbnail_color` | string | Mã màu ảnh đại diện. |
| 8 | `data[].round1_decision` | string | Kết quả vòng 1: `approved` hoặc `rejected`. |
| 9 | `data[].round1_reason_code` | string\|null | Mã lý do vòng 1; `null` khi vòng 1 là `approved`. |
| 10 | `data[].round1_reviewer_id` | string | ID người review vòng 1. |
| 11 | `data[].round1_reviewer_name` | string | Tên người review vòng 1. |
| 12 | `data[].round1_reviewed_at` | datetime\|null | Thời điểm vòng 1 chấm xong. |
| 13 | `data[].round1_revision` | integer | Số bản sửa của bản ghi review vòng 1 tại thời điểm chấm. |
| 14 | `data[].entered_audit_at` | datetime\|null | Thời điểm item vào hàng đợi Audit (`audit_entered_at`, fallback `updated_at`); là cột "Vào audit" trên bảng. |
| 15 | `pagination.page` | integer | Trang hiện tại. |
| 16 | `pagination.limit` | integer | Số dòng mỗi trang. |
| 17 | `pagination.total` | integer | Tổng số item chờ audit sau khi đã áp luật tách vai và bộ lọc. |
| 18 | `error.detail` | string | `Bạn không có quyền truy cập Audit.` khi trả 403. |

**3.2.2. F-02 Get Audit Review Detail**

#### A. **Flow**

**Diagram**

> *(Đề xuất: Sequence diagram — luồng tuyến tính một lượt gọi, chưa vẽ vì giá trị thấp so với F-01/F-03 đã có)*

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | Auditor | Bấm nút Audit trên một dòng hàng đợi (hoặc bấm vào dòng) |
| 2 | Frontend | Điều hướng `/qc/audit/{item_id}`, gọi `GET /api/v1/qc/audit/queue/{item_id}/review` |
| 3 | API | Kiểm tra quyền `qc:audit:perform`; thiếu quyền trả 403 |
| 4 | API | Tra item trong hàng đợi hiển thị cho auditor (`status='pending_audit'`, đã áp luật tách vai ở tầng SQL); không thấy thì trả 404 |
| 5 | API | Trả kết quả vòng 1 đầy đủ, khối review vòng 1 (`review`, gồm `criteria`) và lịch sử các vòng audit trước |
| 6 | Frontend | Render màn chấm ở chế độ chỉ đọc; video gọi riêng `GET /api/v1/qc/queue/{item_id}/playback` |

### B. API Specification

**Endpoint**: `/api/v1/qc/audit/queue/{item_id}/review`
**Method**: GET
**Description**: Chi tiết một item cho màn chấm Audit, gồm kết quả vòng 1, khối review vòng 1 và lịch sử các vòng audit.

**Request**

| **No** | **Field** | **Data type** | **Default value** | **Mandatory** | **Description** |
| --- | --- | --- | --- | --- | --- |
| **Header** | | | | | |
| 1 | `Authorization` | string | | Yes | Bearer token. |
| **Path** | | | | | |
| 2 | `item_id` | uuid | | Yes | ID item trong hàng đợi (nhận cả `external_id`). |

**Response**

| **No** | **Field** | **Data type** | **Description** |
| --- | --- | --- | --- |
| 1 | `item_id` | string | ID item trong hàng đợi. |
| 2 | `uuidv7` | string | Định danh phiên dữ liệu (đã resolve, kể cả nhánh segment). |
| 3 | `status` | string | Luôn là `pending_audit` khi trả về thành công. |
| 4 | `round1.decision` | string | `approved` hoặc `rejected`. |
| 5 | `round1.reason_code` | string\|null | Mã lý do vòng 1. |
| 6 | `round1.notes` | string\|null | Ghi chú của reviewer vòng 1. |
| 7 | `round1.reviewer_id` | string\|null | ID người review vòng 1. |
| 8 | `round1.reviewer_name` | string\|null | Tên người review vòng 1. |
| 9 | `round1.reviewed_at` | datetime\|null | Thời điểm chấm vòng 1. |
| 10 | `round1.revision` | integer | Số bản sửa của bản ghi review vòng 1. |
| 11 | `review` | object | Khối `QcReviewDetailOut` của vòng 1: `item`, `metadata`, `timeline`, `criteria` (bộ tiêu chí), `metadata_sidecar`, `review_sessions`… dùng lại nguyên khuôn của màn QC Review. |
| 12 | `audit_rounds[]` | array | Lịch sử các vòng audit đã chấm của item (rỗng nếu chưa từng chấm): `round_no`, `decision`, `reason_code`, `notes`, `auditor_id`, `auditor_name`, `audited_at`. |
| 13 | `error.detail` | string | `Bạn không có quyền truy cập Audit.` khi 403; `Audit queue item not found` khi 404 (gồm cả trường hợp item không ở trạng thái chờ audit hoặc vi phạm luật tách vai — item không nằm trong hàng đợi hiển thị của người gọi). |

**3.2.3. F-03 Submit Audit Decision**

#### A. **Flow**

**Diagram**

Xem sequence diagram: [[docs/review/qc-audit/srs/qc-audit-flows.md|F-03 Submit Audit Decision (Sequence)]]

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | Auditor | Bấm Pass (xác nhận trong hộp thoại), hoặc bấm Reject rồi chọn mã lý do và xác nhận |
| 2 | Frontend | Nhánh reject: nút xác nhận bị vô hiệu hoá khi chưa chọn `reason`, không gọi API |
| 3 | Frontend | Gọi `POST /api/v1/qc/audit/queue/{item_id}/submit` |
| 4 | API | Kiểm tra quyền `qc:audit:perform` |
| 5 | API | `SELECT ... FOR UPDATE` trên item để chống hai auditor cùng ghi |
| 6 | API | Item không còn trong hàng đợi hiển thị (đã bị chấm xong / không ở `pending_audit`) thì trả 409 hoặc 404 — đây là cách xử lý tranh chấp thay cho khóa item |
| 7 | API | Kiểm tra luật tách vai; vi phạm thì trả 403 |
| 8 | API | Ghi `qc_audit_reviews` với `decision`, `reason_code`, `notes`, `auditor_id`, `round_no` tăng dần, kèm `round1_revision` và `round1_reviewer_id` |
| 9 | API | Nhánh pass: gọi `_autofill_delivery_on_pass`, đặt `status='audit_passed'`, xoá `reprocess_status` |
| 10 | API | Nhánh reject: đặt `status='audit_rejected'`, đặt `reprocess_status='requested'` và phát yêu cầu chạy lại xử lý (F-06) |
| 11 | API | Ghi sự kiện `audit_decision` vào Iceberg outbox trong cùng transaction |
| 12 | API | Commit, xoá cache chi tiết/queue, rồi phát Kafka `qc.audit.passed` / `qc.audit.rejected` nếu `pipeline_kafka_active` |
| 13 | Frontend | Hiển thị toast tương ứng và quay về hàng đợi |

### B. API Specification

**Endpoint**: `/api/v1/qc/audit/queue/{item_id}/submit`
**Method**: POST
**Description**: Ghi nhận quyết định vòng 2. Quyết định này ghi đè kết quả vòng 1 và là quyết định cuối cùng.

**Request**

| **No** | **Field** | **Data type** | **Default value** | **Mandatory** | **Description** |
| --- | --- | --- | --- | --- | --- |
| **Header** | | | | | |
| 1 | `Content-Type` | string | application/json | Yes | Thân yêu cầu dạng JSON. |
| 2 | `Authorization` | string | | Yes | Bearer token. |
| **Path** | | | | | |
| 3 | `item_id` | uuid | | Yes | ID item trong hàng đợi. |
| **Body** | | | | | |
| 4 | `decision` | string | | Yes | Chỉ nhận `pass` hoặc `reject` (ràng buộc `pattern` trong `AuditSubmitRequest`). |
| 5 | `reason` | string\|null | | Có điều kiện | **Mã lý do, bắt buộc theo giao diện khi `decision = reject`.** Backend chỉ cưỡng chế "reject phải có `reason` **hoặc** `comment`"; giá trị `reason` không bị kiểm tra thuộc danh mục — xem ghi chú ở Mục 4.3. Giao diện có hai biến thể theo cờ `ots_reject_reasons`: template `ots-gopro-v1` hiện 6 mã checkbox chọn nhiều (`preview`, `segmentation`, `face`, `id`, `annotation`, `other`) và gửi lên chuỗi ghép `ots:<code>,<code>`; item còn lại vẫn chọn một mã trong `METADATA_QC_REJECT_REASON_KEYS` (5 mã: `reject_reason_segment_error`, `reject_reason_personal_data`, `reject_reason_corruption`, `reject_reason_fps`, `reject_reason_other`). |
| 6 | `comment` | string\|null | | No | Ghi chú tự do; lưu vào `notes` của bản ghi audit. |

**Response**

| **No** | **Field** | **Data type** | **Description** |
| --- | --- | --- | --- |
| 1 | `id` | string | ID item trong hàng đợi. |
| 2 | `status` | string | `audit_passed` hoặc `audit_rejected`. |
| 3 | `decision` | string | `pass` hoặc `reject`. |
| 4 | `audit_round` | integer | Số thứ tự vòng audit của item này, bắt đầu từ 1 và tăng mỗi lần item quay lại. |
| 5 | `error.detail` | string | `Reject requires reason or comment` khi 422; `Bạn không có quyền truy cập Audit.` khi 403 thiếu quyền; `Bạn không thể audit item mà bạn đã review ở vòng 1.` khi 403 vi phạm luật tách vai; `Item này vừa được người khác chấm. Danh sách sẽ được làm mới.` khi 409; `Audit queue item not found` khi 404. |

> **Về 409 khi tranh chấp.** Nhánh 409 nằm sau bước tra item có khoá (`get_audit_item_for_user(for_update=True)`), mà truy vấn đó đã lọc `status='pending_audit'`. Khi auditor khác đã chấm xong, item không còn khớp bộ lọc nên hàm trả `None` và endpoint trả **404** (`Audit queue item not found`), không phải 409 — trừ khi bản ghi được nạp theo cách khác. Vì vậy nhánh toast 409 ở frontend có thể không chạy trong ca tranh chấp thật. Test `test_audit_stale_item_returns_409` kiểm chứng nhánh này bằng cách mock hàm tra item trả về item `audit_passed`, không đi qua truy vấn thật. <!-- TBD: có nên trả 409 thay vì 404 cho ca tranh chấp? -->

**3.2.4. F-04 Enqueue Item To Audit**

#### A. **Flow**

**Diagram**

Xem state diagram: [[docs/review/qc-audit/srs/qc-audit-states.md|QcQueueItem — vòng đời qua hai vòng QC]]

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | Reviewer vòng 1 | Gửi quyết định qua `POST /api/v1/qc/queue/{item_id}/submit` sẵn có |
| 2 | System | `review_store.submit_review` ghi `qc_reviews` như hiện tại, không đổi |
| 3 | System | **Thay đổi:** thay vì `item.status = portal_status_from_review(decision)`, đặt `item.status = 'pending_audit'` khi Pass (kèm `audit_entered_at`) và `item.status = 'needs_revision'` khi Reject |
| 4 | System | **Thay đổi:** bỏ lời gọi `_autofill_delivery_on_pass()` tại đây, chuyển sang F-05 |
| 5 | System | Giữ nguyên các bước còn lại: ghi outbox `review_decision`, đóng phiên review, ghi phiên bản metadata |

### B. API Specification

Không có API — đây là thay đổi hành vi bên trong `review_store.submit_review` của endpoint `POST /api/v1/qc/queue/{item_id}/submit` đã tồn tại. Hợp đồng đối ngoại của endpoint đó không đổi ngoài giá trị `status` trả về, nay là `pending_audit` khi Pass và `needs_revision` khi Reject thay vì `passed`/`rejected`.

**3.2.5. F-05 Handoff To Warehousing On Audit Pass**

#### A. **Flow**

**Diagram**

Xem sequence diagram nhánh `decision = pass`: [[docs/review/qc-audit/srs/qc-audit-flows.md|F-03 Submit Audit Decision (Sequence)]]

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | System | Trong cùng transaction của F-03 nhánh pass, gọi `_autofill_delivery_on_pass` (đã dời từ vòng 1 sang) |
| 2 | System | Dựng bundle bàn giao từ metadata coordinator và giá trị model, theo `resolve_delivery_profiles` và `build_delivery_bundle` sẵn có; kết quả lưu vào `review_config.delivery_overrides` |
| 3 | System | Đặt `item.status = 'audit_passed'`, xoá `reprocess_status` |
| 4 | System | Mở cổng bàn giao: `_audit_gate_open` trong `lakehouse/deliverable_sync.py` chỉ cho deliverable sync chạy khi item ở `audit_passed` (các trạng thái `pending_audit` / `audit_rejected` bị chặn) |
| 5 | System | Phát Kafka `qc.audit.passed` (khi `pipeline_kafka_active`) để Dagster chạy Phase 2 |

> Bước 4–5 là ranh giới tích hợp. Phía Delivery nay đã có kho thật: bảng `portal_warehouse_items`, dòng kho được tạo từ lần Audit Pass (`materialize_from_audit_pass`), màn `/warehousing` đọc `GET /api/v1/warehousing/items`. Endpoint `GET /api/v1/delivery/warehousing/mock-items` cũ chỉ còn phục vụ bộ chọn item của đơn giao hàng, không còn cấp dữ liệu cho màn kho. <!-- TBD: hợp đồng tích hợp Warehousing -->

### B. API Specification

Không có API — xử lý nội bộ, chạy đồng bộ trong transaction của F-03.

**3.2.6. F-06 Requeue For Reprocessing On Audit Reject**

#### A. **Flow**

**Diagram**

Xem state diagram nhánh `audit_rejected → pending`: [[docs/review/qc-audit/srs/qc-audit-states.md|QcQueueItem — vòng đời qua hai vòng QC]]

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | System | Trong F-03 nhánh reject, đặt `item.status = 'audit_rejected'` |
| 2 | System | `audit_reprocessing.request_audit_reprocess` đặt `item.reprocess_status = 'requested'` và ghi outbox `audit_reprocess_requested` |
| 3 | System | Khi `pipeline_kafka_active`, phát Kafka `qc.audit.reprocess_requested`; quá trình xử lý lại bất đồng bộ, không chặn phản hồi của F-03 |
| 4 | Pipeline | Chạy lại toàn bộ khâu xử lý |
| 5 | System | `audit_reprocessing.complete_audit_reprocess(success=True)` đặt `item.status = 'pending'`, `reprocess_status='completed'`, xoá `audit_entered_at` và người được giao — **hàm này chưa có caller trong code**, nên hiện item chưa tự quay về hàng đợi vòng 1 |
| 6 | System | Không giới hạn số vòng — `round_no` tiếp tục tăng ở lần audit sau |

> Bước 5 là điểm hở đã biết: `complete_audit_reprocess` đã có nhưng chưa được nối vào bất kỳ luồng nào (không có endpoint callback từ pipeline). Trường hợp bước 4 thất bại, hoặc thành công mà không ai gọi bước 5, item mắc ở `audit_rejected` và không tự quay về hàng đợi nào. Cần chốt cách xử lý (callback từ pipeline, thử lại tự động, hay danh sách item mắc kẹt cho người vận hành). <!-- TBD: xử lý lỗi khi chạy lại pipeline thất bại -->

### B. API Specification

Không có API riêng — portal phát yêu cầu qua outbox/Kafka; **hiện chưa có cơ chế nhận kết quả xử lý lại** để đưa item về `pending`. Trạng thái reprocess xem được ở cột `qc_queue_items.reprocess_status`.

**3.2.7. F-07 Expose Audit Result In Review History**

#### A. **Flow**

**Diagram**

> *(Đề xuất: không cần diagram — một lượt đọc dữ liệu, không có rẽ nhánh nghiệp vụ)*

**Description**

> **Chưa hoàn thành so với yêu cầu US-005.** Backend đã có endpoint lịch sử Audit, nhưng bọc quyền `qc:audit:perform` nên chỉ auditor gọi được; endpoint lịch sử cũ `/qc/queue/{item_id}/review-sessions` vẫn chỉ trả phiên vòng 1 và không được mở rộng; không màn frontend nào hiển thị kết quả Audit cho reviewer vòng 1. Bảng dưới mô tả hành vi thực tế của endpoint mới.

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | Auditor | Gọi lịch sử của một item (hiện chưa có màn nào gọi; API dùng được trực tiếp) |
| 2 | Frontend | `GET /api/v1/qc/audit/queue/{item_id}/history` |
| 3 | API | Kiểm tra quyền `qc:audit:perform` — reviewer vòng 1 và QC Lead không có quyền này, nên không truy cập được |
| 4 | API | Tra item: ưu tiên hàng đợi hiển thị cho người gọi (auditor thấy item `pending_audit` hoặc item audit của mình); không thấy thì 404 |
| 5 | API | Trả `round1_sessions` (các phiên review vòng 1) và `audit_rounds` (các vòng audit đã chấm) |

### B. API Specification

**Endpoint**: `/api/v1/qc/audit/queue/{item_id}/history`
**Method**: GET
**Description**: Lịch sử hai vòng của một item. Là endpoint riêng, **không** phải mở rộng của `/qc/queue/{item_id}/review-sessions`.

**Request**

| **No** | **Field** | **Data type** | **Default value** | **Mandatory** | **Description** |
| --- | --- | --- | --- | --- | --- |
| **Header** | | | | | |
| 1 | `Authorization` | string | | Yes | Bearer token. |
| **Path** | | | | | |
| 2 | `item_id` | uuid | | Yes | ID item (nhận cả `external_id`). |

**Response** — `AuditReviewHistoryOut`

| **No** | **Field** | **Data type** | **Description** |
| --- | --- | --- | --- |
| 1 | `round1_sessions[]` | array | Các phiên review vòng 1 (`QcReviewSessionOut`): `id`, `reviewer_id`, `reviewer_name`, `opened_at`, `expires_at`, `status`, `submitted_at`, `decision`, `revision`, `reason_code`, `notes`. |
| 2 | `audit_rounds[].round_no` | integer | Số thứ tự vòng audit. |
| 3 | `audit_rounds[].decision` | string | `pass` hoặc `reject`. |
| 4 | `audit_rounds[].reason_code` | string\|null | Mã lý do khi reject. |
| 5 | `audit_rounds[].notes` | string\|null | Ghi chú của auditor. |
| 6 | `audit_rounds[].auditor_id` | string | ID auditor. |
| 7 | `audit_rounds[].auditor_name` | string | Tên auditor (không ẩn danh). |
| 8 | `audit_rounds[].audited_at` | datetime | Thời điểm chấm vòng 2. |
| 9 | `error.detail` | string | `Bạn không có quyền truy cập Audit.` khi 403; `QC queue item not found` khi 404. |

> Trạng thái "item chưa audit" trong yêu cầu cũ (field `audit_pending`) **không tồn tại** trong schema thực tế: client tự suy ra từ `audit_rounds` rỗng.

## 4. NON-FUNCTIONAL REQUIREMENTS

**4.1. Performance Requirements**

Hàng đợi Audit có khối lượng truy vấn tương đương `/qc/queue` hiện có, cộng thêm một phép join sang `qc_reviews` và một điều kiện lọc theo `reviewer_id`. Chỉ tiêu đặt ngang với hàng đợi vòng 1:

- 95% lượt gọi `GET /audit/queue` phản hồi dưới 800 ms với trang 50 dòng.
- 95% lượt gọi `POST /audit/queue/{id}/submit` phản hồi dưới 1000 ms, không tính thời gian pipeline chạy lại ở nhánh reject (bất đồng bộ).
- Số người dùng đồng thời: 20 auditor.
- Kiểm thử tải: 20 người dùng ảo, tăng dần trong 2 phút, chạy 10 phút.

Cần chỉ mục trên `qc_queue_items.status` và `qc_reviews.reviewer_id` để phép lọc luật tách vai không gây quét toàn bảng. Truy vấn hàng đợi hiện có sẵn chỉ mục `qc_reviews(uuidv7)` và `qc_audit_reviews(uuidv7, auditor_id, audited_at, queue_item_id)` từ migration `20260909_0050`.

**4.2. Availability & Reliability**

- Độ sẵn sàng: 99.5% mỗi tháng, ngang với phần còn lại của portal.
- RTO 4 giờ, RPO 15 phút — theo cấu hình sao lưu PostgreSQL hiện hành, sub-module này không đặt yêu cầu riêng.
- Ghi quyết định Audit và cập nhật trạng thái item phải nằm trong **cùng một transaction** với bản ghi outbox, để không xảy ra trạng thái đã đổi mà sự kiện chưa phát. (Đã thực hiện: `audit_store.submit_audit_decision` ghi `QcAuditReview` + đổi trạng thái + `enqueue_iceberg_event` rồi mới commit.)
- Nhánh reject: pipeline chạy lại thất bại không được làm mất bản ghi quyết định Audit đã commit. **Chưa có cơ chế đưa item về `pending` sau khi xử lý lại — xem F-06.**

**4.3. Security Requirements**

- Xác thực: OIDC qua Keycloak dùng chung, đúng cơ chế hiện có của portal.
- Phân quyền: RBAC theo nhóm SSO. Quyền `qc:audit:perform` cấp cho nhóm `vd-qc-auditors`. **Không cấp quyền này cho `vd-qc-reviewers`** để giữ tách bạch hai vòng.
- **Luật tách vai cưỡng chế ở tầng backend**, không chỉ ẩn ở giao diện: F-01 lọc ở tầng SQL (`QcReview.reviewer_id != user.id`), F-03 chặn ghi (403). F-02 vì dùng chung truy vấn hàng đợi nên item vi phạm không hiển thị → trả 404 chứ không phải 403. Ẩn ở frontend là tiện lợi cho người dùng, không phải biện pháp bảo mật.
- Kiểm tra đầu vào: `decision` chỉ nhận `pass`/`reject` theo ràng buộc `pattern`. **`reason` chưa bị cưỡng chế ở backend**: kiểu là `string | null`, không đối chiếu danh mục; backend chỉ chặn khi reject mà thiếu cả `reason` lẫn `comment` (422). Danh mục mã lý do (6 mã OTS GoPro hoặc 5 mã còn lại) hiện chỉ được giới hạn ở giao diện.
- Nhật ký kiểm toán: mọi quyết định Audit lưu vĩnh viễn trong `qc_audit_reviews` kèm `auditor_id` và thời điểm; không có API sửa/xoá bản ghi sau khi ghi.

**Đã chốt tên (trước đây là xung đột cần xử lý).** Quyền `audit:view` và nhóm `vd-audit-viewers` vẫn tồn tại cho mục đích khác (xem nhật ký quản trị). Tính năng này dùng tên khác hẳn: quyền `qc:audit:perform`, nhóm `vd-qc-auditors`; không gộp vào `vd-audit-viewers`.

**4.4. Scalability Requirements**

- Không cần khả năng mở rộng riêng: sub-module chạy trong tiến trình backend sẵn có, mở rộng theo cùng cơ chế.
- Bảng `qc_audit_reviews` tăng theo số lượt audit; item quay vòng nhiều lần sinh nhiều dòng. Ước tính ban đầu dưới 100 nghìn dòng mỗi năm — không cần phân mảnh.
- Kết nối cơ sở dữ liệu dùng chung pool qua PgBouncer như hiện tại.
- Không đặt ngưỡng tự động mở rộng riêng cho sub-module này.

**4.5. Maintainability Requirements**

- Độ phủ kiểm thử đơn vị tối thiểu 80% cho `audit_store.py` và `audit_queries.py`, ngang chuẩn đang áp cho `backend/tests/features/qc/`. Hiện có `backend/tests/features/qc/test_audit.py` (pass nhánh tách vai, tranh chấp, reject thiếu lý do) và phần cập nhật trong `test_review_submit.py`.
- Bắt buộc có test cho ba nhánh dễ sai: luật tách vai, tranh chấp hai auditor cùng chấm, và thiếu mã lý do khi reject.
- Tài liệu API sinh tự động qua OpenAPI của FastAPI, xem tại `/docs`.
- Triển khai theo pipeline CI/CD hiện hành; migration `20260909_0050_qc_audit_round2` tạo bảng và hai cột mới, chưa kèm script chuyển đổi dữ liệu cho item đang ở `passed`/`rejected` tại thời điểm phát hành (`_audit_gate_open` vẫn cho các dòng `passed` cũ đi tiếp nên không chặn nhầm).
- Quan sát vận hành: ghi log ở mức thông tin cho mỗi quyết định Audit (`logger` trong `audit_reprocessing`), mức cảnh báo khi reprocess thất bại.

**4.6. Usability & Accessibility**

- Trình duyệt hỗ trợ: theo chuẩn chung của portal, không đặt yêu cầu riêng.
- Bố cục thiết kế cho màn hình rộng 1024 px trở lên — xem [[docs/review/qc-audit/ascii-screen/_index.md|wireframe]]. Không tối ưu cho điện thoại ở phase này.
- Song ngữ Việt–Anh qua cơ chế i18n sẵn có; mọi chuỗi mới phải có cả hai bản.
- Mã lý do dùng lại các khóa dịch `reject_reason_*` đã có; riêng item OTS GoPro thêm 6 khóa mới `reject_reason_ots_*` (preview, segmentation, face detection, ID card, annotation, other), có cả bản Việt và Anh.
- Chuẩn hỗ trợ tiếp cận: **không áp dụng riêng cho phase này** — portal chưa đặt mức WCAG chính thức cho bất kỳ màn nào; Audit theo mặt bằng chung.

**4.7. Compliance & Regulatory**

- Dữ liệu xử lý là nội dung thu thập đã qua khâu làm mờ khuôn mặt ở vòng 1; Audit không tạo thêm loại dữ liệu cá nhân mới.
- Nhật ký quyết định Audit chứa định danh người dùng nội bộ, không chứa dữ liệu cá nhân của người được quay.
- Thời gian lưu bản ghi Audit: theo chính sách lưu trữ chung của dữ liệu QC. <!-- TBD: chưa có chính sách lưu trữ thành văn cho dữ liệu QC -->
- Không áp dụng chuẩn ngành riêng (PCI-DSS, HIPAA) — không xử lý dữ liệu thanh toán hay y tế.

**NFR Summary Table**

| **ID** | **Requirement** | **Metric / Target** | **Priority** |
| --- | --- | --- | --- |
| **NFR-P-01** | Thời gian phản hồi truy vấn hàng đợi Audit | 95% lượt gọi < 800 ms, trang 50 dòng | High |
| **NFR-P-02** | Thời gian phản hồi ghi quyết định Audit | 95% lượt gọi < 1000 ms, không tính pipeline bất đồng bộ | High |
| **NFR-P-03** | Số auditor đồng thời | 20 người | Medium |
| **NFR-P-04** | Cấu hình kiểm thử tải | 20 người dùng ảo, tăng dần 2 phút, chạy 10 phút | Medium |
| **NFR-A-01** | Độ sẵn sàng của sub-module | >= 99.5% mỗi tháng | High |
| **NFR-A-02** | Thời gian phục hồi sau sự cố (RTO) | <= 4 giờ | Medium |
| **NFR-A-03** | Mất mát dữ liệu tối đa (RPO) | <= 15 phút | Medium |
| **NFR-A-04** | Tính nguyên tử của quyết định Audit | Ghi quyết định, đổi trạng thái và ghi outbox trong cùng 1 transaction | High |
| **NFR-SEC-01** | Cưỡng chế luật tách vai ở backend | Đã có ở tầng SQL cho danh sách + ghi quyết định (403); chi tiết trả 404 do dùng chung truy vấn hàng đợi | High |
| **NFR-SEC-02** | Tách quyền giữa hai vòng | `qc:audit:perform` không cấp cho nhóm `vd-qc-reviewers`; nhóm auditor là `vd-qc-auditors` | High |
| **NFR-SEC-03** | Ràng buộc giá trị mã lý do | Chưa đạt: backend nhận chuỗi tự do, chỉ chặn reject thiếu cả lý do lẫn ghi chú; danh mục mã do UI giới hạn (OTS GoPro: 6 mã, gửi chuỗi ghép) | High |
| **NFR-SEC-04** | Tính bất biến của nhật ký Audit | Bản ghi không xóa, không sửa sau khi ghi | High |
| **NFR-SC-01** | Khối lượng dữ liệu bảng audit | < 100.000 dòng/năm, không cần phân mảnh | Low |
| **NFR-M-01** | Độ phủ kiểm thử đơn vị | >= 80% cho `audit_store.py` và `audit_queries.py` | High |
| **NFR-M-02** | Kiểm thử bắt buộc cho nhánh rủi ro | Có test cho tách vai, tranh chấp đồng thời, thiếu mã lý do | High |
| **NFR-U-01** | Bề rộng màn hình mục tiêu | >= 1024 px; không tối ưu điện thoại ở phase này | Medium |
| **NFR-U-02** | Song ngữ | Mọi chuỗi mới có cả bản Việt và Anh | Medium |
| **NFR-C-01** | Chuẩn ngành riêng | Không áp dụng — không xử lý dữ liệu thanh toán hay y tế | Low |

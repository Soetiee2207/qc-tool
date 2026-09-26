---
title: QC Review Queue — baseline từ code hiện có
feature: qc-queue
idea-slug: baseline-from-code
mode: deep
owner: "@cursor-agent"
updated: 2026-09-25
tags: [brainstorm, qc, queue, review]
changelog:
  - 2026-09-25 | docs-sync | Lựa chọn nay giữ khi đổi trang (chỉ reset theo filter); bulk assign chia cân bằng theo thời lượng (`buildBalancedAssignMap`), không còn round-robin
  - 2026-09-22 | docs-sync | Đảo kết luận cũ: selection nay reset khi đổi trang/filter (DP-394); thanh chọn hợp nhất `QCQueueSelectionBar`, "Xuất tất cả" chạy nền
  - 2026-09-11 | docs-sync | Đối chiếu code: route `/qc/review`, bulk assign qua modal (1 hoặc nhiều reviewer), selection không còn bị clear khi đổi trang/filter
  - 2026-09-05 | /brainstorm | Viết lại đầy đủ từ router.py + QCQueue.tsx
---

# Brainstorm — QC Review Queue

## 1. Tổng quan

**QC Review Queue** là màn hình danh sách video chờ QC trên portal Data Platform. QC Lead và Reviewer xem, lọc, gán người review, xuất báo cáo và mở màn review chi tiết. Hệ thống đồng bộ item từ ingestion/lakehouse vào hàng đợi PostgreSQL (`qc_queue_items`).

**Pain:** Không có single pane để biết ai đang review gì, filter theo project/priority/status, bulk assign cho team.

**Why now:** Module đã ship trên prod/dev; cần baseline doc để onboard dev/QA và traceability sang URD/SRS.

## 2. User types & capabilities

| Role | Mô tả | P0 | P1 |
|------|-------|----|----|
| QC Reviewer | Review video được gán | Xem queue (scope project), mở review | — |
| QC Lead | Phân công, giám sát | Bulk assign, export, filter all projects | Saved views |
| Admin / `vd_qc_leads` | Toàn quyền queue | Filter mọi project | Sync manual |
| Annotation reviewer | Hàng đợi annotation | `manual_annotation_only=true` mode | — |

**P0:** List + filter URL-sync, pagination 20/trang, bulk assign, export xlsx/csv, navigate review.

**P1:** Batch filter (`batch_id`), assignee filter API (chưa wire FE đầy đủ), TapData queue variant.

**P2:** Real-time queue updates (websocket).

## 3. Entry points

| Route | Mode | `product_line` / flag |
|-------|------|------------------------|
| `/qc/review` | Final QC | `product_line=all` |
| `/qc/review/{id}` | Chi tiết review | quyền `qc:review:perform` |
| `/qc/queue` | (legacy) | redirect → `/qc/review` |
| `/qc/annotation` | Manual annotation | `manual_annotation_only=true` |

Sidebar: **Đánh giá → QC Review** (mục `nav_qc_queue` trong nhóm `nav_qc_review`). Mode `tapdata_qc` vẫn còn trong code nhưng không route nào mount; `/tapdata/qc/queue` redirect về `/qc/review`.

## 4. Assumptions

- Auth Keycloak SSO; permission `qc:queue:view` bắt buộc.
- Visibility scope: reviewer **không** có `qc:assign` chỉ thấy item được gán cho mình; **trừ** thành viên project ở Members tab với role `qc_reviewer` (thấy cả queue của project — cập nhật 2026-09-22); lead/admin thấy rộng hơn (logic `visible_queue_list_stmt`, cache key qua `review_queue_assignee_only`).
- Status hợp lệ: `pending`, `in_review`, `passed`, `rejected`, `needs_revision`.
- Priority: `critical`, `high`, `medium`, `low`.
- Assign chuyển `pending` → `in_review` tự động.
- Export large warning khi `count > 10_000`.

## 5. Core Flows (Happy Path)

### 5.1 Xem và lọc hàng đợi

1. User mở `/qc/review` (URL cũ `/qc/queue` redirect về đây).
2. FE kiểm tra `qc:queue:view`; đọc query params (`page`, `q`, `status`, `priority`, `project_id`, `from`, `to`).
3. FE gọi `GET /api/v1/qc/queue` (limit=20).
4. Backend filter theo visibility + params; trả `data[]` + `pagination`.
5. FE render bảng: checkbox, thumbnail, filename, upload id, project, duration, status chip (+ lý do reject nếu có), priority, assignee, tuổi item, nút mở đánh giá.
6. User đổi filter → URL cập nhật (`replace: true`) → refetch.

```
┌──────────┐    GET /qc/queue     ┌─────────┐    SQL      ┌──────────┐
│ Reviewer │ ───────────────────► │ FastAPI │ ──────────► │ Postgres │
│ Browser  │ ◄─────────────────── │  qc     │ ◄────────── │ qc_queue │
└──────────┘   JSON + pagination  └─────────┘             └──────────┘
```

### 5.2 Bulk assign

1. QC Lead tick checkbox nhiều dòng trên trang hiện tại (hoặc select all trang); selection **giữ nguyên khi đổi trang** và chỉ **bị reset khi đổi filter** (DP-394) — muốn gán cho cả tập khớp lọc thì tick hết trang rồi bấm "Chọn hết" trên banner.
2. Thanh chọn `QCQueueSelectionBar` (chỉ render khi user có quyền VÀ có ≥1 dòng được chọn) hiện badge "Đã chọn {N} mục", nút **Phân công**, 2 nút Export (theo quyền), link **Hủy**; tick hết trang thì hiện banner "Chọn cả {N} mục khớp bộ lọc?".
3. Bấm **Phân công** → mở modal `QCQueueBulkAssignDialog`; chọn reviewer từ `GET /api/v1/qc/auto-assign/reviewers` (search + tick), có thể chọn nhanh theo nhóm người dùng (`GET /api/v1/admin/users/groups` + `…/members`).
4. 1 reviewer → `POST /api/v1/qc/queue/assign` với `item_ids`, `assignee_id`, `assignee_name`, `assignee_initials`.
5. ≥2 reviewer → FE chia cân bằng theo tổng thời lượng (`buildBalancedAssignMap` — item dài nhất trước), hiện bảng preview sửa tay, rồi gửi `assignments[]` (mỗi item 1 assignee).
6. Batch > 200 item → phải tick checkbox xác nhận trong modal mới gửi được.
7. Backend cập nhật assignee; `pending` → `in_review`; đảm bảo project access; item đã có người gán bị bỏ qua và đếm vào `skipped`.
8. Toast: "Đã phân công {updated} mục cho {assignee}" (1 người) hoặc "Đã gán {updated} mục cho {K} người" / "Đã gán {X}/{Y} mục — {Z} mục không gán được" (có skip).

### 5.3 Export danh sách

1. User tick ≥1 dòng → thanh chọn hiện; hoặc dùng nút "Xuất tất cả" cho scope theo filter.
2. Bấm **Xuất theo lựa chọn** / **Xuất tất cả** → `POST /qc/queue/export/preview`.
3. Preview trả `count`, `scope` (`selected`|`filtered`), `large_export_warning`.
4. Dialog chọn xlsx/csv → confirm. Scope `selected` → `POST /qc/queue/export` (đồng bộ); scope `filtered` → job nền + poll → download.

### 5.4 Mở review

1. User click row hoặc nút review (chỉ status `pending|in_review|needs_revision`).
2. FE navigate `/qc/review/{id}` với `state.nextIds` (queue reviewable còn lại trên trang).

## 6. System Behavior Deep Dive

### 6.1 Decision Points

| ID | Flow | Khi nào | YES | NO |
|----|------|---------|-----|-----|
| D-01 | List | User có `dashboard:admin` hoặc role `vd_qc_leads`? | Filter all projects | Chỉ assigned projects |
| D-02 | Assign | Item tồn tại trong scope? | Update + count++ | Skip item |
| D-03 | Assign | `status=pending`? | → `in_review` | Giữ status |
| D-04 | Export | `item_ids` non-empty? | scope=selected | scope=filtered |
| D-05 | Export | count=0? | Toast lỗi, không mở dialog | Mở dialog |
| D-06 | Review btn | status ∈ REVIEWABLE? | Navigate review | Row vẫn click được |

### 6.2 Scenario matrix

| From state | Action | Rule | Result |
|------------|--------|------|--------|
| pending | Assign | có `qc:assign` | in_review + assignee set |
| in_review | Assign | reassign | assignee đổi, status giữ |
| passed | Assign | — | Vẫn assign được (code không chặn) |
| any | Export 0 rows | preview count=0 | Error toast `qc_export_no_items` |
| filtered | Change filter (đổi trang giữ nguyên lựa chọn) | selection reset | `assignSelected` về rỗng (DP-394) — phải tick lại |
| bất kỳ | Assign item đã có assignee | `_queue_item_already_assigned` | Bỏ qua item đó, đếm vào `skipped` |

### 6.3 State transitions (queue item)

| Entity | Từ | Sang | Trigger | Quay lại? |
|--------|-----|------|---------|-----------|
| QcQueueItem | pending | in_review | bulk_assign / auto_assign | Không tự động |
| QcQueueItem | in_review | passed/rejected/needs_revision | submit review (module khác) | needs_revision → in_review khi assign lại |

### 6.4 Edge cases khác

- Legacy URL param `project` → migrate sang `project_id` qua `resolveProjectFilterId`.
- Project filter text (tên) → resolve UUID async trước khi gọi API.
- Đổi filter → selection **bị reset** (`clearSelection()` qua effect `selectionResetKey` — key đã bỏ `page`); đổi trang thì giữ nguyên lựa chọn. Effect cũng xoá `assignOpen` và `dismissSelectAllBanner`. Chỉ còn một tập chọn `assignSelected` dùng chung cho Gán lẫn Xuất.
- Empty queue → `EmptyState` "Hàng đợi trống".

## 7. Validation, Limits & Wording

### 7.1 Limits

| Rule | Giá trị |
|------|---------|
| Page size FE | 20 (`QC_QUEUE_PAGE_SIZE`) |
| API limit max | 500 |
| Export large warning | count > 10_000 |
| Assign min items | ≥1 — `item_ids` rỗng/None thì backend trả 422 `item_ids or assignments required` |
| Assign cảnh báo batch lớn | > 200 item (FE, phải tick checkbox xác nhận mới gửi) |
| Assign batch cap | Không cap trên `item_ids`/`assignments` |
| Queue total cache TTL | 30s (page 1, no filters) |

### 7.2 Error messages (i18n keys → VI)

| Key | Wording (VI) |
|-----|--------------|
| `bulk_assign_no_page_selection` | Chọn ít nhất 1 video để gán — **dead code**: thanh chọn chỉ render khi đã có ≥1 mục, không còn đường nào fire key này |
| `bulk_assign_pick_reviewer` | Chọn ít nhất 1 người để gán |
| `auto_assign_reviewers_none_available` | Không có reviewer khả dụng |
| `bulk_assign_quick_group_empty` | Không tìm thấy nhóm |
| `bulk_assign_quick_group_none` | Không có reviewer QC hợp lệ trong nhóm này |
| `bulk_assign_quick_group_failed` | Không tải được danh sách thành viên nhóm |
| `assign_failed` | Phân công thất bại |
| `assign_success` | Đã phân công {updated} mục cho {assignee} |
| `qc_export_no_items` | Không có mục để xuất |
| `qc_export_failed` | Xuất thất bại |
| `empty_queue_title` | Hàng đợi trống |
| `empty_queue_desc` | Không có video nào khớp bộ lọc |

### 7.3 Success / info

| Key | Wording |
|-----|---------|
| `qc_in_queue` | trong hàng đợi |
| `assign_multi_success` | Đã gán {updated} mục cho {reviewers} người |
| `assign_partial_success` | Đã gán {updated}/{total} mục — {skipped} mục không gán được |
| `bulk_assign_selected` | Đã chọn {count} mục |
| `bulk_assign_quick_group_selected` | Đã thêm {count} reviewer QC hợp lệ từ nhóm |
| Export scope selected | Xuất {count} mục đã chọn |
| Export scope filtered | Xuất {count} mục theo bộ lọc |

## 8. System context (business)

- **Lưu:** queue item metadata, assignee, status, priority, tags/batch_id, project link.
- **Đọc:** Projects (tên), ingestion sync, lakehouse duration mirror.
- **Không** xử lý playback/review submit trên màn list (module review detail).

## 9. Risks

| Rủi ro | Khả năng | Hậu quả | Cách phòng |
|--------|----------|---------|------------|
| Export 10k+ rows chậm | Thỉnh thoảng | Browser timeout | large_export_warning + **job nền đã ship** (scope `filtered`, DP-382) |
| Visibility scope sai | Hiếm | Lộ data cross-project | Test matrix role × project |
| Stale total count | Thường | Số subtitle lệch 30s | Accept cache hoặc giảm TTL |

## 10. Success metrics

- p95 list API < 2s với filter thông thường.
- Bulk assign 50 items < 3s.
- 0 item ngoài scope được assign thành công.

## 11. Open questions

| ID | Câu hỏi |
|----|---------|
| OQ-1 | FE chưa expose `assignee_id` / `batch_id` filter — có ship P1? |
| OQ-2 | TapData queue có cần export column khác? |

## 12. API inventory (tham chiếu SRS)

| Method | Path | Permission |
|--------|------|------------|
| GET | `/api/v1/qc/queue` | `qc:queue:view` |
| GET | `/api/v1/qc/queue/{item_id}` | `qc:queue:view` |
| GET | `/api/v1/qc/queue/batches` | `qc:queue:view` |
| GET | `/api/v1/qc/queue/assignees` | `qc:queue:view` |
| POST | `/api/v1/qc/queue/assign` | `qc:assign` |
| POST | `/api/v1/qc/queue/export/preview` | `qc:result:export` |
| POST | `/api/v1/qc/queue/export` | `qc:result:export` |
| POST | `/api/v1/qc/queue/export/jobs` | `qc:result:export` + group |
| GET | `/api/v1/qc/queue/export/jobs/{job_id}` | `qc:result:export` + group (chỉ job mình tạo) |
| GET | `/api/v1/qc/queue/export/jobs/{job_id}/download` | `qc:result:export` + group (chỉ job mình tạo) |
| POST | `/api/v1/qc/sync` | `qc:queue:view` |

Modal Gán hàng loạt còn gọi API nhóm người dùng (module Admin): `GET /api/v1/admin/users/groups` và `GET /api/v1/admin/users/groups/{name}/members` (`user:view`); tạo nhóm nhanh `POST /api/v1/admin/users/groups` + `PUT /api/v1/admin/users/groups/{name}/members` (`user:manage`). Xuất file còn yêu cầu user thuộc nhóm SSO trong `QC_QUEUE_EXPORT_GROUPS` (`require_qc_queue_export`).

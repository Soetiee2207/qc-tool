## Wireframe (ASCII)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Đánh giá  ›  QC Review                                                                                  │
│  128 video trong hàng đợi                                                                                │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  [ Saved views ▼ ]  [ Tìm theo tên file, upload id, project...            ]  [ Từ ngày ] – [ Đến ngày ]  │
│  [ Project: Tất cả ▼ ]  [ Ưu tiên: Mọi ưu tiên ▼ ]  [ Trạng thái: Tất cả trạng thái ▼ ]  [ Làm mới ]     │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  Đã chọn 20 mục  │  [ Phân công ]  │  [ Xuất theo lựa chọn ]  │  [ Xuất tất cả 128 mục khớp lọc ]  │ Hủy │
│  Đã chọn 20/20 mục trên trang. Chọn cả 128 mục khớp bộ lọc?   [ Chọn hết ]  [ Bỏ qua ]                   │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ☐ │ ▶ │ filename.mp4         │ UP-2026-001 │ Project Alpha │ 02:15 │ ● Chờ xử lý    │ Cao        │ NV A │ 05/09 │
│ ☑ │ ▶ │ clip_bathroom_01.mp4 │ UP-2026-002 │ Project Beta  │ 01:42 │ ◐ Đang xem xét │ Trung bình │ —    │ 04/09 │
│ ☑ │ ▶ │ kitchen_task_03.mp4  │ UP-2026-003 │ Project Alpha │ 03:01 │ ● Chờ xử lý    │ Khẩn cấp   │ —    │ 04/09 │
│ ☐ │ ▶ │ passed_sample.mp4    │ UP-2026-004 │ Project Gamma │ 00:58 │ ✓ Đã duyệt     │ Thấp       │ TB   │ 03/09 │
│                    [ ◀ Trước ]   Trang 2 / 7   [ Sau ▶ ]                                                 │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

*Mỗi dòng có thêm nút icon "Mở đánh giá" ở cột cuối (bấm cả dòng cũng mở đánh giá).*

**Thanh chọn (`QCQueueSelectionBar`) chỉ render khi đã tick ≥1 dòng** — không có bước "bật chế độ xuất" riêng, và không còn nút Xuất nào ở góc phải header. Bỏ tick hết (hoặc bấm "Hủy") thì thanh chọn biến mất.

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Tiêu đề PageShell | Heading | string | • `nav_qc_queue` / `nav_tapdata_qc_queue` / `nav_qc_annotation` theo `mode`<br>• Subtitle: `{pagination.total} {dash_qc_videos} {qc_in_queue}`<br>• Không có nút action nào trên header (prop `actions` của `PageShell` không còn được dùng) |
| 2 | Ô tìm kiếm | Text input | string | • Placeholder `qc_search_placeholder`<br>• Debounce qua `useDebouncedUrlSearch`; commit → `q` param, `page=1`<br>• Search ILIKE filename, external_id, assignee, project name, ingest_job_id |
| 3 | Saved views | Dropdown | saved params | • `savedViewPage`: `qc-queue` \| `tapdata-qc-queue` \| `qc-annotation-queue`<br>• Apply → merge `qcFiltersToSavedParams` |
| 4 | Làm mới | Button | — | • `reload()` TanStack Query<br>• Thứ tự thật trên thanh filter: Saved views → ô tìm kiếm → khoảng ngày → Project → Ưu tiên → Trạng thái → Làm mới |
| 5 | Lọc trạng thái | Select | enum | • Option đầu = "Tất cả trạng thái" (`all_statuses`); các giá trị còn lại theo mode: queue Review/TapData chỉ có pending / in_review, mode annotation mới đủ 5 giá trị pending / in_review / passed / rejected / needs_revision<br>• URL `status` |
| 6 | Lọc ưu tiên | Select | enum | • Option đầu = "Mọi ưu tiên" (`all_priorities`); các giá trị: critical / high / medium / low<br>• URL `priority`<br>• Mọi writer nay dùng `DEFAULT_PRIORITY` = `medium` (`priority.py`) — giá trị lạ `normal` cũ đã backfill về `medium`, nên không còn dòng nào hiện badge Medium mà filter không khớp (DP-380) |
| 7 | Lọc project | ProjectFilterInput | uuid\|all | • `assigned=!canFilterAllProjects`<br>• Lead/admin: all projects<br>• URL `project_id`; legacy `project` auto-migrate |
| 8 | Khoảng ngày | Date range | ISO date | • `from`, `to` → `created_from`, `created_to` API (GMT+7 day boundary) |
| 9 | Thanh chọn (`QCQueueSelectionBar`) | Toolbar (above table) | — | • Mục đích: điểm vào DUY NHẤT cho cả Gán lẫn Xuất — thay cho cặp bulk bar Gán + mode bar Xuất trước đây<br>• States: render **chỉ khi** `assignSelected.size > 0`; bỏ tick hết hoặc bấm "Hủy" thì thanh biến mất (không có trạng thái disabled toàn thanh)<br>• Thứ tự phần tử: badge → Phân công → Xuất theo lựa chọn → Xuất tất cả → Hủy; các nút Export chỉ render khi có `qc:result:export` |
| 10 | Badge lựa chọn | Text (badge) | int | • `bulk_assign_selected` = "Đã chọn {N} mục" — dùng chung cho cả Gán lẫn Xuất (không còn nhãn riêng cho chế độ xuất)<br>• N = `assignSelected.size` — gồm cả các dòng đã tick ở trang khác vì **đổi trang không reset** lựa chọn; chỉ đổi filter mới reset (xem #15) |
| 11 | Nút Phân công | Button | — | • Mục đích: mở modal Gán hàng loạt (`qc-queue-bulk-assign.md`); nhãn `assign` = "Phân công" + icon Users<br>• Chỉ render khi user có `qc:assign`; không có trạng thái disabled vì thanh chọn đã yêu cầu ≥1 mục được chọn<br>• Navigation: mở modal, không điều hướng route |
| 12 | Nút "Xuất theo lựa chọn" | Button | — | • `qc_export_selected_action`; gate `qc:result:export`<br>• Export đúng N dòng đã tick, **không** phụ thuộc filter hiện tại; chạy **đồng bộ** (`POST /api/v1/qc/queue/export`)<br>• Disabled khi đang load preview hoặc `selectedCount === 0`<br>• Chi tiết dialog xem `docs/review/qc-review-export-list/` |
| 13 | Nút "Xuất tất cả {M} mục khớp lọc" | Button | — | • `qc_export_filtered_action`, `{count}` = `pagination.total`; gate `qc:result:export`<br>• Export toàn bộ item khớp filter (mọi trang) qua **job nền** — `POST /api/v1/qc/queue/export/jobs`, poll, rồi tải; user chờ trong dialog (timeout 10 phút)<br>• Disabled khi đang load preview hoặc `filteredTotal === 0` |
| 14 | Link Hủy | Link | — | • `cancel` = "Hủy" → `clearSelection()`: `assignSelected` + `assignSelectedMeta` về rỗng, đóng modal Gán nếu đang mở, reset banner "chọn hết" |
| 15 | Checkbox cột | Checkbox | set\<id\> | • Mục đích: cập nhật **một** tập `assignSelected` dùng chung cho cả Gán lẫn Xuất — không còn tập chọn riêng cho export<br>• Header: select all **trang hiện tại**<br>• **Selection chỉ reset khi đổi filter** (`selectionResetKey` đã bỏ `page` → `clearSelection()`, DP-394) — đổi trang (kể cả quay lại trang cũ) vẫn giữ nguyên tick; muốn chọn rộng hơn thì dùng banner "Chọn hết" (#16) |
| 16 | Banner chọn theo lọc | Banner (inline) | — | • Mục đích: cho phép mở rộng chọn ra toàn bộ N video khớp bộ lọc hiện tại thay vì tick tay từng trang — cách duy nhất gom cả tập khớp lọc trong 1 lượt gán<br>• States: chỉ hiện khi (a) có `qc:assign`, (b) đã tick hết **toàn bộ** dòng đang hiển thị trên trang, (c) `pagination.total > số dòng trang này` (còn mục khác ngoài trang) và (d) chưa bấm "Bỏ qua"<br>• Wording `bulk_assign_select_all_banner`: "Đã chọn {pageSelected}/{pageTotal} mục trên trang. Chọn cả {filteredTotal} mục khớp bộ lọc?"<br>• Nút [ Chọn hết ] (`bulk_assign_select_all_action`) → FE gọi `fetchAllFilteredQcQueueItems` (nhiều lần `GET /api/v1/qc/queue`, limit=500/lần) tới khi đủ N id, gộp vào selection rồi tự ẩn banner; [ Bỏ qua ] (`bulk_assign_select_all_dismiss`) → ẩn banner, giữ nguyên chọn theo trang |
| 17 | Thumbnail ▶ | Color block | hex | • `thumbnail_color` từ API |
| 18 | Filename | Text + link | string | • `TruncatedFilename`; mono font |
| 19 | Upload ID | Text | string | • `external_id` / upload id column |
| 20 | Project | ProjectLink | uuid+name | • Navigate project detail |
| 21 | Duration | Text | string | • Human duration từ lakehouse mirror |
| 22 | Status | StatusChip | enum | • `qcStatusLabel`; màu theo status<br>• Khi status = `rejected` và có `reject_reason_code`, hiện thêm dòng lý do (`rejectReasonLabel`) ngay dưới chip |
| 23 | Priority | StatusChip | enum | • `priorityLabel` |
| 24 | Assignee | Avatar initials + Text | string | • Vòng tròn initials từ `assignee_initials` + tên qua `assigneeLabel`<br>• Chưa gán → initials "—" và nhãn "Chưa phân công" (`assignee_unassigned`) |
| 25 | Created at | Text | string | • Cột header `created_at` nhưng giá trị render là `item.age` — nhãn tuổi tương đối do API trả (vd `05/09`), fallback "—" |
| 26 | Nút Review | Button | — | • `ClipboardCheck` icon, aria-label/tooltip "Mở đánh giá" (`open_review`)<br>• Row click cũng mở review<br>• Navigate `qcReviewPath(mode, id)` + `nextIds` |
| 27 | Phân trang | ListPagination | int | • `QC_QUEUE_PAGE_SIZE=20`<br>• URL `page` |
| 28 | Empty state | EmptyState | — | • `empty_queue_title` / `empty_queue_desc` khi `items.length=0` và không loading |

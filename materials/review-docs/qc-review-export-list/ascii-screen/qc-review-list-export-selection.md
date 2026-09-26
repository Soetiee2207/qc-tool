## Wireframe (ASCII)

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│  QC Review                                                                               │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│  [ Tìm kiếm...                    ]  [ Project: Tapdata B ▼ ]  [ Status: Passed ▼ ]     │
│                                                                                          │
│  ┌────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ Đã chọn 5 mục  [Phân công] [Xuất theo lựa chọn] [Xuất tất cả 62 mục khớp lọc]  Hủy │  │
│  └────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                          │
│  ☑  Clip  Filename              Upload ID    Project      Duration  Status    Priority   │
│  ──────────────────────────────────────────────────────────────────────────────────────  │
│  ☑  ▶   clip_002.mp4            UP-8843      Arm A1        01:12     Passed    Medium    │
│  ☐  ▶   clip_007.mp4            UP-8850      Tapdata B     02:01     Passed    High      │
│  ☑  ▶   clip_009.mp4            UP-8852      Tapdata B     00:45     Passed    Low       │
│                                                                                          │
│                    [ ◀ Trước ]   Trang 3/12   [ Sau ▶ ]                                  │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Thanh chọn (`QCQueueSelectionBar`) | Toolbar nổi (above table) | — | • Điều kiện render duy nhất: `assignSelected.size > 0` — **không** hiện khi chưa tick dòng nào; thanh không có gate quyền riêng, chỉ từng nút bên trong mới gate<br>• Badge `bulk_assign_selected`: `"Đã chọn {N} mục"` — N = số dòng đã tick, dùng chung cho cả Gán lẫn Xuất (không còn nhãn riêng cho chế độ xuất)<br>• Thứ tự phần tử: badge → **Phân công** → **Xuất theo lựa chọn** → **Xuất tất cả {M} mục khớp lọc** → **Hủy**<br>• Đây là thanh chọn hợp nhất thay cho cặp bulk bar Gán + mode bar Xuất trước đây; không còn "chế độ chọn" nào để bật/tắt |
| 2 | "Phân công" | Button phụ | — | • `assign` = "Phân công"; gate `qc:assign`<br>• Mở modal Gán hàng loạt (`qc-queue-bulk-assign.md`) với `selectedItems` lấy từ `assignSelected`/`assignSelectedMeta`<br>• Không render nếu user thiếu `qc:assign` |
| 3 | "Xuất theo lựa chọn" | Button phụ | — | • `qc_export_selected_action`; gate `qc:result:export`<br>• Export **chỉ** các ID đã tick — **không** phụ thuộc filter hiện tại; chạy **đồng bộ** (`POST /api/v1/qc/queue/export`)<br>• Disabled khi `selectedCount === 0` hoặc đang load preview<br>• Dialog: `"Xuất {N} mục đã chọn. Tiếp tục?"` |
| 4 | "Xuất tất cả {M} mục khớp lọc" | Button phụ | — | • `qc_export_filtered_action` với `{count}` = `pagination.total`; gate `qc:result:export`<br>• Export toàn bộ item khớp filter (mọi trang) qua **job nền**: `POST /api/v1/qc/queue/export/jobs` → poll `GET …/export/jobs/{id}` (2 s/lần, timeout 10 phút) → `GET …/export/jobs/{id}/download`<br>• Disabled khi `filteredTotal === 0` hoặc đang load preview<br>• Dialog: `"Xuất {M} mục khớp bộ lọc hiện tại. Tiếp tục?"` |
| 5 | Hủy | Button text | — | • `cancel` = "Hủy" → `clearSelection()`: xoá `assignSelected` + `assignSelectedMeta`, đóng modal Gán nếu đang mở, reset banner "chọn hết"; thanh chọn ẩn<br>• Không còn nút Xuất/Hủy toggle nào trên header |
| 6 | Checkbox rows | Checkbox | boolean | • Tick/bỏ tick cập nhật số trên thanh chọn<br>• **Đổi filter → selection bị xoá** (DP-394); **sang trang thì giữ** — muốn chọn nhiều hơn trong 1 lần export thì dùng "Xuất tất cả {M} mục khớp lọc" |
| 7 | Edge — item ngoài phạm vi | System | — | • Project Administrator: selected item thuộc project không được phép → server loại khi build file<br>• Nếu sau lọc còn 0 dòng → HTTP 400 `"No items to export"` → toast `"Không có mục để xuất"` |
| 8 | Edge — job nền lỗi/timeout | System | — | • Job `failed` → `GET …/download` trả **409**; FE hiện `job.error` (hoặc `"Xuất thất bại…"`)<br>• Poll quá 10 phút → throw `export_job_timeout`, không treo dialog<br>• Người khác poll/download job → **404** (job thuộc riêng người tạo) |

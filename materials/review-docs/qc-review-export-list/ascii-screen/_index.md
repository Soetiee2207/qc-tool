---
type: screen-index
feature: "review/qc-review-export-list"
device: "desktop-1024"
owner: "@binhhm"
updated: "2026-09-25"
changelog:
  - "2026-09-25 | docs-sync | selection chỉ reset khi đổi filter; sang trang vẫn giữ (DP-394)"
  - "2026-09-22 | docs-sync | bỏ nút Xuất header + thanh chế độ xuất: entry point nay là thanh chọn hợp nhất khi có ≥1 dòng tick; \"Xuất tất cả\" chạy nền; selection reset khi đổi filter/trang"
  - "2026-09-11 | /wireframe-ascii | đối chiếu code: nút Xuất header bật chế độ chọn-để-xuất → mode bar 2 hành động (Xuất theo lựa chọn / Xuất tất cả N mục khớp lọc) + Hủy; dialog dùng wording tiếng Việt"
  - "2026-09-10 | /wireframe-ascii | sửa mô tả selection: Export/Gán là 2 chế độ chọn loại trừ nhau trên cùng checkbox, không còn tick đồng thời"
  - "2026-09-03 | /wireframe-ascii | initial 4 screens: list default, list selection, export dialog, large warning"
---

# Export QC Review List — Wireframe (ASCII)

## Screens

| # | Screen slug | Tên màn | Thuộc luồng | Trạng thái | Cập nhật |
|---|-------------|---------|-------------|------------|----------|
| 1 | `qc-review-list-export-default` | QC Review list — trạng thái mặc định (không có nút Export nào) | Export filtered | draft | 2026-09-22 |
| 2 | `qc-review-list-export-selection` | QC Review list — thanh chọn hợp nhất + 2 hành động Export | Export selected / filtered | draft | 2026-09-22 |
| 3 | `qc-review-export-dialog-confirm` | Dialog xác nhận export | Export dialog | draft | 2026-09-22 |
| 4 | `qc-review-export-dialog-large-warning` | Dialog export — warning >10k dòng | Export dialog | draft | 2026-09-22 |

## Descriptions

### qc-review-list-export-default

Màn QC Review Listing với filter bar — header **không còn nút Export** (`PageShell` bỏ prop `actions`). Điểm vào duy nhất của chức năng Export là thanh chọn `QCQueueSelectionBar`, chỉ render khi đã tick ≥1 dòng; sang màn `qc-review-list-export-selection`.

### qc-review-list-export-selection

Cùng màn list khi đã tick ≥1 dòng. Thanh chọn hiện `"Đã chọn {N} mục"` cùng **Phân công** / **Xuất theo lựa chọn** / **Xuất tất cả {M} mục khớp lọc** và link **Hủy**. "Xuất theo lựa chọn" chạy đồng bộ; "Xuất tất cả" xếp job nền rồi FE poll (2 s/lần, timeout 10 phút).

### qc-review-export-dialog-confirm

Dialog modal: chọn Excel (mặc định) / CSV, câu confirm số dòng, nút Hủy / Tiếp tục.

### qc-review-export-dialog-large-warning

Cùng dialog khi N >10.000 — thêm dòng warning `"Việc này có thể mất một lúc"`.

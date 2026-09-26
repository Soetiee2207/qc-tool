---
feature: qc-queue
device: Desktop (1024)
updated: 2026-09-25
changelog:
  - 2026-09-25 | docs-sync | giữ lựa chọn khi đổi trang (chỉ reset theo filter); bulk assign chia cân bằng theo thời lượng, preview 3 cột + badge tải + dòng tổng
  - 2026-09-22 | docs-sync | bỏ nút Xuất ở header + thanh chế độ xuất: thanh chọn hợp nhất `QCQueueSelectionBar` (Gán + Xuất theo lựa chọn + Xuất tất cả), selection reset khi đổi filter/trang, "Xuất tất cả" chạy nền
  - 2026-09-11 | docs-sync | đối chiếu code: route `/qc/review` (`/qc/queue` redirect), nhãn nút "Phân công", chọn nhanh theo nhóm + "Tạo nhóm" trong modal Gán, checkbox xác nhận batch lớn
  - 2026-09-10 | /wireframe-ascii | qc-queue-list: tách Xuất thành nút cố định + chế độ chọn riêng, độc lập hoàn toàn với chế độ chọn để Gán
  - 2026-09-10 | /wireframe-ascii | qc-queue-list: bulk bar → badge + nút Gán mở modal + banner chọn-tất-cả-theo-lọc; thêm màn mới qc-queue-bulk-assign (US-006)
  - 2026-09-05 | initial | qc-queue-list từ QCQueue.tsx + QCQueueTable.tsx
---

# QC Queue — ASCII Screens

| Screen | File | Mô tả |
|--------|------|--------|
| QC Queue list | [[qc-queue-list.md]] | Danh sách hàng đợi (`/qc/review`), filter, thanh chọn hợp nhất assign/export |
| Gán hàng loạt (modal) | [[qc-queue-bulk-assign.md]] | Modal mở từ nút "Phân công" — chọn 1 hoặc nhiều reviewer (có chọn nhanh theo nhóm), auto chia cân bằng theo thời lượng + sửa tay |

## Descriptions

- **qc-queue-list:** Màn chính `QCQueue` ở route `/qc/review` (URL cũ `/qc/queue` redirect về đây) — modes `final_qc`, `tapdata_qc`, `annotation` dùng chung layout; khác `product_line` / `manual_annotation_only` API param. Thanh chọn `QCQueueSelectionBar` chỉ render khi đã tick ≥1 dòng và mang cả hành động Gán lẫn Xuất; tập chọn giữ nguyên khi đổi trang, chỉ reset khi đổi filter.
- **qc-queue-bulk-assign:** Modal gán hàng loạt (US-006) — mở từ nút "Phân công" trên thanh chọn của `qc-queue-list`. Chọn 1 người → xác nhận ngay; chọn ≥2 người → hệ thống tự chia cân bằng theo tổng thời lượng, hiện bảng preview (file / thời lượng / người phụ trách) cho sửa tay trước khi xác nhận. Có ô chọn nhanh theo nhóm người dùng (kèm nút "Tạo nhóm" khi user có `user:manage`).

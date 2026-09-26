---
feature: qc-audit
device: Desktop (1024)
updated: 2026-09-25
changelog:
  - 2026-09-25 | /docs-sync | mã lý do từ chối: item OTS GoPro dùng checkbox 6 mã chọn nhiều, gửi `ots:<code>,<code>`; item khác vẫn radio
  - 2026-09-11 | /docs-sync | đối chiếu code: hàng đợi không còn cột "Lý do vòng 1" (thêm cột "Vào audit"), màn chấm có sidebar 2 tab + video phải + toolbar Pass/Reject, hộp thoại reject dùng nút vô hiệu hoá thay vì dòng lỗi, bổ sung hộp thoại xác nhận Pass
  - 2026-09-08 | /wireframe-ascii | initial 5 screens: audit-queue, audit-queue-empty, audit-review-detail, audit-reject-dialog + error state
---

# Audit — ASCII Screens

| Screen | File | Mô tả |
|--------|------|--------|
| Audit queue | [[audit-queue.md]] | Hàng đợi Audit, lọc theo kết quả vòng 1, mở màn chấm |
| Audit queue — rỗng | [[audit-queue-empty.md]] | Trạng thái không có item nào chờ audit |
| Audit review detail | [[audit-review-detail.md]] | Màn chấm vòng 2: khối kết quả vòng 1 + sidebar 2 tab + preview chỉ xem |
| Reject dialog | [[audit-reject-dialog.md]] | Hộp thoại từ chối, chọn mã lý do bắt buộc (OTS: checkbox nhiều mã; còn lại: radio) |
| Reject dialog — chưa chọn lý do | [[audit-reject-dialog-error.md]] | Nút xác nhận bị vô hiệu hoá khi chưa chọn mã lý do |
| Pass dialog | [[audit-pass-dialog.md]] | Hộp thoại xác nhận duyệt trước khi ghi nhận Audit Pass |

## Descriptions

- **audit-queue:** Màn chính của sub-module Audit, nằm ở mục menu "Audit QC" trong nhóm "Đánh giá" của module Review. Nhận 100% item đã có quyết định vòng 1 (cả Passed lẫn Rejected). Khác `qc-queue-list`: bỏ checkbox + bulk assign/export, và cột kết quả vòng 1 chỉ còn "QC1" (chip Pass/Reject) + "Reviewer" + "Vào audit" — mã lý do vòng 1 có trong API nhưng không hiển thị trên bảng. Item do chính người đang đăng nhập chấm ở vòng 1 bị ẩn khỏi danh sách — luật tách vai chặn cứng.
- **audit-queue-empty:** Trạng thái rỗng của màn trên. Giữ nguyên thanh lọc để auditor tự kiểm tra bộ lọc có quá hẹp không. Không có nút Làm mới ở giữa khối rỗng (nút Làm mới nằm trên thanh lọc).
- **audit-review-detail:** Màn chấm vòng 2. Sidebar bên trái chứa khối "QC vòng 1" và hai tab "Audit bàn giao" (metadata chỉ đọc) + "Lịch sử review"; video nằm bên phải; nút Pass/Reject ở góc phải thanh công cụ trên. Auditor **không sửa được dữ liệu** (khác reviewer vòng 1) và màn hiện **chưa render checklist tiêu chí**. Quyết định ở đây là quyết định cuối cùng, ghi đè vòng 1.
- **audit-reject-dialog:** Mở khi bấm Reject ở màn chấm. Dùng lại component `RejectDialog` của QC Review: item template `ots-gopro-v1` hiện 6 mã lý do dạng checkbox chọn nhiều (giá trị gửi lên `ots:<code>,<code>`), item khác vẫn radio chọn một mã; nút xác nhận chỉ bật khi đã chọn. Không có câu cảnh báo hệ quả trong hộp thoại — hệ quả chỉ hiện ở toast sau khi gửi.
- **audit-reject-dialog-error:** Trạng thái khi chưa chọn mã lý do. Code không render dòng lỗi; nút "Xác nhận từ chối" bị `disabled` nên không có gì được gửi đi. Tách file riêng theo quy ước 1 màn = 1 trạng thái.
- **audit-pass-dialog:** Mở khi bấm Pass ở màn chấm. Dùng lại component `SimplePassDialog` của QC Review — hộp thoại xác nhận ngắn, không nhập gì thêm.

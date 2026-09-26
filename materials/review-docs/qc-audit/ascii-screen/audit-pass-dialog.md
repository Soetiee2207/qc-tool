## Wireframe (ASCII)

```
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░░░░░┌──────────────────────────────────────┐░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░░░░░│  Xác nhận duyệt                      │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░░░░░│                                      │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░░░░░│  Duyệt bản ghi này để chạy Phase 2?  │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░░░░░│                                      │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░░░░░│      ( Hủy )   [ Xác nhận duyệt ]    │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░░░░░└──────────────────────────────────────┘░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Screen description

> Hộp thoại dùng lại component `SimplePassDialog` của QC Review (`frontend/src/features/qc/review/QCReviewDialogs.tsx`). Không có bản riêng cho Audit và không có field nào để nhập.

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Tiêu đề "Xác nhận duyệt" | Heading | string | • Khóa `confirm_pass` |
| 2 | Câu mô tả | Text | string | • Wording hiện tại: "Duyệt bản ghi này để chạy Phase 2?" (khóa `qc_simple_pass_msg`)<br>• Wording này viết cho luồng QC Review cũ; với Audit, hệ quả thật là item chuyển `audit_passed` và mở cổng bàn giao — **cần PO duyệt lại câu chữ cho ngữ cảnh Audit** |
| 3 | Nút Hủy | Button (phụ) | — | • Đóng hộp thoại, không ghi nhận gì, item vẫn ở trạng thái chờ audit |
| 4 | Nút Xác nhận duyệt | Button (chính) | action | • Ghi nhận Audit Pass, đóng hộp thoại<br>• Sau khi thành công: toast "Đã ghi nhận audit pass.", quay về hàng đợi Audit<br>• Không hỏi thêm gì — quyết định Pass không yêu cầu dữ liệu kèm theo |

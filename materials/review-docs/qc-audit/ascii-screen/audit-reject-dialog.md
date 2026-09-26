## Wireframe (ASCII)

```
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░┌──────────────────────────────────────────────┐░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│  Từ chối video                               │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░├──────────────────────────────────────────────┤░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│  Lý do từ chối                               │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│  ( ) Video test camera                       │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│  (•) Metadata sai                            │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│  ( ) Mờ chuyển động vượt ngưỡng             │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│  ( ) Tay hiện dưới 80%                       │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│  ( ) Che mặt chưa đầy đủ                     │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│  ( ) Dữ liệu cá nhân                         │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│  ( ) Tay ngoài khung hình                    │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│  ( ) Thời lượng không hợp lệ (<30s hoặc 30p) │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│  ( ) Không có hoạt động làm việc             │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│                                              │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│  Ghi chú bổ sung (tùy chọn)                  │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│  ┌────────────────────────────────────────┐  │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│  │ Chi tiết tùy chọn…                     │  │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│  └────────────────────────────────────────┘  │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│                                              │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░│           ( Hủy )      [ Xác nhận từ chối ]  │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░└──────────────────────────────────────────────┘░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Screen description

> Hộp thoại dùng lại component `RejectDialog` của QC Review (`frontend/src/features/qc/review/QCReviewDialogs.tsx`) — cùng khuôn với vòng 1, không có bản riêng cho Audit. Rộng 420 px. **Item thuộc project dùng template `ots-gopro-v1` hiện 6 mã dạng checkbox, chọn nhiều mã; item khác vẫn là radio, chọn một** — không phải dropdown.

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Tiêu đề "Từ chối video" | Heading | string | • Khóa `qc_reject_title`. Không nêu tên file trong hộp thoại — định danh item nằm ở thanh công cụ phía sau |
| 2 | Lý do từ chối | Checkbox list (6 mục, chọn nhiều) với template `ots-gopro-v1`; Radio list (5 mục) với item còn lại | enum | • **Bắt buộc** — nút xác nhận chỉ bật khi đã chọn ít nhất 1 mã (OTS) hoặc 1 mã<br>• Cờ quyết định danh mục là `ots_reject_reasons` trả về từ API chi tiết; khi bật, dùng 6 mã `preview`, `segmentation`, `face`, `id`, `annotation`, `other`; khi tắt, dùng danh sách một lựa chọn `METADATA_QC_REJECT_REASON_KEYS` (5 mã), không lập danh mục riêng cho Audit<br>• Giá trị gửi lên field `reason`: OTS gửi chuỗi ghép `ots:<code>,<code>`, còn lại gửi đúng mã đã chọn<br>• Mặc định chưa chọn; đóng hộp thoại thì reset cả lý do và ghi chú<br>• Chưa chọn mà nhìn nút xác nhận: xem màn `audit-reject-dialog-error` |
| 3 | Ghi chú bổ sung | Textarea | string | • **Tùy chọn** — nhãn "Ghi chú bổ sung (tùy chọn)", placeholder "Chi tiết tùy chọn…"<br>• Gửi lên backend ở field `comment`; backend cũng chấp nhận reject khi chỉ có ghi chú mà không có lý do (UI vẫn chặn)<br>• Không có giới hạn độ dài ở UI<br>• Biến thể OTS: ô này chỉ hiện khi đã tick mã `other` (nhãn "Other", placeholder "Mô tả lỗi…") và giá trị đi vào field `comment`; các mã khác không có ô ghi chú riêng |
| 4 | Nút Hủy | Button (phụ) | — | • Đóng hộp thoại, không ghi nhận gì, quay về màn chấm; item vẫn ở trạng thái chờ audit |
| 5 | Nút Xác nhận từ chối | Button (chính, nền đỏ) | action | • Ghi nhận Audit Reject kèm mã lý do và ghi chú; tắt hộp thoại trước khi gọi API<br>• Vô hiệu hoá khi chưa chọn lý do (`disabled`) |
| 6 | Sau khi gửi thành công | Toast | — | • Toast "Đã ghi nhận audit reject — đã yêu cầu reprocess." rồi quay về hàng đợi Audit<br>• Item bị reject nhiều lần vẫn tiếp tục quay vòng — phase này không giới hạn số vòng (quyết định có ý thức) |

> Hộp thoại **không có câu cảnh báo hệ quả** nào. Hệ quả (dữ liệu được xử lý lại) chỉ hiện ở toast sau khi gửi. Nếu cần cảnh báo trước khi gửi thì phải bổ sung vào component dùng chung.

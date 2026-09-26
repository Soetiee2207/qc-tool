## Wireframe (ASCII)

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ←  │ clip_bathroom_01.mp4    Màn audit chỉ đọc                        [ ✓ Pass ]  [ ✕ Reject ]        │
├──────────────────────────────────┬─────────────────────────────────────────────────────────────────────┤
│ ┌── QC vòng 1 ─────────────────┐ │                                                                     │
│ │  Quyết định        Reject    │ │                                                                     │
│ │  Lý do             Mờ khuôn… │ │                  ┌──────────────────────────┐                         │
│ │  Reviewer          Trần B    │ │                  │          PREVIEW         │                         │
│ │  Thời điểm chấm    05/09 14:22│ │                 │                          │                         │
│ │  Ghi chú           Khung 00:42│ │                  └──────────────────────────┘                         │
│ └──────────────────────────────┘ │                                                                     │
│ ┌─ Audit bàn giao ─┬─ Lịch sử review của tôi ─┐                                                        │
│ │                                             ││   [▶]  [────────●──────────────]   00:42 / 03:10      │
│ │  (metadata sidecar — chỉ đọc)               ││                                                       │
│ │  • Trường bắt buộc / giá trị                ││                                                       │
│ │  • Cảnh báo thiếu / mock                    ││                                                       │
│ │                                             ││                                                       │
│ └─────────────────────────────────────────────┘│                                                       │
└──────────────────────────────────┴─────────────────────────────────────────────────────────────────────┘
```

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Nút quay lại (←) | Icon button | — | • Về hàng đợi Audit, không ghi nhận gì<br>• Item vẫn ở trạng thái chờ audit, người khác vẫn lấy được (không khóa) |
| 2 | Tên file trên thanh công cụ | Text (mono) | string | • Định danh item đang chấm; không có breadcrumb và không hiển thị tên project |
| 3 | Chú thích chỉ đọc | Text | string | • Wording: "Màn audit chỉ đọc" (khóa `audit_readonly_hint`), ẩn ở màn hẹp (`hidden md:inline`)<br>• Nêu rõ khác biệt với vòng 1: reviewer vòng 1 chỉnh được vùng làm mờ và metadata, auditor thì không<br>• Khối metadata chỉ đọc, không có nút lưu |
| 4 | Nút Pass (góc phải) | Button (chính) | action | • Kết luận item đạt ở vòng 2 — **đây là quyết định cuối cùng**, ghi đè quyết định vòng 1<br>• Bấm không gửi ngay mà mở hộp thoại `audit-pass-dialog` để xác nhận<br>• Sau khi xác nhận: status chuyển `audit_passed`, chuẩn bị bundle bàn giao, toast "Đã ghi nhận audit pass.", quay về hàng đợi<br>• Vòng 1 Rejected + Audit Pass vẫn đi Warehousing — đây là đường cứu data bị loại oan |
| 5 | Nút Reject (góc phải) | Button (phụ, viền đỏ) | action | • Kết luận item không đạt ở vòng 2 — cũng là quyết định cuối cùng<br>• Mở hộp thoại `audit-reject-dialog` để chọn mã lý do bắt buộc<br>• Sau khi xác nhận: status chuyển `audit_rejected`, toast "Đã ghi nhận audit reject — đã yêu cầu reprocess.", phát yêu cầu chạy lại xử lý dữ liệu |
| 6 | Khối "QC vòng 1" (trên sidebar trái) | Display field group (read-only) | object | • Luôn hiển thị, nằm cố định phía trên hai tab nên vẫn thấy khi chuyển tab<br>• Gồm: Quyết định (Pass/Reject), Lý do, Reviewer, Thời điểm chấm, Ghi chú<br>• **Dòng nào rỗng thì ẩn hẳn** (không render nhãn) — vòng 1 Pass không có mã lý do thì không hiện dòng "Lý do"<br>• Đặt ở đầu sidebar vì auditor được phép biết trước kết quả vòng 1 (quyết định nghiệp vụ đã chốt)<br>• Rủi ro đã ghi nhận: biết trước dễ khiến auditor chấm theo quán tính vòng 1 |
| 7 | Tab "Audit bàn giao" | Tab trigger (mặc định) | — | • Mở panel metadata sidecar ở chế độ chỉ đọc (`MetadataSidecarPanel`, `embedded`)<br>• Hiển thị trường bàn giao, cảnh báo thiếu trường bắt buộc, nhãn `mock` nếu giá trị là dữ liệu dev<br>• Tab mặc định khi mở màn |
| 8 | Tab "Lịch sử review" | Tab trigger | — | • Mở `ReviewHistoryPanel` (variant sidebar): các phiên review vòng 1 của item<br>• Nhãn phụ thuộc quyền: có `qc:assign` thì "Lịch sử review", ngược lại "Lịch sử review của tôi" — nhóm `vd-qc-auditors` không có `qc:assign` nên mặc định thấy "Lịch sử review của tôi"<br>• Chấm đỏ nhỏ hiện trên tab khi có phiên vòng 1 bị reject, để auditor chú ý<br>• Tab này hiển thị lịch sử vòng 1; **không** hiển thị kết quả Audit (xem F-07 trong SRS) |
| 9 | Khung preview nội dung | Video player (playback-only) | video stream | • Nằm bên phải ở màn rộng (≥ xl), xếp trên sidebar ở màn hẹp<br>• Dùng `VideoPlayer` với `fitContainer` + toolbar; giữ nguyên hành vi phát của QC Review, không thêm chức năng chỉnh sửa<br>• Nguồn video gọi `GET /api/v1/qc/queue/{item_id}/playback` với profile `preview`<br>• States: loading / error / playing / paused. Lỗi hoặc không có nguồn thì hiện "Không thể phát video. Hãy thử tải lại trang." |

> **Checklist tiêu chí không được render ở màn này.** Bộ tiêu chí vẫn có trong payload (`review.criteria`) nhưng UI Audit hiện chỉ hiển thị khối QC vòng 1 + hai tab trên. Yêu cầu "chấm theo bộ tiêu chí dùng chung" vì vậy chưa có chỗ thao tác trong màn.

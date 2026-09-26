## Wireframe (ASCII)

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Audit QC                                                                                              │
│  42 video chờ audit                                                                                    │
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  [ Tìm filename, project, ID…              ]  [ Kết quả QC1: Tất cả ▼ ]  [ Project ▼ ]  [ Làm mới ]     │
│  [ Từ ngày ] – [ Đến ngày ]                                                                            │
├───┬───────────────────────┬─────────────┬──────────┬───────────┬──────────────┬─────────────┬─────────┤
│ ▶ │ Tên file              │ Project     │ Thời lượng │ QC1     │ Reviewer     │ Vào audit   │ Thao tác│
├───┼───────────────────────┼─────────────┼──────────┼───────────┼──────────────┼─────────────┼─────────┤
│ ▶ │ filename.mp4          │ Alpha       │ 00:12:30 │ ✓ Pass    │ ● NV  Nguyễn A│ 05/09 14:22 │  [Audit]│
│ ▶ │ clip_bathroom_01.mp4  │ Beta        │ 00:03:10 │ ✕ Reject  │ ● TB  Trần B  │ 05/09 09:05 │  [Audit]│
│ ▶ │ kitchen_task_03.mp4   │ Alpha       │ 00:08:44 │ ✓ Pass    │ ● LM  Lê M    │ 04/09 18:40 │  [Audit]│
│ ▶ │ hallway_walk_07.mp4   │ Gamma       │ 00:05:02 │ ✕ Reject  │ ● NV  Nguyễn A│ 04/09 11:12 │  [Audit]│
│                                                                                                        │
│                    [ ◀ Trước ]   Trang 1 / 3   [ Sau ▶ ]                                               │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

> Nút "Filter"/"Saved views" trên thanh lọc lấy từ `ListFiltersBar` dùng chung. Bấm cả dòng hoặc nút Audit ở cuối dòng đều mở màn chấm.

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Tiêu đề "Audit QC" + số item chờ | Heading + subtitle | string + số | • Tiêu đề lấy từ khóa i18n `nav_qc_audit`; subtitle dạng "42 video chờ audit" (`total` + `dash_qc_videos` + `audit_in_queue`)<br>• Không có breadcrumb "Review › Audit"; mục menu "Audit QC" nằm trong nhóm "Đánh giá" của sidebar |
| 2 | Ô tìm kiếm | Text input | string | • Tìm nhanh item theo tên file, external ID hoặc tên project (backend `q`)<br>• Không bắt buộc; để trống thì hiện toàn bộ hàng đợi<br>• States: default / đang gõ / có kết quả / không có kết quả |
| 3 | Nút Làm mới | Button | — | • Tải lại hàng đợi — cần thiết vì item liên tục được đẩy vào từ QC Review và bị người khác chấm mất<br>• Hệ thống không khóa item nên danh sách có thể lệch thực tế giữa hai lần tải |
| 4 | Lọc kết quả vòng 1 ("Kết quả QC1") | Select | enum | • Lọc theo quyết định của QC Review vòng 1: Tất cả / Pass / Reject (`round1_decision`)<br>• Mặc định "Tất cả" — cả hai nhánh đều phải được audit, không nhánh nào được bỏ qua<br>• Dùng khi auditor muốn tập trung soát một nhóm (vd chỉ xem các ca vòng 1 đã reject để tìm ca bị loại oan) |
| 5 | Lọc project | Select | uuid \| all | • Thu hẹp hàng đợi theo project/đối tác (`project_id`)<br>• Mặc định "Tất cả"<br>• **Lưu ý:** danh sách project trong dropdown chỉ gồm project người dùng được giao (`assigned`), trừ khi người dùng là platform admin hoặc có role `vd_qc_leads`. Auditor vì vậy có thể không chọn được một số project vẫn có item trong hàng đợi — chọn "Tất cả" thì vẫn thấy |
| 6 | Khoảng ngày | Date range | ISO date | • Lọc theo thời điểm item vào audit (`audit_entered_at`, fallback `updated_at`) — không phải thời điểm chấm vòng 1<br>• Không bắt buộc; để trống thì không giới hạn thời gian |
| 7 | Cột thumbnail ▶ | Color block | hex | • Ảnh đại diện nội dung, giúp nhận diện nhanh trong danh sách dài |
| 8 | Cột Tên file / Project / Thời lượng | Text | string | • Định danh item; project là link sang trang project (bấm không mở màn chấm) |
| 9 | Cột "QC1" — kết quả QC Review vòng 1 | StatusChip | enum (Pass \| Reject) | • Quyết định của vòng 1 (`approved` → Pass, còn lại → Reject), hiển thị ngay trên danh sách vì auditor được phép biết trước (quyết định nghiệp vụ đã chốt ở brainstorm)<br>• Chỉ có hai giá trị — item chưa có quyết định vòng 1 thì không vào hàng đợi này<br>• **Mã lý do vòng 1 không hiển thị trên bảng** dù API có trả `round1_reason_code`; auditor xem ở khối "QC vòng 1" trong màn chấm |
| 10 | Cột "Reviewer" — người review vòng 1 | Text + avatar chữ viết tắt | string | • Tên người chấm vòng 1, kèm avatar initials<br>• Item do chính người đang đăng nhập chấm ở vòng 1 **không xuất hiện** trong danh sách này — luật tách vai đã chốt, chặn cứng ở tầng SQL, không có ngoại lệ cho Lead |
| 11 | Cột "Vào audit" | Text | datetime | • `audit_entered_at` (fallback `updated_at`) — dùng để ưu tiên xử lý item tồn lâu<br>• Định dạng theo locale (`vi-VN` / `en-US`); không có giá trị thì hiện "—" |
| 12 | Nút Audit trên dòng | Icon button (ClipboardCheck) | — | • Mở màn chấm `/qc/audit/{id}` cho item đó (bấm cả dòng cũng mở)<br>• Không khóa item: hai auditor cùng mở được, người bấm gửi trước được tính<br>• Người bấm sau nhận toast "Item vừa được người khác chấm. Đang làm mới danh sách." và bị đưa về hàng đợi |
| 13 | Phân trang | Pagination | số trang | • Điều hướng khi hàng đợi dài; `limit` cố định 50 dòng mỗi trang<br>• Đổi bộ lọc thì quay về trang 1 |

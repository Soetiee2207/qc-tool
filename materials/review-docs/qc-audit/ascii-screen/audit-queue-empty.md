## Wireframe (ASCII)

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Audit QC                                                                                              │
│  0 video chờ audit                                                                                     │
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  [ Tìm filename, project, ID…              ]  [ Kết quả QC1: Tất cả ▼ ]  [ Project ▼ ]  [ Làm mới ]     │
│  [ Từ ngày ] – [ Đến ngày ]                                                                            │
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                        │
│                                        ┌───────┐                                                       │
│                                        │  ▭    │                                                       │
│                                        └───────┘                                                       │
│                                  Không có item chờ audit                                               │
│                   Sau khi reviewer submit QC vòng 1, item sẽ xuất hiện ở đây.                         │
│                                                                                                        │
│                                                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Tiêu đề + số đếm "0 video chờ audit" | Heading + subtitle | string + số | • Cùng tiêu đề với `audit-queue`, chỉ khác số đếm bằng 0 |
| 2 | Thanh tìm kiếm + bộ lọc | Text input + Select + Date range | như `audit-queue` | • **Vẫn hiển thị và thao tác được** dù danh sách rỗng — để auditor tự kiểm tra xem mình có đang lọc quá hẹp không<br>• Ẩn thanh lọc ở trạng thái rỗng sẽ khiến người dùng tưởng hệ thống hỏng<br>• Nút "Làm mới" nằm trên thanh lọc này, không nằm trong khối rỗng |
| 3 | Câu chính trạng thái rỗng | Text | string | • Wording: "Không có item chờ audit" (khóa `audit_queue_empty_title`)<br>• Xuất hiện khi hàng đợi thật sự rỗng, hoặc khi bộ lọc hiện tại không khớp item nào |
| 4 | Câu phụ giải thích | Text | string | • Wording: "Sau khi reviewer submit QC vòng 1, item sẽ xuất hiện ở đây." (khóa `audit_queue_empty_body`)<br>• Cho auditor biết nguồn item đến từ đâu, tránh hiểu nhầm là lỗi hệ thống<br>• Icon `Inbox` nằm trong vòng tròn phía trên câu chính (component `EmptyState` dùng chung) |

> Khối rỗng không có nút hành động nào (`EmptyState` chỉ nhận `title` và `description` ở màn này).

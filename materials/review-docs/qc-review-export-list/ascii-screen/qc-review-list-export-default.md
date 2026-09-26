## Wireframe (ASCII)

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│  QC Review                                                                               │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│  [ Tìm kiếm...                    ]  [ Project: Tất cả ▼ ]  [ Status: Tất cả ▼ ]  [ ↻ ]  │
│  [ Priority: Tất cả ▼ ]   Từ [____] Đến [____]                                           │
│                                                                                          │
│  ☐  Clip  Filename              Upload ID    Project    Duration  Status    Priority ... │
│  ──────────────────────────────────────────────────────────────────────────────────────  │
│  ☐  ▶   clip_001.mp4            UP-8842      Arm A1     02:34     Pending   High         │
│  ☐  ▶   clip_002.mp4            UP-8843      Arm A1     01:12     Passed    Medium       │
│  ☐  ▶   clip_003.mp4            UP-8844      Tapdata B   03:01     Rejected  Low          │
│                                                                                          │
│                    [ ◀ Trước ]   Trang 1/12   [ Sau ▶ ]                                  │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Tiêu đề + header | Header | — | • Tiêu đề màn QC Review list (theo mode: final QC / annotation)<br>• Header **không có nút action nào**: nút **Xuất** từng nằm ở đây đã bị bỏ, `PageShell` không còn dùng prop `actions`. Điểm vào Export nay nằm trên thanh chọn, chỉ xuất hiện khi có ≥1 dòng được tick (xem `qc-review-list-export-selection`) |
| 2 | Bộ lọc | Filter bar | mixed | • Tìm kiếm, Project, Status, Priority, khoảng ngày, nút refresh (biểu tượng ↻)<br>• Giữ nguyên behavior list hiện tại<br>• Export (scope filtered) lấy **toàn bộ** kết quả khớp filter, mọi trang |
| 3 | Checkbox cột đầu | Checkbox (per-row + header) | boolean | • Luôn render và tick được, không cần "bật chế độ" nào trước và không bị gate quyền — tick vào **một** tập `assignSelected` dùng chung cho cả Gán lẫn Xuất<br>• Có ≥1 selected → thanh chọn hiện (`qc-review-list-export-selection`); hành động bên trong thanh mới gate theo quyền<br>• Selection **reset khi đổi filter** (DP-394) nhưng **giữ nguyên khi chỉ sang trang** |
| 4 | Bảng danh sách QC | Table | list | • Cột: clip, filename, upload ID, project, duration, status, priority, assignee, created at, actions<br>• Bấm dòng → mở QC Review detail (không đổi) |
| 5 | Nút Export | — | — | • **Đã bỏ.** Không còn nút Xuất cố định nào trên màn; 2 hành động export nằm trong thanh chọn khi có selection → dialog `qc-review-export-dialog-confirm` (hoặc `large-warning` nếu N>10.000) |
| 6 | Phân trang | Pagination | — | • Chuyển trang **không** xoá selection đã tick (DP-394 — selection thuộc tập filter hiện tại, không thuộc trang); "Xuất tất cả {N} mục khớp lọc" (trên thanh chọn) là cách export toàn bộ filtered pages |

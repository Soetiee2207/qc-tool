## Wireframe (ASCII)

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│  QC Review Listing (mờ — overlay)                                                        │
│                                                                                          │
│              ┌────────────────────────────────────────┐                                  │
│              │  Xuất danh sách QC Review                │                                  │
│              ├────────────────────────────────────────┤                                  │
│              │                                         │                                  │
│              │  Xuất 247 mục khớp bộ lọc hiện tại.     │                                  │
│              │  Tiếp tục?                              │                                  │
│              │                                         │                                  │
│              │  Định dạng                              │                                  │
│              │    (●) Excel (.xlsx)   ← default        │                                  │
│              │    ( ) CSV                              │                                  │
│              │                                         │                                  │
│              │              [ Hủy ]  [ Tiếp tục ]       │                                  │
│              └────────────────────────────────────────┘                                  │
│                                                                                          │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Overlay | Modal backdrop | — | • Làm mờ list phía sau; click ngoài / Esc = đóng (nhưng **bị chặn khi `isExporting`**) |
| 2 | Tiêu đề dialog | Text | string | • `qc_export_list_title` = `"Xuất danh sách QC Review"` |
| 3 | Câu confirm | Text | string | • **Filtered (scope=filtered):** `"Xuất {N} mục khớp bộ lọc hiện tại. Tiếp tục?"`<br>• **Selected:** `"Xuất {N} mục đã chọn. Tiếp tục?"`<br>• N = số dòng thực tế sẽ export (từ `POST /export/preview`, sau enforce project scope) |
| 4 | Chọn format | Radio group | enum | • `Excel (.xlsx)` — **mặc định**<br>• `CSV` — UTF-8 **with BOM** (Excel Windows đọc tiếng Việt đúng)<br>• Disable khi `isExporting` |
| 5 | Hủy | Button phụ | — | • `cancel` = "Hủy" — đóng dialog, không export, không đổi selection/filter<br>• **Disabled khi `isExporting`** |
| 6 | Tiếp tục | Button chính | — | • `qc_continue`; **Trigger:** rẽ nhánh theo scope — `selected` build file đồng bộ trong request, `filtered` xếp job nền rồi poll<br>• **Loading:** nút đổi thành `"Đang chuẩn bị xuất…"`, nút Hủy cũng disable cho đến khi xong hoặc lỗi; với scope `filtered` thời gian chờ gồm cả lúc worker dựng file nên lâu hơn<br>• **Success:** browser download `qc-review-export-YYYY-MM-DD.xlsx` hoặc `.csv`, đóng dialog + xoá selection<br>• **Fail:** toast `"Xuất thất bại. Vui lòng thử lại hoặc thu hẹp bộ lọc."` (job `failed` thì ưu tiên hiện `job.error`) |
| 7 | Edge — empty | System | — | • Không mở dialog nếu preview trả `count=0` — toast `"Không có mục để xuất"` trên list |
| 8 | Edge — timeout job nền | System | — | • Scope `filtered` poll quá **10 phút** → báo lỗi timeout (`export_job_timeout`) thay vì giữ dialog "Đang chuẩn bị xuất…" vô hạn |

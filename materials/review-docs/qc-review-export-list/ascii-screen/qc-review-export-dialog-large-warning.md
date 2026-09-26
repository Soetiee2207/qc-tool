## Wireframe (ASCII)

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│  QC Review Listing (mờ — overlay)                                                        │
│                                                                                          │
│              ┌────────────────────────────────────────┐                                  │
│              │  Xuất danh sách QC Review                │                                  │
│              ├────────────────────────────────────────┤                                  │
│              │                                         │                                  │
│              │  Xuất 12,450 mục khớp bộ lọc hiện tại.  │                                  │
│              │  Tiếp tục?                              │                                  │
│              │                                         │                                  │
│              │  Việc này có thể mất một lúc  ← amber   │                                  │
│              │                                         │                                  │
│              │  Định dạng                              │                                  │
│              │    (●) Excel (.xlsx)                    │                                  │
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
| 1 | Warning banner | Inline alert (trong dialog, dưới câu confirm) | — | • Chỉ hiện khi `large_export_warning = true`, tức N **> 10.000** dòng (selected hoặc filtered)<br>• **Wording chính xác:** `qc_export_large_warning` = `"Việc này có thể mất một lúc"` — render màu amber<br>• Vẫn cho phép Tiếp tục — không hard block |
| 2 | Câu confirm | Text | string | • Giống dialog confirm thường — hiện N thực tế (vd 12,450) |
| 3 | Format + actions | Radio + buttons | — | • Giống `qc-review-export-dialog-confirm`<br>• User có thể Hủy để thu hẹp filter rồi export lại |
| 4 | Loading | State | — | • Sau Tiếp tục: nút hiện `"Đang chuẩn bị xuất…"` — user chờ trên màn; scope `selected` build đồng bộ trong request, scope `filtered` build ở worker nền nên chờ lâu hơn (FE poll 2 s/lần, timeout 10 phút)<br>• Đóng tab = hủy, không resume |
| 5 | Business rule | — | — | • Không giới hạn hard cap số dòng — warning là soft guard duy nhất |

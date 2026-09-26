## Wireframe (ASCII)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│  State: Presigned URL hết hạn (US-005)                                                           │
│                                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                                                                                            │  │
│  │              ! Liên kết video đã hết hạn. Vui lòng tải lại trang.                          │  │
│  │                                                                                            │  │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │  │
│  │  │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│  │  │
│  │  ├──────────────────────────────────────────────────────────────────────────────────────┤  │  │
│  │  │  [ > ]  [«]  [»]  00:03:10 / 00:10:00   (🔊)  [0.5×][1×][2×][4×][8×]  (⛶)           │  │  │
│  │  └──────────────────────────────────────────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────────────────────────────────────┘  │
│  Ghi chú: playback dừng; timeline disabled; user reload trang / màn cha refetch URL mới          │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Thông báo lỗi | Inline error | string | • Exact wording: "Liên kết video đã hết hạn. Vui lòng tải lại trang." (`video_url_expired`)<br>• Playback dừng; không crash UI |
| 2 | Progress bar (disabled) | Progress indicator | — | • Giữ vị trí cuối nhưng không seek được; thanh mờ (`aria-disabled=true`) |
| 3 | Thời gian | Display field | time | • Giữ `current / total` tại thời điểm lỗi — không cập nhật |
| 4 | Hành vi recovery | — | — | • Retry nội bộ: presigned/proxy tối đa **8 lần**, cách 3s (`scheduleStreamRetry`); sau lần thứ 2 gọi `onPlaybackError` để màn cha refetch URL mới<br>• Nguồn không presigned: tối đa 120 lần, cách 5s → `video_playback_error`<br>• Hết retry → hiện thông báo trên, user tải lại trang |

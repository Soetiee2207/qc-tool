## Wireframe (ASCII)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│  State: Video load fail (US-005)                                                                 │
│                                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                                                                                            │  │
│  │                         ! Không thể phát video. Vui lòng thử lại.                          │  │
│  │                                                                                            │  │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │  │
│  │  │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│  │  │
│  │  ├──────────────────────────────────────────────────────────────────────────────────────┤  │  │
│  │  │  [ > ]  [«]  [»]  --:--:-- / --:--:--   (🔊)  [0.5×][1×][2×][4×][8×]  (⛶)           │  │  │
│  │  └──────────────────────────────────────────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────────────────────────────────────┘  │
│  Ghi chú: timeline disabled/mờ (opacity-40); hover không hiện tooltip; không seek được           │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Thông báo lỗi | Inline error | string | • Exact wording: "Không thể phát video. Vui lòng thử lại." (`video_playback_error`)<br>• Hiện giữa vùng video khi metadata load fail |
| 2 | Progress bar (disabled) | Progress indicator | — | • `opacity-40` + `cursor-not-allowed` (`aria-disabled=true`) — không tương tác<br>• Không seek, không hover tooltip |
| 3 | Play + thời gian | Button + display | — | • Play không có tác dụng (không có `src`/`duration`)<br>• Thời gian không cập nhật (vẫn `00:00:00 / 00:00:00` — không có nhánh hiển thị `--:--:--`) |
| 4 | Skip / Mute / Tốc độ / Fullscreen | Controls | — | • Vẫn render trên thanh nhưng vô nghĩa khi chưa có video<br>• User reload trang hoặc bấm retry (nếu màn cha có nút `qc_retry_playback`) để recover |

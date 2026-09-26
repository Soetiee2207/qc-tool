## Wireframe (ASCII)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│  State: Đang kéo scrub — UI only, chưa seek (US-001)                                             │
│                                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                                                                                            │  │
│  │                                   VIDEO FRAME (16:9)                                       │  │
│  │                                                                                            │  │
│  │                          ┌──────────┐                                                      │  │
│  │                          │ 00:07:45 │  ← tooltip theo con trỏ                            │  │
│  │                          └─────┬────┘                                                      │  │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │  │
│  │  │████ played ████▒▒▒ buffered ▒▒▒▒▒▒▒▒▒░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ track ░░░░░░░●○│  │  │
│  │  ├──────────────────────────────────────────────────────────────────────────────────────┤  │  │
│  │  │ [‖]  [«]  [»]  00:07:45 / 10:00:00      (🔊)  [0.5×][1×][2×][4×][8×]  (⛶)           │  │  │
│  │  └──────────────────────────────────────────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────────────────────────────────────┘  │
│  Ghi chú: tooltip + số current theo con trỏ; video chưa nhảy cho đến khi thả chuột               │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Drag tooltip | Tooltip nhỏ | timecode `HH:MM:SS` | • Tooltip đi theo con trỏ trong suốt thao tác kéo<br>• Timecode phản ánh vị trí kéo (vd `00:07:45`), không vị trí phát thật<br>• Không có card/ảnh thumbnail |
| 2 | Progress bar (dragging) | Slider (drag) | time | • Thanh expanded (9px) + vòng tròn preview tại vị trí con trỏ<br>• **Move phase:** chỉ UI cập nhật — video chưa seek; `onPreviewSecChange` đẩy vị trí lên control bar |
| 3 | Thời gian hiển thị | Display field | time | • `current` tạm hiện vị trí kéo (`00:07:45`) trong lúc drag (`dragPreviewSec`)<br>• **End phase (pointerup):** commit seek; video nhảy; `current` trở về vị trí thật |
| 4 | Kẹp biên | Validation | time range | • Kéo ra ngoài thanh vẫn kẹp `0 → duration` (pointer capture giữ sự kiện)<br>• Thả chuột ngoài thanh vẫn seek tới vị trí kẹp |

## Wireframe (ASCII)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│  State: Timeline hover — time tooltip (US-002)                                                   │
│                                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                                                                                            │  │
│  │                                   VIDEO FRAME (16:9)                                       │  │
│  │                                                                                            │  │
│  │                          ┌──────────┐                                                      │  │
│  │                          │ 00:05:12 │  ← time tooltip (nền đen, chữ trắng)                  │  │
│  │                          └─────┬────┘                                                      │  │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │  │
│  │  │████ played ████▒▒▒ buffered ▒▒▒▒▒▒▒▒▒░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ track ░░░░░░●○│  │  │
│  │  ├──────────────────────────────────────────────────────────────────────────────────────┤  │  │
│  │  │ [‖]  [«]  [»]  01:23:45 / 10:00:00      (🔊)  [0.5×][1×][2×][4×][8×]  (⛶)           │  │  │
│  │  └──────────────────────────────────────────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────────────────────────────────────┘  │
│  Ghi chú: thanh cao 9px (hover), chấm playhead tại vị trí phát thật + vòng tròn tại vị trí con trỏ│
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Time tooltip | Tooltip nhỏ | timecode `HH:MM:SS` | • Nhãn bo góc, nền `rgba(0,0,0,0.85)`, chữ trắng 11px, đặt phía trên thanh tại vị trí con trỏ<br>• Debounce hover 50ms (`HOVER_DEBOUNCE_MS`)<br>• Kẹp mép ±28px để không tràn khỏi thanh<br>• `data-testid="progress-hover-time-tooltip"`<br>• **Card thumbnail 160×90 + shimmer CHƯA ship** — P2, chờ API sprite sheet |
| 2 | Progress bar (expanded) | Progress indicator | time | • Chiều cao 5px → 9px khi hover (`transition-[height] 80ms ease-out`)<br>• Cùng logic played/buffered/track như màn playing |
| 3 | Playhead + hover ring | Slider thumb | time | • Chấm 15px `bg-primary` + viền trắng tại vị trí phát hiện tại (`●`)<br>• Vòng tròn 15px viền `border-primary` tại vị trí con trỏ (`○`) khi lệch playhead > 0.5% |
| 4 | Control row | Button group | — | • Giữ nguyên như màn playing — không đổi khi hover<br>• Rời chuột (không kéo): tooltip ẩn, thanh về 5px nếu video không phát |

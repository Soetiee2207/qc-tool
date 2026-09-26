## Wireframe (ASCII)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Multicam layout — 1 master timeline chung cho 3 camera (US-004)                                  │
│                                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                              HEAD                                                          │  │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │  │
│  │  │                                   VIDEO HEAD                                         │  │  │
│  │  └──────────────────────────────────────────────────────────────────────────────────────┘  │  │
│  ├───────────────────────────────────────────┬────────────────────────────────────────────────┤  │
│  │             LEFT WRIST                    │              RIGHT WRIST                       │  │
│  │  ┌─────────────────────────────────────┐  │  ┌─────────────────────────────────────────┐   │  │
│  │  │          VIDEO LEFT WRIST           │  │  │          VIDEO RIGHT WRIST              │   │  │
│  │  └─────────────────────────────────────┘  │  └─────────────────────────────────────────┘   │  │
│  ├────────────────────────────────────────────────────────────────────────────────────────────┤  │
│  │ ████ played ██▒▒▒ buffered ▒▒▒▒▒░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ track ░░░░░░░░░●  │  │
│  │ [‖]  [«]  [»]  00:30 / 10:00:00         (🔊)  [0.5×][1×][2×][4×][8×]  (⛶)                 │  │
│  └────────────────────────────────────────────────────────────────────────────────────────────┘  │
│  Ghi chú: chỉ có MỘT thanh timeline/controls (gắn head camera); 2 pane wrist không có toolbar    │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Camera panes (HEAD / LEFT WRIST / RIGHT WRIST) | Video display | video stream | • Bố cục tam giác: head `flex-[3]` trên, 2 wrist `flex-[2]` chia đôi dưới<br>• Mỗi pane **không** có timeline/controls riêng — chỉ vùng video<br>• Label góc cam ở đầu pane (`scaleai_slot_head` / `_left` / `_right`) |
| 2 | Master timeline (1 thanh chung) | Progress bar | time | • Gắn **head camera**; buffered/played lấy từ head<br>• Kéo/click → seek cả 3 (wrist mirror transport + áp `syncOffsets`) |
| 3 | Shared control bar | Button group | action | • Play/pause, `<<`/`>>` ±5s, `current / total`, mute, 5 nút tốc độ, fullscreen<br>• `fullscreenRef` = container lưới 3 video (fullscreen cả lưới, không chỉ 1 pane) |
| 4 | Trạng thái đồng bộ | Overlay | — | • Khi seek/play cần chờ slave bắt kịp → overlay mờ + spinner + `"Đang đồng bộ…"` (`scaleai_qc_seek_syncing`)<br>• Click vào 1 pane video → toggle play/pause cả nhóm |
| 5 | Khác biệt so với brainstorm gốc | — | — | • **Không** có timeline độc lập từng camera (US-004 bản cũ) — implementation là master + slave sync |

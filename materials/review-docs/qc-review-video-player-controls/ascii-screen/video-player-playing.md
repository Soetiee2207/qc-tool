## Wireframe (ASCII)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Embed: QC Review / Upload Preview / Annotation — focus vùng Video Player Controls               │
│                                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                                                                                            │  │
│  │                                                                                            │  │
│  │                                   VIDEO FRAME (16:9)                                       │  │
│  │                                                                                            │  │
│  │                                                                                            │  │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │  │
│  │  │████ played ████▒▒▒ buffered ▒▒▒▒▒▒▒▒▒░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ track ░░░░░░░░●│  │  │
│  │  ├──────────────────────────────────────────────────────────────────────────────────────┤  │  │
│  │  │ [‖]  [«]  [»]  01:23:45 / 10:00:00      (🔊)  [0.5×][1×][2×][4×][8×]  (⛶)           │  │  │
│  │  └──────────────────────────────────────────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Video frame | Video display | video stream | • Hiển thị nội dung video đang phát<br>• States: loading / playing / paused / ended / error (màn lỗi tách file riêng)<br>• Embed trong màn QC, upload preview, annotation… — không đổi business flow màn cha |
| 2 | Progress bar — played | Progress indicator | time % | • Đoạn tô **primary green** (`bg-primary`) từ 0 đến playhead — **không** phải đỏ YouTube literal<br>• Cập nhật realtime khi video phát |
| 3 | Progress bar — buffered | Progress indicator | buffered range | • Đoạn `bg-white/35` phía trước playhead = đã tải sẵn<br>• Player chủ động giữ ~30s buffer trước playhead (MP4 prefetch + HLS `maxBufferLength`) |
| 4 | Progress bar — track | Progress indicator | duration | • Nền `bg-white/20` toàn bộ chiều dài video<br>• Click anywhere → seek; kéo = scrub 2 pha (US-001) |
| 5 | Playhead (chấm tròn) | Slider thumb | time | • Chấm 15px `bg-primary` + viền trắng, hiện khi **đang phát HOẶC hover HOẶC đang kéo**<br>• Ẩn khi pause + không hover |
| 6 | Nút Play/Pause | Button toggle | action | • Icon `Play` khi pause; `Pause` khi playing (`aria-label` = `video_play` / `video_pause`)<br>• Khi video pause còn có overlay nút play lớn giữa khung video (click để phát) |
| 7 | Nút `<<` / `>>` | Button | action | • Lùi / tiến **5 giây** (`SEEK_SKIP_SECONDS`)<br>• Hiển thị literal `<<` / `>>` (không dùng icon track)<br>• `aria-label`/`title` = "Lùi 5 giây" / "Tiến 5 giây" |
| 8 | Thời gian `current / total` | Display field | time (HH:MM:SS) | • Ví dụ `01:23:45 / 10:00:00` — `formatPlaybackClock` chỉ có giờ/phút/giây, **không** có frame<br>• Khi đang hover/kéo, phần `current` tạm hiện vị trí con trỏ |
| 9 | Nút Mute | Button (icon) | action | • `Volume2` ↔ `VolumeX`, `aria-pressed` theo `video.muted`<br>• **Không có** slider âm lượng |
| 10 | Tốc độ phát | **5 nút** liền nhau | enum {0.5,1,2,4,8}× | • Không phải dropdown — mỗi mức là 1 nút, click chọn trực tiếp<br>• Nút đang chọn: nền `bg-primary` + chữ trắng; còn lại `text-white/55`<br>• Mặc định `1×` |
| 11 | Nút Fullscreen | Button | action | • `Maximize2`; gọi `requestFullscreen()` trên container (hoặc `fullscreenRef` của grid multicam)<br>• Bấm lần nữa (khi đang fullscreen) → thoát |

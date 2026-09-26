## Wireframe (ASCII)

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ tapdata_clip_0421.mp4   Project: Tapdata Pilot   Profile: tapdata-iphone-std             │
│ [ Pass ]  ( Reject )  ( Back )                                                           │
├──────────────────────────┬───────────────────────────────────────────────────────────────┤
│ Tapdata Delivery Audit   │                                                               │
│                          │                                                               │
│ PHẦN 1: Face & Hands     │                    ┌─────────────────────┐                    │
│  face_visible_percent    │                    │                     │                    │
│   42.3%  (≤50%) PASS     │                    │    VIDEO PREVIEW    │                    │
│  face_visible_result     │                    │      (1 camera)     │                    │
│   PASS                   │                    │                     │                    │
│  hand_visible_percent    │                    └─────────────────────┘                    │
│   71.2%  (>60%) PASS     │                                                               │
│  hand_visible_result     │  [▶] [──────────●──────────────]  00:42 / 58:10               │
│   PASS                   │                                                               │
│                          │  Review History                                               │
│ PHẦN 2: QC Auto          │  ┌─────────────────────────────────────────────────────────┐  │
│  video_resolution  1080p │  │ 2026-08-20 14:02 — passed — reviewer: minh.nv         │    │
│  display_ratio     16:9  │  └─────────────────────────────────────────────────────────┘  │
│  video_fps         30.0  │                                                               │
│  format_name       mp4   │                                                               │
│  video_codec       h264  │                                                               │
│  minimum_video       PASS│                                                               │
│  video_duration    3490s │                                                               │
│   (≤3600s) PASS          │                                                               │
│  video_bitrate     12Mbps│                                                               │
│  final_result      PASS  │                                                               │
│                          │                                                               │
│ PHẦN 3: QC Manual        │                                                               │
│  pov                 PASS│                                                               │
│  hands_with_task     PASS│                                                               │
│  hands_out_scr       PASS│                                                               │
│  task_description    PASS│                                                               │
│  task_noisy          FAIL│                                                               │
└──────────────────────────┴───────────────────────────────────────────────────────────────┘
```

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|--------------|
| 1 | Toolbar filename / project / profile | Display text | string | • Hiển thị tên file, project, **delivery profile** (`tapdata-iphone-std` / `tapdata-gopro-std`) — profile quyết định cột ngưỡng (US-001)<br>• Read-only |
| 2 | Nút Pass / Reject / Back | Button | action | • **Giữ nguyên** hành vi QC Review egocentric (US-003)<br>• Pass: ghi passed rồi quay về Tapdata QC Queue — **không** hard-block khi `final_result` = FAIL hoặc PHẦN 3 có FAIL<br>• Reject: dialog lý do nếu rule hiện tại bắt buộc; submit xong cũng quay về queue |
| 3 | Panel "Tapdata Delivery Audit" | Sidebar 2 tab (tab audit mở mặc định) | object | • Sidebar trái dạng tab `ReviewSidebarTabs`: tab **Tapdata Delivery Audit** + tab **Review History**; **toàn bộ read-only**<br>• Chia 3 section header: PHẦN 1 / 2 / 3<br>• **Không** input, dropdown, hay control chỉnh sửa |
| 4 | `face_visible_percent` | Display field (read-only) | float 0–100 | • % mặt tích lũy; ngưỡng **≤50%**<br>• Hiển thị kèm ngưỡng + PASS/FAIL hint<br>• FAIL → highlight đỏ/amber |
| 5 | `face_visible_result` | Display field (read-only) | string PASS/FAIL | • PASS khi mục **(1)** đạt ngưỡng |
| 6 | `hand_visible_percent` | Display field (read-only) | float 0–100 | • Ngưỡng **>60%** |
| 7 | `hand_visible_result` | Display field (read-only) | string PASS/FAIL | • PASS khi mục **(3)** đạt |
| 8 | `video_resolution` | Display field (read-only) | string | • Vd `1080p`; ngưỡng ≥1080p<br>• Không sửa — hệ thống detect (PHẦN 2) |
| 9 | `display_ratio` | Display field (read-only) | string | • Vd `16:9`; ngưỡng 16:9 |
| 10 | `video_fps` | Display field (read-only) | float | • Ngưỡng ≥29.9 |
| 11 | `format_name` | Display field (read-only) | string | • iPhone: mp4/mov; GoPro: mp4 |
| 12 | `video_codec` | Display field (read-only) | string | • h264 hoặc hevc |
| 13 | `minimum_video` | Display field (read-only) | string PASS/FAIL | • PASS khi `video_duration` ≥ 30s (ngưỡng cố định 30)<br>• Không hiển thị số 30 thay cho duration thực |
| 14 | `video_duration` | Display field (read-only) | float (giây) | • Độ dài thực detect; PASS khi ≤ 3600s<br>• Hiển thị kèm `(≤3600s) PASS/FAIL` |
| 15 | `video_bitrate_kpbs` | Display field (read-only) | number (Mbps) | • iPhone ≥8 Mbps; GoPro ≥25 Mbps |
| 16 | `final_result` | Display field (read-only) | string PASS/FAIL | • **PASS** iff mục 1–12 đều PASS<br>• **FAIL** nếu bất kỳ mục 1–12 FAIL; không gồm PHẦN 3 |
| 17 | `pov` | Display field (read-only) | string PASS/FAIL | • PHẦN 3 — giá trị từ upstream; **không** dropdown (US-002) |
| 18 | `hands_with_task` | Display field (read-only) | string PASS/FAIL | • Read-only |
| 19 | `hands_out_screen` | Display field (read-only) | string PASS/FAIL | • Wireframe rút label `hands_out_scr` do bề rộng |
| 20 | `task_description_map` | Display field (read-only) | string PASS/FAIL | • Read-only |
| 21 | `task_noisy` | Display field (read-only) | string PASS/FAIL | • Read-only |
| 22 | Video Preview (1 camera) | Video player (playback-only) | video stream | • **Đúng 1 video** — layout egocentric single, **không** tam giác 3-cam<br>• States: loading / error / playing / paused — reuse player hiện có |
| 23 | Playback controls | Button + slider | time mm:ss | • Play/pause, seek, thời gian hiện tại / tổng — giữ shortcut Space/←/→ |
| 24 | Review History | Tab thứ hai trong sidebar | review sessions[] | • Nằm trong tab **Review History** của sidebar (không còn dưới Preview)<br>• Hiển thị reviewer, thời gian, kết quả các lần review trước |

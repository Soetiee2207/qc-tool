---
type: screen-index
feature: review/qc-review-video-player-controls
device: desktop-1024
owner: "@binhhm"
updated: 2026-09-11
changelog:
  - 2026-09-11 | /wireframe-ascii | đối chiếu code: hover/kéo chỉ có time tooltip (không card 160×90); control bar thật gồm play/pause, «/» ±5s, thời gian HH:MM:SS, mute, 5 nút tốc độ, fullscreen; multicam dùng 1 master timeline chung
  - 2026-08-28 | /wireframe-ascii | initial 6 screens: playing, hover, drag, playback-error, url-expired, multicam
---

# Video Player Controls — Wireframe (ASCII)

## Screens

| # | Screen slug | Tên màn | Thuộc luồng | Trạng thái | Cập nhật |
|---|-------------|---------|-------------|------------|----------|
| 1 | `video-player-playing` | Player — đang phát (default) | Xem & điều khiển video | draft | 2026-09-11 |
| 2 | `video-player-timeline-hover` | Timeline hover + time tooltip | US-002 | draft | 2026-09-11 |
| 3 | `video-player-timeline-drag` | Timeline đang kéo scrub | US-001 | draft | 2026-09-11 |
| 4 | `video-player-playback-error` | Lỗi load video | US-005 | draft | 2026-09-11 |
| 5 | `video-player-url-expired` | URL hết hạn | US-005 | draft | 2026-09-11 |
| 6 | `video-player-multicam` | Layout multicam — 1 master timeline chung | US-004 | draft | 2026-09-11 |

## Descriptions

### video-player-playing

Trạng thái mặc định: video đang phát với control bar YouTube-style (timeline, play/pause, `<<`/`>>` ±5s, thời gian `HH:MM:SS`, mute, 5 nút tốc độ, fullscreen). Embed trong mọi màn có video.

### video-player-timeline-hover

User rê chuột lên timeline — thanh nở 5px→9px, time tooltip `HH:MM:SS` theo con trỏ, chấm playhead + vòng hover. Không có card thumbnail 160×90 (P2).

### video-player-timeline-drag

User đang kéo scrub — tooltip và số `current` theo con trỏ; video chưa seek cho đến khi thả chuột.

### video-player-playback-error

Video không load được — thông báo lỗi, timeline disabled.

### video-player-url-expired

Presigned link hết hạn giữa session — retry nội bộ rồi thông báo reload, timeline disabled.

### video-player-multicam

Ba camera bố cục tam giác, **một** thanh timeline/controls chung gắn head camera; 2 pane wrist không có toolbar riêng, phát đồng bộ theo offset.

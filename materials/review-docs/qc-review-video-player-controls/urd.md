<!-- doc-meta: type=urd | feature=review/qc-review-video-player-controls | status=draft | updated=2026-09-11 -->
# **User Requirement** Documentation

Video Player Controls — YouTube-Style Timeline

Version 1.1  |  2026-09-11

|  |  |  |  |
| --- | --- | --- | --- |
| **Version**  | **Date**  | **Author**  | **Changes**  |
| 1.1  | 2026-09-11  | @binhhm  | Đối chiếu code: hover/kéo chỉ hiện **time tooltip** (chưa có card 160×90 + shimmer); US-004 multicam thực tế dùng **1 master timeline chung** (synced playback), không phải timeline độc lập từng cam; bổ sung buffer ahead ~30s |
| 1.0  | 2026-08-28  | @binhhm  | Initial draft từ brainstorm `youtube-style-timeline`  |

**Table of Contents**

1. **INTRODUCTION**

**1.1. Purpose**

- Tài liệu này viết cho PM, dev/tech lead, QA.
- Phục vụ mục tiêu: làm baseline yêu cầu nghiệp vụ cho thanh điều khiển video kiểu YouTube dùng chung toàn portal, chuẩn bị nguồn đầu vào cho `/srs video-player-controls`.
- Phạm vi: áp dụng cho v1 rollout component timeline mới (chưa gắn sprint/release cụ thể).

**1.2. Scope**

- **IN SCOPE:**
  - Thanh timeline / progress bar kiểu YouTube: played (đỏ), buffered (sáng), track (tối).
  - Tương tác seek: click nhảy vị trí; kéo scrub 2 pha (UI khi kéo → seek thật khi thả); kẹp trong `0 → duration`.
  - Hover: thanh cao hơn (5px → 9px), chấm đỏ playhead, **time tooltip** `HH:MM:SS` theo vị trí con trỏ (card thumbnail 160×90 + shimmer là P2, chưa ship — chờ API sprite sheet).
  - Play/Pause + hiển thị `current / total` (`HH:MM:SS`).
  - Phím `←` / `→` (và `<` / `>`) tua ±5 giây; `Home` / `End` nhảy đầu/cuối video (không kích hoạt khi focus trong input/textarea/select).
  - Tốc độ phát: `0.5×, 1×, 2×, 4×, 8×` (mặc định `1×`) — 5 nút chọn trực tiếp trên control bar.
  - Mute/unmute (icon) — chưa có volume slider.
  - Fullscreen với control bar overlay dưới video (chrome tối kiểu YouTube).
  - Buffer ahead ~30 giây trước playhead cho cả MP4 progressive và HLS.
  - Component **dùng chung** — thay scrub bar cũ / native `<video controls>` trên mọi surface có video trên portal.
  - Layout multicam: 3 camera phát **đồng bộ** qua 1 master timeline chung (xem US-004 — điều chỉnh so với brainstorm ban đầu).
  - Thanh disabled khi video chưa load metadata (`duration === 0`).
  - Thông báo lỗi phát: "Không thể phát video. Vui lòng thử lại." / "Liên kết video đã hết hạn. Vui lòng tải lại trang."
  - Segment markers trên thanh khi màn cha truyền ngữ cảnh segment (QC layouts) — P1 trong brainstorm, ghi nhận in-scope nếu consumer đã có segment window.
- **OUT OF SCOPE:**
  - API thumbnail / sprite sheet thật — v1 chỉ time tooltip; card preview là phase sau (inherit OQ-1 từ brainstorm).
  - Timeline riêng cho từng camera (multicam dùng chung 1 master timeline + synced playback — xem US-004).
  - Thay thế `MultiLaneTimeline` (NLE multi-lane editor) — vai trò khác, không thuộc feature này.
  - Lưu vị trí phát qua session / resume khi user quay lại màn.
  - Volume slider — v1 icon-only hoặc chưa có (inherit OQ-3); không cam kết slider đầy đủ.
  - Timecode frame-accurate `HH:MM:SS:FF` trong preview label.
  - Mobile/touch behavior riêng — chưa chốt v1 (inherit OQ-2 từ brainstorm).
  - Phân quyền theo role cho timeline (mọi user thấy cùng bộ điều khiển).
- **Integration boundary:**
  - Video CDN / presigned URL / HLS playback — dùng hạ tầng phát hiện có; feature này chỉ thay lớp điều khiển UI.
  - Thumbnail service (tương lai) — 1 request sprite sheet/video; chưa có contract v1.

**1.3. Definitions and Acronyms**

|  |  |
| --- | --- |
| **Term / Acronym**  | **Definition**  |
| **URD** | User Requirement Documentation |
| **Timeline / Progress bar** | Thanh hiển thị tiến độ phát, vị trí playhead, vùng buffered và điểm tương tác seek |
| **Scrub** | Hành động tua video bằng kéo hoặc click trên timeline |
| **Buffered range** | Đoạn video đã tải sẵn, hiển thị sáng hơn trên thanh — user hiểu có thể tua tới đó ít phải đợi |
| **Time tooltip** | Nhãn nhỏ hiện timecode `HH:MM:SS` tại vị trí con trỏ khi hover/kéo timeline — card thumbnail 160×90 chưa ship |
| **Playhead** | Vị trí hiện tại trên timeline tương ứng thời điểm đang phát |
| **Portal user** | Mọi người dùng nội bộ tương tác video trên portal (annotator, QC reviewer, admin/ops…) — không phân quyền timeline |

## 2. System Overview

### 2.1 High-Level User Flow

1. User mở bất kỳ màn nào trên portal có video (QC review, annotation, upload history, multicam…).
2. Hệ thống load metadata video — thanh timeline enabled tại `0:00` hoặc disabled + thông báo lỗi nếu load fail.
3. User bấm Play — video phát; playhead và `current / total` cập nhật theo thời gian thực; vạch buffered mở rộn khi tải thêm.
4. User rê chuột lên thanh — thanh nở, chấm đỏ hiện, time tooltip (debounce 50ms) hiện timecode `HH:MM:SS` tại vị trí con trỏ.
5. User click hoặc kéo thanh — seek tới vị trí mới (kéo: UI theo chuột trước, seek thật khi thả).
6. User dùng phím tắt / tốc độ / fullscreen khi cần — không cần native browser controls.
7. Video hết — bấm Play phát lại từ đầu.
8. *(Multicam)* 3 camera phát **đồng bộ** theo 1 master timeline chung (head camera điều khiển, wrist mirror theo offset) — user không tua riêng từng góc.

### 2.2 System User Profile

|  |  |  |  |
| --- | --- | --- | --- |
| **User Role**  | **Description**  | **Permission Level**  | **Key Actions**  |
| Portal user (Annotator / QC reviewer)  | Nhân viên xem và tua video trong luồng QC, annotation  | Cùng quyền truy cập màn hiện có — timeline không thêm phân quyền  | Play/pause, seek, đổi tốc độ, mute, fullscreen, xem time tooltip  |
| Portal user (Admin / Ops)  | Người xem upload history, preview file đã upload  | Như trên  | Play/pause, seek, xem time tooltip  |
| Portal user (Multicam viewer)  | Người xem nhiều góc camera trên cùng màn  | Như trên  | Điều khiển playback **đồng bộ** cả 3 góc qua 1 thanh timeline chung  |

## 3. User Stories

### 3.1 User Story List

| **US Code** | **US Name** | **US Description** |
| --- | --- | --- |
| US-001 | Tua và seek video với timeline YouTube-style | User click hoặc kéo thanh timeline để nhảy tới vị trí mong muốn, thấy vạch buffered và playhead cập nhật đúng |
| US-002 | Xem preview vị trí khi hover/kéo | User rê hoặc kéo trên thanh và thấy time tooltip `HH:MM:SS` tại vị trí con trỏ (card thumbnail là P2) |
| US-003 | Điều khiển phát video đầy đủ | User play/pause, xem thời gian, đổi tốc độ, dùng phím tắt và fullscreen mà không cần native controls |
| US-004 | Điều khiển playback đồng bộ cho multicam | User điều khiển cả 3 góc camera qua 1 master timeline chung (synced) |
| US-005 | Xử lý lỗi khi video không phát được | User nhận thông báo rõ ràng khi video load fail hoặc link hết hạn, timeline không gây crash UI |
| US-006 | Phát mượt — buffer trước playhead | Hệ thống giữ ~30 giây dữ liệu phía trước playhead để scrub/seek ít phải chờ |

### 3.2 User Story Detail

#### 3.2.1 US-001 Tua và seek video với timeline YouTube-style

**Story**

**As a** `Portal user` **I want** `to click or drag the video timeline to jump to any position` **So that** `I can review video quickly and accurately without struggling with the old scrub bar`

**Acceptance Criteria**

- **AC 1 (Click seek):**
    - **Given** video đã load metadata, duration > 0, user đang xem tại 00:30,
    - **When** user click vào 75% chiều dài thanh timeline,
    - **Then** video nhảy tới ~75% duration, playhead và `current` time cập nhật ngay.
- **AC 2 (Kéo scrub 2 pha):**
    - **Given** video đang phát tại 01:00,
    - **When** user giữ chuột và kéo playhead tới 02:30 rồi thả,
    - **Then** trong lúc kéo chỉ UI (playhead + time tooltip + số `current` tạm) di chuyển; sau khi thả video seek tới 02:30 và tiếp tục trạng thái phát/pause như trước khi kéo.
- **AC 3 (Video chưa sẵn sàng):**
    - **Given** video chưa load xong metadata (`duration === 0`),
    - **When** user click hoặc kéo thanh timeline,
    - **Then** thanh ở trạng thái disabled/mờ, không seek được.

**Business Requirement Table**

|  |  |
| --- | --- |
| **User Story** | US-001 Tua và seek video với timeline YouTube-style |
| **Description**  | Cho phép user tua video bằng click hoặc kéo scrub trên thanh timeline thống nhất toàn portal |
| **Actor**  | Portal user |
| **Pre-Conditions** | User đã mở màn có video; player hiển thị thanh timeline mới |
| **Trigger** | Click thanh timeline / mousedown → drag → mouseup trên thanh |
| **Post-Conditions** | Video tại vị trí seek mới (sau thả chuột hoặc ngay khi click); playhead khớp vị trí |
| **Business Rules** | Seek kẹp trong `0 ≤ time ≤ duration`; kéo ra ngoài thanh vẫn kẹp biên; played segment màu đỏ `#FF0000`; buffered hiển thị sáng hơn track tối; áp dụng mọi surface video portal |

**UI/UX**

- Wireframe: [[docs/review/qc-review-video-player-controls/ascii-screen/video-player-playing.md|US-001 — player default (playing)]]
- Wireframe: [[docs/review/qc-review-video-player-controls/ascii-screen/video-player-timeline-drag.md|US-001 — timeline đang kéo scrub]]

#### 3.2.2 US-002 Xem preview vị trí khi hover/kéo

**Story**

**As a** `Portal user` **I want** `to see the timecode at my cursor position when I hover or drag the timeline` **So that** `I know exactly where I will land before releasing the scrub`

**Acceptance Criteria**

- **AC 1 (Hover time tooltip):**
    - **Given** video đã load, user rê chuột lên thanh tại vị trí tương ứng 05:12,
    - **When** con trỏ dừng ≥50ms trên thanh,
    - **Then** thanh nở (5px → 9px), chấm tròn playhead hiện, tooltip nhỏ nền đen `rgba(0,0,0,0.85)` hiện timecode `00:05:12` ngay trên vị trí con trỏ (tooltip bị kẹp mép để không tràn khỏi thanh).
- **AC 2 (Tooltip khi kéo):**
    - **Given** user đang kéo scrub,
    - **When** di chuyển con trỏ dọc thanh,
    - **Then** tooltip timecode đi **theo con trỏ** trong suốt thao tác kéo và số `current` trên control bar cũng tạm hiện vị trí kéo.
- **AC 3 (Rời chuột):**
    - **Given** user không đang kéo, video không phát,
    - **When** user rời chuột khỏi thanh,
    - **Then** tooltip ẩn; chấm playhead ẩn trừ khi video đang phát.

**Business Requirement Table**

|  |  |
| --- | --- |
| **User Story** | US-002 Xem preview vị trí khi hover/kéo |
| **Description**  | Hiển thị timecode tại vị trí con trỏ khi hover/kéo; card thumbnail để phase sau |
| **Actor**  | Portal user |
| **Pre-Conditions** | Video metadata đã load; thanh timeline enabled |
| **Trigger** | Mouseenter / pointermove trên thanh; drag scrub |
| **Post-Conditions** | User thấy timecode đúng vị trí con trỏ; không block seek |
| **Business Rules** | Debounce hover 50ms (`HOVER_DEBOUNCE_MS`); tooltip chỉ chứa timecode `HH:MM:SS` — không câu chữ mô tả thêm; card thumbnail 160×90 + shimmer **chưa ship** (P2, chờ API sprite sheet) |

**UI/UX**

- Wireframe: [[docs/review/qc-review-video-player-controls/ascii-screen/video-player-timeline-hover.md|US-002 — timeline hover + time tooltip]]
- Wireframe: [[docs/review/qc-review-video-player-controls/ascii-screen/video-player-timeline-drag.md|US-002 — tooltip khi kéo scrub]]

#### 3.2.3 US-003 Điều khiển phát video đầy đủ

**Story**

**As a** `Portal user` **I want** `to use play/pause, speed, time display, keyboard shortcuts, and fullscreen on a consistent control bar` **So that** `I don't need inconsistent native browser video controls`

**Acceptance Criteria**

- **AC 1 (Play/Pause + thời gian):**
    - **Given** video đã load, đang pause tại 01:00 / tổng 10:00,
    - **When** user bấm Play,
    - **Then** video phát, nút chuyển Pause, hiển thị `01:00 / 10:00` cập nhật liên tục.
- **AC 2 (Phím tắt tua):**
    - **Given** player đang active, focus không nằm trong input/textarea,
    - **When** user bấm `→`,
    - **Then** video tua thêm 5 giây (kẹp tại duration); `←` tua lùi 5 giây (kẹp tại 0).
- **AC 3 (Hết video — phát lại từ đầu):**
    - **Given** video đã phát hết (ended), playhead ở cuối,
    - **When** user bấm Play,
    - **Then** video phát lại từ `0:00`.

**Business Requirement Table**

|  |  |
| --- | --- |
| **User Story** | US-003 Điều khiển phát video đầy đủ |
| **Description**  | Bộ điều khiển play/pause, tốc độ, thời gian, phím tắt, fullscreen thống nhất |
| **Actor**  | Portal user |
| **Pre-Conditions** | Video đã load metadata |
| **Trigger** | Bấm Play/Pause / chọn tốc độ / phím tắt / bấm Fullscreen |
| **Post-Conditions** | Trạng thái phát hoặc fullscreen thay đổi theo thao tác |
| **Business Rules** | Tốc độ chỉ trong `{0.5, 1, 2, 4, 8}×`, mặc định `1×`; `Home`/`End` nhảy đầu/cuối; fullscreen giữ control bar overlay chrome tối; thay native `<video controls>` trên upload preview và scrub cũ trên QC player |

**UI/UX**

- Wireframe: [[docs/review/qc-review-video-player-controls/ascii-screen/video-player-playing.md|US-003 — control bar đầy đủ (playing)]]

#### 3.2.4 US-004 Điều khiển playback đồng bộ cho multicam

> **Cập nhật 2026-09-11 (đối chiếu code):** bản URD gốc mô tả mỗi camera có timeline độc lập. Code thực tế đi theo hướng ngược lại: **1 master timeline chung** trên head camera, 2 wrist camera mirror theo master + `syncOffsets`. Đổi tên và AC cho khớp.

**Story**

**As a** `Multicam viewer` **I want** `one shared timeline that keeps all three cameras in sync` **So that** `I compare the same moment across angles without manually aligning them`

**Acceptance Criteria**

- **AC 1 (Tua master):**
    - **Given** màn hiển thị 3 camera head/left_wrist/right_wrist đang phát đồng bộ tại 00:30,
    - **When** user kéo timeline chung (thanh toolbar dưới lưới video) tới 02:00 và thả,
    - **Then** cả 3 video nhảy tới 02:00 (wrist áp `syncOffsets` tương ứng).
- **AC 2 (Trạng thái phát mirror):**
    - **Given** 3 camera đang phát,
    - **When** user bấm play/pause trên thanh chung,
    - **Then** cả 3 camera đổi trạng thái theo; trong lúc seek đồng bộ, overlay `"Đang đồng bộ…"` (`scaleai_qc_seek_syncing`) hiện cho tới khi các pane bắt kịp.
- **AC 3 (Pane video không có toolbar riêng):**
    - **Given** đang ở layout multicam,
    - **When** user nhìn từng pane camera,
    - **Then** mỗi pane chỉ có vùng video (không timeline/controls riêng); click vào pane bật/tắt phát cả nhóm.

**Business Requirement Table**

|  |  |
| --- | --- |
| **User Story** | US-004 Điều khiển playback đồng bộ cho multicam |
| **Description**  | Một master timeline chung điều khiển 3 camera synced (thay cho timeline độc lập từng cam trong brainstorm gốc) |
| **Actor**  | Multicam viewer (Portal user) |
| **Pre-Conditions** | Màn multicam hiển thị ≥2 camera |
| **Trigger** | Tương tác master timeline / play-pause trên thanh chung |
| **Post-Conditions** | Cả 3 camera cùng vị trí phát (đã áp offset) |
| **Business Rules** | Master = head camera; wrist slave mirror transport + drift correction qua `useSyncedMulticamVideos`; offset từ backend `multicam_sync_offsets`; không có timeline riêng/camera |

**UI/UX**

- Wireframe: [[docs/review/qc-review-video-player-controls/ascii-screen/video-player-multicam.md|US-004 — multicam master timeline chung]]

#### 3.2.5 US-005 Xử lý lỗi khi video không phát được

**Story**

**As a** `Portal user` **I want** `clear error messages when video fails to load or the link expires` **So that** `I know what to do instead of seeing a broken player`

**Acceptance Criteria**

- **AC 1 (Load fail):**
    - **Given** video không load được metadata,
    - **When** màn hiển thị player,
    - **Then** thanh timeline disabled; user thấy "Không thể phát video. Vui lòng thử lại." (không crash UI).
- **AC 2 (URL hết hạn):**
    - **Given** user đang xem video qua presigned link,
    - **When** link hết hạn giữa session,
    - **Then** playback dừng; user thấy "Liên kết video đã hết hạn. Vui lòng tải lại trang."

**Business Requirement Table**

|  |  |
| --- | --- |
| **User Story** | US-005 Xử lý lỗi khi video không phát được |
| **Description**  | Thông báo lỗi rõ ràng khi phát video thất bại hoặc link hết hạn |
| **Actor**  | Portal user; System (phát hiện lỗi) |
| **Pre-Conditions** | User mở màn có video |
| **Trigger** | Video load fail / URL expired trong lúc phát |
| **Post-Conditions** | User biết lỗi và hướng xử lý (thử lại / reload); timeline không tương tác được |
| **Business Rules** | Wording error cố định như AC; giữ flow lỗi phát hiện có trên `VideoPlayer` — không regression |

**UI/UX**

- Wireframe: [[docs/review/qc-review-video-player-controls/ascii-screen/video-player-playback-error.md|US-005 — lỗi load video]]
- Wireframe: [[docs/review/qc-review-video-player-controls/ascii-screen/video-player-url-expired.md|US-005 — URL hết hạn]]

#### 3.2.6 US-006 Phát mượt — buffer trước playhead

**Story**

**As a** `Portal user` **I want** `the player to keep roughly 30 seconds buffered ahead of the playhead` **So that** `scrubbing and short seeks rarely stall on loading`

**Acceptance Criteria**

- **AC 1 (MP4 progressive):**
    - **Given** video MP4 đang phát, buffer phía trước playhead < 30s,
    - **When** có hoạt động playback (`progress` / `timeupdate`),
    - **Then** player chủ động prefetch thêm range phía trước playhead (debounce 400ms) cho tới khi đạt ~30s.
- **AC 2 (HLS):**
    - **Given** video phát bằng HLS,
    - **When** hls.js khởi tạo,
    - **Then** buffer cấu hình theo ~30s (`maxBufferLength=30`, `maxMaxBufferLength=90`, `backBufferLength=30`).
- **AC 3 (Không chặn UX):**
    - **Given** prefetch lỗi (mạng, CORS, URL hết hạn),
    - **When** user vẫn xem video,
    - **Then** không hiện lỗi cho user — browser tiếp tục buffer qua thẻ `<video>` (best-effort).

**Business Requirement Table**

|  |  |
| --- | --- |
| **User Story** | US-006 Phát mượt — buffer trước playhead |
| **Description**  | Giữ ~30s buffer phía trước playhead cho MP4 progressive và HLS |
| **Actor**  | Portal user; System (prefetch) |
| **Pre-Conditions** | Video đã load metadata, `src` là URL fetch được |
| **Trigger** | Playback progress / seek |
| **Post-Conditions** | Vùng buffered trên thanh timeline mở rộng ~30s trước playhead |
| **Business Rules** | `MIN_PLAYBACK_BUFFER_AHEAD_SEC = 30`; chỉ prefetch khi buffer hiện tại < ngưỡng và không có request inflight; bỏ HEAD request với presigned S3 (dùng `Range: bytes=0-0` để lấy dung lượng) |

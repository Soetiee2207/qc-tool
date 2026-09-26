<!-- doc-meta: type=srs | feature=review/qc-review-video-player-controls | status=draft | updated=2026-09-11 -->
# **SOFTWARE REQUIREMENTS SPECIFICATION**

Video Player Controls — YouTube-Style Timeline

Version 1.1 | 2026-09-11

|  |  |  |  |
| --- | --- | --- | --- |
| **Version** | **Date** | **Author** | **Changes** |
| 1.1 | 2026-09-11 | @binhhm | Đối chiếu code: toolbar thật gồm play/pause, skip `<<`/`>>` ±5s, thời gian `HH:MM:SS`, mute toggle, 5 nút tốc độ, fullscreen; bổ sung **buffer ahead ~30s** (`videoBufferAhead.ts` + `useVideoBufferPrefetch`) và màu control theo primary green; nhấn mạnh hover chỉ có **time tooltip** (không card 160×90) |
| 1.0 | 2026-09-03 | @cursor-agent | Initial draft — kế thừa `urd.md`, brainstorm `youtube-style-timeline`, wireframe `ascii-screen/`; đối chiếu `VideoPlayer.tsx`, `YoutubeStyleProgressBar.tsx` |

**Table of Contents**

1. **INTRODUCTION**

**1.1. Purpose**

- Đặc tả kỹ thuật component điều khiển video kiểu YouTube dùng chung portal (`VideoPlayer` + `YoutubeStyleProgressBar`).
- Đối tượng: dev frontend, QA.
- Kế thừa `docs/review/qc-review-video-player-controls/urd.md`.

**1.2. Scope**

- **IN SCOPE:**
  - `YoutubeStyleProgressBar` — played (`bg-primary` = primary green), buffered (`bg-white/35`), track (`bg-white/20`); seek click + drag 2-phase (UI khi kéo → `onSeek` khi pointer up); playhead dot 15px (`bg-primary` + viền trắng) hiện khi playing/hover/drag; vòng preview 15px khi vị trí con trỏ lệch playhead > 0.5%.
  - Hover: bar height 5px → 9px (transition 80ms), debounce 50ms (`HOVER_DEBOUNCE_MS`); **time tooltip** `HH:MM:SS` (`data-testid="progress-hover-time-tooltip"`, kẹp mép ±28px) — **không** có thumbnail card 160×90.
  - `VideoPlayer` toolbar (thứ tự trái → phải): play/pause → skip `<<` `>>` (±5s, `SEEK_SKIP_SECONDS`) → `current / total` (`formatPlaybackClock`, `HH:MM:SS`) → mute toggle (`video_mute`/`video_unmute`, `aria-pressed`) → 5 nút tốc độ `{0.5, 1, 2, 4, 8}×` (nút đang chọn `bg-primary`) → fullscreen (`Maximize2`, `fullscreenRef` hoặc container).
  - Keyboard shortcuts khi `showToolbar` và focus không trong input/textarea/select: `←` / `<` / `Shift+,` lùi 5s; `→` / `>` / `Shift+.` tiến 5s; `Home` về 0; `End` tới cuối (`scrubDurationSec`).
  - **Buffer ahead ~30s**: `MIN_PLAYBACK_BUFFER_AHEAD_SEC = 30` — HLS cấu hình `maxBufferLength`/`maxMaxBufferLength`/`backBufferLength` theo hằng số này; MP4 dùng `useVideoBufferPrefetch` (debounce 400ms, gọi `prefetchMp4BufferAhead`) chỉ khi `bufferAheadSec(video) < 30`.
  - Segment markers (`SegmentScrubMarker`) khi parent truyền `segmentPlayback`.
  - Timeline disabled khi `durationSec <= 0` hoặc `loadError` (opacity-40, `cursor-not-allowed`).
  - Error kinds: `video_playback_error` (generic), `video_url_expired` (presigned/proxy retry exhausted); retry presigned/proxy tối đa 8× (3s), nguồn khác 120× (5s).
  - Consumers: `QCReviewDetail`, `AutoAssignRulesPanel` không dùng — cụ thể: `MetadataQcReviewLayout`, `QCReviewDetail` (annotation/legacy), `ScaleAiMulticamVideoView`, `StereoVideoView`, `DualVideoCompare`, `UploadHistoryVideoPreview`.
  - HLS (`hls.js`) và native MP4; lock `currentLevel = 0` sau `MANIFEST_PARSED`; presigned URL retry + `onPlaybackError` refetch.
- **OUT OF SCOPE:**
  - Thumbnail/sprite preview API (URD mock card 160×90 — chưa implement; v1 chỉ time tooltip).
  - `MultiLaneTimeline` (NLE editor).
  - Session resume playhead position.
  - Volume slider (icon mute only).
  - Mobile/touch behavior riêng.
  - Phân quyền theo role.
- **Integration boundary:** Playback URL từ QC/ingest APIs (presigned S3, HLS). Feature chỉ thay lớp UI điều khiển.

**1.3. Definitions**

|  |  |
| --- | --- |
| **Scrub 2-phase** | Drag chỉ cập nhật UI (`pointerPct`, tooltip); `onSeek(sec)` gọi khi `pointerup` |
| **Segment playback** | Parent timeline window (`startSec`, `endSec`, `parentDurationSec`) — scrub hiển thị parent time |
| **Master timeline (multicam)** | `ScaleAiMulticamVideoView` dùng **một** shared toolbar gắn head camera; wrist slaves sync qua `useSyncedMulticamVideos` — **không** có timeline riêng/camera như URD US-004 mô tả |

## 2. System Overview

**2.1. Architecture**

```
VideoPlayer.tsx
├── <video> + hls.js (optional)
├── useVideoBufferPrefetch(videoRef, src) → prefetchMp4BufferAhead (~30s)
├── YoutubeStyleProgressBar
│   ├── playedPct, bufferedRanges (video.buffered)
│   ├── HOVER_DEBOUNCE_MS = 50, BAR_HEIGHT 5 → 9
│   └── onSeek → seekToScrubSec → seekToPct
├── Toolbar: play, "<<"/">>" ±5s, current/total, mute, 5 speed buttons, fullscreen
└── Keyboard: ArrowLeft/Right (< >), Home/End (SEEK_SKIP_SECONDS = 5)

ScaleAiMulticamVideoView
├── 3× VideoPlayer (showToolbar=false, per-pane video only)
└── 1× VideoPlayer (showVideo=false, showToolbar=true) — master controls head + sync slaves
```

**Wireframes:** `docs/review/qc-review-video-player-controls/ascii-screen/`

**2.2. User Profile**

Mọi portal user có quyền xem màn chứa video — không thêm permission cho timeline.

## 3. Functional Requirements

### 3.1 Function List

| **ID** | **Function** | **Description** |
| --- | --- | --- |
| F-01 | Timeline seek & scrub | Click/drag `YoutubeStyleProgressBar`; clamp `0…durationSec`. |
| F-02 | Hover preview timecode | Debounced tooltip; playhead dot khi playing/hover/drag. |
| F-03 | Playback toolbar & shortcuts | Play/pause, speed, time display, ±5s, Home/End, fullscreen. |
| F-04 | Multicam master controls | Shared toolbar on head; slave sync via `useSyncedMulticamVideos`. |
| F-05 | Playback error handling | Load fail / URL expired messaging; timeline disabled. |
| F-06 | Buffer ahead ~30s | HLS buffer config + `useVideoBufferPrefetch` cho MP4 progressive. |

**Traceability:** US-001→F-01; US-002→F-02; US-003→F-03; US-004→F-04 (implementation: master sync, not per-cam scrub); US-005→F-05; US-006→F-06.

### 3.2 Function Detail

**3.2.1. F-01 Timeline seek & scrub**

#### A. Flow

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | User | `pointerdown` trên track → `setDragging(true)`, cập nhật `pointerPct`. |
| 2 | User | Drag → chỉ UI (`previewPct`, tooltip) di chuyển. |
| 3 | User | `pointerup` → `onSeek(sec)` với `sec = pct * durationSec` clamped. |
| 4 | System | `VideoPlayer.seekToPct` → `video.currentTime` + `onTimeUpdate`. |
| 5 | System | `disabled \|\| durationSec <= 0` → ignore pointer events, `opacity-40`. |

#### B. API Specification

**Không có API** — props interface:

```typescript
interface YoutubeStyleProgressBarProps {
  durationSec: number;
  positionSec: number;
  bufferedRanges: { start: number; end: number }[];
  disabled?: boolean;
  playing?: boolean;
  ariaLabel: string;
  segmentOverlay?: React.ReactNode;
  onSeek: (sec: number) => void;
  /** Temporary scrub/hover position for parent time display. */
  onPreviewSecChange?: (sec: number | null) => void;
}
```

---

**3.2.2. F-02 Hover preview timecode**

#### A. Flow

| **Step** | **Description** |
| --- | --- |
| 1 | `mouseenter` → `hovering=true`, bar expands 5→9px. |
| 2 | `mousemove` → `scheduleHoverPct` debounce 50ms → `debouncedHoverPct`. |
| 3 | Tooltip `formatPlaybackClock(previewSec)` hiện khi `hovering \|\| dragging`. |
| 4 | `mouseleave` (không dragging) → clear hover state, tooltip ẩn. |

**Note:** URD mô tả card 160×90 + shimmer — **chưa shipped**; v1 chỉ time tooltip `data-testid="progress-hover-time-tooltip"`.

#### B. API Specification

**Không có API** — covered by F-01 props `onPreviewSecChange`.

---

**3.2.3. F-03 Playback toolbar & shortcuts**

#### A. Flow

| **Step** | **Description** |
| --- | --- |
| 1 | Play/Pause toggles `playing` state → `video.play()` / `pause()`; overlay play button hiện khi `mediaPaused && !buffering`. |
| 2 | Ended + Play → `applyClipSeconds(0)` restart. |
| 3 | Speed: 5 nút riêng `PLAYBACK_SPEED_OPTIONS = [0.5, 1, 2, 4, 8]`, click chọn trực tiếp → `video.playbackRate`; nút active `bg-primary` + `aria-pressed`. |
| 4 | Skip `<<` / `>>` → `seekBySeconds(∓SEEK_SKIP_SECONDS)` (5s); keyboard `ArrowLeft`/`ArrowRight` (và `<`/`>`/`Shift+,`/`Shift+.`) cùng bước 5s. |
| 5 | `Home`/`End` → seek 0 / `scrubDurationSec`. |
| 6 | Mute: `toggleMuted()` set trực tiếp `video.muted`, đồng bộ lại từ event `volumechange`; nhãn `video_mute` ↔ `video_unmute`. |
| 7 | Fullscreen → `fullscreenRef` (vd grid multicam) hoặc `containerRef` `requestFullscreen()`; thoát bằng `document.exitFullscreen()`. |
| 8 | Display: `formatPlaybackClock(displayCurrentSec) / formatPlaybackClock(displayTotalSec)`; khi đang kéo/hover, `displayCurrentSec` lấy vị trí con trỏ (`dragPreviewSec`). |

#### B. API Specification

**Không có API** — `VideoPlayer` props; keyboard listener on `window` when `showToolbar`.

---

**3.2.4. F-04 Multicam master controls**

#### A. Flow

| **Step** | **Description** |
| --- | --- |
| 1 | Mỗi camera pane: `VideoPlayer` với `showToolbar={false}`, `followExternalSeek={false}`. |
| 2 | `showSharedToolbar` → bottom `VideoPlayer` `showVideo={false}`, `videoRef=headVideoRef`. |
| 3 | Seek/play trên shared toolbar → head video; `useSyncedMulticamVideos` mirrors transport + drift correction tới left/right wrist. |
| 4 | `syncOffsets` từ backend điều chỉnh slave `currentTime` relative to master. |

**Deviation from URD US-004:** Không có timeline độc lập/camera — một master timeline điều khiển cả 3 góc (synced playback).

#### B. API Specification

**Không có API** — consumes `GET /qc/.../playback` URLs per camera role (parent feature).

---

**3.2.5. F-05 Playback error handling**

#### A. Flow

| **Step** | **Description** |
| --- | --- |
| 1 | Load fail → `loadError=true`, `timelineDisabled=true`. |
| 2 | Presigned/proxy URL: retry up to 8× (3s interval); sau đó `playbackErrorKind=url_expired` → `video_url_expired`. |
| 3 | Other sources: up to 120 retries (5s) → `video_playback_error`. |
| 4 | `onPlaybackError` callback refetches playback URL (parent `useStablePlaybackSrc`). |

#### B. API Specification

**Không có API mới** — error strings từ i18n keys `video_playback_error`, `video_url_expired`.

---

**3.2.6. F-06 Buffer ahead ~30s**

#### A. Flow

| **Step** | **Description** |
| --- | --- |
| 1 | Hằng số `MIN_PLAYBACK_BUFFER_AHEAD_SEC = 30` (`videoBufferAhead.ts`) — mục tiêu buffer trước playhead. |
| 2 | HLS: khởi tạo `hls.js` với `maxBufferLength = 30`, `maxMaxBufferLength = 90`, `backBufferLength = 30`, `maxBufferSize = 100MB`. |
| 3 | MP4 progressive: `useVideoBufferPrefetch(videoRef, src, enabled)` lắng nghe `progress` / `timeupdate` / `loadedmetadata`, debounce 400ms (`PREFETCH_DEBOUNCE_MS`) rồi gọi `prefetchMp4BufferAhead`. |
| 4 | Guard: bỏ qua khi `bufferAheadSec(video) >= 30` hoặc đang có request inflight; lỗi prefetch là best-effort (browser vẫn tự buffer qua `<video>`); chỉ tự lên lịch lại khi video còn đang phát. |
| 5 | Xác định dung lượng file: `resolveVideoContentLength()` — **bỏ HEAD** khi URL là presigned S3 (tránh 403 ồn ào), dùng `Range: bytes=0-0` + `Content-Range` thay thế; cache theo URL. |

#### B. API Specification

**Không có API** — thuần client-side (Range request trực tiếp tới presigned URL).

## 4. Non-Functional Requirements

| **ID** | **Requirement** | **Target** | **Priority** |
| --- | --- | --- | --- |
| NFR-P-01 | Seek UI response | Pointer move → tooltip < 16ms (RAF) | High |
| NFR-P-02 | Hover debounce | 50ms (`HOVER_DEBOUNCE_MS`) | Medium |
| NFR-U-01 | Keyboard skip | ±5s clamped to `[0, duration]` | High |
| NFR-U-02 | Disabled timeline | No seek when `durationSec <= 0` | High |
| NFR-M-01 | Unit tests | `YoutubeStyleProgressBar.test.tsx` — seek on pointer up only | High |
| NFR-M-02 | Unit tests | `VideoPlayer.test.tsx` | Medium |
| NFR-M-03 | Unit tests | `videoBufferAhead.test.ts`, `playbackTime.test.ts` | Medium |
| NFR-A-01 | Progress bar a11y | `role="slider"`, `aria-valuenow/min/max`, `aria-disabled` | Medium |
| NFR-P-03 | Buffer ahead (MP4/HLS) | Target ~30s trước playhead; prefetch debounce 400ms | Medium |

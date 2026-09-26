---
type: brainstorm
feature: review/qc-review-video-player-controls
idea_slug: youtube-style-timeline
status: draft
mode: deep
lang: vi
owner: "@binhhm"
created: 2026-08-28
updated: 2026-08-28
complexity_flags: [has_async_flow, has_state_machine]
links: []
tags: [brainstorm, video-player-controls, youtube-style]
stale_reason: ""
changelog:
  - 2026-08-28 | /brainstorm | initial brainstorm youtube-style timeline, deep mode, 4 OQs flagged
---

# YouTube-Style Video Timeline — Brainstorm

> Feature: video-player-controls | Idea: youtube-style-timeline
> 1 feature có thể có nhiều brainstorm — đây là 1 idea/draft độc lập.

## 1. Idea Seed

> "I want to build video timeline control similar youtube.com. You can mimic youtube yeah."
>
> Ghi chú thêm: thumbnail API chưa có — v1 chỉ UI mock, backend pending.

## 2. Context

- **Pain hiện tại:** thanh timeline / scrub bar trên portal đang rất kém — khó tua, thiếu feedback buffered, không có preview khi rê chuột.
- **Why now:** preview video quan trọng cho roadmap tương lai (QC, annotation, upload history, multicam…).
- **Phạm vi:** áp dụng **mọi chỗ có video** trên portal — không phân quyền theo role.
- **Visual direction:** mimic YouTube (đỏ `#FF0000`, chrome tối, hover expand bar, card preview).
- **Ràng buộc v1:** thumbnail chỉ mock (placeholder + timecode); API sprite sheet để phase sau.

## 3. User Types (preliminary)

| User Type | Pain Point | Primary Need |
|-----------|-----------|--------------|
| Annotator / QC reviewer | Scrub khó, không biết chỗ đã buffer | Tua nhanh chính xác, thấy preview vị trí |
| Admin / ops xem upload | Native `<video controls>` không đồng nhất | Trải nghiệm phát video thống nhất toàn portal |
| Multicam viewer | Nhiều góc cam, cần tua từng góc | Timeline độc lập mỗi camera |

## 4. Capabilities Breakdown

### P0 — must have

- Thanh progress kiểu YouTube: played (đỏ), buffered (sáng), track (tối).
- Click thanh → seek ngay.
- Kéo scrub 2 pha: UI theo chuột khi kéo → seek thật khi thả.
- Hover: thanh cao hơn (5px → 9px), chấm đỏ, card preview **mock** + timecode.
- Play/Pause + hiển thị `current / total`.
- Phím `←` / `→` tua ±5s; `Home` / `End` nhảy đầu/cuối.
- Tốc độ phát: `0.5×, 1×, 2×, 4×, 8×` (mặc định `1×`).
- Fullscreen với control bar overlay dưới video.
- Component **dùng chung** — rollout mọi surface có video.
- Multicam: mỗi camera timeline **độc lập** (tua cam A không kéo cam B).
- Disabled khi video chưa load metadata; kẹp seek trong `0 → duration`.

### P1 — should have

- Segment / chapter markers trên thanh (nếu parent truyền window segment — QC layouts).
- Touch drag scrub (mobile/tablet) tương đương mouse.
- Keyboard shortcuts khi player đang active (không steal focus từ input).

### P2 — nice to have

- `ApiThumbnailProvider` khi backend sprite sheet sẵn sàng.
- Volume slider (v1 có thể icon-only).
- Frame-accurate timecode `HH:MM:SS:FF` trong preview label.

> P0/P1/P2 là tentative; final scope chốt ở `/prd video-player-controls`.

## 5. Core Flows (Happy Path)

### 5.1 Xem và tua video (1 camera)

1. User mở màn có video → hệ thống load metadata.
2. Thanh timeline enabled tại `0:00`; vạch buffered cập nhật khi tải thêm.
3. User bấm Play → video phát; playhead chạy theo thời gian thực.
4. User rê chuột lên thanh → thanh nở, chấm đỏ hiện, card mock (shimmer ~150ms → placeholder xám + timecode).
5. User kéo thanh → playhead + card mock theo con trỏ; video **chưa** nhảy.
6. User thả chuột → video seek tới vị trí mới; tiếp tục phát hoặc pause tùy trạng thái trước đó.
7. Video hết → user bấm Play → phát lại **từ đầu**.

```
User mở màn có video
        │
        ▼
┌───────────────────┐
│ Hệ thống load     │
│ metadata video    │
└─────────┬─────────┘
          │
    ┌─────┴─────┐
    │           │
  FAIL        OK
    │           │
    ▼           ▼
 Thanh        Thanh timeline
 disabled     enabled (0:00)
 + lỗi phát       │
                   ├─ Hover thanh ──► nở + chấm đỏ
                   │                  + card mock + timecode
                   │
                   ├─ Click thanh ──► seek ngay ──► phát tiếp
                   │
                   ├─ Kéo thanh ──► UI theo chuột (chưa seek)
                   │       │
                   │    Thả chuột
                   │       │
                   │       ▼
                   │    Seek video ──► phát / pause
                   │
                   ├─ Phím ← / → ──► tua ±5s
                   │
                   ├─ Buffer tăng ──► vạch sáng trên thanh
                   │
                   └─ Hết video ──► Play lại từ đầu
```

### 5.2 Multicam — tua độc lập từng camera

1. User mở layout nhiều camera.
2. Mỗi camera có thanh timeline riêng (playhead, buffered, preview mock độc lập).
3. User tua cam A → chỉ video cam A nhảy; cam B,C giữ nguyên vị trí.
4. User có thể tua từng cam để so sánh cùng thời điểm thủ công.

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Camera A   │  │  Camera B   │  │  Camera C   │
│  [timeline] │  │  [timeline] │  │  [timeline] │
└──────┬──────┘  └─────────────┘  └─────────────┘
       │
 User kéo A only
       │
       ▼
  Seek A only
  B, C unchanged
```

## 6. System Behavior Deep Dive

### 6.1 Decision Points

| ID | Flow | Khi nào | YES (nhánh đồng ý) | NO (nhánh từ chối) |
|---|---|---|---|---|
| D1 | Load video | Metadata load thành công? | Thanh enabled, seek được | Thanh disabled + thông báo lỗi phát |
| D2 | Click thanh | Duration > 0? | Seek ngay tới vị trí click | Không làm gì |
| D3 | Kéo scrub | User thả chuột? | Commit seek video | Chỉ cập nhật UI playhead |
| D4 | Video ended | User bấm Play? | Phát lại từ 0:00 | Giữ ở cuối, paused |
| D5 | Hover thanh | Đang kéo scrub? | Card mock theo con trỏ kéo | Card mock theo vị trí hover |
| D6 | Multicam | User tương tác timeline cam X? | Chỉ seek video cam X | Không ảnh hưởng cam khác |

### 6.2 Scenario Matrix (input states)

| From State | To State | Rule | Action | Result |
|------------|----------|------|--------|--------|
| Chưa load | Sẵn sàng | `loadedmetadata` + duration > 0 | Enable thanh | User tua được |
| Sẵn sàng | Đang phát | Bấm Play | Bắt đầu playback | Playhead chạy |
| Đang phát | Tạm dừng | Bấm Pause | Dừng playback | Playhead đứng |
| Đang phát | Buffering | Mạng chậm | Hiện spinner / dừng playhead | Tự resume khi đủ buffer |
| Bất kỳ | Đang kéo | mousedown trên thanh | UI-only update | Chưa seek |
| Đang kéo | Sau seek | mouseup | Commit seek | Video nhảy tới vị trí |
| Hết video | Phát lại | Bấm Play | Reset playhead 0 | Phát từ đầu |

### 6.3 State Transitions

```
Video: Chưa sẵn sàng → Sẵn sàng → Đang phát ↔ Tạm dừng → Hết
                              ↘ Buffering ↗
Timeline UI: Bình thường → Hover → Đang kéo → (seek) → Bình thường
```

| Entity | Từ | Sang | Trigger | Quay lại được? |
|--------|------|----|---------|-------------|
| Video | Chưa sẵn sàng | Sẵn sàng | Load xong metadata | — |
| Video | Sẵn sàng / Đang phát | Đang phát | Bấm Play | Pause được |
| Video | Đang phát | Tạm dừng | Bấm Pause | Play tiếp |
| Video | Đang phát | Buffering | Mạng chậm | Tự về phát khi đủ buffer |
| Video | Bất kỳ | Hết | Tới cuối duration | Play lại từ đầu |
| Thanh timeline | Bình thường | Hover | Rê chuột lên thanh | Rời chuột |
| Thanh timeline | Hover / Bình thường | Đang kéo | Giữ chuột + kéo | Thả chuột → seek |

### 6.4 Interrupted Transactions

| Tình huống | Hệ thống còn lại gì | Resume | Cleanup |
|---|---|---|---|
| Đóng tab / rời màn giữa lúc kéo | Không commit seek | Mở lại màn từ đầu | Không lưu vị trí kéo dở |
| Mạng chậm / buffer | Playhead có thể dừng; buffered range tăng dần | Tự resume khi đủ data | Không cần user action |
| Video load fail | Thanh disabled | User reload trang / thử lại | Hiện lỗi phát |
| URL / presigned link hết hạn | Playback dừng | User reload / request link mới | Thông báo lỗi, UI không crash |
| Mở video khác trên cùng player | Reset timeline | Playhead 0, buffered mới | State cũ bỏ |
| 2 camera cùng màn | Trạng thái độc lập mỗi cam | Tua từng cam riêng | Không conflict |

### 6.5 Other Edge Cases

- Kéo chuột ra ngoài thanh rồi thả → vẫn seek tới vị trí kẹp trong `0 → duration`.
- Focus đang ở input/textarea → phím tắt tua **không** kích hoạt.
- Thumbnail mock pending → shimmer rồi placeholder; không throw lỗi, không block scrub.
- Upload preview (presigned MP4) và HLS QC player dùng **cùng** component — UX đồng nhất.
- Segment markers (QC): highlight window trên thanh khi parent truyền segment context.

## 7. Validation, Limits & Wording

### 7.1 Validation rules

| Field / Input | Rule |
|---|---|
| Vị trí seek | Kẹp trong `0 ≤ time ≤ duration` |
| Thanh timeline | Disabled khi `duration === 0` hoặc chưa `loadedmetadata` |
| Tốc độ phát | Chỉ chọn trong `{0.5, 1, 2, 4, 8}×` |
| Phím tắt | Bỏ qua khi focus trong input/textarea/select |

### 7.2 Limits & Quotas (exact values)

| Tham số | Giá trị | Window | Behavior khi vượt |
|---|---|---|---|
| Tua phím tắt | ±5 giây / lần | mỗi keypress | Kẹp tại 0 hoặc duration |
| Debounce preview mock | 50 ms | mỗi hover move | Chờ 50ms rồi mới cập nhật card |
| Shimmer mock | ~150 ms | mỗi lần hover mới | Rồi hiện placeholder |
| Tốc độ phát tối đa | 8× | — | Không có option cao hơn v1 |
| Kích thước card preview | 160×90 px | — | Fixed v1 |

### 7.3 Wording samples (exact strings)

#### Error messages

| Tình huống | Wording | Code |
|---|---|---|
| Video không phát được | "Không thể phát video. Vui lòng thử lại." | E-VIDEO-PLAYBACK |
| URL / link hết hạn | "Liên kết video đã hết hạn. Vui lòng tải lại trang." | E-VIDEO-URL-EXPIRED |

#### Success messages

| Tình huống | Wording |
|---|---|
| *(Timeline v1 không dùng toast success)* | — |

#### Info / neutral messages

| Tình huống | Wording |
|---|---|
| Card preview mock | Chỉ timecode (vd `01:23:45`) — không câu chữ |
| Đang buffer | *(không bắt buộc text — spinner trên Play hoặc thanh)* |

## 8. Assumptions

- Mọi surface video trên portal có thể migrate sang component chung mà không đổi business flow.
- Presigned URL / HLS playback patterns hiện có giữ nguyên — chỉ thay lớp điều khiển UI.
- Thumbnail API sẽ trả sprite sheet (1 request/video) — chi tiết contract chưa chốt (OQ-1).
- Multicam không cần master clock đồng bộ scrub — mỗi cam độc lập (đã confirm user).
- Visual style YouTube literal được chấp nhận trên nền portal (dark chrome trong card sáng cũng OK).

## 9. Risks

| Rủi ro | Khả năng | Hậu quả nghiệp vụ | Cách phòng |
|--------|----------|-------------------|-----------|
| Thumbnail API chậm ship (vendor/timeline) | thường | User quen mock, phải đổi kỳ vọng khi có preview thật | Provider injectable từ v1; document migration path |
| Rollout không đồng bộ giữa các màn (process) | thỉnh thoảng | Trải nghiệm lẫn lộn old/new scrub | Shared component + checklist migrate consumers |
| Hiệu năng máy yếu / nhiều camera (adoption) | thỉnh thoảng | Annotator chậm, complaint QC | Debounce preview; mock nhẹ, không decode frame v1 |
| Mobile touch chưa spec (timeline) | thỉnh thoảng | Trải nghiệm kém trên tablet | OQ-2 — xác nhận trước release mobile |

## 10. Success Criteria (preliminary)

- 100% surface video trên portal dùng timeline mới (thay scrub cũ / native controls).
- Annotator/QC có thể tua ±5s và kéo scrub mà không cần native browser controls.
- Preview mock hiện đúng timecode trong vòng 200ms perceived (debounce + shimmer).
- Không regression playback error handling (URL expired, load fail).

*Final metrics chốt ở `/urd video-player-controls`.*

## 11. Open Questions

- [ ] OQ-1: Contract API thumbnail (sprite URL, frame size, interval_sec, duration) — khi backend sẵn sàng.
- [ ] OQ-2: Mobile/touch — behavior riêng (tap vs drag) có bắt buộc v1 không?
- [ ] OQ-3: Volume — icon-only v1 hay cần slider ngay?
- [ ] OQ-4: Quy mô dùng (users/day, videos opened) — user skip ở interview; cần cho capacity planning.

## 12. Next Steps

Sau brainstorm này (sau khi BA approve):

- `/urd video-player-controls` — capture user perspective (inherit OQ còn hold)
- `/prd` — cập nhật Feature Map nếu cần
- `/srs video-player-controls` — spec kỹ thuật component + consumer migration

*KHÔNG nhảy thẳng implement — qua URD/PRD trước.*

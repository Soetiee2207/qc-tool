---
type: brainstorm
feature: review/qc-review-detail-tapdata
idea_slug: standalone-single-video-qc
status: draft
mode: shallow
lang: vi
owner: "Product Owner"
created: 2026-08-27
updated: 2026-08-27
complexity_flags: [has_state_machine]
links:
  - docs/review/qc-review-detail-scaleai-3cam/urd.md
  - docs/upload/recording-session-multicam-qr/urd.md
tags: [brainstorm, tapdata-qc-review, shallow]
stale_reason: ""
changelog:
  - 2026-08-27 | /brainstorm | initial — module Tapdata QC Review standalone, metadata Tapdata + preview 1 video
  - 2026-08-27 | /brainstorm | chốt final_result (1–12), minimum_video/video_duration, display_ratio 16:9, Pass/Reject rule
  - 2026-08-27 | /brainstorm | metadata 18 field read-only trên QC Review (bỏ editable/dropdown)
---

# Tapdata QC Review — module standalone (1 video)

> Feature: tapdata-qc-review | Idea: standalone-single-video-qc
> 1 feature có thể có nhiều brainstorm — đây là 1 idea/draft độc lập.

## 1. Idea Seed

Tạo module standalone **Tapdata-QC-Review** — side product line của Tapdata, tương tự cách ScaleAI có Recording Sessions / QC riêng trong portal. Layout QC review giống luồng egocentric MP4 hiện có (1 video preview), **không** dùng layout 3-camera của ScaleAI. Khác biệt chính: panel **Delivery Audit** dùng schema metadata Tapdata (18 field, 3 phần: Face & Hands auto, QC Auto video specs, QC Manual). Mọi thứ còn lại (queue, Pass/Reject, Review History, playback controls, auto-next…) **giữ nguyên** hành vi QC Review hiện tại.

*Raw input từ PO — không gắn pain point; request trực tiếp từ Product Owner.*

## 2. Context

- **Tapdata** là side module — product line riêng, không phụ thuộc pain point cụ thể.
- **Standalone** theo mô hình **ScaleAI**: menu/route riêng trong sidebar portal, không nhét chung QC Queue generic của egocentric legacy.
- **Tham chiếu kỹ thuật hiện có:**
  - Layout 1 video + sidebar metadata: `MetadataQcReviewLayout` (nhánh non-ScaleAI multicam) — sidebar cố định + Preview 1 video + Review History dưới Preview.
  - Layout 3 video (KHÔNG dùng cho Tapdata): `ScaleAiMulticamVideoView` + `MetadataQcSidebarTabs` — feature `scaleai-qc-review`.
  - Module độc lập trong sidebar: `scaleai-multicam-qr-sync` (Recording Sessions).
- **Nguồn schema PHẦN 3 QC Manual:** tham khảo file BìnhHM — khối Data, ngày 17/7/2026.
- **Hai delivery profile / ngưỡng:** `tapdata-iphone-std`, `tapdata-gopro-std` — hệ thống chọn profile theo project/upload (không do reviewer chọn tay trên màn).

## 3. User Types (preliminary)

| User Type | Pain Point | Primary Need |
|-----------|-----------|--------------|
| QC Reviewer | <!-- TBD: roles/gating skipped per PO --> | Xem 1 video Tapdata, **đọc** metadata read-only, Pass/Reject |
| Product Owner | Cần product line Tapdata tách biệt trên portal | Module QC riêng, schema chuẩn hóa theo 2 profile iPhone/GoPro |

## 4. Capabilities Breakdown

### P0 — must have

- Menu sidebar riêng **Tapdata QC** (hoặc tên hiển thị tương đương) → **Tapdata QC Queue** → màn detail.
- Màn detail: **sidebar trái** panel Tapdata Delivery Audit (18 field, 3 phần) + **Preview 1 video** (phải) + **Review History** dưới Preview — layout giống egocentric single-video QC, không tab 3-cam.
- Hiển thị **delivery profile** đang áp dụng (`tapdata-iphone-std` / `tapdata-gopro-std`) và ngưỡng tương ứng.
- **PHẦN 1 (Face & Hands):** read-only — giá trị từ pipeline; reviewer **không** sửa trên màn QC Review.
- **PHẦN 2 (QC Auto):** read-only — hệ thống tự detect; `final_result` = **PASS** khi **tất cả** mục 1–12 PASS, **FAIL** khi **bất kỳ** mục 1–12 FAIL (PHẦN 3 không tính vào `final_result`).
- **PHẦN 3 (QC Manual):** read-only — 5 field PASS/FAIL từ upstream; reviewer **không** chọn dropdown trên màn này; quyết định qua Pass/Reject toolbar.
- Toolbar **Pass / Reject / Back** — hành vi giữ nguyên QC Review hiện tại (Reject bắt lý do nếu đang có rule đó).
- Playback controls (play/pause, seek, shortcuts P/R/Space…) — giữ nguyên.

### P1 — should have

- Badge/highlight field FAIL hoặc không đạt ngưỡng trên sidebar (tương tự missing-field highlight của Delivery Audit hiện tại).
- Hiển thị ngưỡng kế bên giá trị (vd `42.3% (≤50%)`).

### P2 — nice to have

- Keyboard shortcut riêng nhảy giữa 3 phần metadata.
- Export kết quả QC Manual ra báo cáo.

> P0/P1/P2 là tentative; final scope chốt ở `/prd tapdata-qc-review`.

## 5. Core Flows (Happy Path)

### 5.1 Reviewer xử lý 1 item Tapdata QC

1. Reviewer vào menu **Tapdata QC** → thấy hàng đợi video chờ review.
2. Bấm 1 item → hệ thống mở màn detail: sidebar **Tapdata Delivery Audit** (profile + 18 field), Preview **1 video**, Review History bên dưới Preview.
3. Reviewer xem video, đối chiếu **metadata read-only** (PHẦN 1–3).
4. Reviewer bấm **Pass** hoặc **Reject** → hệ thống ghi quyết định (và lý do nếu Reject) → chuyển item tiếp theo nếu bật auto-next, hoặc về queue.

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│ Tapdata QC  │────▶│ Màn detail       │────▶│ Pass / Reject       │
│ Queue       │     │ 1 video + audit  │     │ → item kế / queue   │
└─────────────┘     └──────────────────┘     └─────────────────────┘
                            │
                            ▼
                    ┌──────────────────┐
                    │ Đọc metadata     │
                    │ read-only 1–3    │
                    └──────────────────┘
```

## 6. System Behavior Deep Dive

### 6.1 Decision Points

| ID | Flow | Khi nào | YES (nhánh đồng ý) | NO (nhánh từ chối) |
|---|---|---|---|---|
| D1 | Auto QC PHẦN 1–2 | Giá trị đạt ngưỡng profile | Field hiển thị PASS / trong ngưỡng | Field hiển thị FAIL / highlight cảnh báo |
| D2 | `final_result` | Mục 1–12 **đều** PASS | `final_result` = PASS | **Bất kỳ** mục 1–12 FAIL → `final_result` = FAIL |
| D3 | Submit review | Reviewer bấm Pass | Ghi passed (không hard-block dù `final_result` FAIL — reviewer tự đánh giá) | — |
| D4 | Submit review | Reviewer bấm Reject | Bắt lý do (theo rule QC hiện tại) → ghi rejected | — |

### 6.3 State Transitions

| Entity | Từ | Sang | Trigger | Quay lại được? |
|--------|-----|------|---------|----------------|
| QC item | `pending` / `in_review` | `passed` | Reviewer Pass | không |
| QC item | `pending` / `in_review` | `rejected` | Reviewer Reject | không (có thể re-queue ngoài phạm vi) |

### 6.5 Other Edge Cases

- Video chưa có auto metadata → PHẦN 1–2 hiển thị trạng thái loading/thiếu; reviewer vẫn có thể điền PHẦN 3 và Reject.
- Profile không xác định → fallback hiển thị cảnh báo; ngưỡng mặc định theo rule backend (TBD ở SRS).
- Item đã `passed`/`rejected` → màn read-only giống QC Review hiện tại.

## 7. Validation, Limits & Wording

### 7.1 Validation rules — ngưỡng theo profile

| Field | tapdata-iphone-std | tapdata-gopro-std |
|---|---|---|
| `face_visible_percent` | ≤ 50% | ≤ 50% |
| `hand_visible_percent` | > 60% | > 60% |
| `video_resolution` | ≥ 1080p | ≥ 1080p |
| `display_ratio` | 16:9 | 16:9 |
| `video_fps` | ≥ 29.9 | ≥ 29.9 |
| `format_name` | mp4, mov | mp4 |
| `video_codec` | h264, hevc | h264, hevc |
| `minimum_video` | PASS khi `video_duration` ≥ 30s | PASS khi `video_duration` ≥ 30s |
| `video_duration` | ≤ 3600 giây (độ dài thực detect) | ≤ 3600 giây (độ dài thực detect) |
| `video_bitrate_kpbs` | ≥ 8 Mbps | ≥ 25 Mbps |
| `final_result` | PASS iff mục 1–12 đều PASS; else FAIL | PASS iff mục 1–12 đều PASS; else FAIL |

*Ghi chú: `display_ratio` PO gốc `16:09` → chuẩn hóa **16:9** (khớp chính xác).*

### 7.3 Wording samples (exact strings)

#### Error messages

| Tình huống | Wording | Code |
|---|---|---|
| Không tải được video | "Không phát được video. Thử lại." | E-TAP-PLAYBACK |
| Reject thiếu lý do | Giữ nguyên wording QC Review hiện tại | E-QC-REJECT |

#### Success messages

| Tình huống | Wording |
|---|---|
| Pass thành công | Giữ nguyên toast QC Review hiện tại |

## 8. Assumptions

- Permission / role / Keycloak group **chưa chốt** (PO skip) — tạm reuse QC Reviewer.
- Delivery profile gắn theo **project type** hoặc upload profile khi ingest — không chọn tay trên màn detail.
- `minimum_video` = check PASS/FAIL “đủ dài tối thiểu 30s”; `video_duration` = số giây thực tế detect, PASS khi ≤ 3600s.
- `final_result` = AND logic trên mục 1–12; một FAIL → FAIL.
- Pass/Reject toolbar **không** hard-block theo `final_result` hay PHẦN 3 — giữ hành vi QC Review hiện tại.
- `display_ratio` 16:09 trong bảng PO = typo **16:9** (đã chốt).

## 9. Risks

| Rủi ro | Khả năng | Hậu quả nghiệp vụ | Cách phòng |
|--------|----------|-------------------|-----------|
| Reviewer nhầm profile ngưỡng iPhone vs GoPro | thỉnh thoảng | Chấm sai bitrate/format → dữ liệu không đạt delivery | Hiển thị rõ profile trên header + cột ngưỡng cạnh giá trị |
| Schema 18 field thay đổi sau khi Data chốt file 17/7 | hiếm | Rework UI + tài liệu | Version `metadata.schema_version` cho Tapdata |
| Trùng hành vi với QC Queue cũ gây nhầm menu | thỉnh thoảng | Reviewer mở nhầm queue | Tên menu + route riêng, copy rõ "Tapdata" |

## 10. Success Criteria (preliminary)

- Reviewer hoàn tất 1 item Tapdata (xem video + điền PHẦN 3 + Pass/Reject) **không cần rời portal** hoặc tool ngoài.
- 100% 18 field hiển thị đúng nhóm 3 phần trên màn detail.
- Layout 1 video — không regression sang layout 3-cam ScaleAI.

## 11. Open Questions

- [x] OQ-1: `display_ratio` — chốt **16:9** (PO gốc `16:09` = typo).
- [ ] OQ-2: Permission / menu placement / tên hiển thị sidebar chính thức?
- [x] OQ-3: `final_result` chỉ tính mục 1–12; Pass/Reject không hard-block — reviewer quyết định (giữ QC Review hiện tại).

## 12. Next Steps

Sau brainstorm này (sau khi BA approve):

- `/urd tapdata-qc-review` — ✅ đã draft cùng session
- `/wireframe-ascii tapdata-qc-review` — ✅ đã draft cùng session
- `/srs tapdata-qc-review` — chi tiết kỹ thuật API + backend
- `/prd` — thêm row Feature Map nếu có `docs/_product/prd.md`

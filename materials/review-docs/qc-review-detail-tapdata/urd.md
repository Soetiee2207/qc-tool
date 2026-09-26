<!-- doc-meta: type=urd | feature=review/qc-review-detail-tapdata | status=draft | updated=2026-09-25 -->
# **User Requirement** Documentation

Tapdata QC Review — module standalone (1 video preview)

Version 1.3  |  2026-09-25

|  |  |  |  |
| --- | --- | --- | --- |
| **Version**  | **Date**  | **Author**  | **Changes**  |
| 1.3  | 2026-09-25  | @kimi-code  | Đối chiếu code: sidebar 2 tab, Pass/Reject đều về queue, bỏ auto-next |
| 1.0  | 2026-08-27  | Product Owner  | Initial draft từ brainstorm standalone-single-video-qc |
| 1.1  | 2026-08-27  | Product Owner  | Chốt logic final_result (1–12); làm rõ minimum_video/video_duration; sửa typo AC; đồng bộ tên field |
| 1.2  | 2026-08-27  | Product Owner  | Toàn bộ Tapdata Delivery Audit read-only (bỏ editable PHẦN 1 & dropdown PHẦN 3) — giống QC Review egocentric |

**Table of Contents**

1. **INTRODUCTION**

**1.1. Purpose**

- Tài liệu này viết cho PO, dev frontend/backend, QA.
- Phục vụ mục tiêu: baseline nghiệp vụ cho module **Tapdata QC Review** — product line Tapdata trên portal, tách biệt QC Queue egocentric/ScaleAI generic.
- Phạm vi: màn Tapdata QC Queue + màn detail review **1 video** với panel metadata Tapdata (18 field).

**1.2. Scope**

- **IN SCOPE:**
  - Module standalone trong sidebar portal (mô hình **routing/menu riêng** giống ScaleAI Recording Sessions — **không** dùng layout 3-camera ScaleAI QC): route/menu riêng **Tapdata QC**.
  - Tapdata QC Queue — danh sách item chờ review (hành vi list/filter/pagination **giữ nguyên** pattern QC Queue hiện có, chỉ lọc dataset Tapdata).
  - Màn detail: **sidebar trái 2 tab** (Tapdata Delivery Audit mở mặc định + Review History) + **Preview 1 video** — **không** dùng layout 3-camera ScaleAI.
  - Schema metadata 18 field (3 phần) theo 2 delivery profile: `tapdata-iphone-std`, `tapdata-gopro-std`.
  - Toolbar Pass / Reject / Back, playback controls, keyboard shortcuts — **giữ nguyên** hành vi QC Review hiện tại.
- **OUT OF SCOPE:**
  - Layout preview 3 video (ScaleAI multicam) — thuộc feature `scaleai-qc-review`.
  - Annotation / segment editor — thuộc feature `annotation` (face bbox editor **không còn** thuộc luồng annotation từ CR-20260912-001; nằm ở `final_qc` / feature `scaleai-qc-review`).
  - Thay đổi pipeline auto-detect video (ffprobe/ML face-hand) — chỉ định nghĩa **hiển thị và QC manual** trên portal; chi tiết kỹ thuật ở `/srs`.
  - Upload / ingest Tapdata — giả định video đã vào queue từ luồng upload hiện có.
  - Phân quyền chi tiết (PO chưa chốt) — tạm reuse QC Reviewer; chốt sau ở PRD/SRS.
- **Integration boundary:** Đọc metadata auto từ kết quả pipeline nội bộ (face/hand %, video specs); không gọi dịch vụ bên thứ 3 trên màn review.

**1.3. Definitions and Acronyms**

|  |  |
| --- | --- |
| **Term / Acronym**  | **Definition**  |
| **URD** | User Requirement Documentation |
| **Tapdata Delivery Audit** | Panel metadata bên trái màn Tapdata QC detail — 18 field chia 3 phần (Face & Hands, QC Auto, QC Manual) |
| **Delivery profile** | Bộ ngưỡng QC: `tapdata-iphone-std` hoặc `tapdata-gopro-std` — gắn theo project/upload, quyết định cột ngưỡng áp dụng |
| **PHẦN 1 — Face & Hands** | 4 field auto (face/hand visible % + PASS/FAIL); **read-only** trên màn QC Review — giá trị từ pipeline, reviewer không sửa |
| **PHẦN 2 — QC Auto** | 9 field thông số video do hệ thống detect — read-only trên UI |
| **PHẦN 3 — QC Manual** | 5 field PASS/FAIL từ kết quả QC manual upstream — **read-only** trên màn QC Review (reviewer chỉ xem, quyết định qua Pass/Reject toolbar) |
| **final_result** | PASS khi **tất cả** mục 1–12 đạt ngưỡng profile; **FAIL** ngay khi **bất kỳ** mục 1–12 nào không đạt (không gồm PHẦN 3) |

## 2. System Overview

### 2.1 High-Level User Flow

1. QC Reviewer vào menu **Tapdata QC** trong sidebar.
2. Hệ thống hiện **Tapdata QC Queue** — danh sách video Tapdata chờ review.
3. Reviewer chọn 1 item → màn detail: sidebar 2 tab — **Tapdata Delivery Audit** mở mặc định (profile + 18 field) và **Review History**; Preview **1 video**.
4. Reviewer xem video, đối chiếu **toàn bộ metadata read-only** (PHẦN 1–3).
5. Reviewer bấm **Pass** hoặc **Reject** → hệ thống ghi quyết định (Reject: lý do theo rule QC hiện tại) → quay về Tapdata QC Queue.

### 2.2 System User Profile

|  |  |  |  |
| --- | --- | --- | --- |
| **User Role**  | **Description**  | **Permission Level**  | **Key Actions**  |
| QC Reviewer  | Nhân viên review chất lượng video Tapdata  | Truy cập Tapdata QC Queue + detail <!-- TBD: group Keycloak -->  | Xem video, **đọc** metadata audit (read-only), Pass/Reject  |

## 3. User Stories

### 3.1 User Story List

| **US Code** | **US Name** | **US Description** |
| --- | --- | --- |
| US-001 | Xem detail 1 video + Tapdata Delivery Audit | Mở item từ Tapdata QC Queue → sidebar 18 field read-only + preview 1 video + review history |
| US-002 | Metadata sidebar read-only | Toàn bộ 18 field chỉ hiển thị — không input/dropdown chỉnh sửa trên màn QC Review |
| US-003 | Pass / Reject giữ nguyên QC Review | Submit quyết định với toolbar và luồng hiện có (lý do reject); submit xong quay về queue |

### 3.2 User Story Detail

#### 3.2.1 US-001 Xem detail 1 video + Tapdata Delivery Audit

**Story**

**As a** `QC Reviewer` **I want** `xem 1 video Tapdata cùng toàn bộ metadata QC (18 field) trên một màn` **So that** `tôi đánh giá chất lượng bản ghi theo chuẩn iPhone hoặc GoPro mà không cần tool ngoài`

**Acceptance Criteria**

- **AC 1 (Happy path):**
    - **Given** Reviewer mở 1 item từ Tapdata QC Queue,
    - **When** màn detail tải xong,
    - **Then** sidebar trái hiện 2 tab — tab **Tapdata Delivery Audit** mở mặc định với 3 phần (Face & Hands, QC Auto, QC Manual) và **tất cả field read-only**, header hiện **delivery profile** (`tapdata-iphone-std` hoặc `tapdata-gopro-std`); tab thứ hai là **Review History**; Preview hiện **đúng 1 video** — **không** có layout 3-camera ScaleAI.
- **AC 2 (Edge — auto metadata chưa sẵn sàng):**
    - **Given** pipeline chưa trả PHẦN 1–2,
    - **When** Reviewer mở màn detail,
    - **Then** các field auto hiện trạng thái loading/thiếu dữ liệu (không crash); Reviewer vẫn xem được video và bấm Reject; **không** có control chỉnh metadata.

**Business Requirement Table**

|  |  |
| --- | --- |
| **User Story** | US-001 Xem detail 1 video + Tapdata Delivery Audit |
| **Description**  | Màn detail Tapdata: 1 video preview + sidebar metadata 18 field theo profile |
| **Actor**  | QC Reviewer |
| **Pre-Conditions** | Item thuộc Tapdata QC Queue; video playable |
| **Trigger** | Reviewer bấm 1 item trên queue |
| **Post-Conditions** | Màn hiển thị đủ layout: audit sidebar + 1 video + history |
| **Business Rules** | Profile ngưỡng lấy từ project/upload — không chọn tay; **toàn bộ 18 field read-only** trên màn QC Review (giống Delivery Audit egocentric); `final_result` = PASS iff mục 1–12 đều PASS, else FAIL; PHẦN 3 không ảnh hưởng `final_result` |

**Tapdata Delivery Audit — Field Schema (18 field)**

| # | Field | Type | Profile: tapdata-iphone-std | Profile: tapdata-gopro-std | UI | Ghi chú nghiệp vụ |
| --- | --- | --- | --- | --- | --- | --- |
| **PHẦN 1: Face & Hands** | | | | | | |
| 1 | `face_visible_percent` | float (0–100) | ≤ 50% | ≤ 50% | Read-only | % mặt tích lũy — từ pipeline |
| 2 | `face_visible_result` | string PASS/FAIL | PASS khi mục (1) đạt | PASS khi mục (1) đạt | Read-only | Kết quả auto/upstream |
| 3 | `hand_visible_percent` | float (0–100) | > 60% | > 60% | Read-only | % tay tích lũy — từ pipeline |
| 4 | `hand_visible_result` | string PASS/FAIL | PASS khi mục (3) đạt | PASS khi mục (3) đạt | Read-only | Kết quả auto/upstream |
| **PHẦN 2: QC Auto** | | | | | | |
| 5 | `video_resolution` | string | ≥ 1080p | ≥ 1080p | Read-only | Hệ thống detect |
| 6 | `display_ratio` | string | 16:9 (khớp chính xác) | 16:9 (khớp chính xác) | Read-only | PO gốc ghi `16:09` — chuẩn hóa **16:9** |
| 7 | `video_fps` | float | ≥ 29.9 | ≥ 29.9 | Read-only | |
| 8 | `format_name` | string | mp4 hoặc mov | mp4 | Read-only | Giá trị detect phải thuộc tập cho phép |
| 9 | `video_codec` | string | h264 hoặc hevc | h264 hoặc hevc | Read-only | Giá trị detect phải thuộc tập cho phép |
| 10 | `minimum_video` | string PASS/FAIL | PASS khi `video_duration` ≥ 30s | PASS khi `video_duration` ≥ 30s | Read-only | Check độ dài tối thiểu (không phải lưu số 30 — 30 là ngưỡng) |
| 11 | `video_duration` | float (giây) | ≤ 3600 | ≤ 3600 | Read-only | Độ dài thực tế do hệ thống detect; PASS khi ≤ 3600s |
| 12 | `video_bitrate_kpbs` | number (Mbps) | ≥ 8 | ≥ 25 | Read-only | Tên field giữ theo PO (`kpbs`); đơn vị hiển thị **Mbps** |
| 13 | `final_result` | string PASS/FAIL | PASS khi mục 1–12 đều PASS | PASS khi mục 1–12 đều PASS | Read-only | **FAIL** nếu bất kỳ mục 1–12 nào FAIL; không gồm PHẦN 3 |
| **PHẦN 3: QC Manual** | | | | | | |
| 14 | `pov` | string PASS/FAIL | PASS: góc nhìn thứ nhất đúng | PASS: góc nhìn thứ nhất đúng | Read-only | Từ kết quả QC manual upstream |
| 15 | `hands_with_task` | string PASS/FAIL | PASS: tay hiện diện và có thao tác | PASS: tay hiện diện và có thao tác | Read-only | |
| 16 | `hands_out_screen` | string PASS/FAIL | PASS: tay không ra rìa | PASS: tay không ra rìa | Read-only | |
| 17 | `task_description_map` | string PASS/FAIL | PASS: hành động khớp mô tả task Tapdata | PASS: hành động khớp mô tả task Tapdata | Read-only | |
| 18 | `task_noisy` | string PASS/FAIL | PASS: không có hành động vô nghĩa | PASS: không có hành động vô nghĩa | Read-only | |

*Bảng này là nguồn schema chính thức — wireframe trích dẫn lại, không định nghĩa riêng.*

**UI/UX**

- Wireframe: [[docs/review/qc-review-detail-tapdata/ascii-screen/tapdata-qc-review-detail.md|US-001 Tapdata QC Review detail — wireframe]]

#### 3.2.2 US-002 Metadata sidebar read-only

**Story**

**As a** `QC Reviewer` **I want** `xem toàn bộ metadata Tapdata mà không chỉnh sửa trên màn QC Review` **So that** `tôi tập trung xem video và quyết định Pass/Reject — giống Delivery Audit egocentric hiện tại`

**Acceptance Criteria**

- **AC 1 (Happy path):**
    - **Given** Reviewer mở màn detail Tapdata QC (item chưa hoặc đã quyết định),
    - **When** Reviewer tương tác với sidebar Tapdata Delivery Audit,
    - **Then** **không** có text input, number input, hay dropdown PASS/FAIL — mọi field PHẦN 1–3 chỉ hiển thị giá trị + highlight PASS/FAIL theo ngưỡng (nếu có).
- **AC 2 (Edge — thiếu giá trị PHẦN 3):**
    - **Given** upstream chưa cung cấp kết quả QC manual (mục 14–18),
    - **When** Reviewer mở màn detail,
    - **Then** field hiện trạng thái thiếu/chưa có (vd "—" hoặc "Chưa có") — **không** cho nhập tay trên màn này.

**Business Requirement Table**

|  |  |
| --- | --- |
| **User Story** | US-002 Metadata sidebar read-only |
| **Description**  | Cấm chỉnh sửa metadata trên màn QC Review — display-only cho 18 field |
| **Actor**  | QC Reviewer |
| **Pre-Conditions** | Đang ở màn Tapdata QC detail |
| **Trigger** | Màn detail load / reviewer scroll sidebar |
| **Post-Conditions** | Không có thay đổi metadata từ UI reviewer |
| **Business Rules** | Giống `MetadataSidecarPanel` egocentric — read-only; quyết định cuối chỉ qua Pass/Reject toolbar; chỉnh metadata (nếu có) thuộc luồng upstream khác, ngoài phạm vi màn này |

**UI/UX**

> *Leave it empty* — cùng wireframe US-001

#### 3.2.3 US-003 Pass / Reject giữ nguyên QC Review

**Story**

**As a** `QC Reviewer` **I want** `Pass hoặc Reject bằng toolbar quen thuộc` **So that** `tôi không phải học luồng mới khi chuyển sang Tapdata`

**Acceptance Criteria**

- **AC 1 (Happy path):**
    - **Given** Reviewer hoàn tất xem video và metadata,
    - **When** Reviewer bấm Pass,
    - **Then** hệ thống ghi `passed`, lưu snapshot metadata read-only hiện tại (gồm PHẦN 1–3), rồi quay về Tapdata QC Queue.
- **AC 2 (Reject):**
    - **Given** Reviewer bấm Reject,
    - **When** chưa nhập lý do (nếu rule QC hiện tại bắt buộc),
    - **Then** hiện dialog lý do — hành vi **giữ nguyên** QC Review egocentric hiện có.

**Business Requirement Table**

|  |  |
| --- | --- |
| **User Story** | US-003 Pass / Reject giữ nguyên QC Review |
| **Description**  | Toolbar và luồng submit không đổi so với QC Review |
| **Actor**  | QC Reviewer |
| **Pre-Conditions** | Item playable |
| **Trigger** | Pass / Reject trên toolbar |
| **Post-Conditions** | Trạng thái item cập nhật; session review ghi vào Review History |
| **Business Rules** | `final_result` chỉ phản ánh mục 1–12; **Pass/Reject** là quyết định reviewer (giữ hành vi QC Review hiện tại — không hard-block Pass khi `final_result` = FAIL hoặc PHẦN 3 có FAIL; reviewer tự Reject khi cần) |

**UI/UX**

> *Leave it empty*

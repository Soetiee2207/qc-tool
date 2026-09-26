<!-- doc-meta: type=srs | feature=review/qc-review-detail-tapdata | status=draft | updated=2026-09-25 -->
# **SOFTWARE REQUIREMENTS SPECIFICATION**

Tapdata QC Review — module standalone (1 video preview)

Version 1.1 | 2026-09-25

|  |  |  |  |
| --- | --- | --- | --- |
| **Version** | **Date** | **Author** | **Changes** |
| 1.1 | 2026-09-25 | @kimi-code | Đối chiếu code: sidebar 2 tab, Pass/Reject đều về queue, bỏ auto-next |
| 1.0 | 2026-09-03 | @cursor-agent | Initial draft — kế thừa `urd.md`, brainstorm `standalone-single-video-qc`, wireframe `ascii-screen/` |

**Table of Contents**

1. **INTRODUCTION**

**1.1. Purpose**

- Tài liệu đặc tả kỹ thuật cho module **Tapdata QC Review** trên portal: queue lọc product line Tapdata, màn detail 1 video với **Tapdata Delivery Audit** (18 field read-only), Pass/Reject.
- Đối tượng: dev frontend/backend, tech lead, QA.
- Kế thừa nghiệp vụ từ `docs/review/qc-review-detail-tapdata/urd.md`.

**1.2. Scope**

- **IN SCOPE:**
  - Tapdata QC Queue: `GET /api/v1/qc/queue?product_line=tapdata` — chỉ item thuộc project Tapdata (`collection_spec.qc.ui_profile = "tapdata_single"` hoặc `pipeline.profile_id = "tapdata-v1"`).
  - Màn detail: reuse `MetadataQcReviewLayout` — sidebar 2 tab `ReviewSidebarTabs` (tab **Tapdata Delivery Audit** + tab **Review History**) + `StereoVideoView` (1 eye, no toggle) + footer "Segment hiện tại". **Không** `ScaleAiMulticamVideoView`.
  - Nhận diện Tapdata: `isTapdataQcReview(review)` khi `qc_ui_profile === "tapdata_single"` (hoặc `mode === "tapdata_qc"`).
  - Backend build sidecar: `build_tapdata_v1_delivery_audit_sidecar()` — 18 field, 3 section, profile `tapdata-iphone-std` | `tapdata-gopro-std`, tính `final_result` (mục 1–12).
  - Toàn bộ field read-only trên UI (`MetadataSidecarPanel` — không input/dropdown).
  - Playback: `useAnonymizedPlayback` → `GET /playback` variant `anonymized`, view `left`.
  - Submit: `POST /api/v1/qc/queue/{item_id}/submit` — Pass/Reject giữ hành vi QC hiện tại (không hard-block theo `final_result`).
  - Route alias: `/tapdata/qc/review/:id` → redirect `/qc/review/:id` (giữ `location.state` cho chip "+N trong hàng đợi" và đường quay về queue).
- **OUT OF SCOPE:**
  - Layout 3-camera ScaleAI multicam — feature `qc-review-detail-scaleai-3cam`.
  - Chỉnh sửa metadata trên màn QC Review (PHẦN 1–3 read-only).
  - Pipeline auto-detect face/hand/ffprobe — chỉ **consume** kết quả từ bronze mirror / ingest metadata.
  - Upload/ingest Tapdata.
  - Phân quyền Keycloak riêng (TBD URD) — tạm reuse `qc:review:perform`, `qc:queue`.
- **Integration boundary:** Đọc dữ liệu từ `BronzeEgocentricMirror.row_json`, `IngestJob.media_metadata`, `QcQueueItem.metadata_json` — không gọi API bên thứ 3 trên màn review.

**TBD (routing):** Route `/tapdata/qc/queue` hiện redirect `/qc/queue` (mode `final_qc`, `product_line=all`). Target SRS: route riêng mount `QCQueue mode="tapdata_qc"` để lọc `product_line=tapdata` — xem F-01.

**1.3. Definitions and Acronyms**

|  |  |
| --- | --- |
| **Term / Acronym** | **Definition** |
| **SRS / FR / NFR** | Software / Functional / Non-Functional Requirements |
| **Tapdata Delivery Audit** | `metadata_sidecar` 18 field — PHẦN 1 Face & Hands, PHẦN 2 QC Auto, PHẦN 3 QC Manual |
| **Delivery profile** | `tapdata-iphone-std` (bitrate ≥8 Mbps, format mp4/mov) hoặc `tapdata-gopro-std` (≥25 Mbps, mp4 only) |
| **final_result** | PASS iff mục auto 1–12 đều PASS; FAIL nếu bất kỳ FAIL; PHẦN 3 không tính |
| **product_line** | Query filter queue: `tapdata` \| `default` \| `all` |
| **tapdata_single** | `qc.ui_profile` value kích hoạt Tapdata QC UI |

## 2. System Overview

**2.1. High-Level Architecture**

```
[Sidebar nav] Tapdata QC (TBD dedicated route)
    → QCQueue mode=tapdata_qc
    → GET /qc/queue?product_line=tapdata

[Detail] /qc/review/:id (or /tapdata/qc/review/:id redirect)
    → QCReviewDetail mode=final_qc
    → MetadataQcReviewLayout
        ├── isTapdataQcReview(review) → title tapdata_delivery_audit_title
        ├── ReviewSidebarTabs (2 tab)
        │   ├── Tab audit → MetadataSidecarPanel ← metadata_sidecar (build_tapdata_v1_delivery_audit_sidecar)
        │   ├── Tab history → ReviewHistoryPanel variant=sidebar
        │   └── Footer → QcCurrentSegmentPanel (segment hiện tại)
        ├── StereoVideoView showViewToggle=false
        │   └── useAnonymizedPlayback → GET /playback anonymized left

Backend metadata_sidecar.py
    → tapdata_v1_delivery_audit_for_project(project)
    → build_tapdata_v1_delivery_audit_sidecar()
        → infer_tapdata_delivery_profile()
        → _extract_audit_values() + _format_display() thresholds
```

**Stack:** React 18 + TanStack Query 5 + FastAPI + PostgreSQL + Keycloak JWT.

**Wireframe:** [[docs/review/qc-review-detail-tapdata/ascii-screen/tapdata-qc-review-detail.md|Tapdata QC Review detail]]

**2.2. System User Profile**

|  |  |  |  |
| --- | --- | --- | --- |
| **User Role** | **Description** | **Permission Level** | **Key Actions** |
| QC Reviewer | Review chất lượng video Tapdata | `qc:queue`, `qc:review:perform` | Xem queue Tapdata, xem detail, Pass/Reject |
| QC Lead | Xem toàn bộ review sessions | `qc:assign` (optional) | History không filter theo reviewer |
| System (Backend) | Tính audit field + final_result | Internal | `tapdata_delivery_audit.py` |

## 3. Functional Requirements

### 3.1 Function List

|  |  |  |
| --- | --- | --- |
| **ID** | **Function Name** | **Description (technical)** |
| F-01 | List Tapdata QC queue | `GET /qc/queue` với `product_line=tapdata` — chỉ project `tapdata_single` / `tapdata-v1`. |
| F-02 | Load Tapdata review detail | Fetch item + review + sessions; set `qc_ui_profile=tapdata_single`; **không** multicam layout. |
| F-03 | Build & display Tapdata Delivery Audit | Backend `build_tapdata_v1_delivery_audit_sidecar` → FE `MetadataSidecarPanel` read-only 18 field + PASS/FAIL highlight. |
| F-04 | Single-video playback | `StereoVideoView` 1 camera + `useAnonymizedPlayback`; sidebar 2 tab dùng chung với mọi item review. |
| F-05 | Submit Pass / Reject | `POST /submit` — không validate `final_result` server-side trước Pass. |

**Traceability:**

| URD | Functions |
| --- | --- |
| US-001 Detail 1 video + audit | F-01, F-02, F-03, F-04 |
| US-002 Metadata read-only | F-03 |
| US-003 Pass/Reject | F-05 |

### 3.2 Function Detail

**3.2.1. F-01 List Tapdata QC queue**

#### A. Flow

> *(Đề xuất: Activity Diagram — reviewer mở Tapdata QC menu → queue filtered.)*

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | QC Reviewer | Mở Tapdata QC Queue (target route: `QCQueue mode="tapdata_qc"`). |
| 2 | System (Frontend) | Gọi `useQcQueue({ productLine: "tapdata", ...filters })`. |
| 3 | System (Backend) | `_apply_product_line_filter(stmt, "tapdata")` — `project_id IN` tapdata projects (`tapdata_shows_in_review_queue`). |
| 4 | System (Frontend) | Render bảng queue; click item → `navigate(/qc/review/{id})`. |

#### B. API Specification

**Endpoint**: `GET /api/v1/qc/queue`
**Method**: GET
**Description**: Danh sách item QC thuộc product line Tapdata.

**Request**

| **No** | **Field** | **Data type** | **Default** | **Mandatory** | **Description** |
| --- | --- | --- | --- | --- | --- |
| **Header** | | | | | |
| 1 | `Authorization` | string | — | Yes | Bearer JWT. |
| **Query** | | | | | |
| 2 | `product_line` | string | — | Yes (Tapdata) | Giá trị `tapdata` cho queue Tapdata. |
| 3 | `page` | integer | `1` | No | Pagination. |
| 4 | `limit` | integer | `20` | No | Page size. |
| 5 | `project_id` | string | — | No | Filter project. |
| 6 | `status` | string | — | No | pending/passed/rejected. |
| 7 | `q` | string | — | No | Search filename. |

**Response**

| **No** | **Field** | **Data type** | **Description** |
| --- | --- | --- | --- |
| 1 | `data[]` | array | `QcQueueItemOut` — id, filename, project, status, duration, stereo_review, … |
| 2 | `pagination.page` | integer | Trang hiện tại. |
| 3 | `pagination.total` | integer | Tổng item. |
| 4 | `error.detail` | string | 403 nếu thiếu `qc:queue`. |

---

**3.2.2. F-02 Load Tapdata review detail**

#### A. Flow

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | QC Reviewer | Mở `/qc/review/{itemId}` (item Tapdata). |
| 2 | System (Frontend) | `useQcQueueItem(itemId, { multicamSource: "auto" })`. |
| 3 | System (Backend) | `get_review_detail` → `_attach_project_qc_spec` set `qc_ui_profile` từ `collection_spec.qc.ui_profile`. |
| 4 | System (Frontend) | `isTapdataQcReview(review)` → true; `isScaleAiMulticamReview` → **false** (mutually exclusive profile). |
| 5 | System (Frontend) | Chọn layout legacy (F-04), title sidecar `tapdata_delivery_audit_title`. |

#### B. API Specification

**Endpoint**: `GET /api/v1/qc/queue/{item_id}/review`
**Method**: GET

**Response** (fields Tapdata)

| **No** | **Field** | **Data type** | **Description** |
| --- | --- | --- | --- |
| 1 | `qc_ui_profile` | string | `"tapdata_single"`. |
| 2 | `scaleai_multicam_review` | boolean | `false` cho Tapdata. |
| 3 | `stereo_review` | boolean | Thường `false` (single video). |
| 4 | `metadata_sidecar` | object | 3 sections từ `build_tapdata_v1_delivery_audit_sidecar`. |
| 5 | `metadata_sidecar.sections[].source` | string | `"Tapdata iPhone"` hoặc `"Tapdata GoPro"` (profile label). |
| 6 | `review_sessions` | array | Lịch sử review. |

**Endpoint**: `GET /api/v1/qc/queue/{item_id}/review-sessions` — same as ScaleAI SRS.

---

**3.2.3. F-03 Build & display Tapdata Delivery Audit**

#### A. Flow

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | System (Backend) | `build_metadata_sidecar` detect `tapdata_v1_delivery_audit_for_project(project)`. |
| 2 | System (Backend) | Load bronze row `BronzeEgocentricMirror` by `uuidv7`; merge ingest `media_metadata`. |
| 3 | System (Backend) | `infer_tapdata_delivery_profile()` — explicit meta → `.mov`/iPhone → `tapdata-iphone-std`; gopro hint → `tapdata-gopro-std`; else project default. |
| 4 | System (Backend) | `_extract_audit_values()` — tính %, thresholds, `final_result` (AND mục 1–12 có giá trị). |
| 5 | System (Backend) | Emit `QcMetadataSidecarOut` — sections `face_hands`, `qc_auto`, `qc_manual`; field `invalid=true` khi FAIL; `missing=true` khi null → display `"—"`. |
| 6 | System (Frontend) | `MetadataSidecarPanel` render sections/fields — **không** editable; highlight đỏ/amber cho missing/invalid. |
| 7 | QC Reviewer | Đọc PHẦN 1–3; không có control chỉnh sửa (US-002). |

**18 field keys (backend `_FIELD_LABELS`):**

`face_visible_percent`, `face_visible_result`, `hand_visible_percent`, `hand_visible_result`, `video_resolution`, `display_ratio`, `video_fps`, `format_name`, `video_codec`, `minimum_video`, `video_duration`, `video_bitrate_kpbs`, `final_result`, `pov`, `hands_with_task`, `hands_out_screen`, `task_description_map`, `task_noisy`.

**Thresholds (backend `_THRESHOLDS`):**

| Field | tapdata-iphone-std | tapdata-gopro-std |
| --- | --- | --- |
| face_visible_percent | ≤ 50% | ≤ 50% |
| hand_visible_percent | > 60% | > 60% |
| video_resolution | ≥ 1080p | ≥ 1080p |
| display_ratio | 16:9 | 16:9 |
| video_fps | ≥ 29.9 | ≥ 29.9 |
| format_name | mp4, mov | mp4 |
| video_codec | h264, hevc | h264, hevc |
| video_duration min (minimum_video) | ≥ 30s | ≥ 30s |
| video_duration max | ≤ 3600s | ≤ 3600s |
| video_bitrate_kpbs | ≥ 8 Mbps | ≥ 25 Mbps |

#### B. API Specification

**Không có API riêng** — sidecar embedded trong `GET .../review` response (`metadata_sidecar`).

**Sidecar field shape (`QcMetadataFieldOut`):**

| **No** | **Field** | **Data type** | **Description** |
| --- | --- | --- | --- |
| 1 | `key` | string | Field id (vd `face_visible_percent`). |
| 2 | `label` | string | Display label. |
| 3 | `value` | string | Formatted display (vd `42.3% (≤50%)`, `12.0 Mbps (≥8)`). |
| 4 | `missing` | boolean | `true` → UI `"—"` / thiếu dữ liệu. |
| 5 | `invalid` | boolean | `true` → FAIL / không đạt ngưỡng — highlight amber/red. |
| 6 | `required` | boolean | `false` cho Tapdata (không đếm missing_required). |
| 7 | `source` | string | `"tapdata"`. |

---

**3.2.4. F-04 Single-video playback**

#### A. Flow

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | System (Frontend) | `!isScaleAiMulticamReview` → `useAnonymizedPlayback(itemId, stereoReview=false)`. |
| 2 | System (Frontend) | `StereoVideoView` với `showViewToggle={false}` — single left eye. |
| 3 | System (Frontend) | `ReviewHistoryPanel` render trong tab thứ hai của `ReviewSidebarTabs` (`variant="sidebar"`) — không còn khối dưới preview. |
| 4 | QC Reviewer | Play/pause/seek; shortcuts Space/←/→/P/R giữ nguyên. |

#### B. API Specification

**Endpoint**: `GET /api/v1/qc/queue/{item_id}/playback`
**Method**: GET

**Request**

| **No** | **Field** | **Data type** | **Default** | **Mandatory** | **Description** |
| --- | --- | --- | --- | --- | --- |
| 1 | `Authorization` | header | — | Yes | Bearer JWT. |
| 2 | `variant` | query | `anonymized` | No | FE `useAnonymizedPlayback` primary. |
| 3 | `format` | query | `mp4` | No | `mp4` hoặc `hls`. |
| 4 | `view` | query | `left` | No | Single video — `left` only. |

**Response:** `QcPlaybackOut` — `url`, `expires_at`, `format`, `view`, `fallback_url`, `hls_status`.

---

**3.2.5. F-05 Submit Pass / Reject**

#### A. Flow

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | QC Reviewer | Bấm Pass hoặc Reject trên `MetadataQcReviewToolbar`. |
| 2 | System (Frontend) | Pass → `submitReview({ decision: "pass" })`; Reject → dialog reason → `{ decision: "reject", reason, comment? }`. |
| 3 | System (Backend) | `POST /submit` cập nhật item status; ghi review session. |
| 4 | System (Frontend) | Toast success; cả Pass và Reject đều gọi `navigateToQueue()` → quay về queue (`listPath` + `returnSearch`). |
| 5 | System | **Không** block Pass khi `final_result=FAIL` hoặc PHẦN 3 có FAIL (business rule URD). |

#### B. API Specification

**Endpoint**: `POST /api/v1/qc/queue/{item_id}/submit`
**Method**: POST

**Request**

| **No** | **Field** | **Data type** | **Mandatory** | **Description** |
| --- | --- | --- | --- | --- |
| **Header** | | | | |
| 1 | `Authorization` | string | Yes | Bearer JWT. |
| **Body** | | | | |
| 2 | `decision` | string | Yes | `"pass"` \| `"reject"`. |
| 3 | `reason` | string | No | Reject reason code (bắt buộc theo UI dialog nếu reject). |
| 4 | `comment` | string | No | Ghi chú reject. |
| 5 | `validation_actuals` | object | No | Không dùng Tapdata metadata QC (empty). |
| 6 | `export_target_ids` | array | No | Không dùng Tapdata detail layout. |

**Response** (`QcReviewSubmitResponse`)

| **No** | **Field** | **Data type** | **Description** |
| --- | --- | --- | --- |
| 1 | `id` | string | Queue item id. |
| 2 | `status` | string | `passed` \| `rejected`. |
| 3 | `decision` | string | `pass` \| `reject`. |
| 4 | `error.detail` | string | Lỗi validation / 404. |

## 4. Non-Functional Requirements

**4.1. Performance**

- Queue list p95 < 800ms cho 20 items/page.
- Review detail + sidecar build p95 < 1.5s (bao gồm bronze mirror read).
- Single playback URL p95 < 1s.
- Sidecar render 18 field — không lag scroll sidebar (60fps).

**4.2. Availability & Reliability**

- Kế thừa portal SLA ≥ 99.5%/tháng.
- Bronze row thiếu → sidecar field `missing=true`, màn vẫn load (US-001 AC2).
- Playback fail → error state + retry button (`qc_retry_playback`).

**4.3. Security**

- Auth: Keycloak JWT; permissions `qc:queue`, `qc:review:perform`.
- `product_line=tapdata` filter server-side — không expose non-tapdata items qua filter.
- Playback presigned URL — không persist full URL client analytics.

**4.4. Scalability**

- Không áp dụng riêng — reuse QC service scale.
- Target ≤ 30 concurrent Tapdata reviewers.

**4.5. Maintainability**

- Unit tests: `tapdataQc.test.ts`, `test_tapdata_delivery_audit.py` (final_result, gopro bitrate, project detection).
- Backend thresholds tập trung `_THRESHOLDS` — đổi profile không sửa FE.
- Profile ids: `TAPDATA_IPHONE_PROFILE`, `TAPDATA_GOPRO_PROFILE` trong `projects/tapdata.py`.

**4.6. Usability & Accessibility**

- Desktop ≥ 1024px; layout giống egocentric QC.
- i18n: `tapdata_delivery_audit_title`, `nav_tapdata_qc_queue`.
- Field FAIL: `invalid` styling (amber) — P1 wireframe threshold hint trong `value` string.

**4.7. Compliance**

- Không áp dụng quy định riêng — nội bộ QC video.

**NFR Summary Table**

|  |  |  |  |
| --- | --- | --- | --- |
| **ID** | **Requirement** | **Metric / Target** | **Priority** |
| NFR-P-01 | Queue list response | p95 < 800ms | High |
| NFR-P-02 | Review detail + sidecar | p95 < 1.5s | High |
| NFR-P-03 | Playback URL | p95 < 1s | High |
| NFR-A-01 | Portal uptime | ≥ 99.5% / month | Medium |
| NFR-SEC-01 | Tapdata queue isolation | 100% items from tapdata projects when `product_line=tapdata` | High |
| NFR-M-01 | Tapdata audit unit tests | `test_tapdata_delivery_audit.py` pass | High |
| NFR-U-01 | Read-only audit UI | 0 editable controls on 18 fields | High |
| NFR-U-02 | Viewport | Desktop ≥ 1024px | Medium |

<!-- doc-meta: type=srs | feature=review/qc-review-detail-scaleai-3cam | status=draft | updated=2026-09-25 -->
# **SOFTWARE REQUIREMENTS SPECIFICATION**

Bố cục lại màn QC Review detail cho preview 3-video (ScaleAI multicam)

Version 1.3 | 2026-09-25

|  |  |  |  |
| --- | --- | --- | --- |
| **Version** | **Date** | **Author** | **Changes** |
| 1.3 | 2026-09-25 | @kimi-code | Sidebar 2 tab cho mọi item; bỏ tên MetadataQcSidebarTabs và SegmentSummaryCard |
| 1.2 | 2026-09-11 | @binhhm | Đối chiếu code: bổ sung toolbar thật (back icon, filename, project link, status chip, `+N trong hàng đợi`, toggle sidebar/dark/help, nút Reject/Pass), header panel Delivery Audit (đếm trường thiếu + nút hướng dẫn), section `Delivery audit` / source `ScaleAI v1 template`, toggle "Xoay 2 cam cổ tay 180°", badge `mock` khi bật instant-QC dev |
| 1.1 | 2026-09-03 | @cursor-agent | Đối chiếu source code: phạm vi `final_qc` only, sidebar collapse, SegmentSummaryCard, reject hint shipped, breakpoint `xl` |
| 1.0 | 2026-09-03 | @cursor-agent | Initial draft — kế thừa `urd.md`, brainstorm `review-detail-3cam-layout`, wireframe `ascii-screen/` |

**Table of Contents**

1. **INTRODUCTION**

**1.1. Purpose**

- Tài liệu này viết cho **dev frontend**, **tech lead**, **QA** — đặc tả kỹ thuật cho việc redesign layout màn QC Review detail khi item thuộc loại ScaleAI multicam (3 camera).
- Phục vụ mục tiêu: baseline implementation contract (component tree, layout branching, API đã có sẵn cần consume, NFR đo được) và nguồn test case cho UAT 2 biến thể layout (multicam vs stereo/single).
- Phạm vi áp dụng: sprint redesign layout QC detail ScaleAI multicam; kế thừa nghiệp vụ từ `docs/review/qc-review-detail-scaleai-3cam/urd.md`.

**1.2. Scope**

- **IN SCOPE:**
  - Frontend branching trong `MetadataQcReviewLayout` với **`mode="final_qc"`** (route `/qc/review/:id`): sidebar trái **luôn** dùng `ReviewSidebarTabs` (2 tab: Delivery Audit, Review History) cho mọi item; khi `isScaleAiMulticamReview(review)` → `scaleai_multicam_review === true` HOẶC `qc_ui_profile === "multicam_triple"` → Preview dùng `ScaleAiMulticamVideoView` bố cục tam giác, **không** render `ReviewHistoryPanel` dưới Preview.
  - Tab Delivery Audit mở mặc định (`sidebarTab = "audit"`), reset về `"audit"` mỗi khi `id` đổi (`useEffect` on `id`).
  - Chuyển tab sidebar không remount `ScaleAiMulticamVideoView` (component nằm ngoài `Tabs.Content`); Radix `Tabs.Content` dùng `data-[state=inactive]:hidden` — giữ playhead/play state.
  - Nút collapse sidebar (`studio.metadataCollapsed` từ `loadQcStudioPrefs`) ẩn **toàn bộ** sidebar (cả tabs) — không collapse riêng từng tab.
  - Thông tin segment hiện tại nằm trong footer cố định của sidebar (`QcCurrentSegmentPanel`, testid `qc-current-segment-panel`), hiện khi item là segment queue item / có `segmentId` / bật `segmentPlayback` — `SegmentSummaryCard` **không còn được render** ở màn này.
  - Toolbar (`MetadataQcReviewToolbar`, cao 48px, 1 hàng): icon Back → filename (mono) → `ProjectLink` (ẩn < `lg`) → `StatusChip` (`in_review` khi đang chấm) → `+{n} trong hàng đợi` → toggle ẩn/hiện sidebar (`md+`) → toggle dark mode (`md+`) → nút Help → nút **Reject** (mở `RejectDialog` chọn lý do + ghi chú) và **Pass** (mở `SimplePassDialog` xác nhận).
  - Preview multicam (`ScaleAiMulticamVideoView` với `playbackOnly`): 1 thanh timeline/controls **chung** gắn head camera; 2 pane wrist không có toolbar riêng; checkbox **"Xoay 2 cam cổ tay 180°"** mặc định **bật** (`flipWristCameras = true`) để chỉnh hướng hiển thị 2 cam cổ tay.
  - Dấu hiệu reject trên tab History: dot đỏ `metadata-qc-sidebar-history-reject-hint` khi `hasPriorRejectInSessions()` — **đã implement**.
  - Panel Delivery Audit (`MetadataSidecarPanel embedded`): header hiện tiêu đề `qc_delivery_audit_title` = "Audit bàn giao" + dòng đếm `qc_delivery_audit_missing_count` ("Thiếu {missing}/{total} trường bắt buộc") hoặc `qc_delivery_audit_complete` và nút info mở popover hướng dẫn; body render section `Delivery audit` (source `ScaleAI v1 template`) rồi 7 field.
  - Dev-only: khi project bật instant QC (`scaleai_instant_qc_enabled`), field rỗng được sinh giá trị mock và UI gắn badge `mock` (`qc_delivery_audit_mock_badge`) + dòng `qc_delivery_audit_complete_with_mock`.
  - Item stereo/single (không multicam) → cùng sidebar 2 tab `ReviewSidebarTabs`; khác biệt còn lại là vùng Preview dùng `StereoVideoView`/player 1-2 video thay cho `ScaleAiMulticamVideoView`.
  - Consume API: `GET /review`, `GET /review-sessions`, `GET /playback` ×3 (`multicam_source=repack` cho playback hook).
  - Sidebar width `320px` tại Tailwind `xl` (≥1280px); full-width phía trên breakpoint đó.
- **OUT OF SCOPE:**
  - Thay đổi logic Pass/Reject, submit review, reject reason flow.
  - Thay đổi schema Delivery Audit (backend `scaleai_delivery_audit.py` — FE chỉ render `metadata_sidecar`).
  - Đồng bộ nội bộ 3 camera (`useSyncedMulticamVideos`, `multicam_sync_offsets`, `multicamSyncRef`).
  - Responsive/mobile dưới 1024px.
  - **`mode="tapdata_qc"`** và Tapdata Delivery Audit — feature `qc-review-detail-tapdata`.
  - **Annotation QC** (`AnnotationQcReviewLayout`, `QCReviewDetail` legacy path) — dùng `ReviewSidebarTabs` với footer riêng (`annotation-segment-tasks`) và vẫn có `ScaleAiMulticamVideoView` cho multicam.
  - API endpoint mới.
- **Integration boundary:** Không có external system mới. Auth qua Keycloak SSO (`https://auth.datafactory.fit`, realm `vd-dev`, client `vd-portal`). Playback URL từ S3 presign nội bộ qua FastAPI QC service.

**1.3. Definitions and Acronyms**

|  |  |
| --- | --- |
| **Term / Acronym** | **Definition** |
| **SRS** | Software Requirements Specification |
| **FR** | Functional Requirement — yêu cầu chức năng |
| **NFR** | Non-Functional Requirement — yêu cầu phi chức năng |
| **UC** | Use Case |
| **API** | Application Programming Interface |
| **Delivery Audit** | Panel metadata bàn giao (`metadata_sidecar`) — các trường `partner_name`, `collector_id`, `metadata.schema_version`, `activity_tags.*` |
| **Review History** | Danh sách `review_sessions` — ai review, khi nào, kết quả |
| **ScaleAI Multicam** | Project profile `ingest.multicam.profile = "scaleai_v1"` hoặc `qc.ui_profile = "multicam_triple"` — 3 camera: `head`, `left_wrist`, `right_wrist` |
| **Layout variant** | `multicam` (Preview tam giác 3 video) hoặc `legacy` (Preview 1-2 video) — sidebar 2 tab dùng chung cho cả hai |
| **MetadataQcReviewLayout** | React shell màn QC Review detail — feature này chỉ áp dụng nhánh `mode="final_qc"` |
| **QcStudioPrefs** | Local prefs (`metadataCollapsed`, `darkMode`) — persist `qc-studio` localStorage |

## 2. System Overview

**2.1. High-Level Architecture**

Portal QC Review detail là **SPA React 18** (Vite 6, TypeScript 5.6, TanStack Query 5, Tailwind CSS 4, Radix UI Tabs) gọi **FastAPI** backend (`/api/v1/qc/*`) với **Bearer JWT** (Keycloak ID token).

**Component tree (phạm vi feature):**

```
QCReviewDetail mode="final_qc" → MetadataQcReviewLayout
├── MetadataQcReviewToolbar (Back, filename, project, status chip, +N queue,
│   toggle sidebar, dark mode, help, Reject dialog, Pass dialog)
├── useQcQueueItem(itemId, { multicamSource: "auto" })
├── isScaleAiMulticamReview(review)  → layout branch (NOT video count)
├── !studio.metadataCollapsed ?
│   └── ReviewSidebarTabs (xl:w-[320px])   ← mọi item, không phân nhánh
│       ├── Tab audit → MetadataSidecarPanel embedded
│       ├── Tab history → ReviewHistoryPanel variant=sidebar
│       └── Footer → QcCurrentSegmentPanel (segment hiện tại)
├── [multicam] ScaleAiMulticamVideoView playbackOnly
│   ├── 3 panes (head flex-3 / 2 wrist flex-2) + toggle "Xoay 2 cam cổ tay 180°"
│   └── useScaleAiMulticamPlayback(preview, repack) → GET /playback ×3
└── [legacy] StereoVideoView + useAnonymizedPlayback
```

**Entry route:** `GET /qc/review/:id` → `QCReviewDetail mode="final_qc"`.

**Backend flags** (trong `QcReviewDetailOut`, set bởi `review_builder._attach_project_qc_spec`):

- `scaleai_multicam_review: bool` — true khi `qc.ui_profile === "multicam_triple"` HOẶC `ingest.multicam.profile === "scaleai_v1"`.
- `stereo_review: bool` — true khi có `converted_uris.right`.
- `multicam_sync_offsets: { head, left_wrist, right_wrist }` — offset giây cho sync playback.

**Wireframe tham chiếu:**

- [[docs/review/qc-review-detail-scaleai-3cam/ascii-screen/qc-review-detail-3cam-audit.md|Tab Delivery Audit mở]]
- [[docs/review/qc-review-detail-scaleai-3cam/ascii-screen/qc-review-detail-3cam-history.md|Tab Review History mở]]

**2.2. System User Profile**

|  |  |  |  |
| --- | --- | --- | --- |
| **User Role** | **Description** | **Permission Level** | **Key Actions** |
| QC Reviewer | Nhân viên nội bộ thực hiện kiểm tra chất lượng bản ghi trước khi duyệt | `qc:review:perform` (bắt buộc mở màn detail) | Xem Delivery Audit, Preview 3 video, chuyển tab Review History, Pass/Reject |
| QC Lead / Assigner | Reviewer có quyền xem toàn bộ lịch sử review | `qc:assign` (optional) | Xem tất cả `review_sessions` trong tab History (không filter theo `reviewer_id`) |
| System (Frontend) | React app resolve layout variant từ API flags | Internal | Branch component tree, giữ playback state khi đổi tab |

## 3. Functional Requirements

### 3.1 Function List

|  |  |  |
| --- | --- | --- |
| **ID** | **Function Name** | **Description (technical)** |
| F-01 | Resolve layout variant | Đọc `QcReviewDetailOut`, gọi `isScaleAiMulticamReview()` → `"multicam"` hoặc `"legacy"`; mặc định `"legacy"` khi flag không xác định. |
| F-02 | Render multicam detail layout | Mount `ReviewSidebarTabs` (mọi item, tab audit mặc định) + `ScaleAiMulticamVideoView` khi variant = multicam; không render history dưới preview. |
| F-03 | Switch sidebar tab (audit ↔ history) | Radix Tabs đổi `activeTab` local state; Preview subtree không unmount; không refetch playback khi đổi tab. |
| F-04 | Render legacy layout (stereo/single) | Khi variant = legacy: vùng Preview dùng `StereoVideoView` + `useAnonymizedPlayback`; sidebar vẫn là `ReviewSidebarTabs` như mọi item. |

**Traceability (URD → Function):**

| URD | Functions |
| --- | --- |
| US-001 Xem preview 3-video + sidebar tab | F-01, F-02 |
| US-002 Chuyển tab Delivery Audit ↔ Review History | F-03 |
| US-003 Giữ layout cũ cho 1-2 video | F-01 (nhánh legacy), F-04 |

### 3.2 Function Detail

**3.2.1. F-01 Resolve layout variant**

#### A. Flow

> *(Đề xuất: Activity Diagram — rẽ nhánh `isScaleAiMulticamReview` vs legacy. Tham chiếu wireframe `qc-review-detail-3cam-audit.md`.)*

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | QC Reviewer | Navigate tới `/qc/review/{itemId}` từ Final QC Queue. |
| 2 | System (Frontend) | Gọi `useQcQueueItem(itemId, { multicamSource: "auto" })` — fetch queue item + review detail + review sessions. |
| 3 | System (Frontend) | Đọc `review.scaleaiMulticamReview` và `review.qcUiProfile` từ response đã map (`qc-mappers.ts`). |
| 4 | System (Frontend) | `isScaleAiMulticamReview(review)` → `true` nếu `scaleaiMulticamReview === true` HOẶC `qcUiProfile === "multicam_triple"`. |
| 5 | System (Frontend) | `true` → set layout variant `multicam`, chuyển F-02. `false` → set variant `legacy`, chuyển F-04. |
| 6 | System (Frontend) | Edge: API lỗi hoặc review chưa load → hiển thị loading/error shell, **không** assume multicam. |

#### B. API Specification

**Endpoint**: `GET /api/v1/qc/queue/{item_id}/review`
**Method**: GET
**Description**: Load review detail kèm flags layout (`scaleai_multicam_review`, `stereo_review`, `qc_ui_profile`, `metadata_sidecar`, `multicam_sync_offsets`). Nguồn: US-001, US-003.

**Request**

| **No** | **Field** | **Data type** | **Default value** | **Mandatory** | **Description** |
| --- | --- | --- | --- | --- | --- |
| **Header** | | | | | |
| 1 | `Authorization` | string | — | Yes | `Bearer <keycloak_id_token>`. |
| **Path** | | | | | |
| 2 | `item_id` | string (uuid) | — | Yes | QC queue item ID. |
| **Query** | | | | | |
| 3 | `multicam_source` | string | `auto` | No | `auto` \| `conversion` \| `repack` — FE dùng `auto` khi load review. |
| 4 | `include_sessions` | boolean | `false` | No | FE hook có thể gọi endpoint sessions riêng. |
| 5 | `include_versions` | boolean | `false` | No | Không dùng cho layout feature. |

**Response** (fields liên quan layout)

| **No** | **Field** | **Data type** | **Description** |
| --- | --- | --- | --- |
| 1 | `scaleai_multicam_review` | boolean | `true` → layout multicam (F-02). |
| 2 | `qc_ui_profile` | string \| null | `"multicam_triple"` → layout multicam (fallback nếu flag 1 false). |
| 3 | `stereo_review` | boolean | `true` + không multicam → stereo legacy (F-04). |
| 4 | `multicam_sync_offsets` | object | `{ head, left_wrist, right_wrist }` float seconds — pass vào `ScaleAiMulticamVideoView`. |
| 5 | `metadata_sidecar` | object \| null | Delivery Audit sections + `missing_required_count`. |
| 6 | `review_sessions` | array | Review detail không truyền `include_sessions`; hook `useQcQueueItem` luôn gọi `GET .../review-sessions` riêng và merge đè khi có dữ liệu. |
| 7 | `error.detail` | string | `"QC queue item not found"` nếu 404; `"Forbidden"` nếu thiếu `qc:review:perform`. |

**Endpoint bổ sung (review sessions):**

`GET /api/v1/qc/queue/{item_id}/review-sessions` — trả `QcReviewSessionOut[]`. Hook `useQcQueueItem` gọi **endpoint này riêng** (không truyền `include_sessions` vào review detail) rồi merge vào `review.reviewSessions`; FE filter theo `qc:assign` permission trước khi render History tab.

---

**3.2.2. F-02 Render multicam detail layout**

#### A. Flow

> *(Đề xuất: Sequence Diagram — `MetadataQcReviewLayout` → `useScaleAiMulticamPlayback` → 3× `GET /playback`. Wireframe: `qc-review-detail-3cam-audit.md`.)*

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | System (Frontend) | Render `ReviewSidebarTabs` với `activeTab="audit"` (default, reset khi `id` đổi) — dùng cho mọi item, không chỉ multicam. |
| 2 | System (Frontend) | Tab audit: embed `MetadataSidecarPanel` (`embedded`) với `sidecar={review.metadataSidecar}` — header hiện "Audit bàn giao" + dòng đếm trường thiếu/tổng bắt buộc (`qc_delivery_audit_missing_count`) hoặc "Đủ tất cả trường bắt buộc", kèm nút info mở popover hướng dẫn; body render section `Delivery audit` / source `ScaleAI v1 template` rồi 7 field (partner_name, collector_id, metadata.schema_version, activity_tags, ↳ task, ↳ environment, ↳ scene). Field thiếu tô đỏ + nhãn "Thiếu — cần audit"; field sai ngưỡng tô amber + hậu tố "(giá trị không hợp lệ)". **Không** có badge trên nhãn tab. |
| 3 | System (Frontend) | Gọi `useScaleAiMulticamPlayback(itemId, "preview", false, "repack")` — 3 query song song (`view=head|left_wrist|right_wrist`, `format=mp4`). |
| 4 | System (Frontend) | Render `ScaleAiMulticamVideoView` (`playbackOnly`) với `cameras={head,left_wrist,right_wrist}`, bố cục tam giác (head `flex-[3]` trên, 2 wrist `flex-[2]` dưới), `syncOffsets` từ API; thanh controls chung gắn head; checkbox "Xoay 2 cam cổ tay 180°" (mặc định bật). |
| 5 | System (Frontend) | **Không** mount `ReviewHistoryPanel` với `variant="below-preview"`. |
| 6 | QC Reviewer | Xem 3 video đồng bộ; toolbar Pass/Reject/Back giữ nguyên vị trí header; khi seek cần chờ slave bắt kịp → overlay mờ `"Đang đồng bộ…"` (`scaleai_qc_seek_syncing`). |

#### B. API Specification

**Endpoint**: `GET /api/v1/qc/queue/{item_id}/playback` (gọi **3 lần** song song)
**Method**: GET
**Description**: Lấy presigned URL cho từng camera role. Nguồn: US-001.

**Request** (mỗi camera)

| **No** | **Field** | **Data type** | **Default value** | **Mandatory** | **Description** |
| --- | --- | --- | --- | --- | --- |
| **Header** | | | | | |
| 1 | `Authorization` | string | — | Yes | Bearer JWT. |
| **Path** | | | | | |
| 2 | `item_id` | string | — | Yes | Queue item ID. |
| **Query** | | | | | |
| 3 | `variant` | string | `preview` | No | FE multicam preview dùng `preview`. |
| 4 | `format` | string | `mp4` | No | `mp4` hoặc `hls`. |
| 5 | `view` | string | — | Yes | `head` \| `left_wrist` \| `right_wrist` (mỗi request 1 view). |
| 6 | `multicam_source` | string | `repack` | No | FE playback hook dùng `repack` cho preview chất lượng. |

**Response** (`QcPlaybackOut`)

| **No** | **Field** | **Data type** | **Description** |
| --- | --- | --- | --- |
| 1 | `url` | string | Presigned S3 URL hoặc stream proxy URL. |
| 2 | `expires_at` | datetime (ISO 8601) | Hết hạn URL — FE refresh trước expiry. |
| 3 | `variant` | string | `preview`. |
| 4 | `format` | string | `mp4` \| `hls`. |
| 5 | `view` | string | Camera role đã request. |
| 6 | `s3_uri` | string \| null | URI gốc trên object storage (không presign). |
| 7 | `fallback_url` | string \| null | URL dự phòng nếu primary fail. |
| 8 | `hls_status` | string \| null | Trạng thái packaging HLS nếu `format=hls`. |
| 9 | `error.detail` | string | Lỗi 404/403/500 tương ứng. |

**Auth:** `require_any_permission("qc:review:perform", "qc:audit:perform")` — màn audit cũng gọi được playback.

**UI-only (không API riêng):** Bố cục tam giác, sidebar 320px, tab default audit, toggle xoay cam cổ tay — xử lý nội bộ React (`MetadataQcReviewLayout.tsx`, `review/ReviewSidebarTabs.tsx`, `ScaleAiMulticamVideoView.tsx`).

**Delivery Audit field schema (nguồn: `scaleai_delivery_audit._build_scaleai_fields`):**

| Field key | Label hiển thị | Required | Ghi chú |
| --- | --- | --- | --- |
| `partner_name` | `partner_name` | Yes | Mặc định `VinDynamics` (`SCALEAI_V1_DEFAULT_PARTNER`) khi không có nguồn khác |
| `collector_id` | `collector_id` | Yes | |
| `metadata.schema_version` | `metadata.schema_version` | No | Mặc định `v1.0`; **không** tính vào mẫu số required |
| `activity_tags` | `activity_tags` | Yes | Container — UI gắn `*`; **không** được đếm vào `required_count` (chỉ tính missing nếu thiếu con) |
| `activity_tags.task` | `↳ task` | Yes | |
| `activity_tags.environment` | `↳ environment` | Yes | Chỉ nhận 1 trong 6 giá trị `SCALEAI_V1_ENVIRONMENTS`; ngoài tập → `invalid=true` (khác `missing`) |
| `activity_tags.scene` | `↳ scene` | Yes | |

`required_count` thực tế = **5** (partner_name, collector_id, ↳ task, ↳ environment, ↳ scene); `activity_tags` và `metadata.schema_version` không tính. Field lấy từ nhiều nguồn (`sidecar`, portal submission, bronze, VLM row, catalog, gateway session/upload, multicam rig) — field `source` trong response ghi nguồn thắng.

---

**3.2.3. F-03 Switch sidebar tab (audit ↔ history)**

#### A. Flow

> *(Đề xuất: Activity Diagram — tab switch với điều kiện giữ Preview mounted. Wireframe: `qc-review-detail-3cam-history.md`.)*

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | QC Reviewer | Đang xem item multicam; tab audit hoặc history đang active. |
| 2 | QC Reviewer | Click tab còn lại trên `Tabs.List` (Radix). |
| 3 | System (Frontend) | `onTabChange` cập nhật `activeTab` state (`"audit"` \| `"history"`). |
| 4 | System (Frontend) | Re-render nội dung sidebar: audit → `MetadataSidecarPanel`; history → `ReviewHistoryPanel` variant `sidebar`. |
| 5 | System (Frontend) | Preview subtree (`ScaleAiMulticamVideoView`) **không** unmount — `playheadPct`, playing state, seek position giữ nguyên. |
| 6 | System (Frontend) | Edge: click tab đang active → Radix no-op, không refetch API, không scroll jump. |
| 7 | System (Frontend) | Tab history hiển thị dot đỏ (`metadata-qc-sidebar-history-reject-hint`) nếu `hasPriorRejectInSessions(sessions)` — không badge số trên nhãn tab. |

#### B. API Specification

**Không có API — xử lý nội bộ.** Dữ liệu `review_sessions` và `metadata_sidecar` đã load ở F-01; chuyển tab chỉ đổi panel hiển thị trong sidebar, không gọi endpoint mới.

---

**3.2.4. F-04 Render legacy layout (stereo/single)**

#### A. Flow

> *(Đề xuất: Activity Diagram — nhánh legacy khi `!isScaleAiMulticamReview(review)`.)*

**Description**

| **Step** | **Actor** | **Description** |
| --- | --- | --- |
| 1 | System (Frontend) | F-01 trả variant `legacy` (`scaleai_multicam_review === false` và `qc_ui_profile !== "multicam_triple"`). |
| 2 | System (Frontend) | Sidebar giống mọi item: `ReviewSidebarTabs` (tab audit + history) — nhánh legacy chỉ khác vùng Preview. |
| 3 | System (Frontend) | `effectiveStereoReview = stereoReview && !scaleaiMulticamReview` → `StereoVideoView` (left/right toggle) hoặc single-eye (no toggle). |
| 4 | System (Frontend) | `useAnonymizedPlayback` — 1-2 call `GET /playback` với `view=left|right`, `variant=anonymized`. |
| 5 | System (Frontend) | History nằm trong tab của sidebar (`variant="sidebar"`), không còn khối dưới khung video. |
| 6 | QC Reviewer | Trải nghiệm giống hệt pre-redesign — US-003 AC1. |
| 7 | System (Frontend) | Edge: không xác định được loại video → default legacy (US-003 AC2). |

#### B. API Specification

**Endpoint**: `GET /api/v1/qc/queue/{item_id}/playback`
**Method**: GET
**Description**: Legacy stereo/single — 1-2 request với `view=left` và/hoặc `view=right`, `variant=anonymized` (fallback `preview`). Cùng schema response như F-02.

**Không có API mới** — branching UI-only dựa trên flags từ F-01.

## 4. Non-Functional Requirements

**4.1. Performance Requirements**

- Layout branch decision (F-01) phải hoàn tất trong cùng React render cycle sau khi `review` query `isSuccess` — không thêm round-trip API.
- Tab switch (F-03): thời gian đổi nội dung sidebar **< 50ms** (p95) trên desktop — đo bằng React Profiler, không refetch playback.
- Multicam playback: 3 request `GET /playback` chạy **song song** (Promise.all); tổng thời gian chờ URL **< 2s** (p95) khi backend healthy.
- Không gây layout shift > 100px khi chuyển từ loading → multicam layout (CLS target < 0.1 cho màn detail).

**4.2. Availability & Reliability**

- Không áp dụng SLA riêng cho feature UI layout — kế thừa portal prod SLA **≥ 99.5%** uptime/tháng.
- Khi 1/3 playback URL fail: `ScaleAiMulticamVideoView` hiển thị error state per-pane, không crash toàn màn (graceful degradation hiện có).
- RTO/RPO: không thay đổi — feature không persist state server-side.

**4.3. Security Requirements**

- Authentication: Keycloak OIDC, JWT Bearer trên mọi API call (`AuthProvider.tsx` → `client.ts`).
- Authorization: `qc:review:perform` bắt buộc cho review/playback endpoints; `qc:assign` quyết định filter review sessions (xem tất cả vs chỉ của mình).
- Data in-transit: TLS 1.2+ cho portal và API.
- Playback URL: presigned S3, expiry theo `expires_at` — không log full URL vào client analytics.
- Input validation: `item_id` UUID format — invalid → 404 từ backend, FE hiển thị error boundary.

**4.4. Scalability Requirements**

- Không áp dụng cho feature này — pure frontend layout; backend QC APIs đã scale theo portal hiện tại.
- Concurrent reviewers: kế thừa portal target **≤ 50** concurrent QC sessions mà không degrade playback load time p95 > 3s.

**4.5. Maintainability Requirements**

- Unit test coverage: `MetadataQcReviewLayout.test.tsx`, `scaleaiMulticamQc.test.ts`, `review/ReviewSidebarTabs.test.tsx` — **giữ pass** sau mọi thay đổi.
- Component tách biệt: `ReviewSidebarTabs` (shared, dùng cho mọi item review) vs `MetadataSidecarPanel` (nội dung tab audit) — không duplicate Delivery Audit render logic.
- `data-testid`: `metadata-qc-sidebar-tabs`, `metadata-qc-sidebar-tab-audit`, `metadata-qc-sidebar-tab-history` — bắt buộc giữ cho E2E/QA.
- CI: `npm run test` (Vitest) + `npm run lint` trước merge.

**4.6. Usability & Accessibility**

- Browser support: Chrome ≥ 120, Firefox ≥ 120, Edge ≥ 120 — desktop/laptop ≥ **1024px** viewport width (URD OUT OF SCOPE responsive nhỏ hơn).
- Tab navigation: Radix Tabs hỗ trợ keyboard (Arrow keys, Tab focus) — tab order: Audit → History → Preview controls.
- Localization: nhãn tab dùng i18n keys `qc_delivery_audit_title`, `qc_review_history_title` / `qc_review_history_title_mine` — không hardcode.
- UI response: skeleton/loading state khi `review` query pending — không flash layout legacy trước khi biết variant multicam.

**4.7. Compliance & Regulatory**

- Không áp dụng quy định riêng — feature chỉ sắp xếp lại UI xem metadata/video nội bộ; không thu thập PII mới.
- Audit trail review (Pass/Reject) kế thừa hệ thống QC hiện có — không thay đổi retention.

**NFR Summary Table**

|  |  |  |  |
| --- | --- | --- | --- |
| **ID** | **Requirement** | **Metric / Target** | **Priority** |
| NFR-P-01 | Tab switch latency | p95 < 50ms, no playback refetch | High |
| NFR-P-02 | Multicam playback URL load | 3 parallel requests, p95 total < 2s | High |
| NFR-P-03 | Cumulative Layout Shift (detail page) | CLS < 0.1 | Medium |
| NFR-A-01 | Portal uptime (inherited) | ≥ 99.5% / month | Medium |
| NFR-SEC-01 | API auth | 100% QC endpoints require valid JWT + `qc:review:perform` | High |
| NFR-SEC-02 | Review history ACL | Sessions filtered by `qc:assign` when absent | High |
| NFR-M-01 | Layout branch unit tests | 3 test files pass; no regression on merge | High |
| NFR-U-01 | Minimum viewport | Desktop ≥ 1024px; sidebar fixed 320px từ `xl` (1280px) | High |
| NFR-U-02 | Tab keyboard navigation | Radix Tabs a11y defaults enabled | Medium |
